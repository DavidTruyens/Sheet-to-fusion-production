# Spike 7 — which coordinate space is a placeholder body measured in?
#
# Update Children reports a box in a SUB-COMPONENT as "rotated" while boxes
# sitting directly in the layout read fine. The suspicion:
#
#   Fill    reads the box as a SELECTION PROXY  -> world coordinates
#   Update  reads it as attribute.parent        -> NATIVE body, whose geometry
#                                                  is relative to its parent
#                                                  component
#
# The child's occurrence.transform2 is world either way, so for a box inside a
# component with a non-identity transform the two disagree, and the mismatch
# surfaces as "rotated". That is a guess. This measures it.
#
# It also has to answer the SECOND question: which repair actually works. Two
# candidates are tried on every body found — reading bodies from an occurrence
# (proxies in context) and createForAssemblyContext — so the fix is chosen from
# what Fusion does rather than from what the API reference implies.
#
# READ-ONLY. It writes nothing and modifies nothing.
#
# Setup: open the LAYOUT that shows the problem, with boxes both directly in a
# layout component AND inside a sub-component. Run with the layout active.

import traceback

import adsk.core
import adsk.fusion

ATTR_GROUP = 'SheetVariants'
SLOT_ID_ATTR = 'slotId'
CHILD_RECIPE_ATTR = 'childRecipe'


def _seq(collection):
    """findAttributes returns an AttributeVector — a sequence with no .count."""
    try:
        return [collection.item(i) for i in range(collection.count)]
    except AttributeError:
        return [collection[i] for i in range(len(collection))]


def _flat_normals(body):
    """Unit normals of the body's flat faces, in whatever space it is in."""
    out = []
    try:
        faces = body.faces
        for i in range(faces.count):
            plane = adsk.core.Plane.cast(faces.item(i).geometry)
            if plane:
                n = plane.normal
                out.append((n.x, n.y, n.z))
    except Exception:
        pass
    return out


def _frame_of(occurrence):
    """The (width, depth, up) axes carried by an occurrence transform — the same
    columns placeholder_core.frame_from_matrix reads."""
    m = list(occurrence.transform2.asArray())
    return ((m[0], m[4], m[8]), (m[1], m[5], m[9]), (m[2], m[6], m[10]))


def _aligned(normals, frame, tolerance=1e-4):
    """placeholder_core.is_axis_aligned, inlined — a spike cannot import the
    add-in's modules."""
    for axis in frame:
        hit = False
        for n in normals:
            d = abs(n[0] * axis[0] + n[1] * axis[1] + n[2] * axis[2])
            if abs(d - 1.0) <= tolerance:
                hit = True
                break
        if not hit:
            return False
    return True


