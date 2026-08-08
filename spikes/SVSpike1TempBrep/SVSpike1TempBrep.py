# Spike 1 — do TemporaryBRepManager bodies survive activating and closing other
# documents, and can they still be inserted afterwards?
#
# This is the load-bearing assumption behind the whole cross-document engine:
# Phase 1 snapshots geometry with the mother active, Phase 2 inserts it with the
# layout active. If a snapshot dies when another document is activated, the two
# phases cannot be separated and the design has to change shape.
#
# build_exports() already proves snapshots survive documents.add(). This goes
# further: activate a real second design, create AND close a scratch document,
# come back, then actually insert.
#
# It also probes app.data.findFileById(), which Plan 1's _open_mother() needs to
# reopen a mother by id. app.data.activeProject is deliberately NOT used — it
# throws InternalValidationError when the Data Panel has not resolved, which is
# a property of the session, not of anything this design depends on.
#
# Setup: open a document containing at least one solid body. Having a second
# document open as well makes the test stronger but is not required.

import traceback

import adsk.core
import adsk.fusion


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    notes = []
    checks = {}
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open a design with a solid body first.')
            return

        source_doc = app.activeDocument
        bodies = [b for b in design.rootComponent.bRepBodies if b.isSolid]
        for occurrence in design.rootComponent.allOccurrences:
            bodies.extend(b for b in occurrence.bRepBodies if b.isSolid)
        if not bodies:
            ui.messageBox('This design has no solid bodies to snapshot.')
            return

        tbm = adsk.fusion.TemporaryBRepManager.get()
        temp = tbm.copy(bodies[0])
        volume_before = temp.volume
        notes.append('volume before: {:.6f}'.format(volume_before))
        notes.append('')

        # --- probe app.data.findFileById --------------------------------------
        # Plan 1 reopens a mother with exactly this call. If it is unreliable
        # here, _open_mother() needs a different strategy — better to know now.
        notes.append('--- app.data probe ---')
        probe_id = None
        for i in range(app.documents.count):
            try:
                data_file = app.documents.item(i).dataFile
                if data_file:
                    probe_id = data_file.id
                    notes.append('probing with "{}"'.format(app.documents.item(i).name))
                    break
            except Exception:
                continue
        if probe_id is None:
            notes.append('no saved document open — findFileById NOT exercised')
            checks['findFileById'] = None
        else:
            try:
                found = app.data.findFileById(probe_id)
                checks['findFileById'] = found is not None
                notes.append('findFileById: {}'.format(
                    'resolved "{}" v{}'.format(found.name, found.versionNumber)
                    if found else 'returned None'))
            except Exception as err:
                checks['findFileById'] = False
                notes.append('findFileById FAILED — {}'.format(err))
        notes.append('')

        # --- activate a real second design, if one is open --------------------
        notes.append('--- document switching ---')
        other = None
        for i in range(app.documents.count):
            candidate = app.documents.item(i)
            if candidate is not source_doc:
                other = candidate
                break
        if other:
            notes.append('activating "{}"'.format(other.name))
            other.activate()
            adsk.doEvents()
        else:
            notes.append('only one document open — activation of an existing '
                         'design NOT exercised')

        # --- create a scratch document, activate it, close it ------------------
        scratch = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        adsk.doEvents()
        notes.append('created and activated a scratch document')
        scratch.close(False)
        adsk.doEvents()
        notes.append('closed the scratch document')

        source_doc.activate()
        adsk.doEvents()
        notes.append('re-activated "{}"'.format(source_doc.name))
        notes.append('')

        # --- is the snapshot still alive? -------------------------------------
        notes.append('--- snapshot survival ---')
        try:
            volume_after = temp.volume
            notes.append('volume after:  {:.6f}'.format(volume_after))
            checks['alive'] = (abs(volume_after - volume_before) < 1e-9
                               and volume_after > 0)
        except Exception as err:
            notes.append('volume after:  FAILED — {}'.format(err))
            checks['alive'] = False

        # --- and can it still be INSERTED? This is what Phase 2 actually does.
        try:
            new_doc = app.documents.add(
                adsk.core.DocumentTypes.FusionDesignDocumentType)
            new_design = adsk.fusion.Design.cast(
                new_doc.products.itemByProductType('DesignProductType'))
            root = new_design.rootComponent
            base = root.features.baseFeatures.add()
            base.startEdit()
            try:
                root.bRepBodies.add(temp, base)
            finally:
                base.finishEdit()
            adsk.doEvents()
            checks['inserted'] = root.bRepBodies.count > 0
            notes.append('inserted into a fresh document: {} body(s), volume {:.6f}'
                         .format(root.bRepBodies.count,
                                 root.bRepBodies.item(0).volume))
            notes.append('(that new untitled document can be closed without saving)')
        except Exception:
            checks['inserted'] = False
            notes.append('insert FAILED:\n' + traceback.format_exc())

        # --- verdict -----------------------------------------------------------
        passed = checks.get('alive') and checks.get('inserted')
        notes.append('')
        notes.append('SPIKE 1: ' + ('PASS' if passed else 'FAIL'))
        if not passed:
            notes.append('Fallback: snapshot into a hidden staging design while '
                         'the mother is active, then copy from staging into the '
                         'layout. Revise the spec before starting Plan 1.')
        if checks.get('findFileById') is False:
            notes.append('')
            notes.append('SEPARATE PROBLEM: findFileById does not work here, so '
                         'Plan 1 Task 9 _open_mother() cannot reopen a mother by '
                         'id. Report this — it needs its own answer.')
        elif checks.get('findFileById') is None:
            notes.append('')
            notes.append('findFileById was not exercised. Re-run with a saved '
                         'document open to confirm Plan 1 can reopen mothers.')
        if not other:
            notes.append('')
            notes.append('Only one document was open, so switching to an existing '
                         'design was not tested. Re-run with two open for the '
                         'stronger result.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
