# cutlist_cmd.py
# The Create Cut List CSV command: measure every part's smallest rectangular
# blank and write them out as a cut list, one line per distinct size.
#
# Imports adsk, so nothing here is unit-tested; the extents arithmetic, the
# offset, the grouping and the CSV shape all live in cutlist_core.py, which is.
#
# The blank follows the design's own axes. measureManager's box is used rather
# than BRepBody.boundingBox because it is measured rather than approximated —
# the plain bounding box can run loose around curved surfaces — and Spike 15
# confirmed the two agree exactly on a flat panel, so nothing is lost by
# preferring the tighter one.
#
# A part resting on a slope gets a blank bigger than itself and a Z that is not
# its thickness. Nothing measured along fixed axes can avoid that, so such a
# part is named in the report instead of passing silently.

import csv
import os
import re
import sys
import traceback

import adsk.core
import adsk.fusion

_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
# Fusion keeps one Python process alive across Stop/Run, so a helper module
# stays cached in sys.modules; drop it first so reloading the add-in picks up
# the current file. Same treatment the other helper modules get.
sys.modules.pop('cutlist_core', None)
import cutlist_core

app = adsk.core.Application.get()
ui = app.userInterface

CUTLIST_CMD_ID = 'sheetVariantsCutListCmd'
CUTLIST_CMD_NAME = 'Create Cut List CSV'
CUTLIST_CMD_DESC = ('Measures the smallest rectangular blank each part can be cut '
                    'from and writes them to a CSV: name, X, Y, Z and quantity, '
                    'with identical blanks grouped.')

# Icon resource folder (16x16/32x32/64x64 PNGs). Absolute so Fusion resolves it
# regardless of its current working directory, as the other commands' are.
_ICON_FOLDER = os.path.join(_ADDIN_DIR, 'resources', 'CutList')

# 1 cm in Fusion's internal units — 10 mm of material on every side.
DEFAULT_OFFSET_CM = 1.0

_handlers = []
_panel = None


# --------------------------------------------------------------------------- #
# Which bodies make up a part.
# --------------------------------------------------------------------------- #
def _solid_bodies_of(occurrence):
    """Solid bodies of an occurrence and everything beneath it, as proxies.

    A proxy carries its assembly-context position, which is what makes the
    measurement below describe where the part actually sits. Walked in Python
    rather than flattened with allOccurrences so one unreadable child costs
    only itself, matching how the rest of the add-in collects bodies.
    """
    try:
        bodies = [b for b in occurrence.bRepBodies if b.isSolid]
    except Exception:
        bodies = []
    try:
        children = list(occurrence.childOccurrences)
    except Exception:
        children = []
    for child in children:
        bodies.extend(_solid_bodies_of(child))
    return bodies


def _selected_parts(selection_input):
    """(name, bodies) for each picked entity, in the order they were picked."""
    parts = []
    for index in range(selection_input.selectionCount):
        try:
            entity = selection_input.selection(index).entity
        except Exception:
            continue
        occurrence = adsk.fusion.Occurrence.cast(entity)
        if occurrence:
            parts.append((occurrence.name, _solid_bodies_of(occurrence)))
            continue
        body = adsk.fusion.BRepBody.cast(entity)
        if body:
            parts.append((body.name, [body]))
    return parts


def _all_top_level_parts(design):
    """(name, bodies) for every top-level component, plus any loose root body.

    What the command measures when nothing is selected. Bodies owned by the
    root component itself belong to no occurrence, so they are listed under
    their own names rather than being lost.
    """
    root = design.rootComponent
    parts = []
    try:
        for body in root.bRepBodies:
            if body.isSolid:
                parts.append((body.name, [body]))
    except Exception:
        pass
    try:
        occurrences = list(root.occurrences)
    except Exception:
        occurrences = []
    for occurrence in occurrences:
        bodies = _solid_bodies_of(occurrence)
        if bodies:
            parts.append((occurrence.name, bodies))
    return parts


# --------------------------------------------------------------------------- #
# Measuring one part.
# --------------------------------------------------------------------------- #
def _extent_along(obb, direction):
    """How far an oriented box reaches along ``direction``.

    Asked for rather than assumed. The box comes back described by its own
    three axes, and projecting each of them onto the direction we care about
    gives the right answer whether or not Fusion hands back the axes in the
    order they were requested — and a merely conservative one if it ever hands
    back a box that is not aligned to the request at all.
    """
    return (abs(obb.lengthDirection.dotProduct(direction)) * obb.length
            + abs(obb.widthDirection.dotProduct(direction)) * obb.width
            + abs(obb.heightDirection.dotProduct(direction)) * obb.height)


