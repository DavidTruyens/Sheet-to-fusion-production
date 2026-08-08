# Spike 4 — how is the joint-origin collection spelled, and can a joint origin's
# position be read after a parameter change?
#
# The anchor is a NAMED joint origin, chosen because it survives the parameter
# changes this feature makes where a face reference would not. Two things to
# confirm: the API property name (long-standing upstream typo), and that the
# origin's position moves with the model so it can be read after the recompute.
#
# Setup: a design containing at least one joint origin. Ideally one whose
# position depends on a parameter, so the second half is meaningful.

import traceback

import adsk.core
import adsk.fusion


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    notes = []
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open a design first.')
            return
        root = design.rootComponent

        misspelled = hasattr(root, 'jointOrgins')
        correct = hasattr(root, 'jointOrigins')
        notes.append('root.jointOrgins  exists: {}'.format(misspelled))
        notes.append('root.jointOrigins exists: {}'.format(correct))
        notes.append('')
        notes.append('USE THIS SPELLING IN placeholder_cmds.py: {}'
                     .format('jointOrgins' if misspelled else
                             'jointOrigins' if correct else 'NEITHER — investigate'))

        origins = getattr(root, 'jointOrgins', None) or getattr(root, 'jointOrigins', None)
        if origins is None:
            notes.append('')
            notes.append('SPIKE 4: FAIL — neither spelling resolves.')
            ui.messageBox('\n'.join(notes))
            return

        notes.append('')
        notes.append('joint origins in the root component: {}'.format(origins.count))
        for i in range(origins.count):
            origin = origins.item(i)
            try:
                point = origin.geometry.origin
                notes.append('  "{}" at ({:.3f}, {:.3f}, {:.3f})'
                             .format(origin.name, point.x, point.y, point.z))
            except Exception as err:
                notes.append('  "{}" position unreadable — {}'
                             .format(origin.name, err))

        if origins.count == 0:
            notes.append('')
            notes.append('Add a joint origin (Assemble > Joint Origin) and re-run '
                         'to see whether its position tracks a parameter change.')
            ui.messageBox('\n'.join(notes))
            return

        # Does the origin's position follow a recompute? _snapshot_for() reads the
        # anchor AFTER driving the parameters, so it must.
        params = design.userParameters
        if params.count == 0:
            notes.append('')
            notes.append('No user parameters to nudge — position-after-recompute '
                         'not tested. Add one and re-run if the anchor depends on it.')
            ui.messageBox('\n'.join(notes))
            return

        param = params.item(0)
        original = param.expression
        first = origins.item(0)
        name = first.name
        before = first.geometry.origin
        try:
            param.expression = '({}) * 1.5'.format(original)
            adsk.doEvents()
            fresh_root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
            fresh = (getattr(fresh_root, 'jointOrgins', None)
                     or getattr(fresh_root, 'jointOrigins')).itemByName(name)
            after = fresh.geometry.origin
            notes.append('')
            notes.append('nudged parameter "{}": {} -> *1.5'.format(param.name, original))
            notes.append('  anchor before: ({:.3f}, {:.3f}, {:.3f})'
                         .format(before.x, before.y, before.z))
            notes.append('  anchor after:  ({:.3f}, {:.3f}, {:.3f})'
                         .format(after.x, after.y, after.z))
            notes.append('  (identical is fine if the anchor does not depend on '
                         'this parameter — what matters is that it was READABLE '
                         'after the recompute)')
        finally:
            param.expression = original
            adsk.doEvents()
            notes.append('  parameter restored')

        notes.append('')
        notes.append('SPIKE 4: PASS')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
