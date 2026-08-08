# Spike 1 — do TemporaryBRepManager bodies survive activating and closing a
# DIFFERENT document, and can they still be inserted afterwards?
#
# This is the load-bearing assumption behind the whole cross-document engine:
# Phase 1 snapshots geometry with the mother active, Phase 2 inserts it with the
# layout active. If a snapshot dies when another document is activated, the two
# phases cannot be separated and the design has to change shape.
#
# build_exports() already proves snapshots survive documents.add(). This goes
# further: open, activate and CLOSE another document, then actually insert.
#
# Setup: open a document containing at least one solid body, and have at least
# one other saved document in the same project. Run this script.

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
            ui.messageBox('Open a design with a solid body first.')
            return

        source_bodies = [b for b in design.rootComponent.bRepBodies if b.isSolid]
        for occurrence in design.rootComponent.allOccurrences:
            source_bodies.extend(b for b in occurrence.bRepBodies if b.isSolid)
        if not source_bodies:
            ui.messageBox('This design has no solid bodies to snapshot.')
            return

        tbm = adsk.fusion.TemporaryBRepManager.get()
        temp = tbm.copy(source_bodies[0])
        volume_before = temp.volume
        notes.append('volume before: {:.6f}'.format(volume_before))

        # --- open, activate and close a DIFFERENT document -------------------
        active_file = app.activeDocument.dataFile
        active_id = active_file.id if active_file else None
        other = None
        files = app.data.activeProject.rootFolder.dataFiles
        for i in range(files.count):
            candidate = files.item(i)
            if candidate.id != active_id:
                other = candidate
                break
        if not other:
            ui.messageBox('This project needs a second saved document. Save any '
                          'other design into this project and re-run.')
            return

        notes.append('opened: {}'.format(other.name))
        opened = app.documents.open(other)
        opened.activate()
        adsk.doEvents()
        opened.close(False)
        adsk.doEvents()
        notes.append('closed it again')

        # --- is the snapshot still alive? ------------------------------------
        try:
            volume_after = temp.volume
            notes.append('volume after:  {:.6f}'.format(volume_after))
            alive = abs(volume_after - volume_before) < 1e-9 and volume_after > 0
        except Exception as err:
            notes.append('volume after:  FAILED — {}'.format(err))
            alive = False

        # --- and can it still be INSERTED? This is what Phase 2 actually does.
        inserted = False
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
            inserted = root.bRepBodies.count > 0
            notes.append('inserted into a fresh document: {} body(s), volume {:.6f}'
                         .format(root.bRepBodies.count,
                                 root.bRepBodies.item(0).volume))
        except Exception:
            notes.append('insert FAILED:\n' + traceback.format_exc())

        verdict = 'PASS' if (alive and inserted) else 'FAIL'
        notes.append('')
        notes.append('SPIKE 1: ' + verdict)
        if verdict == 'FAIL':
            notes.append('Fallback: snapshot into a hidden staging design while '
                         'the mother is active, then copy from staging into the '
                         'layout. Revise the spec before starting Plan 1.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