def _world_box(measure, body):
    """One body's box on the design's axes, as union_extents() wants it."""
    x = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    y = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    z = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    obb = measure.getOrientedBoundingBox(body, x, y)
    if not obb:
        return None
    centre = obb.centerPoint
    return (centre.x, _extent_along(obb, x),
            centre.y, _extent_along(obb, y),
            centre.z, _extent_along(obb, z))


def _measure_part(measure, bodies):
    """The part's extents on the design's axes, in centimetres, or None.

    A body that will not measure drops out of the union rather than ending the
    part, the same way the rest of the add-in treats a body it cannot read — a
    part only fails when nothing in it could be measured at all.
    """
    boxes = []
    for body in bodies:
        try:
            box = _world_box(measure, body)
        except Exception:
            box = None
        if box:
            boxes.append(box)
    return cutlist_core.union_extents(boxes)


def _largest_flat_face_normal_z(bodies):
    """Z of the normal of the part's biggest flat face, or None if it has none.

    The biggest flat face is the one a panel rests on, which is why the tilt
    check asks about that one and not about every face: a chamfer or a bevel is
    a tilted plane on a part that is lying perfectly flat, and testing those
    would report almost every real part as tilted.
    """
    best_area = 0.0
    best_z = None
    for body in bodies:
        try:
            faces = list(body.faces)
        except Exception:
            faces = []
        for face in faces:
            try:
                plane = adsk.core.Plane.cast(face.geometry)
                if not plane:
                    continue
                area = face.area
            except Exception:
                continue
            if area > best_area:
                try:
                    normal = plane.normal
                    normal.normalize()
                except Exception:
                    continue
                best_area, best_z = area, normal.z
    return best_z


# --------------------------------------------------------------------------- #
# The run.
# --------------------------------------------------------------------------- #
def build_cut_list(parts, offset_mm, progress=None):
    """Measure every part. Returns (rows, warnings), or (None, warnings) if the
    run was cancelled. Rows are ``(name, x, y, z)`` in millimetres."""
    measure = app.measureManager
    rows, warnings = [], []
    for index, (name, bodies) in enumerate(parts):
        if progress:
            if progress.wasCancelled:
                return None, warnings
            progress.progressValue = index
        if not bodies:
            warnings.append('{}: no solid bodies, skipped.'.format(name))
            continue
        try:
            extents = _measure_part(measure, bodies)
        except Exception:
            extents = None
        if not extents:
            warnings.append('{}: could not be measured, skipped.'.format(name))
            continue
        dx, dy, dz = extents
        rows.append((name,) + cutlist_core.blank_dims(cutlist_core.cm_to_mm(dx),
                                                      cutlist_core.cm_to_mm(dy),
                                                      cutlist_core.cm_to_mm(dz),
                                                      offset_mm))
        normal_z = _largest_flat_face_normal_z(bodies)
        if normal_z is not None and cutlist_core.is_tilted(normal_z):
            warnings.append(
                '{}: sits tilted, so its blank is oversized and Z is not its '
                'thickness. Lay it flat and re-run.'.format(name))
    return rows, warnings


def _save_path():
    """Ask where the cut list goes. None if the save dialog was cancelled."""
    dialog = ui.createFileDialog()
    dialog.title = 'Save cut list'
    dialog.filter = 'CSV files (*.csv)'
    base = (app.activeDocument.name or 'cutlist').split(' v')[0]
    dialog.initialFilename = (
        (re.sub(r'[^A-Za-z0-9_\- ]', '_', base).strip() or 'parts') + '_cutlist.csv')
    if dialog.showSave() != adsk.core.DialogResults.DialogOK:
        return None
    path = dialog.filename
    if not path.lower().endswith('.csv'):
        path += '.csv'
    return path


def create_cut_list(parts, offset_mm):
    """Measure, ask where to save, write the CSV. Returns the report to show."""
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    try:
        progress.show('Measuring parts', 'Part %v of %m', 0, len(parts), 0)
        rows, warnings = build_cut_list(parts, offset_mm, progress)
    finally:
        progress.hide()

    if rows is None:
        return 'Cancelled.'
    if not rows:
        return '\n'.join(['Nothing was measured.'] + warnings)

    # Asked for after the measuring, not before: a run that measures nothing
    # should not first make you name a file for it.
    path = _save_path()
    if not path:
        return None

    lines = cutlist_core.csv_rows(rows)
    with open(path, 'w', newline='') as handle:
        csv.writer(handle).writerows(lines)

    report = ['Wrote {} blank{} from {} part{} to:'.format(
        len(lines) - 1, '' if len(lines) == 2 else 's',
        len(rows), '' if len(rows) == 1 else 's'), path]
    if warnings:
        report += [''] + warnings
    return '\n'.join(report)


