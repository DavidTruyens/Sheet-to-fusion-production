# Spike 4 — joint origin API spelling, and is an anchor readable AFTER a recompute?
#
# The anchor is a NAMED joint origin, chosen because it survives the parameter
# changes this feature makes where a face reference would not. Two questions:
#
#   4a which spelling resolves? (Fusion has a long-standing upstream typo)
#   4b after driving the mother's parameters, can the anchor's position still be
#      read, and does it MOVE with the model?
#
# 4b is the load-bearing one. placeholder_cmds._snapshot_for() reads the anchor
# AFTER applying the config row and the box's width/depth/height, because the
# anchor moves with the geometry. If that read returns stale coordinates — or
# throws — every generated child lands in the wrong place.
#
# The first run of this spike reported "joint origins: 0" and skipped 4b, so this
# version BUILDS the scenario itself: a parameter-driven box with a joint origin
# on its top face, which must move when the parameter changes.
#
# Setup: none. It creates and closes its own document. If the ACTIVE design
# already has joint origins, it reports those too before building its own.

import traceback

import adsk.core
import adsk.fusion

app = adsk.core.Application.get()

PARAM = 'svSpikeHeight'
ANCHOR = 'SV_Anchor'


def _origins(component):
    """The joint-origin collection under whichever spelling this build exposes."""
    return (getattr(component, 'jointOrgins', None)
            or getattr(component, 'jointOrigins', None))


def _spelling_report():
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent if design else None
    misspelled = hasattr(root, 'jointOrgins') if root else False
    correct = hasattr(root, 'jointOrigins') if root else False
    lines = ['--- 4a: API spelling ---',
             'root.jointOrgins  exists: {}'.format(misspelled),
             'root.jointOrigins exists: {}'.format(correct)]
    if misspelled and correct:
        lines.append('BOTH exist on this build. Use "jointOrgins": older Fusion '
                     'builds have only the typo, so it is the compatible one.')
    elif misspelled:
        lines.append('USE: jointOrgins')
    elif correct:
        lines.append('USE: jointOrigins')
    else:
        lines.append('NEITHER resolves — investigate before Task 7.')
    if root:
        existing = _origins(root)
        count = existing.count if existing else 0
        lines.append('joint origins in the ACTIVE design: {}'.format(count))
        for i in range(count):
            try:
                point = existing.item(i).geometry.origin
                lines.append('  "{}" at ({:.3f}, {:.3f}, {:.3f})'
                             .format(existing.item(i).name, point.x, point.y, point.z))
            except Exception as err:
                lines.append('  "{}" unreadable — {}'
                             .format(existing.item(i).name, err))
    return lines


def _build_scenario():
    """A parameter-driven box with a named joint origin on its top face, in a
    fresh document. Returns (doc, design, joint_origin_name)."""
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    adsk.doEvents()
    design = adsk.fusion.Design.cast(
        doc.products.itemByProductType('DesignProductType'))
    root = design.rootComponent

    design.userParameters.add(
        PARAM, adsk.core.ValueInput.createByString('5 cm'), 'cm', 'spike height')

    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(10, 8, 0))
    extrude_input = root.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    extrude_input.setDistanceExtent(
        False, adsk.core.ValueInput.createByString(PARAM))
    root.features.extrudeFeatures.add(extrude_input)
    adsk.doEvents()

    # Anchor on the TOP face, so its Z tracks the parameter.
    body = root.bRepBodies.item(0)
    top, best = None, None
    for i in range(body.faces.count):
        face = body.faces.item(i)
        centroid = face.centroid
        if best is None or centroid.z > best:
            best, top = centroid.z, face
    geometry = adsk.fusion.JointGeometry.createByPlanarFace(
        top, None, adsk.fusion.JointKeyPointTypes.CenterKeyPoint)
    origins = _origins(root)
    joint_origin = origins.add(origins.createInput(geometry))
    joint_origin.name = ANCHOR
    adsk.doEvents()
    return doc, design


def run(context):
    ui = app.userInterface
    notes = []
    doc = None
    try:
        notes.extend(_spelling_report())
        notes.append('')
        notes.append('--- 4b: is the anchor readable after a recompute? ---')

        doc, design = _build_scenario()
        origins = _origins(design.rootComponent)
        before = origins.itemByName(ANCHOR).geometry.origin
        notes.append('built a {} box with "{}" on its top face'.format(PARAM, ANCHOR))
        notes.append('  anchor before: ({:.3f}, {:.3f}, {:.3f})'
                     .format(before.x, before.y, before.z))

        # Drive the parameter the way _snapshot_for does, then re-read the anchor
        # from a FRESHLY derived design — a recompute invalidates held objects.
        design.userParameters.itemByName(PARAM).expression = '12 cm'
        adsk.doEvents()
        fresh = adsk.fusion.Design.cast(app.activeProduct)
        after = _origins(fresh.rootComponent).itemByName(ANCHOR).geometry.origin
        notes.append('  set {} = 12 cm'.format(PARAM))
        notes.append('  anchor after:  ({:.3f}, {:.3f}, {:.3f})'
                     .format(after.x, after.y, after.z))

        moved = abs(after.z - before.z) > 1e-6
        expected = abs(after.z - 12.0) < 1e-6
        notes.append('  moved with the model: {}'.format(moved))
        notes.append('  landed at the new height (z == 12.000): {}'.format(expected))

        # And back again — a run restores the mother's parameters afterwards.
        design.userParameters.itemByName(PARAM).expression = '5 cm'
        adsk.doEvents()
        restored = _origins(adsk.fusion.Design.cast(app.activeProduct)
                            .rootComponent).itemByName(ANCHOR).geometry.origin
        back = abs(restored.z - before.z) < 1e-6
        notes.append('  after restoring the parameter, anchor returned: {}'.format(back))

        notes.append('')
        notes.append('SPIKE 4: ' + ('PASS' if (moved and expected and back) else 'FAIL'))
        if not (moved and expected and back):
            notes.append('The anchor does not track the recompute reliably. '
                         '_snapshot_for() reads it after driving the parameters, '
                         'so children would be misplaced. Report this before Task 9.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
    finally:
        if doc is not None:
            try:
                doc.close(False)
            except Exception:
                pass
