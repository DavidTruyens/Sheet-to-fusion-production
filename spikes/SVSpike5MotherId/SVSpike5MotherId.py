# Spike 5 — why does Update Children report "mother not found" for a mother
# that is open in the next tab?
#
# Update Children resolves a child's mother with
# app.data.findFileById(recipe['mother']['fileId']), where that fileId was
# recorded at fill time as doc.dataFile.id. All children came back "mother not
# found", which means findFileById returned None (or raised) for an id that was
# valid when it was stored.
#
# The leading hypothesis is that DataFile.id is VERSION-SPECIFIC: the mother has
# been saved repeatedly since (it is on v16), so the recorded id names a version
# that no longer answers, and the lookup needs a version-independent id instead.
# That is a guess. This script prints the facts rather than assuming it.
#
# READ-ONLY. It writes nothing and modifies nothing.
#
# Setup: open the LAYOUT document that shows the problem, and leave the mother
# open too. Run this with the LAYOUT as the active document.

import traceback

import adsk.core
import adsk.fusion

ATTR_GROUP = 'SheetVariants'
CHILD_RECIPE_ATTR = 'childRecipe'


def _seq(collection):
    """findAttributes returns an AttributeVector — a Python sequence with no
    .count — while real Fusion collections have .count/.item(i)."""
    try:
        return [collection.item(i) for i in range(collection.count)]
    except AttributeError:
        return [collection[i] for i in range(len(collection))]


def _interesting(obj, label, notes):
    """Print every id-ish / version-ish property, so we can see which one is
    version-independent without guessing the API surface."""
    notes.append('  {}:'.format(label))
    for name in sorted(dir(obj)):
        if name.startswith('_'):
            continue
        low = name.lower()
        if not any(k in low for k in ('id', 'version', 'urn', 'name', 'path')):
            continue
        try:
            value = getattr(obj, name)
        except Exception as err:
            notes.append('    {} -> unreadable ({})'.format(name, err))
            continue
        if callable(value):
            continue
        notes.append('    {} = {!r}'.format(name, value))


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    notes = []
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open the layout design and run this again.')
            return

        # --- what every OPEN document reports about itself -------------------
        notes.append('=== OPEN DOCUMENTS ===')
        for i in range(app.documents.count):
            doc = app.documents.item(i)
            try:
                notes.append('doc.name = {!r}'.format(doc.name))
            except Exception as err:
                notes.append('doc {} name unreadable ({})'.format(i, err))
                continue
            try:
                data_file = doc.dataFile
            except Exception as err:
                notes.append('  dataFile unreadable ({})'.format(err))
                continue
            if not data_file:
                notes.append('  dataFile is None (never saved)')
                continue
            _interesting(data_file, 'dataFile', notes)
            # Does the id this document reports right now resolve?
            try:
                found = app.data.findFileById(data_file.id)
                notes.append('  findFileById(its OWN id) -> {}'.format(
                    'v{}'.format(found.versionNumber) if found else 'None'))
            except Exception as err:
                notes.append('  findFileById(its OWN id) raised: {}'.format(err))
        notes.append('')

        # --- what the children actually recorded -----------------------------
        notes.append('=== CHILD RECIPES IN THIS DESIGN ===')
        attributes = _seq(design.findAttributes(ATTR_GROUP, CHILD_RECIPE_ATTR))
        notes.append('found {} child recipe(s)'.format(len(attributes)))
        seen = set()
        for attribute in attributes:
            try:
                import json
                recipe = json.loads(attribute.value)
                mother = recipe.get('mother') or {}
            except Exception as err:
                notes.append('  unparseable recipe ({})'.format(err))
                continue
            file_id = mother.get('fileId') or ''
            notes.append('  child on {!r}'.format(
                getattr(attribute.parent, 'name', '?')))
            notes.append('    recorded name    = {!r}'.format(mother.get('name')))
            notes.append('    recorded version = {!r}'.format(mother.get('version')))
            notes.append('    recorded fileId  = {!r}'.format(file_id))
            if not file_id or file_id in seen:
                continue
            seen.add(file_id)
            try:
                found = app.data.findFileById(file_id)
                if found:
                    notes.append('    findFileById -> FOUND, v{}, name {!r}'
                                 .format(found.versionNumber, found.name))
                else:
                    notes.append('    findFileById -> None   <-- this is the bug')
            except Exception as err:
                notes.append('    findFileById RAISED: {}: {}'
                             .format(type(err).__name__, err))
        notes.append('')

        notes.append('=== WHAT TO COMPARE ===')
        notes.append('Does a recipe\'s recorded fileId match the open mother\'s')
        notes.append('CURRENT dataFile.id? If they differ, the id is version-')
        notes.append('specific and Update Children needs a version-independent')
        notes.append('one — look above for a property that stays constant across')
        notes.append('versions. If they MATCH and findFileById still returns None,')
        notes.append('the problem is the lookup itself, not the stored id.')

        text = '\n'.join(notes)
        ui.messageBox(text[:9000])
        print(text)   # full text in the Text Commands palette
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
