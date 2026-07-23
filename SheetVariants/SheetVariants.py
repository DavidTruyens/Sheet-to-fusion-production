# SheetVariants.py
# Fusion add-in: read parametric variants from a Google Sheet, apply the
# parameters to the active model, and build one new design per enabled
# export profile — each profile's design gets one component per variant,
# laid out left-to-right by bounding box. A profile selects either the
# whole model (every solid body) or a named subset of the model's
# components; profiles are edited in the Build dialog's table and saved to
# settings.json. Geometry is copied in-memory (TemporaryBRepManager), never
# exported to SAT/STEP/DXF, so the add-in still works on Fusion Personal.
#
# Sheet layout (one variant per row):
#   | Name      | length | width | height | ...   |   <- header row
#   | Bracket_S | 50 mm  | 20 mm | 10 mm  | ...   |
#   | Bracket_M | 80 mm  | 30 mm | 15 mm  | ...   |
#
# - Column A header must be "Name" (used as the component name).
# - Every other header must match a parameter name in the source model exactly.
# - Cell values are written straight into the parameter expression, so include
#   units ("50 mm", "30 deg") to avoid ambiguity.

import adsk.core
import adsk.fusion
import traceback
import os
import re
import csv
import urllib.request
import urllib.error
import sys

# Make this add-in's folder importable so the pure-logic module resolves
# regardless of Fusion's current working directory.
_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
# Fusion keeps a single Python process alive, so helper modules stay cached in
# sys.modules across Stop/Run. Drop sheet_core before importing so reloading the
# add-in always picks up the current file instead of a stale cached version.
sys.modules.pop('sheet_core', None)
import sheet_core

app = adsk.core.Application.get()
ui = app.userInterface

# Keep event handlers referenced so Python does not garbage-collect them.
_handlers = []

# Component names of the active design at the moment the Build dialog opened,
# used to populate each named-components profile's checkbox-dropdown.
_component_name_cache = []

# Whether the Build dialog's most recent validation pass allows OK to be
# pressed; written by _run_build_validation, read by ValidateInputsHandler.
_build_report = {"ok": True}

# Sentinel tab-dropdown label used when list_tabs() finds no selectable tabs
# (a published-to-web or direct-CSV link); _run_build_validation and
# _refresh_test_rows treat this one string as "read as CSV" rather than as an
# unresolved placeholder.
CSV_ONLY_TAB_LABEL = "— single sheet (read as CSV) —"

# The add-in version is declared in SheetVariants.manifest ("version") and shown
# in Fusion's Scripts and Add-Ins list. Bump it there on each change; Fusion
# re-reads it when the add-in is removed and re-added (or on restart).

# The sheet URL is remembered per design (as a document attribute), so each
# design pre-fills its own sheet and a design with none set stays empty.
DESIGN_ATTR_GROUP = 'SheetVariants'
DESIGN_ATTR_URL = 'sheetUrl'

CMD_ID = 'sheetVariantsBuildAssemblyCmd'
CMD_NAME = 'Build Variants Assembly from Sheet'
CMD_DESC = ('Reads model variants from a Google Sheet, applies the parameters, '
            'and assembles a copy of each variant as a component in a new design.')

TEMPLATE_CMD_ID = 'sheetVariantsCreateTemplateCmd'
TEMPLATE_CMD_NAME = 'Create Variant Sheet Template'
TEMPLATE_CMD_DESC = ('Writes a CSV template whose columns are the model\'s favorite '
                     '(or user) parameters, ready to import into Google Sheets.')

TEST_CMD_ID = 'sheetVariantsTestRowCmd'
TEST_CMD_NAME = 'Test Variant Row'
TEST_CMD_DESC = ('Preview one variant row from the sheet live on the active model. '
                 'The model reverts to its original values when you close.')

# Icon resource folders (each holds 16x16/32x32/64x64 PNGs). Absolute paths so
# Fusion resolves them regardless of its current working directory.
_ICON_BASE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources')
BUILD_ICON_FOLDER = os.path.join(_ICON_BASE, 'BuildAssembly')
TEMPLATE_ICON_FOLDER = os.path.join(_ICON_BASE, 'CreateTemplate')

# Place the add-in's commands in their own panel under the MANAGE tab of the
# Design workspace. The tab is matched by its visible name because the internal
# ids are not stable across versions ('ToolsTab' is actually UTILITIES).
WORKSPACE_ID = 'FusionSolidEnvironment'
TAB_NAME = 'MANAGE'
# A panel id must be unique per workspace and Fusion persists API-created panels
# across reloads, so a stale panel left on another tab by an earlier version
# would be reused instead of a fresh one being made on MANAGE. Use a new id and
# delete any older ones during cleanup.
PANEL_ID = 'SheetVariantsManagePanel'
PANEL_NAME = 'Sheet Variants'
OBSOLETE_PANEL_IDS = ('SheetVariantsPanel',)
# Fallback panel (under UTILITIES > ADD-INS) if the Manage tab is unavailable.
FALLBACK_PANEL_ID = 'SolidScriptsAddinsPanel'

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.json')


