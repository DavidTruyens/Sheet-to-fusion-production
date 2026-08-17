# Spike 8 — where does a mother's colour actually live?
#
# build_engine.snapshot_bodies copies each body's BODY-LEVEL appearance override
# and its material, and nothing else. Fusion lets you assign an appearance in
# several other places — to an occurrence, or via the component's material — and
# a colour that lives there has no body-level override to copy, so the child is
# built plain.
#
# 1.18.3 added that fallback: the body's own override wins, then the nearest
# enclosing occurrence, then the component's material. This script stays useful
# for the case where colour STILL does not come through — it says whether the
# model carries any at all, and at which level, per body:
#
#   body.appearance          <- the only thing copied today
#   body.material            <- also copied today
#   occurrence.appearance    <- a candidate fallback
#   component.material       <- a candidate fallback
#
# If a body reports None at EVERY level, the child is a faithful copy of an
# uncoloured model and assigning a colour is the answer. If something is set and
# the child is still plain, the fallback is not reaching it and that is a bug
# worth reporting — say which level holds it.
#
# READ-ONLY. It writes nothing and modifies nothing.
#
# Setup: open the MOTHER model whose colours are not coming through, and run
# this with the mother as the active document.

import traceback

import adsk.core
import adsk.fusion


def _name_of(thing):
    """The name of an Appearance/Material, 'None' if unset, or why it would not
    read — some of these properties raise rather than return None."""
    if thing is None:
        return 'None'
    try:
        return repr(thing.name)
    except Exception as err:
        return 'unreadable ({})'.format(err)


def _read(obj, attribute):
    """(value, note). Distinguishes 'genuinely None' from 'raised'."""
    try:
        return getattr(obj, attribute), ''
    except Exception as err:
        return None, ' <{}: {}>'.format(type(err).__name__, err)


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    notes = []
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open the mother model and run this again.')
            return
        root = design.rootComponent
        notes.append('=== {} ==='.format(app.activeDocument.name))
        notes.append('')

        # Same collection the add-in uses, so this reports on exactly the bodies
        # that would be snapshotted.
        holders = [('root', root)]
        try:
            for i in range(root.allOccurrences.count):
                occurrence = root.allOccurrences.item(i)
                holders.append((occurrence.fullPathName, occurrence))
        except Exception as err:
            notes.append('allOccurrences unreadable ({})'.format(err))

        body_appearance = occ_appearance = comp_material = body_material = 0
        total = 0
        for label, holder in holders:
            try:
                bodies = [b for b in holder.bRepBodies if b.isSolid]
            except Exception as err:
                notes.append('{}: bodies unreadable ({})'.format(label, err))
                continue
            if not bodies:
                continue
            notes.append('{}:'.format(label))

            # The occurrence's own appearance override, if this is one.
            occ_app = None
            if holder is not root:
                occ_app, note = _read(holder, 'appearance')
                notes.append('    occurrence.appearance = {}{}'.format(
                    _name_of(occ_app), note))
                if occ_app is not None:
                    occ_appearance += 1

            for body in bodies:
                total += 1
                try:
                    body_label = body.name
                except Exception:
                    body_label = '?'
                app_value, app_note = _read(body, 'appearance')
                mat_value, mat_note = _read(body, 'material')
                comp_mat = None
                try:
                    comp_mat, comp_note = _read(body.parentComponent, 'material')
                except Exception as err:
                    comp_note = ' <{}>'.format(err)
                if app_value is not None:
                    body_appearance += 1
                if mat_value is not None:
                    body_material += 1
                if comp_mat is not None:
                    comp_material += 1
                notes.append('    {}:'.format(body_label))
                notes.append('        body.appearance      = {}{}   <- copied today'
                             .format(_name_of(app_value), app_note))
                notes.append('        body.material        = {}{}   <- copied today'
                             .format(_name_of(mat_value), mat_note))
                notes.append('        component.material   = {}{}'.format(
                    _name_of(comp_mat), comp_note))
        notes.append('')

        notes.append('=== VERDICT ===')
        notes.append('{} solid bod(ies) examined.'.format(total))
        notes.append('  with a body-level appearance : {}'.format(body_appearance))
        notes.append('  with a body material         : {}'.format(body_material))
        notes.append('  whose component has material : {}'.format(comp_material))
        notes.append('  occurrences with appearance  : {}'.format(occ_appearance))
        notes.append('')
        if body_appearance == 0 and body_material == 0:
            if occ_appearance or comp_material:
                notes.append('NOTHING is set at BODY level, but the occurrence or')
                notes.append('component carries it. That is why children come out')
                notes.append('plain, and a fallback up that chain would fix it.')
                notes.append('Report this — it is a change worth making.')
            else:
                notes.append('No colour anywhere, at any level. The children are a')
                notes.append('faithful copy of a model with no colour: assign one')
                notes.append('to the BODIES and they will come through. Nothing to')
                notes.append('fix in the add-in.')
        else:
            notes.append('Some bodies DO carry a body-level appearance/material,')
            notes.append('so those should already come through. If they did not,')
            notes.append('the problem is in applying them, not in reading them —')
            notes.append('report which bodies above have one and still came out')
            notes.append('plain.')

        text = '\n'.join(notes)
        ui.messageBox(text[:9000])
        print(text)   # full text in the Text Commands palette
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
