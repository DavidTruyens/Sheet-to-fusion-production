# build_engine.py
# The Fusion-side geometry core shared by the sheet-variants build and the
# placeholder-instantiation feature: apply parameter values, snapshot solids as
# temporary BReps, and put those snapshots into a component's base feature.
#
# This module imports adsk and therefore cannot be unit-tested; every rule that
# can be expressed without Fusion belongs in sheet_core.py or placeholder_core.py.
#
# The phase ordering these functions assume is documented in build_exports():
# creating or activating a document invalidates live references to any other
# design, so all reading must finish before any output work begins.

import os
import sys

import adsk.core
import adsk.fusion

_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
sys.modules.pop('placeholder_core', None)
import placeholder_core

app = adsk.core.Application.get()


def _design():
    """The active design, re-derived fresh. Never cache this across a parameter
    write: setting a driving dimension recomputes the model, which can invalidate
    a held collection so the object from the previous call is already dead."""
    return adsk.fusion.Design.cast(app.activeProduct)


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


def apply_values(values):
    """Write {parameter name: expression} into the active design. Blank values are
    skipped, leaving that parameter unchanged."""
    for name, raw in values.items():
        if not (raw or '').strip():
            continue
        param = _design().allParameters.itemByName(name)
        if param:
            apply_expression(param, raw)


def capture_values(names):
    """{name: current expression} for the named parameters, for later restoration."""
    params = _design().allParameters
    captured = {}
    for name in names:
        param = params.itemByName(name)
        if param:
            captured[name] = param.expression
    return captured


def restore_values(values):
    """Put captured expressions back. Best-effort per parameter: a failure on one
    must not leave the rest of the model in a variant state."""
    for name, expression in values.items():
        try:
            param = _design().allParameters.itemByName(name)
            if param:
                param.expression = expression
        except Exception:
            pass


def snapshot_bodies(bodies):
    """Copy each body to a temporary BRep, keeping its qualified name and its
    body-level appearance override and material. Bodies that cannot be copied are
    skipped rather than failing the run."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    snaps = []
    for body in bodies:
        try:
            temp = tbm.copy(body)
        except Exception:
            continue
        appearance = material = None
        component_name = body_name = ''
        try:
            appearance = body.appearance
        except Exception:
            pass
        try:
            material = body.material
        except Exception:
            pass
        try:
            component_name = body.parentComponent.name
        except Exception:
            pass
        try:
            body_name = body.name
        except Exception:
            pass
        snaps.append({
            'temp': temp,
            'appearance': appearance,
            'material': material,
            'name': placeholder_core.qualified_body_name(component_name, body_name),
        })
    return snaps


def transform_snapshot(snaps, matrix16):
    """Move every snapshotted body by a row-major 16-float matrix, in place."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    matrix = adsk.core.Matrix3D.create()
    matrix.setWithArray(matrix16)
    for snap in snaps:
        tbm.transform(snap['temp'], matrix)


def add_snapshot(component, snaps, base=None):
    """Add snapshotted bodies to ``component`` inside a base feature, creating one
    if not supplied. Returns the base feature."""
    if base is None:
        base = component.features.baseFeatures.add()
    base.startEdit()
    try:
        for snap in snaps:
            component.bRepBodies.add(snap['temp'], base)
    finally:
        base.finishEdit()
    return base


def appearance_in(design, src_appr):
    """The appearance named like ``src_appr`` inside ``design``, copied in once if
    needed. Lets a copied body show the source body's appearance (temporary BReps
    lose it). Returns None if it can't be copied."""
    try:
        existing = design.appearances.itemByName(src_appr.name)
        return existing or design.appearances.addByCopy(src_appr, src_appr.name)
    except Exception:
        return None


def material_in(design, src_mat):
    """The material named like ``src_mat`` inside ``design``, copied in once if
    needed. Returns None if it can't be copied."""
    try:
        existing = design.materials.itemByName(src_mat.name)
        return existing or design.materials.addByCopy(src_mat, src_mat.name)
    except Exception:
        return None


def reapply_looks(design, component, snaps):
    """Re-apply the source material and appearance to a component's bodies.

    Temporary BReps lose both, and the body objects returned during a base-feature
    edit go stale after finishEdit(), so fetch the component's bodies fresh and
    match them by index. Best-effort: the geometry is already built, so a failure
    just leaves the default look rather than breaking the build.
    """
    bodies = component.bRepBodies
    for index, snap in enumerate(snaps):
        if index >= bodies.count:
            break
        body = bodies.item(index)
        try:
            if snap['material']:
                material = material_in(design, snap['material'])
                if material:
                    body.material = material
            if snap['appearance']:
                appearance = appearance_in(design, snap['appearance'])
                if appearance:
                    body.appearance = appearance
        except Exception:
            pass  # geometry is built; a failed look just stays default
