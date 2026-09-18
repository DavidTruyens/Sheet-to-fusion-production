# Spike 15 — does the cut list measure what it thinks it measures?
#
# The Create Cut List CSV command rests on claims about the Fusion API that CI
# cannot check, because none of them can be reproduced outside Fusion:
#
#   A. measureManager.getOrientedBoundingBox(body, u, v) exists, and the box it
#      returns is aligned to the frame it was ASKED for — so its three sides
#      really are the design's X, Y and Z — and it agrees with the plain
#      boundingBox, which is documented as world for a proxy.
#   B. A body read from an occurrence (a proxy) is measured in ASSEMBLY space,
#      so a part reports the size it presents where it sits rather than the
#      size it was drawn at. Only a part turned about Z can tell the two apart.
#   C. The blanks the command computes are the ones you would measure by hand.
#   D. A part sitting on a slope is detected, because nothing measured along
#      fixed axes can give it an honest thickness.
#
# The first run of this spike (12 parts, one plank tilted) is what removed the
# rotated-frame search from the command: it found the search picking a LARGER
# blank on the tilted plank, and buying 0.03%-0.67% on seven parts whose ends
# are slanted — each by trading more length for less width. The command now
# measures along the design's axes only, and this spike checks that.
#
# READ-ONLY. It writes nothing and modifies nothing.
#
# Setup: open a design with parts in it. To get an answer for B rather than
# "undetermined", ROTATE one top-level component ~30 degrees ABOUT Z first
# (Move/Copy, then undo it afterwards) — a tilt about X or Y will not do, since
# only a turn about Z changes what the part measures on the design's axes.

import math
import os
import sys
import traceback

import adsk.core
import adsk.fusion

# The real module, so this measures the shipped arithmetic rather than a copy.
_SPIKE_DIR = os.path.dirname(os.path.realpath(__file__))
_ADDIN_DIR = os.path.normpath(os.path.join(_SPIKE_DIR, '..', '..', 'SheetVariants'))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
try:
    sys.modules.pop('cutlist_core', None)
    import cutlist_core
except Exception:
    cutlist_core = None

MAX_PARTS_REPORTED = 20


def _vec(x, y, z):
    return adsk.core.Vector3D.create(x, y, z)


def _extent_along(obb, d):
    """Same formula the command uses: project the box's own axes onto d."""
    return (abs(obb.lengthDirection.dotProduct(d)) * obb.length
            + abs(obb.widthDirection.dotProduct(d)) * obb.width
            + abs(obb.heightDirection.dotProduct(d)) * obb.height)


def _world_box(measure, body):
    x, y, z = _vec(1, 0, 0), _vec(0, 1, 0), _vec(0, 0, 1)
    obb = measure.getOrientedBoundingBox(body, x, y)
    if not obb:
        return None
    c = obb.centerPoint
    return (c.x, _extent_along(obb, x),
            c.y, _extent_along(obb, y),
            c.z, _extent_along(obb, z))


def _measure_part(measure, bodies):
    boxes = []
    for b in bodies:
        try:
            box = _world_box(measure, b)
        except Exception:
            box = None
        if box:
            boxes.append(box)
    return cutlist_core.union_extents(boxes)


def _solid_bodies_of(occ):
    try:
        bodies = [b for b in occ.bRepBodies if b.isSolid]
    except Exception:
        bodies = []
    try:
        children = list(occ.childOccurrences)
    except Exception:
        children = []
    for child in children:
        bodies.extend(_solid_bodies_of(child))
    return bodies


def _rotation_about_z_deg(occ):
    """How far an occurrence is turned about Z, or None if it is not readable."""
    try:
        m = occ.transform2.asArray()
    except Exception:
        try:
            m = occ.transform.asArray()
        except Exception:
            return None
    # asArray() is row-major, so the transformed X axis is the first COLUMN:
    # indices 0, 4, 8. If it were column-major instead, this would read the
    # same rotation with the opposite sign — which changes the number printed
    # but not the only thing this is used for: finding a part that is turned.
    if len(m) < 5:
        return None
    xx, xy = m[0], m[4]
    if math.hypot(xx, xy) < 1e-9:
        return None
    return math.degrees(math.atan2(xy, xx)) % 90.0