# --------------------------------------------------------------------------- #
# Google Sheet reading. Works with no extra Python packages by pulling the
# sheet as CSV over HTTP (Fusion's bundled Python ships urllib + csv).
# --------------------------------------------------------------------------- #
def fetch_rows(url):
    candidates = sheet_core.csv_url_candidates(url)
    raw = None
    last_err = None
    for csv_url in candidates:
        req = urllib.request.Request(csv_url, headers={'User-Agent': 'Mozilla/5.0 (FusionAddin)'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8-sig', errors='replace')
            break
        except urllib.error.HTTPError as e:
            last_err = 'HTTP {} {}'.format(e.code, e.reason)
        except urllib.error.URLError as e:
            last_err = str(e.reason)

    if raw is None:
        raise RuntimeError('Could not download the sheet ({}).\n\n{}'.format(
            last_err or 'unknown error', sheet_core.SHARING_HELP))
    return sheet_core.parse_sheet_csv(raw)


# --------------------------------------------------------------------------- #
# Tab-aware reading. Multi-tab sheets (a real /d/<id>/ spreadsheet link) are
# fetched once as XLSX (stdlib zipfile, parsed by sheet_core) so a specific tab
# can be read; single-tab share/publish/direct-CSV links fall back to the CSV
# export above. sheet_core.py has no adsk dependency and is unit-tested on CI.
# --------------------------------------------------------------------------- #
_xlsx_cache = {"url": None, "bytes": None}


def _xlsx_bytes_for(url):
    if _xlsx_cache["url"] != url or _xlsx_cache["bytes"] is None:
        sid = sheet_core.extract_spreadsheet_id(url)
        req = urllib.request.Request(sheet_core.xlsx_export_url(sid),
                                     headers={"User-Agent": "Mozilla/5.0 (FusionAddin)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            _xlsx_cache["bytes"] = resp.read()
        _xlsx_cache["url"] = url
    return _xlsx_cache["bytes"]


def list_tabs(url):
    if not sheet_core.extract_spreadsheet_id(url):
        return []
    return sheet_core.parse_workbook_tabs(_xlsx_bytes_for(url))


def get_rows(url, tab_name=None):
    sid = sheet_core.extract_spreadsheet_id(url)
    if sid and tab_name:
        rows = sheet_core.read_tab_rows(_xlsx_bytes_for(url), tab_name)
    else:
        rows = fetch_rows(url)
        return rows  # fetch_rows already enforces >=2 rows
    if len(rows) < 2:
        raise RuntimeError("The sheet needs a header row plus at least one variant row.")
    return rows


def known_param_names(design):
    return [p.name for p in design.allParameters]


def driveable_param_names(design):
    favs = [p.name for p in design.allParameters if getattr(p, "isFavorite", False)]
    return favs if favs else [p.name for p in design.userParameters]


def load_pinned_tab(settings, spreadsheet_id):
    return (settings.get("pinned_tabs") or {}).get(spreadsheet_id, "")


def set_pinned_tab(settings, spreadsheet_id, tab):
    pinned = dict(settings.get("pinned_tabs") or {})
    pinned[spreadsheet_id] = tab
    settings["pinned_tabs"] = pinned


def load_design_url(design):
    """The Google Sheet URL for this design: its own stored attribute if set,
    else the last-used URL (app-level fallback), else ''."""
    if design:
        try:
            attr = design.attributes.itemByName(DESIGN_ATTR_GROUP, DESIGN_ATTR_URL)
            if attr and attr.value:
                return attr.value
        except Exception:
            pass
    # Fallback: the last sheet used. Keeps the URL pre-filled even when the active
    # document is a fresh output design, or after a restart where the source
    # document's attribute wasn't saved to disk.
    return sheet_core.load_settings(SETTINGS_FILE).get('sheet_url', '') or ''


def save_design_url(design, url):
    """Remember the sheet URL on this design (as a document attribute) and as the
    app-level last-used URL, so it pre-fills next time regardless of which
    document is active."""
    try:
        s = sheet_core.load_settings(SETTINGS_FILE)
        s['sheet_url'] = url or ''
        sheet_core.save_settings(SETTINGS_FILE, s)
    except Exception:
        pass
    if not design:
        return
    try:
        design.attributes.add(DESIGN_ATTR_GROUP, DESIGN_ATTR_URL, url or '')
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Core work.
# --------------------------------------------------------------------------- #
def apply_expression(param, raw):
    """Write a sheet cell into a parameter's expression.

    Text parameters need a single-quoted string expression (e.g. 'A-6'), but a
    sheet usually supplies the bare text — sometimes with a stray quote left
    over from a spreadsheet's text-prefix (so "1-1" can arrive as "1-1'"). We
    detect text parameters from their current expression and re-quote the value;
    numeric parameters get the value as-is.
    """
    raw = raw.strip()
    if not raw:
        return
    current = (param.expression or '').strip()
    if current[:1] in ("'", '"'):                     # existing text parameter
        param.expression = "'" + raw.strip('\'"') + "'"
        return
    try:
        param.expression = raw
    except Exception:
        try:                                          # maybe an unquoted text param
            param.expression = "'" + raw.strip('\'"') + "'"
        except Exception:
            raise RuntimeError(
                'Could not set parameter "{}" to "{}". Numeric values may need a '
                'unit (e.g. "50 mm"); text values are quoted automatically.'
                .format(param.name, raw))


def iter_solid_bodies(design):
    """Yield every solid BRepBody in the design (root plus all occurrences),
    as proxies positioned in their assembly-context (world) location."""
    root = design.rootComponent
    for b in root.bRepBodies:
        if b.isSolid:
            yield b
    for occ in root.allOccurrences:
        for b in occ.bRepBodies:
            if b.isSolid:
                yield b


def component_names(design):
    """Distinct component names in the active design (order of first appearance)."""
    names, seen = [], set()
    for occ in design.rootComponent.allOccurrences:
        try:
            n = occ.component.name
        except Exception:
            continue
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    return names


def resolve_whole_model(design, profile):
    """Every solid body in the design (root plus all occurrences)."""
    return list(iter_solid_bodies(design)), []


def _component_solid_bodies(design, included_names):
    """Solid bodies of the selected components — one representative occurrence
    per component name, so a part exports once rather than once per instance."""
    wanted = set(included_names)
    got = {}
    for occ in design.rootComponent.allOccurrences:
        try:
            cname = occ.component.name
        except Exception:
            continue
        if cname in wanted and cname not in got:
            bodies = [b for b in occ.bRepBodies if b.isSolid]
            if bodies:
                got[cname] = bodies
    out = []
    for name in included_names:
        out.extend(got.get(name, []))
    return out


def resolve_named_components(design, profile):
    present = component_names(design)
    included, missing = sheet_core.select_component_names(present, profile.get('components', []))
    warnings = []
    if missing:
        warnings.append("component(s) not found: " + ", ".join(missing))
    return _component_solid_bodies(design, included), warnings


RESOLVERS = {
    'whole_model': resolve_whole_model,
    'named_components': resolve_named_components,
}


def _appearance_in(design, src_appr):
    """The appearance named like ``src_appr`` inside ``design``, copied in once if
    needed. Lets a copied body show the source body's appearance (temporary BReps
    lose it). Returns None if it can't be copied."""
    try:
        existing = design.appearances.itemByName(src_appr.name)
        return existing or design.appearances.addByCopy(src_appr, src_appr.name)
    except Exception:
        return None


def _material_in(design, src_mat):
    """The material named like ``src_mat`` inside ``design``, copied in once if
    needed. Returns None if it can't be copied."""
    try:
        existing = design.materials.itemByName(src_mat.name)
        return existing or design.materials.addByCopy(src_mat, src_mat.name)
    except Exception:
        return None


def build_exports(sheet_url, spacing_cm, profiles, tab_name=None):
    """Build one new design per enabled profile. Each profile is built into its
    own document (created before parameters are edited, so the source model is in
    the background while its parameters change). Returns per-profile result dicts
    for reporting."""
    rows = get_rows(sheet_url, tab_name)
    header = [h.strip() for h in rows[0]]
    if not header or not header[0]:
        raise RuntimeError('The first header cell must be "Name".')
    param_names = header[1:]

    src_design = adsk.fusion.Design.cast(app.activeProduct)
    if not src_design:
        raise RuntimeError('Open the parametric source model as the active design before running this command.')

    all_params = src_design.allParameters
    missing = [p for p in param_names if not all_params.itemByName(p)]
    if missing:
        raise RuntimeError('These columns do not match any parameter in the model: ' + ', '.join(missing))

    enabled = [p for p in profiles if p.get('enabled')]
    if not enabled:
        raise RuntimeError('No export profiles are enabled. Enable at least one profile and run again.')

    original = {p: all_params.itemByName(p).expression for p in param_names}
    tbm = adsk.fusion.TemporaryBRepManager.get()

    # One build context per enabled profile; pre-validate selections.
    present = component_names(src_design)
    contexts = []
    for prof in enabled:
        ctx = {'profile': prof, 'name': prof.get('name') or 'Export',
               'built': 0, 'warnings': [], 'skipped': False}
        if prof.get('rule') not in RESOLVERS:
            ctx['skipped'] = True
            ctx['warnings'] = ["unknown rule '{}'".format(prof.get('rule'))]
        elif prof.get('rule') == 'named_components':
            included, miss = sheet_core.select_component_names(present, prof.get('components', []))
            if miss:
                ctx['warnings'].append("component(s) not found: " + ", ".join(miss))
            if not included:
                ctx['skipped'] = True
                ctx['warnings'] = ['no matching components in this design']
        contexts.append(ctx)

    active = [c for c in contexts if not c['skipped']]
    if not active:
        return contexts

    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show('Building exports', 'Variant %v of %m', 0, len(rows) - 1, 0)

    # documents.add() invalidates every reference to the source design (and its
    # allParameters) in this Fusion build — confirmed via the debug log: the
    # first itemByName right after creating an output document raised "deleted
    # Object". So NO output document may be created while we still need to read
    # the source. Phase 1 applies each variant to the source and snapshots its
    # solids as temporary BReps, with the source as the ONLY open design and the
    # design/params re-derived fresh from app.activeProduct each row (a recompute
    # can also invalidate a held collection). Phase 2 then creates the output
    # documents and fills them from the snapshots.
    try:
        try:
            for i, row in enumerate(rows[1:]):
                if progress.wasCancelled:
                    raise RuntimeError('Cancelled by user.')

                raw_name = row[0].strip() if len(row) > 0 else ''
                name = raw_name or 'Variant_{}'.format(i + 1)
                safe_name = re.sub(r'[^A-Za-z0-9_\- ]', '_', name).strip() or 'Variant_{}'.format(i + 1)

                for col, pname in enumerate(param_names, start=1):
                    if col < len(row):
                        val = row[col].strip()
                        if val:
                            # Re-derive design + parameter FRESH for every apply:
                            # setting a driving dimension recomputes the model,
                            # which can invalidate the parameter collection, so the
                            # one from the previous apply may already be dead.
                            p = adsk.fusion.Design.cast(app.activeProduct).allParameters.itemByName(pname)
                            if p:
                                apply_expression(p, val)
                adsk.doEvents()  # recompute the source with this variant's values

                design = adsk.fusion.Design.cast(app.activeProduct)  # fresh after recompute
                for ctx in active:
                    resolver = RESOLVERS[ctx['profile']['rule']]
                    src_bodies, _warn = resolver(design, ctx['profile'])
                    temp_bodies = []
                    for body in src_bodies:
                        try:
                            tmp = tbm.copy(body)
                        except Exception:
                            continue
                        appr = mat = None
                        try:
                            appr = body.appearance   # body-level override, or None
                        except Exception:
                            pass
                        try:
                            mat = body.material
                        except Exception:
                            pass
                        temp_bodies.append((tmp, appr, mat))
                    if temp_bodies:
                        ctx.setdefault('variants', []).append((safe_name, temp_bodies))
                progress.progressValue = i + 1
        finally:
            # Restore the source model — re-derive fresh per parameter, since each
            # set can recompute and invalidate the parameter collection.
            for p, expr in original.items():
                try:
                    rp = adsk.fusion.Design.cast(app.activeProduct).allParameters.itemByName(p)
                    if rp:
                        rp.expression = expr
                except Exception:
                    pass
            adsk.doEvents()

        # Phase 2: one output design per profile, laid out left-to-right. Only now
        # do we create documents — the source has been fully read and restored.
        for ctx in active:
            variants = ctx.get('variants', [])
            if not variants:
                ctx['skipped'] = True
                if not ctx['warnings']:
                    ctx['warnings'] = ['no solid bodies matched']
                continue
            new_doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            nd = adsk.fusion.Design.cast(new_doc.products.itemByProductType('DesignProductType'))
            root = nd.rootComponent
            try:
                root.name = ctx['name']
            except Exception:
                pass

            x_cursor = 0.0
            for safe_name, temp_bodies in variants:
                tmps = [t for (t, _a, _m) in temp_bodies]
                min_x = min(tb.boundingBox.minPoint.x for tb in tmps)
                max_x = max(tb.boundingBox.maxPoint.x for tb in tmps)
                transform = adsk.core.Matrix3D.create()
                transform.translation = adsk.core.Vector3D.create(x_cursor - min_x, 0.0, 0.0)
                occ = root.occurrences.addNewComponent(transform)
                occ.component.name = safe_name
                base = occ.component.features.baseFeatures.add()
                base.startEdit()
                try:
                    for tmp, _appr, _mat in temp_bodies:
                        occ.component.bRepBodies.add(tmp, base)
                finally:
                    base.finishEdit()
                # Re-apply the source look (temporary BReps lose material/appearance).
                # The body objects returned during the base-feature edit go stale
                # after finishEdit(), so fetch the component's bodies fresh and match
                # them by index. Best-effort: the geometry is already built, so any
                # failure just leaves the default look rather than breaking the build.
                comp_bodies = occ.component.bRepBodies
                for idx, (_tmp, appr, mat) in enumerate(temp_bodies):
                    if idx >= comp_bodies.count:
                        break
                    nb = comp_bodies.item(idx)
                    try:
                        if mat:
                            m = _material_in(nd, mat)
                            if m:
                                nb.material = m
                        if appr:
                            a = _appearance_in(nd, appr)
                            if a:
                                nb.appearance = a
                    except Exception:
                        pass  # geometry is built; a failed look just stays default
                x_cursor += (max_x - min_x) + spacing_cm
                ctx['built'] += 1
            # Frame the finished layout. A fresh document opens with the default
            # empty-scene camera, so the built variants sit outside the view.
            # goHome() is the ViewCube Home button; fit() covers home views that
            # are not set to fit. Best-effort — a camera failure must not fail
            # the build. The new doc is still active here (documents.add
            # activates it), so activeViewport is this profile's viewport.
            try:
                adsk.doEvents()
                app.activeViewport.goHome(False)
                app.activeViewport.fit()
            except Exception:
                pass
    finally:
        progress.hide()

    return contexts


# --------------------------------------------------------------------------- #
# Build dialog profiles-table helpers.
# --------------------------------------------------------------------------- #
def _rule_is_named(rule_input):
    item = rule_input.selectedItem
    return bool(item and item.name.startswith('Named'))


def _add_profile_row(table, profile):
    """Append one profile as a table row: [enabled | name | rule | components]."""
    ci = table.commandInputs
    pid = profile['id']
    row = table.rowCount

    en = ci.addBoolValueInput('en_' + pid, 'Enabled', True, '', bool(profile.get('enabled', True)))
    nm = ci.addStringValueInput('nm_' + pid, 'Name', profile.get('name', ''))
    rl = ci.addDropDownCommandInput('rl_' + pid, 'Rule', adsk.core.DropDownStyles.TextListDropDownStyle)
    is_named = profile.get('rule') == 'named_components'
    rl.listItems.add('Whole model', not is_named)
    rl.listItems.add('Named components', is_named)

    cp = ci.addDropDownCommandInput('cp_' + pid, 'Components', adsk.core.DropDownStyles.CheckBoxDropDownStyle)
    selected = set(profile.get('components', []))
    for cn in _component_name_cache:
        cp.listItems.add(cn, cn in selected)
    for cn in profile.get('components', []):   # keep saved-but-absent names visible
        if cn not in _component_name_cache:
            cp.listItems.add(cn + ' (missing)', True)
    cp.isVisible = is_named

    table.addCommandInput(en, row, 0)
    table.addCommandInput(nm, row, 1)
    table.addCommandInput(rl, row, 2)
    table.addCommandInput(cp, row, 3)


def _read_profiles(table):
    """Read the table back into a list of profile dicts."""
    profiles = []
    for r in range(table.rowCount):
        en = table.getInputAtPosition(r, 0)
        nm = table.getInputAtPosition(r, 1)
        rl = table.getInputAtPosition(r, 2)
        cp = table.getInputAtPosition(r, 3)
        pid = nm.id[3:]   # strip 'nm_'
        rule = 'named_components' if _rule_is_named(rl) else 'whole_model'
        comps = []
        for k in range(cp.listItems.count):
            it = cp.listItems.item(k)
            if it.isSelected:
                comps.append(it.name.replace(' (missing)', ''))
        profiles.append({'id': pid, 'name': nm.value or ('Export ' + pid),
                         'enabled': en.value, 'rule': rule, 'components': comps})
    return profiles


# --------------------------------------------------------------------------- #
# Sheet template generation from the model's favorite (or user) parameters.
# --------------------------------------------------------------------------- #
def collect_parameters(use_favorites):
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise RuntimeError('Open the parametric source model as the active design first.')

    params = []
    if use_favorites:
        for p in design.allParameters:
            try:
                if p.isFavorite:
                    params.append(p)
            except Exception:
                pass
    else:
        for p in design.userParameters:
            params.append(p)
    return params


def create_template(use_favorites):
    params = collect_parameters(use_favorites)
    if not params:
        if use_favorites:
            raise RuntimeError(
                'No favorite parameters found. In the Parameters dialog, click the star next to the '
                'parameters you want to drive (or re-run and choose "All user parameters").')
        raise RuntimeError('This model has no user parameters.')

    dlg = ui.createFileDialog()
    dlg.title = 'Save variant sheet template'
    dlg.filter = 'CSV files (*.csv)'
    base = (app.activeDocument.name or 'variants').split(' v')[0]
    dlg.initialFilename = (re.sub(r'[^A-Za-z0-9_\- ]', '_', base).strip() or 'variants') + '_variants.csv'
    if dlg.showSave() != adsk.core.DialogResults.DialogOK:
        return None, 0

    path = dlg.filename
    if not path.lower().endswith('.csv'):
        path += '.csv'

    header = ['Name'] + [p.name for p in params]
    # One example row seeded with the model's current expressions, so the
    # expected "value + unit" format is obvious. Text parameters are written
    # without their surrounding quotes (so 'A-6' becomes A-6) to keep the sheet
    # tidy; the quotes are re-added automatically on import based on the model's
    # parameter type, so a value can even be a number used as engraving text.
    example = ['Variant_1'] + [sheet_core.unquote_text(p.expression) for p in params]

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerow(example)

    return path, len(params)


# --------------------------------------------------------------------------- #
# Row cache for the "Test Variant Row" command's live preview. executePreview
# can fire often, so the selected tab's rows are parsed once per (url, tab)
# instead of on every frame.
# --------------------------------------------------------------------------- #
_rows_cache = {'key': None, 'rows': None}


def _cached_rows(url, tab_name):
    key = (url, tab_name)
    if _rows_cache['key'] != key:
        _rows_cache['rows'] = get_rows(url, tab_name)
        _rows_cache['key'] = key
    return _rows_cache['rows']


# --------------------------------------------------------------------------- #
# Shared helpers: Build-dialog sheet validation and the variant-row list, both
# refreshed immediately (not on OK) as sheetUrl/tab/loadTabs change. The row
# list and live-preview helpers are also used by the standalone "Test Variant
# Row" command.
# --------------------------------------------------------------------------- #
def _find_input(inputs, input_id):
    """Find a command input by id anywhere in the dialog, descending into tab
    and group children.

    Fusion's CommandInputs.itemById does not search across sibling tabs, and in
    an inputChanged handler ``args.inputs`` is scoped to the changed input's own
    tab. A handler firing in one tab must therefore walk the tree explicitly to
    reach an input that lives in another tab (e.g. the Build dialog's "Output
    sets" profiles table, reached from the Sheet tab's Load-tabs handler)."""
    direct = inputs.itemById(input_id)
    if direct:
        return direct
    tab_t = adsk.core.TabCommandInput.classType()
    grp_t = adsk.core.GroupCommandInput.classType()
    for i in range(inputs.count):
        child = inputs.item(i)
        if child.objectType in (tab_t, grp_t):
            found = _find_input(child.children, input_id)
            if found:
                return found
    return None


def _selected_tab_name(inputs):
    """The chosen 'tab' item's name, or None for any placeholder/sentinel
    (anything starting with the em-dash used by all of "— click Load tabs —",
    CSV_ONLY_TAB_LABEL, and "— could not read tab —")."""
    tab_item = _find_input(inputs, 'tab').selectedItem
    if not tab_item or tab_item.name.startswith('—'):
        return None
    return tab_item.name


def _selected_tab_is_csv_only(inputs):
    """True iff the current 'tab' selection is the CSV_ONLY_TAB_LABEL
    sentinel specifically, as opposed to a real tab or an unresolved
    placeholder (e.g. "— click Load tabs —"). Callers that need to tell
    "CSV-only" apart from "nothing chosen yet" use this alongside
    _selected_tab_name, which collapses both cases to None."""
    tab_item = _find_input(inputs, 'tab').selectedItem
    return bool(tab_item and tab_item.name == CSV_ONLY_TAB_LABEL)


def _run_build_validation(inputs):
    """Refresh the report textbox + _build_report flag from current inputs."""
    url = _find_input(inputs, 'sheetUrl').value.strip()
    report_box = _find_input(inputs, 'report')
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        report_box.formattedText = 'Open your parametric source model to validate.'
        _build_report['ok'] = True
        return
    tab_name = _selected_tab_name(inputs)
    if tab_name is None and not _selected_tab_is_csv_only(inputs):
        report_box.formattedText = 'Pick a tab to validate the mapping.'
        _build_report['ok'] = True
        return
    try:
        rows = get_rows(url, tab_name)
    except Exception as e:
        report_box.formattedText = '<font color="#c0392b">{}</font>'.format(str(e))
        _build_report['ok'] = False
        return
    rep = sheet_core.validate_mapping(
        rows[0], rows[1:], known_param_names(design), driveable_param_names(design))
    report_box.formattedText = rep.to_html()
    _build_report['ok'] = rep.ok


def _refresh_test_rows(inputs):
    """Repopulate the Test tab's 'testRow' dropdown from the currently chosen
    tab, called as sheetUrl/tab/loadTabs change in the Build dialog."""
    url = _find_input(inputs, 'sheetUrl').value.strip()
    row_dd = _find_input(inputs, 'testRow')
    row_dd.listItems.clear()
    tab_name = _selected_tab_name(inputs)
    if tab_name is None and not _selected_tab_is_csv_only(inputs):
        row_dd.listItems.add('— load a tab first —', True)
        return
    try:
        rows = _cached_rows(url, tab_name)
    except Exception:
        row_dd.listItems.add('— could not read tab —', True)
        return
    for i, row in enumerate(rows[1:]):
        label = (row[0].strip() if row else '') or 'Variant_{}'.format(i + 1)
        row_dd.listItems.add(label, i == 0)


def _preview_test_row(inputs):
    """Apply the Test tab's selected variant row to the model as a live preview.

    Called from the Build command's executePreview — the one place Fusion allows
    temporary model edits during a command. Only previews while the Test tab is
    the active tab; changes are NOT marked as a valid result, so Fusion reverts
    them when the dialog closes (or before OK/Build runs)."""
    tab_test = _find_input(inputs, 'tabTest')
    if not (tab_test and tab_test.isActive):
        return  # only preview while the Test tab is showing
    if not adsk.fusion.Design.cast(app.activeProduct):
        return
    row_item = _find_input(inputs, 'testRow').selectedItem
    if not row_item or row_item.name.startswith('—'):
        return
    url = _find_input(inputs, 'sheetUrl').value.strip()
    tab_name = _selected_tab_name(inputs)
    try:
        rows = _cached_rows(url, tab_name)
    except Exception:
        return
    param_names = [h.strip() for h in rows[0]][1:]
    data = rows[1:]
    idx = row_item.index
    if idx >= len(data):
        return
    row = data[idx]
    for col, pname in enumerate(param_names, start=1):
        if col >= len(row):
            continue
        val = row[col].strip()
        if not val:
            continue
        # Re-derive fresh per parameter: a recompute can invalidate the collection.
        p = adsk.fusion.Design.cast(app.activeProduct).allParameters.itemByName(pname)
        if p:
            try:
                apply_expression(p, val)
            except Exception:
                pass  # a bad cell just doesn't preview; never crash the preview


# --------------------------------------------------------------------------- #
# Command handlers / UI.
# --------------------------------------------------------------------------- #
class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            url = _find_input(inputs, 'sheetUrl').value.strip()
            spacing_cm = _find_input(inputs, 'spacing').value      # ValueInput returns internal cm
            if not url:
                ui.messageBox('Please paste the Google Sheet URL.')
                return

            tab = _selected_tab_name(inputs)

            settings = sheet_core.load_settings(SETTINGS_FILE)
            profiles = _read_profiles(_find_input(inputs, 'profiles'))
            settings['spacing_mm'] = spacing_cm * 10.0
            settings['profiles'] = profiles
            sid = sheet_core.extract_spreadsheet_id(url)
            if sid and tab:
                set_pinned_tab(settings, sid, tab)
            sheet_core.save_settings(SETTINGS_FILE, settings)
            # Remember this design's sheet URL on the design itself.
            save_design_url(adsk.fusion.Design.cast(app.activeProduct), url)
            results = build_exports(url, spacing_cm, profiles, tab)
            ui.messageBox(sheet_core.summarize_results(results))
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            global _component_name_cache
            _build_report['ok'] = True

            cmd = args.command
            cmd.setDialogInitialSize(560, 460)
            inputs = cmd.commandInputs

            settings = sheet_core.load_settings(SETTINGS_FILE)
            design0 = adsk.fusion.Design.cast(app.activeProduct)
            url0 = load_design_url(design0)  # per-design; empty if none set

            # --- Sheet tab -------------------------------------------------- #
            tab_sheet = inputs.addTabCommandInput('tabSheet', 'Sheet').children

            url_in = tab_sheet.addStringValueInput('sheetUrl', 'Google Sheet URL', url0)
            url_in.tooltip = 'Share link or published-to-web CSV link of the sheet that holds your variants.'

            load_btn = tab_sheet.addBoolValueInput('loadTabs', 'Load tabs', False, '', False)
            load_btn.tooltip = 'Fetch the sheet and list its tabs.'

            tab_dd = tab_sheet.addDropDownCommandInput(
                'tab', 'Tab', adsk.core.DropDownStyles.TextListDropDownStyle)
            tab_dd.tooltip = 'Which worksheet tab holds your variant rows.'
            sid0 = sheet_core.extract_spreadsheet_id(url0)
            pinned0 = load_pinned_tab(settings, sid0) if sid0 else ''
            if pinned0:
                tab_dd.listItems.add(pinned0, True)
            else:
                tab_dd.listItems.add('— click Load tabs —', True)

            report = tab_sheet.addTextBoxCommandInput('report', 'Check', '', 6, True)
            report.isFullWidth = True

            default_mm = float(settings.get('spacing_mm', 100.0))
            spacing_in = tab_sheet.addValueInput('spacing', 'Gap between variants (mm)', 'mm',
                                                 adsk.core.ValueInput.createByReal(default_mm / 10.0))
            spacing_in.tooltip = ('Clear space left between each variant\'s bounding box along X. '
                                  'Set 0 to butt them together.')

            # --- Test tab ----------------------------------------------------#
            tab_test = inputs.addTabCommandInput('tabTest', 'Test').children
            row_dd = tab_test.addDropDownCommandInput(
                'testRow', 'Variant row', adsk.core.DropDownStyles.TextListDropDownStyle)
            row_dd.listItems.add('— load a tab first —', True)
            row_dd.tooltip = 'Pick a row to preview it live on the model.'
            test_note = tab_test.addTextBoxCommandInput('testNote', '', '', 3, True)
            test_note.isFullWidth = True
            test_note.text = ('Load a tab in the Sheet tab, then pick a row here to preview it live '
                              'on the model. It reverts when you close the dialog (Cancel); click OK '
                              'to build the output sets.')

            # --- Output sets tab ---------------------------------------------#
            tab_output = inputs.addTabCommandInput('tabOutput', 'Output sets').children

            # Cache the active design's component names for the checkbox-dropdowns.
            src = adsk.fusion.Design.cast(app.activeProduct)
            _component_name_cache = component_names(src) if src else []

            table = tab_output.addTableCommandInput('profiles', 'Export profiles', 4, '1:3:2:3')
            table.minimumVisibleRows = 2
            table.maximumVisibleRows = 8
            table.columnSpacing = 1
            table.rowSpacing = 1

            add_btn = tab_output.addBoolValueInput('profileAdd', 'Add', False, '', False)
            add_btn.tooltip = 'Add an export profile'
            del_btn = tab_output.addBoolValueInput('profileDelete', 'Remove', False, '', False)
            del_btn.tooltip = 'Remove the selected export profile'
            table.addToolbarCommandInput(add_btn)
            table.addToolbarCommandInput(del_btn)

            for profile in settings['profiles']:
                _add_profile_row(table, profile)

            if not _component_name_cache:
                note = tab_output.addTextBoxCommandInput('compNote', '', '', 2, True)
                note.text = ('Open your source design before running to pick components '
                             'for "Named components" profiles.')

            on_exec = CommandExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)

            on_changed = BuildInputChangedHandler()
            cmd.inputChanged.add(on_changed)
            _handlers.append(on_changed)

            on_preview = BuildExecutePreviewHandler()
            cmd.executePreview.add(on_preview)
            _handlers.append(on_preview)

            on_validate = ValidateInputsHandler()
            cmd.validateInputs.add(on_validate)
            _handlers.append(on_validate)
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class BuildInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            changed = args.input
            # args.inputs is scoped to the changed input's own tab, so use the
            # command's top-level inputs and _find_input to reach other tabs.
            inputs = changed.parentCommand.commandInputs
            table = _find_input(inputs, 'profiles')

            if table is not None and changed.id == 'profileAdd':
                existing = [table.getInputAtPosition(r, 1).id[3:] for r in range(table.rowCount)]
                pid = sheet_core.next_profile_id(existing)
                _add_profile_row(table, {'id': pid, 'name': 'Export ' + pid,
                                         'enabled': True, 'rule': 'whole_model', 'components': []})
            elif table is not None and changed.id == 'profileDelete':
                if table.selectedRow >= 0:
                    table.deleteRow(table.selectedRow)
            elif table is not None and changed.id.startswith('rl_'):
                pid = changed.id[3:]
                for r in range(table.rowCount):
                    cp = table.getInputAtPosition(r, 3)
                    if cp.id == 'cp_' + pid:
                        cp.isVisible = _rule_is_named(changed)
                        break
            elif changed.id == 'loadTabs' and changed.value:
                changed.value = False  # reset the button
                url = _find_input(inputs, 'sheetUrl').value.strip()
                tab_dd = _find_input(inputs, 'tab')
                # Force a fresh download: the user clicked Load tabs, so any
                # cached bytes/rows from an earlier fetch in this session must
                # not mask edits made to the live Google Sheet since then.
                _xlsx_cache["url"] = None
                _xlsx_cache["bytes"] = None
                _rows_cache["key"] = None
                try:
                    tabs = list_tabs(url)
                except Exception as e:
                    _find_input(inputs, 'report').formattedText = \
                        '<font color="#c0392b">{}</font>'.format(str(e))
                    _build_report['ok'] = False
                    return
                # The URL resolved to a readable sheet: remember it on this design.
                save_design_url(adsk.fusion.Design.cast(app.activeProduct), url)
                tab_dd.listItems.clear()
                if not tabs:
                    tab_dd.listItems.add(CSV_ONLY_TAB_LABEL, True)
                    _find_input(inputs, 'report').formattedText = \
                        'This link has no selectable tabs; it will be read as a single CSV.'
                    _build_report['ok'] = True
                    _refresh_test_rows(inputs)
                    return
                settings = sheet_core.load_settings(SETTINGS_FILE)
                sid = sheet_core.extract_spreadsheet_id(url)
                pinned = load_pinned_tab(settings, sid) if sid else ''
                for i, name in enumerate(tabs):
                    tab_dd.listItems.add(name, name == pinned or (not pinned and i == 0))
                _run_build_validation(inputs)
                _refresh_test_rows(inputs)
            elif changed.id in ('tab', 'sheetUrl'):
                _run_build_validation(inputs)
                _refresh_test_rows(inputs)
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class ValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            args.areInputsValid = _build_report.get('ok', True)
        except Exception:
            args.areInputsValid = True


class BuildExecutePreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _preview_test_row(args.command.commandInputs)
            # Leave args.isValidResult False so the preview reverts on close/OK.
        except Exception:
            pass


class TemplateExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            use_favorites = inputs.itemById('source').selectedItem.name.startswith('Favorite')
            path, n = create_template(use_favorites)
            if path is None:
                return  # user cancelled the save dialog
            ui.messageBox(
                'Template with {} parameter column(s) saved to:\n{}\n\n'
                'In Google Sheets: File > Import > Upload, then fill in one row per variant. '
                'Use the same link with "Build Variants Assembly".'.format(n, path))
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class TemplateCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.setDialogInitialSize(380, 120)
            inputs = cmd.commandInputs

            dd = inputs.addDropDownCommandInput('source', 'Parameters',
                                                adsk.core.DropDownStyles.TextListDropDownStyle)
            dd.listItems.add('Favorite parameters', True)
            dd.listItems.add('All user parameters', False)
            dd.tooltip = 'Which parameters become columns in the template.'

            on_exec = TemplateExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


def find_tab_by_name(workspace, name):
    """Find a ribbon tab by its visible name (e.g. 'MANAGE')."""
    tabs = workspace.toolbarTabs
    target = name.strip().lower()
    for i in range(tabs.count):
        tab = tabs.item(i)
        try:
            if (tab.name or '').strip().lower() == target:
                return tab
        except Exception:
            pass
    return None


def get_manage_panel():
    """Create/return the add-in's own panel on the MANAGE tab of the Design
    workspace, falling back to UTILITIES > ADD-INS if the tab can't be found."""
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    if workspace:
        tab = find_tab_by_name(workspace, TAB_NAME)
        if tab:
            panel = tab.toolbarPanels.itemById(PANEL_ID) or \
                tab.toolbarPanels.add(PANEL_ID, PANEL_NAME)
            if panel:
                return panel
    return ui.allToolbarPanels.itemById(FALLBACK_PANEL_ID)


def cleanup_ui():
    """Remove our command controls and our custom panel from wherever they live,
    then delete the command definitions. Run on stop and again before (re)adding
    on start, because a panel ID is unique per workspace: a panel left behind on
    another tab by a previous load would otherwise be reused instead of a fresh
    one being created on the MANAGE tab. Safe to call repeatedly."""
    cmd_ids = (CMD_ID, TEST_CMD_ID, TEMPLATE_CMD_ID)
    panel_ids = (PANEL_ID,) + OBSOLETE_PANEL_IDS

    try:
        for wi in range(ui.workspaces.count):
            try:
                tabs = ui.workspaces.item(wi).toolbarTabs
            except Exception:
                continue
            for ti in range(tabs.count):
                try:
                    panels = tabs.item(ti).toolbarPanels
                except Exception:
                    continue
                stale = []
                for pi in range(panels.count):
                    panel = panels.item(pi)
                    for cid in cmd_ids:
                        ctrl = panel.controls.itemById(cid)
                        if ctrl:
                            ctrl.deleteMe()
                    if panel.id in panel_ids:
                        stale.append(panel)
                for panel in stale:
                    panel.deleteMe()
    except Exception:
        pass

    # Global sweep for any remaining instance of our panels.
    for pid in panel_ids:
        try:
            panel = ui.allToolbarPanels.itemById(pid)
            while panel:
                panel.deleteMe()
                panel = ui.allToolbarPanels.itemById(pid)
        except Exception:
            pass

    for cid in cmd_ids:
        try:
            cmd_def = ui.commandDefinitions.itemById(cid)
            if cmd_def:
                cmd_def.deleteMe()
        except Exception:
            pass


def run(context):
    try:
        cleanup_ui()  # clear any panel/commands a previous load left behind

        cmd_defs = ui.commandDefinitions
        cmd_def = cmd_defs.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC, BUILD_ICON_FOLDER)
        on_created = CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        tmpl_def = cmd_defs.addButtonDefinition(TEMPLATE_CMD_ID, TEMPLATE_CMD_NAME,
                                                TEMPLATE_CMD_DESC, TEMPLATE_ICON_FOLDER)
        on_tmpl_created = TemplateCreatedHandler()
        tmpl_def.commandCreated.add(on_tmpl_created)
        _handlers.append(on_tmpl_created)

        panel = get_manage_panel()
        if panel:
            for cmd_id, definition in ((CMD_ID, cmd_def), (TEMPLATE_CMD_ID, tmpl_def)):
                control = panel.controls.itemById(cmd_id) or panel.controls.addCommand(definition)
                if control:
                    # Show both buttons directly on the panel (not just the overflow).
                    control.isPromoted = True
                    control.isPromotedByDefault = True
    except Exception:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    try:
        cleanup_ui()
        _handlers.clear()
    except Exception:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
