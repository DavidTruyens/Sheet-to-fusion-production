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
import io
import csv
import json
import tempfile
import urllib.request

app = adsk.core.Application.get()
ui = app.userInterface

# Keep event handlers referenced so Python does not garbage-collect them.
_handlers = []

CMD_ID = 'sheetVariantsBuildAssemblyCmd'
CMD_NAME = 'Build Variants Assembly from Sheet'
CMD_DESC = ('Reads model variants from a Google Sheet, applies the parameters, '
            'exports each variant as SAT and assembles them in a new design.')

TEMPLATE_CMD_ID = 'sheetVariantsCreateTemplateCmd'
TEMPLATE_CMD_NAME = 'Create Variant Sheet Template'
TEMPLATE_CMD_DESC = ('Writes a CSV template whose columns are the model\'s favorite '
                     '(or user) parameters, ready to import into Google Sheets.')

PANEL_ID = 'SolidScriptsAddinsPanel'

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.json')


# --------------------------------------------------------------------------- #
# Small persistent settings (remembers the last URL / options between runs).
# --------------------------------------------------------------------------- #
def load_setting(key, default=''):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f).get(key, default)
    except Exception:
        return default


def save_setting(data):
    try:
        existing = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                existing = json.load(f)
        existing.update(data)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(existing, f)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Google Sheet reading. Works with no extra Python packages by pulling the
# sheet as CSV over HTTP (Fusion's bundled Python ships urllib + csv).
# --------------------------------------------------------------------------- #
def to_csv_url(url):
    """Turn a share / edit / publish link into a CSV-export link."""
    url = url.strip()
    if 'output=csv' in url or ('/export?' in url and 'format=csv' in url):
        return url
    # Published-to-web URL: .../d/e/<id>/pub...
    if re.search(r'/spreadsheets/d/e/[^/]+/pub', url):
        sep = '&' if '?' in url else '?'
        return url if 'output=csv' in url else url + sep + 'output=csv'
    # Standard share/edit URL: .../d/<id>/edit#gid=<gid>
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    if m:
        sheet_id = m.group(1)
        gid_match = re.search(r'[#&?]gid=(\d+)', url)
        gid = gid_match.group(1) if gid_match else '0'
        return 'https://docs.google.com/spreadsheets/d/{}/export?format=csv&gid={}'.format(sheet_id, gid)
    return url