def _largest_flat_face_normal_z(bodies):
    best_area, best_z = 0.0, None
    for b in bodies:
        try:
            faces = list(b.faces)
        except Exception:
            faces = []
        for face in faces:
            plane = adsk.core.Plane.cast(face.geometry)
            if not plane:
                continue
            try:
                area = face.area
            except Exception:
                continue
            if area > best_area:
                n = plane.normal
                n.normalize()
                best_area, best_z = area, n.z
    return best_z


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    out = ['Spike 15 — cut list bounding box', '']
    verdicts = []

    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open a design first.')
            return
        out.append('Design: {}'.format(app.activeDocument.name))
        out.append('cutlist_core imported: {}'.format(
            'yes' if cutlist_core else 'NO — checks B, C and D are skipped'))
        out.append('')

        root = design.rootComponent
        measure = app.measureManager

        parts = []
        for occ in root.occurrences:
            bodies = _solid_bodies_of(occ)
            if bodies:
                parts.append((occ, bodies))
        if not parts:
            ui.messageBox('No top-level components with solid bodies in this design.')
            return
        out.append('Top-level parts with solids: {}'.format(len(parts)))
        out.append('')

        sample = parts[0][1][0]

        # ---------------------------------------------------------------- #
        # A. Does the box honour the frame it was asked for?
        # ---------------------------------------------------------------- #
        out.append('A. getOrientedBoundingBox honours the design axes')
        try:
            x, y = _vec(1, 0, 0), _vec(0, 1, 0)
            obb = measure.getOrientedBoundingBox(sample, x, y)
            if not obb:
                out.append('   returned nothing                       FAIL')
                verdicts.append(False)
            else:
                ld, wd, hd = obb.lengthDirection, obb.widthDirection, obb.heightDirection
                out.append('   type:  {}'.format(obb.objectType))
                out.append('   asked length  (1, 0, 0) -> got ({:.3f}, {:.3f}, {:.3f})'
                           .format(ld.x, ld.y, ld.z))
                out.append('   asked width   (0, 1, 0) -> got ({:.3f}, {:.3f}, {:.3f})'
                           .format(wd.x, wd.y, wd.z))
                out.append('   height direction        -> ({:.3f}, {:.3f}, {:.3f})'
                           .format(hd.x, hd.y, hd.z))
                aligned = (abs(abs(ld.x) - 1.0) < 1e-6 and abs(abs(wd.y) - 1.0) < 1e-6
                           and abs(abs(hd.z) - 1.0) < 1e-6)
                out.append('   frame honoured: {}'.format('YES' if aligned else 'NO'))
                verdicts.append(aligned)

                bb = sample.boundingBox
                ax = bb.maxPoint.x - bb.minPoint.x
                ay = bb.maxPoint.y - bb.minPoint.y
                az = bb.maxPoint.z - bb.minPoint.z
                box = _world_box(measure, sample)
                out.append('   plain boundingBox:  {:.4f} x {:.4f} x {:.4f} cm'
                           .format(ax, ay, az))
                out.append('   measured box:       {:.4f} x {:.4f} x {:.4f} cm'
                           .format(box[1], box[3], box[5]))
                close = (abs(ax - box[1]) < 1e-3 and abs(ay - box[3]) < 1e-3
                         and abs(az - box[5]) < 1e-3)
                out.append('   agree: {}  ({})'.format(
                    'YES' if close else 'NO',
                    'same space' if close else 'DIFFERENT SPACES — investigate'))
                verdicts.append(close)
        except Exception as exc:
            out.append('   raised: {}                               FAIL'.format(exc))
            verdicts.append(False)
        out.append('')

        # ---------------------------------------------------------------- #
        # B. Proxy vs native, for a part actually turned about Z.
        # ---------------------------------------------------------------- #
        out.append('B. Proxy vs native body, on an occurrence turned about Z')
        rotated = None
        for occ, bodies in parts:
            turn = _rotation_about_z_deg(occ)
            if turn is not None and 0.5 < turn < 89.5:
                rotated = (occ, bodies, turn)
                break
        if not cutlist_core:
            out.append('   skipped — cutlist_core did not import')
        elif not rotated:
            out.append('   no top-level component is turned ABOUT Z')
            out.append('   -> UNDETERMINED. Turn one ~30 deg about Z and re-run.')
            out.append('      (A tilt about X or Y will not answer this.)')
        else:
            occ, bodies, turn = rotated
            out.append('   occurrence: {} (turned {:.2f} deg about Z)'
                       .format(occ.name, turn))
            try:
                native = occ.component.bRepBodies.item(0)
            except Exception:
                native = None
            pbox = _world_box(measure, bodies[0])
            out.append('   proxy : {:.4f} x {:.4f} cm'.format(pbox[1], pbox[3]))
            if native:
                nbox = _world_box(measure, native)
                out.append('   native: {:.4f} x {:.4f} cm'.format(nbox[1], nbox[3]))
                differ = (abs(pbox[1] - nbox[1]) > 1e-3 or abs(pbox[3] - nbox[3]) > 1e-3)
                out.append('   differ: {}  -> proxy is measured in {} space'.format(
                    'YES' if differ else 'no',
                    'ASSEMBLY' if differ else 'the SAME space as native (suspicious)'))
                verdicts.append(differ)
            else:
                out.append('   native body not readable — comparison skipped')
        out.append('')

        # ---------------------------------------------------------------- #
        # C. The blanks the command would write (offset 0).
        # ---------------------------------------------------------------- #
        out.append('C. Blanks as the command computes them (offset 0, mm)')
        if not cutlist_core:
            out.append('   skipped — cutlist_core did not import')
        else:
            for occ, bodies in parts[:MAX_PARTS_REPORTED]:
                extents = _measure_part(measure, bodies)
                if not extents:
                    out.append('   {:<24} could not be measured'.format(occ.name[:24]))
                    continue
                x, y, z = cutlist_core.blank_dims(
                    cutlist_core.cm_to_mm(extents[0]), cutlist_core.cm_to_mm(extents[1]),
                    cutlist_core.cm_to_mm(extents[2]), 0.0)
                out.append('   {:<24} {:>9.2f} x {:>8.2f} x {:>7.2f}'
                           .format(occ.name[:24], x, y, z))
            if len(parts) > MAX_PARTS_REPORTED:
                out.append('   ... and {} more'.format(len(parts) - MAX_PARTS_REPORTED))
            out.append('   -> check a couple against Fusion\'s own Measure tool')
        out.append('')

        # ---------------------------------------------------------------- #
        # D. Tilt detection.
        # ---------------------------------------------------------------- #
        out.append('D. Largest flat face of each part (tilt check)')
        if not cutlist_core:
            out.append('   skipped — cutlist_core did not import')
        else:
            for occ, bodies in parts[:MAX_PARTS_REPORTED]:
                nz = _largest_flat_face_normal_z(bodies)
                if nz is None:
                    out.append('   {:<24} no flat faces'.format(occ.name[:24]))
                else:
                    out.append('   {:<24} normal z {:+.4f}   {}'.format(
                        occ.name[:24], nz,
                        'TILTED' if cutlist_core.is_tilted(nz) else 'flat/upright'))
        out.append('')

        passed = all(verdicts) and bool(verdicts)
        out.append('VERDICT: {}'.format(
            'PASS — the cut list measures what it claims' if passed
            else 'FAIL / UNDETERMINED — see the lines marked above'))
        ui.messageBox('\n'.join(out), 'Spike 15')
    except Exception:
        ui.messageBox('\n'.join(out) + '\n\nSpike 15 blew up:\n' + traceback.format_exc())