def _describe(label, normals, frame, notes):
    if not normals:
        notes.append('      {}: no flat faces read'.format(label))
        return
    notes.append('      {}: {} flat faces, axis-aligned = {}'.format(
        label, len(normals), _aligned(normals, frame)))
    shown = ['({:.3f},{:.3f},{:.3f})'.format(*n) for n in normals[:6]]
    notes.append('         {}'.format(' '.join(shown)))


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    notes = []
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open the layout design and run this again.')
            return
        root = design.rootComponent

        # --- the child occurrences, to recover each slot's world frame --------
        children = {}
        by_component = {}
        for i in range(root.occurrences.count):
            occurrence = root.occurrences.item(i)
            try:
                by_component.setdefault(occurrence.component.name, occurrence)
            except Exception:
                continue
        for attribute in _seq(design.findAttributes(ATTR_GROUP, CHILD_RECIPE_ATTR)):
            try:
                import json
                slot_id = (json.loads(attribute.value) or {}).get('slotId')
                occurrence = by_component.get(attribute.parent.name)
                if slot_id and occurrence:
                    children[slot_id] = occurrence
            except Exception:
                continue

        # --- candidate repair A: bodies read FROM an occurrence ---------------
        # occurrence.bRepBodies is meant to hand back proxies already in that
        # occurrence's context, i.e. world. If this works it is the whole fix.
        proxies = {}
        proxy_error = ''
        try:
            everywhere = [root] + [root.allOccurrences.item(i)
                                   for i in range(root.allOccurrences.count)]
            for holder in everywhere:
                try:
                    collection = holder.bRepBodies
                except Exception as err:
                    proxy_error = proxy_error or '{}'.format(err)
                    continue
                for i in range(collection.count):
                    body = collection.item(i)
                    try:
                        attr = body.attributes.itemByName(ATTR_GROUP, SLOT_ID_ATTR)
                    except Exception:
                        continue
                    if attr:
                        proxies.setdefault(attr.value, body)
        except Exception as err:
            proxy_error = '{}: {}'.format(type(err).__name__, err)

        notes.append('=== CANDIDATE A: occurrence.bRepBodies ===')
        notes.append('  found {} slot bod(ies) this way{}'.format(
            len(proxies), (' — error: ' + proxy_error) if proxy_error else ''))
        notes.append('')

        # --- every slot body, native vs each repair ---------------------------
        notes.append('=== EACH PLACEHOLDER ===')
        attributes = _seq(design.findAttributes(ATTR_GROUP, SLOT_ID_ATTR))
        notes.append('findAttributes found {} slot bod(ies)'.format(len(attributes)))
        notes.append('')
        for attribute in attributes:
            slot_id = attribute.value
            native = attribute.parent
            notes.append('  slot {}'.format(slot_id))
            try:
                notes.append('    body {!r} in component {!r}'.format(
                    native.name, native.parentComponent.name))
            except Exception as err:
                notes.append('    body unreadable ({})'.format(err))
                continue

            occurrence = children.get(slot_id)
            if not occurrence:
                notes.append('    no child occurrence — nothing to compare against')
                continue
            frame = _frame_of(occurrence)
            notes.append('    child frame (world): w={} d={} u={}'.format(
                *[tuple(round(c, 3) for c in axis) for axis in frame]))

            # What Update Children measures TODAY.
            _describe('NATIVE   (what Update uses today)',
                      _flat_normals(native), frame, notes)

            # Repair A.
            proxy = proxies.get(slot_id)
            if proxy is None:
                notes.append('      PROXY-A: not found for this slot')
            else:
                _describe('PROXY-A  (occurrence.bRepBodies)',
                          _flat_normals(proxy), frame, notes)

            # Repair B: createForAssemblyContext, needs the OWNING occurrence.
            owner = None
            try:
                for i in range(root.allOccurrences.count):
                    candidate = root.allOccurrences.item(i)
                    if candidate.component == native.parentComponent:
                        owner = candidate
                        break
            except Exception as err:
                notes.append('      PROXY-B: owner lookup failed ({})'.format(err))
            if owner is None:
                notes.append('      PROXY-B: body is not inside any occurrence '
                             '(root-level body — already world)')
            else:
                try:
                    _describe('PROXY-B  (createForAssemblyContext)',
                              _flat_normals(native.createForAssemblyContext(owner)),
                              frame, notes)
                    notes.append('         owner occurrence: {!r}'.format(
                        owner.fullPathName))
                except Exception as err:
                    notes.append('      PROXY-B RAISED: {}: {}'.format(
                        type(err).__name__, err))
            notes.append('')

        notes.append('=== HOW TO READ THIS ===')
        notes.append('For the box reported as rotated, look at axis-aligned:')
        notes.append('  NATIVE False + a PROXY True  -> confirmed, and that proxy')
        notes.append('     is the fix. Report which of A or B worked.')
        notes.append('  NATIVE True                  -> the space is NOT the')
        notes.append('     cause; something else reports it rotated.')
        notes.append('  every one False              -> the box really is turned')
        notes.append('     relative to its child, and the report is correct.')

        text = '\n'.join(notes)
        ui.messageBox(text[:9000])
        print(text)   # full text in the Text Commands palette
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