def fetch_rows(url):
    csv_url = to_csv_url(url)
    req = urllib.request.Request(csv_url, headers={'User-Agent': 'Mozilla/5.0 (FusionAddin)'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode('utf-8-sig', errors='replace')

    head = raw.lstrip()[:200].lower()
    if head.startswith('<!doctype html') or '<html' in head:
        raise RuntimeError(
            'That URL returned a web page instead of CSV. Share the sheet as '
            '"Anyone with the link" or publish it to the web as CSV '
            '(File > Share > Publish to web > entire sheet > CSV).')

    rows = [r for r in csv.reader(io.StringIO(raw)) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise RuntimeError('The sheet needs a header row plus at least one variant row.')
    return rows


# --------------------------------------------------------------------------- #
# Core work.
# --------------------------------------------------------------------------- #
def build_assembly(sheet_url, spacing_cm, keep_sat):
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

    # Snapshot original expressions so we can restore the source model afterwards.
    original = {p: all_params.itemByName(p).expression for p in param_names}

    out_dir = os.path.join(tempfile.gettempdir(), 'sheet_variants_export')
    os.makedirs(out_dir, exist_ok=True)

    export_mgr = src_design.exportManager
    exported = []  # list of (component_name, sat_path)

    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show('Exporting variants', 'Exporting %v of %m', 0, len(rows) - 1, 0)

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
                        all_params.itemByName(pname).expression = val
            adsk.doEvents()  # let the parametric model recompute

            sat_path = os.path.join(out_dir, safe_name + '.sat')
            sat_opts = export_mgr.createSATExportOptions(sat_path, src_design.rootComponent)
            export_mgr.execute(sat_opts)
            exported.append((safe_name, sat_path))
            progress.progressValue = i + 1
    finally:
        # Always put the source model back the way we found it.
        for p, expr in original.items():
            try:
                all_params.itemByName(p).expression = expr
            except Exception:
                pass
        adsk.doEvents()
        progress.hide()

    if not exported:
        raise RuntimeError('No variants were exported.')

    # Assemble everything into a brand-new design document.
    new_doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    new_design = adsk.fusion.Design.cast(new_doc.products.itemByProductType('DesignProductType'))
    root = new_design.rootComponent
    import_mgr = app.importManager

    for i, (name, path) in enumerate(exported):
        transform = adsk.core.Matrix3D.create()
        transform.translation = adsk.core.Vector3D.create(i * spacing_cm, 0.0, 0.0)
        occ = root.occurrences.addNewComponent(transform)   # one component per variant
        occ.component.name = name
        sat_opts = import_mgr.createSATImportOptions(path)
        sat_opts.isViewFit = False
        import_mgr.importToTarget(sat_opts, occ.component)

    if not keep_sat:
        for _, path in exported:
            try:
                os.remove(path)
            except Exception:
                pass
        try:
            os.rmdir(out_dir)
        except Exception:
            pass

    return len(exported), (out_dir if keep_sat else None)


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
    # expected "value + unit" format is obvious.
    example = ['Variant_1'] + [p.expression for p in params]

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
            keep = inputs.itemById('keepSat').value
            if not url:
                ui.messageBox('Please paste the Google Sheet URL.')
                return

            save_setting({'sheet_url': url, 'spacing_mm': spacing_cm * 10.0, 'keep_sat': keep})
            count, kept_dir = build_assembly(url, spacing_cm, keep)

            msg = 'Done. Created an assembly with {} variant component(s).'.format(count)
            if kept_dir:
                msg += '\n\nSAT files kept in:\n{}'.format(kept_dir)
            ui.messageBox(msg)
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.setDialogInitialSize(460, 220)
            inputs = cmd.commandInputs

            url_in = inputs.addStringValueInput('sheetUrl', 'Google Sheet URL', load_setting('sheet_url', ''))
            url_in.tooltip = 'Share link or published-to-web CSV link of the sheet that holds your variants.'

            default_mm = float(load_setting('spacing_mm', 100.0))
            spacing_in = inputs.addValueInput(
                'spacing', 'Component spacing (mm)', 'mm',
                adsk.core.ValueInput.createByReal(default_mm / 10.0))
            spacing_in.tooltip = 'Gap between components along X in the new assembly. Set 0 to stack them at the origin.'

            inputs.addBoolValueInput('keepSat', 'Keep intermediate SAT files', True, '',
                                     bool(load_setting('keep_sat', False)))

            on_exec = CommandExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
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


def run(context):
    try:
        cmd_defs = ui.commandDefinitions
        cmd_def = cmd_defs.itemById(CMD_ID) or cmd_defs.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC)

        on_created = CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel and not panel.controls.itemById(CMD_ID):
            panel.controls.addCommand(cmd_def)

        # Template button.
        tmpl_def = cmd_defs.itemById(TEMPLATE_CMD_ID) or \
            cmd_defs.addButtonDefinition(TEMPLATE_CMD_ID, TEMPLATE_CMD_NAME, TEMPLATE_CMD_DESC)
        on_tmpl_created = TemplateCreatedHandler()
        tmpl_def.commandCreated.add(on_tmpl_created)
        _handlers.append(on_tmpl_created)
        if panel and not panel.controls.itemById(TEMPLATE_CMD_ID):
            panel.controls.addCommand(tmpl_def)
    except Exception:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    try:
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        for cid in (CMD_ID, TEMPLATE_CMD_ID):
            if panel:
                ctrl = panel.controls.itemById(cid)
                if ctrl:
                    ctrl.deleteMe()
            cmd_def = ui.commandDefinitions.itemById(cid)
            if cmd_def:
                cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
