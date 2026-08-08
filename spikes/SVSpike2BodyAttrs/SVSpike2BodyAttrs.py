# Spike 2 — do attributes stamped on a BRepBody survive recompute, timeline
# rollback and save/reopen, and does Design.findAttributes still find them?
#
# Slot identity is an attribute stamped on the placeholder box. If it does not
# survive, identity has to fall back to body names and renaming a box silently
# orphans its child. Discovery also depends on findAttributes returning the whole
# set in one call.
#
# Setup: a SAVED document with at least one parametric solid body (sketch +
# extrude) and at least one user parameter to change.
#
# Run it TWICE. The first run stamps and tells you what to do; the second run
# verifies. No editing needed — it detects which phase it is in.

import traceback

import adsk.core
import adsk.fusion

GROUP = 'SheetVariants'
NAME = 'slotId'
VALUE = 'slot-deadbeef'


def _attribute_list(found):
    """findAttributes() returns an AttributeVector, which is NOT a Fusion
    collection — it has no .count/.item(i). Try each shape and report which one
    works, so the plans can use the proven access pattern rather than a guess."""
    try:
        return [found.item(i) for i in range(found.count)], 'count/item'
    except AttributeError:
        pass
    try:
        return [found[i] for i in range(len(found))], 'len/index'
    except (TypeError, AttributeError):
        pass
    try:
        return list(found), 'iteration'
    except TypeError:
        return None, 'NONE WORKED'


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open a design first.')
            return

        bodies = [b for b in design.rootComponent.bRepBodies if b.isSolid]
        if not bodies:
            ui.messageBox('This design has no solid body in the root component.')
            return
        body = bodies[0]

        existing = body.attributes.itemByName(GROUP, NAME)
        if not existing:
            body.attributes.add(GROUP, NAME, VALUE)
            ui.messageBox(
                'STAMPED "{}" on body "{}".\n\n'
                'Now do all of these, then run this script again:\n\n'
                '  1. Change a user parameter so the model recomputes\n'
                '  2. Drag the timeline marker back before the extrude, '
                'then forward again\n'
                '  3. Save the document\n'
                '  4. Close it and reopen it\n\n'
                'The second run verifies the attribute survived.'
                .format(VALUE, body.name))
            return

        # --- verification phase ---------------------------------------------
        notes = ['direct read: {}'.format(existing.value)]
        direct_ok = existing.value == VALUE

        found = design.findAttributes(GROUP, NAME)
        notes.append('findAttributes returns: {}'.format(type(found).__name__))
        attributes, access = _attribute_list(found)
        notes.append('working access pattern: {}   <-- USE THIS IN THE PLANS'
                     .format(access))
        if attributes is None:
            notes.append('')
            notes.append('SPIKE 2: FAIL — findAttributes result is unreadable, so '
                         'child and slot discovery needs a different mechanism.')
            ui.messageBox('\n'.join(notes))
            return
        notes.append('findAttributes count: {}'.format(len(attributes)))
        find_ok = len(attributes) >= 1

        parent_ok = False
        for attribute in attributes:
            try:
                parent = attribute.parent
                is_body = isinstance(parent, adsk.fusion.BRepBody)
                notes.append('  value={} parent={} isBody={}'
                             .format(attribute.value, parent.name, is_body))
                if is_body and attribute.value == VALUE:
                    parent_ok = True
            except Exception as err:
                notes.append('  parent unreadable — {}'.format(err))

        verdict = 'PASS' if (direct_ok and find_ok and parent_ok) else 'FAIL'
        notes.append('')
        notes.append('SPIKE 2: ' + verdict)
        if verdict == 'FAIL':
            notes.append('Fallback: slot identity becomes (component name, body '
                         'name) stored in childRecipe, and the spec must state '
                         'that renaming a placeholder orphans its child.')
        notes.append('')
        notes.append('To re-run from scratch, delete the attribute in the '
                     'browser or use a fresh document.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('Unhandled:\n' + traceback.format_exc())
