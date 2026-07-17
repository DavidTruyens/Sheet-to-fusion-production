# SheetVariants.py
# Fusion add-in: read parametric variants from a Google Sheet, apply the
# parameters to the active model, export each variant as SAT, then assemble
# all variants as separate components in a new design document.
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
import sheet_core

app = adsk.core.Application.get()
ui = app.userInterface

# Keep event handlers referenced so Python does not garbage-collect them.
_handlers = []

# Component names of the active design at the moment the Build dialog opened,
# used to populate each named-components profile's checkbox-dropdown.
_component_name_cache = []

CMD_ID = 'sheetVariantsBuildAssemblyCmd'
CMD_NAME = 'Build Variants Assembly from Sheet'
CMD_DESC = ('Reads model variants from a Google Sheet, applies the parameters, '
            'and assembles a copy of each variant as a component in a new design.')

TEMPLATE_CMD_ID = 'sheetVariantsCreateTemplateCmd'
TEMPLATE_CMD_NAME = 'Create Variant Sheet Template'
TEMPLATE_CMD_DESC = ('Writes a CSV template whose columns are the model\'s favorite '
                     '(or user) parameters, ready to import into Google Sheets.')

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


def build_exports(sheet_url, spacing_cm, profiles):
    """Build one new design per enabled profile. Recomputes each variant once
    and feeds every profile. Returns per-profile result dicts for reporting."""
    rows = fetch_rows(sheet_url)
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
        ctx = {'profile': prof, 'name': prof.get('name') or 'Export', 'design': None,
               'root': None, 'x_cursor': 0.0, 'built': 0, 'warnings': [], 'skipped': False}
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
                        apply_expression(all_params.itemByName(pname), val)
            adsk.doEvents()  # single recompute shared by all profiles

            for ctx in active:
                resolver = RESOLVERS[ctx['profile']['rule']]
                src_bodies, _warn = resolver(src_design, ctx['profile'])
                temp_bodies = []
                for body in src_bodies:
                    try:
                        temp_bodies.append(tbm.copy(body))
                    except Exception:
                        pass
                if not temp_bodies:
                    continue

                if ctx['design'] is None:   # create output design lazily
                    new_doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
                    nd = adsk.fusion.Design.cast(new_doc.products.itemByProductType('DesignProductType'))
                    ctx['design'] = nd
                    ctx['root'] = nd.rootComponent
                    try:
                        nd.rootComponent.name = ctx['name']
                    except Exception:
                        pass

                root = ctx['root']
                min_x = min(tb.boundingBox.minPoint.x for tb in temp_bodies)
                max_x = max(tb.boundingBox.maxPoint.x for tb in temp_bodies)
                transform = adsk.core.Matrix3D.create()
                transform.translation = adsk.core.Vector3D.create(ctx['x_cursor'] - min_x, 0.0, 0.0)
                occ = root.occurrences.addNewComponent(transform)
                occ.component.name = safe_name
                base = occ.component.features.baseFeatures.add()
                base.startEdit()
                try:
                    for tb in temp_bodies:
                        occ.component.bRepBodies.add(tb, base)
                finally:
                    base.finishEdit()
                ctx['x_cursor'] += (max_x - min_x) + spacing_cm
                ctx['built'] += 1

            progress.progressValue = i + 1
    finally:
        for p, expr in original.items():
            try:
                all_params.itemByName(p).expression = expr
            except Exception:
                pass
        adsk.doEvents()
        progress.hide()

    for ctx in active:
        if ctx['built'] == 0 and not ctx['skipped']:
            ctx['skipped'] = True
            if not ctx['warnings']:
                ctx['warnings'] = ['no solid bodies matched']

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
# Command handlers / UI.
# --------------------------------------------------------------------------- #
class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            url = inputs.itemById('sheetUrl').value.strip()
            spacing_cm = inputs.itemById('spacing').value      # ValueInput returns internal cm
            if not url:
                ui.messageBox('Please paste the Google Sheet URL.')
                return

            settings = sheet_core.load_settings(SETTINGS_FILE)
            profiles = _read_profiles(inputs.itemById('profiles'))
            settings['sheet_url'] = url
            settings['spacing_mm'] = spacing_cm * 10.0
            settings['profiles'] = profiles
            sheet_core.save_settings(SETTINGS_FILE, settings)
            results = build_exports(url, spacing_cm, profiles)
            ui.messageBox(sheet_core.summarize_results(results))
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            global _component_name_cache
            cmd = args.command
            cmd.setDialogInitialSize(560, 360)
            inputs = cmd.commandInputs

            settings = sheet_core.load_settings(SETTINGS_FILE)

            url_in = inputs.addStringValueInput('sheetUrl', 'Google Sheet URL', settings.get('sheet_url', ''))
            url_in.tooltip = 'Share link or published-to-web CSV link of the sheet that holds your variants.'

            default_mm = float(settings.get('spacing_mm', 100.0))
            spacing_in = inputs.addValueInput('spacing', 'Gap between variants (mm)', 'mm',
                                              adsk.core.ValueInput.createByReal(default_mm / 10.0))
            spacing_in.tooltip = ('Clear space left between each variant\'s bounding box along X. '
                                  'Set 0 to butt them together.')

            # Cache the active design's component names for the checkbox-dropdowns.
            src = adsk.fusion.Design.cast(app.activeProduct)
            _component_name_cache = component_names(src) if src else []

            table = inputs.addTableCommandInput('profiles', 'Export profiles', 4, '1:3:2:3')
            table.minimumVisibleRows = 2
            table.maximumVisibleRows = 8
            table.columnSpacing = 1
            table.rowSpacing = 1

            add_btn = inputs.addBoolValueInput('profileAdd', 'Add', False, '', False)
            add_btn.tooltip = 'Add an export profile'
            del_btn = inputs.addBoolValueInput('profileDelete', 'Remove', False, '', False)
            del_btn.tooltip = 'Remove the selected export profile'
            table.addToolbarCommandInput(add_btn)
            table.addToolbarCommandInput(del_btn)

            for profile in settings['profiles']:
                _add_profile_row(table, profile)

            if not _component_name_cache:
                note = inputs.addTextBoxCommandInput('compNote', '', '', 2, True)
                note.text = ('Open your source design before running to pick components '
                             'for "Named components" profiles.')

            on_exec = CommandExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)

            on_changed = BuildInputChangedHandler()
            cmd.inputChanged.add(on_changed)
            _handlers.append(on_changed)
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class BuildInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            changed = args.input
            table = args.inputs.itemById('profiles')
            if table is None:
                return
            if changed.id == 'profileAdd':
                existing = [table.getInputAtPosition(r, 1).id[3:] for r in range(table.rowCount)]
                pid = sheet_core.next_profile_id(existing)
                _add_profile_row(table, {'id': pid, 'name': 'Export ' + pid,
                                         'enabled': True, 'rule': 'whole_model', 'components': []})
            elif changed.id == 'profileDelete':
                if table.selectedRow >= 0:
                    table.deleteRow(table.selectedRow)
            elif changed.id.startswith('rl_'):
                pid = changed.id[3:]
                for r in range(table.rowCount):
                    cp = table.getInputAtPosition(r, 3)
                    if cp.id == 'cp_' + pid:
                        cp.isVisible = _rule_is_named(changed)
                        break
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


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
    cmd_ids = (CMD_ID, TEMPLATE_CMD_ID)
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