# --------------------------------------------------------------------------- #
# Command wiring.
# --------------------------------------------------------------------------- #
class CutListExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                return
            inputs = args.command.commandInputs
            selection = inputs.itemById('parts')
            offset_input = inputs.itemById('offset')
            offset_mm = cutlist_core.cm_to_mm(offset_input.value) if offset_input else 0.0

            parts = (_selected_parts(selection)
                     if selection and selection.selectionCount
                     else _all_top_level_parts(design))
            if not parts:
                ui.messageBox('Nothing to measure: this design has no solid bodies.')
                return

            report = create_cut_list(parts, offset_mm)
            if report:
                ui.messageBox(report, CUTLIST_CMD_NAME)
        except Exception:
            ui.messageBox('Create Cut List failed:\n' + traceback.format_exc())


class CutListCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            # Without this, Fusion runs the command when another command
            # pre-empts it — the same reason the add-in's other commands set it.
            cmd.isExecutedWhenPreEmpted = False
            cmd.setDialogInitialSize(400, 200)
            inputs = cmd.commandInputs

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                inputs.addTextBoxCommandInput('err', '', 'Open a design first.', 2, True)
                return

            selection = inputs.addSelectionInput(
                'parts', 'Parts',
                'Components or bodies to measure. Leave empty to measure every '
                'top-level component.')
            selection.addSelectionFilter('Occurrences')
            selection.addSelectionFilter('SolidBodies')
            selection.setSelectionLimits(0, 0)

            offset = inputs.addValueInput(
                'offset', 'Offset per side', 'mm',
                adsk.core.ValueInput.createByReal(DEFAULT_OFFSET_CM))
            offset.tooltip = ('Spare material on every side of X and Y. Z is the '
                              'part\'s thickness and is never grown.')

            inputs.addTextBoxCommandInput(
                'note', '',
                'X and Y are the two larger sides of each part, Z the smallest. '
                'Identical blanks are grouped with a quantity.', 2, True)

            on_execute = CutListExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)
        except Exception:
            ui.messageBox('Failed:\n' + traceback.format_exc())


# (cmd_id, name, description, CommandCreatedEventHandler class), the shape
# register()/unregister() loop over — as in placeholder_cmds.
_COMMANDS = (
    (CUTLIST_CMD_ID, CUTLIST_CMD_NAME, CUTLIST_CMD_DESC, CutListCreatedHandler),
)


def register(panel):
    """Create the command definitions and add them to ``panel``. Handlers are kept
    in this module's _handlers list so Python does not garbage-collect them."""
    global _panel
    _panel = panel
    for cmd_id, name, desc, created_handler_cls in _COMMANDS:
        existing = ui.commandDefinitions.itemById(cmd_id)
        if existing:
            existing.deleteMe()
        # Guarded on the icons alone: an unreadable resource folder should cost
        # the button its picture, not its place on the panel.
        try:
            definition = ui.commandDefinitions.addButtonDefinition(
                cmd_id, name, desc, _ICON_FOLDER)
        except Exception:
            definition = ui.commandDefinitions.addButtonDefinition(cmd_id, name, desc)
        handler = created_handler_cls()
        definition.commandCreated.add(handler)
        _handlers.append(handler)
        control = (panel.controls.itemById(cmd_id)
                   or panel.controls.addCommand(definition))
        if control:
            # Otherwise the button lands in the panel's overflow ("...") menu
            # rather than on the panel, and looks like it was never registered.
            control.isPromoted = True
            control.isPromotedByDefault = True


def unregister():
    """Remove this module's command controls and definitions. Safe to call
    repeatedly, and safe if the panel has since been deleted."""
    global _panel
    for cmd_id, _name, _desc, _cls in _COMMANDS:
        if _panel:
            try:
                control = _panel.controls.itemById(cmd_id)
                if control:
                    control.deleteMe()
            except Exception:
                pass
        try:
            definition = ui.commandDefinitions.itemById(cmd_id)
            if definition:
                definition.deleteMe()
        except Exception:
            pass
    _handlers[:] = []
    _panel = None
