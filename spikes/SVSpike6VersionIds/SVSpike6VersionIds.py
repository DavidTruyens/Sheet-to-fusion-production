# Spike 6 — is latestVersionNumber a LINEAGE-wide property?
#
# Update Children decides whether a child is stale by comparing the version it
# was built from against the mother's current latest version. Reading that
# number is not straightforward:
#
#   - findFileById() has been seen RAISING "3 : file not found" for the lineage
#     urn a document reports about itself, offline and online alike (spike 5).
#   - So a child also records the mother's versionId as a fallback lookup key.
#
# The fallback rests on an assumption nothing here has measured: that a DataFile
# resolved from an OLD version's id still reports the lineage's newest version in
# latestVersionNumber. If it instead reports its own version, a closed mother's
# children read "up to date" forever and never get offered a rebuild — silently
# worse than the "unknown version" they would otherwise show.
#
# This script measures it. READ-ONLY: it writes nothing and modifies nothing.
#
# Setup: open a mother document that has SEVERAL versions (v2 or later), and run
# this with it active. Nothing needs to be saved first.

import traceback

import adsk.core
import adsk.fusion


def _read(obj, name, notes, indent='    '):
    """Read one property, recording whether it answered at all — spike 5 found
    some DataFile properties raising on a perfectly live file."""
    try:
        value = getattr(obj, name)
    except Exception as err:
        notes.append('{}{} -> UNREADABLE ({}: {})'.format(
            indent, name, type(err).__name__, err))
        return None
    notes.append('{}{} = {!r}'.format(indent, name, value))
    return value


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    notes = []
    try:
        doc = app.activeDocument
        data_file = doc.dataFile
        if not data_file:
            ui.messageBox('This document has never been saved. Open a saved '
                          'mother with several versions and run this again.')
            return

        notes.append('=== THE OPEN DOCUMENT ===')
        notes.append('  doc.name = {!r}'.format(doc.name))
        lineage_id = _read(data_file, 'id', notes)
        version_id = _read(data_file, 'versionId', notes)
        open_version = _read(data_file, 'versionNumber', notes)
        open_latest = _read(data_file, 'latestVersionNumber', notes)
        notes.append('')

        notes.append('=== Q1. does the lineage id resolve? ===')
        notes.append('(spike 5 said no for two documents — is that still true?)')
        try:
            by_lineage = app.data.findFileById(lineage_id)
            notes.append('  findFileById(id) -> {}'.format(
                'a DataFile' if by_lineage else 'None'))
            if by_lineage:
                _read(by_lineage, 'versionNumber', notes)
                _read(by_lineage, 'latestVersionNumber', notes)
        except Exception as err:
            notes.append('  findFileById(id) RAISED: {}: {}'.format(
                type(err).__name__, err))
        notes.append('')

        notes.append('=== Q2. does the version id resolve? ===')
        try:
            by_version = app.data.findFileById(version_id)
            notes.append('  findFileById(versionId) -> {}'.format(
                'a DataFile' if by_version else 'None'))
            if by_version:
                _read(by_version, 'versionNumber', notes)
                _read(by_version, 'latestVersionNumber', notes)
        except Exception as err:
            notes.append('  findFileById(versionId) RAISED: {}: {}'.format(
                type(err).__name__, err))
        notes.append('')

        # THE QUESTION. Build an OLD version's id by hand and ask that DataFile
        # for the latest version. versionId looks like '...?version=N', so an
        # earlier version's id is the same string with a smaller N. If the real
        # format differs this prints what it tried, which is the useful result.
        notes.append('=== Q3. THE ONE THAT MATTERS ===')
        notes.append('An OLD version\'s DataFile — does latestVersionNumber give')
        notes.append('the LINEAGE tip, or just that old version back?')
        if not version_id or '?version=' not in str(version_id):
            notes.append('  versionId is {!r} — no "?version=N" to rewrite, so an'
                         .format(version_id))
            notes.append('  old id cannot be built this way. Report this: the')
            notes.append('  fallback needs a different way to name a version.')
        elif not isinstance(open_version, int) or open_version < 2:
            notes.append('  this document is at v{} — open a mother with SEVERAL'
                         .format(open_version))
            notes.append('  versions so there is an older one to ask about.')
        else:
            older = '{}?version={}'.format(
                str(version_id).split('?version=')[0], open_version - 1)
            notes.append('  asking about: {!r}'.format(older))
            try:
                old_file = app.data.findFileById(older)
                if not old_file:
                    notes.append('  -> None. The fallback cannot work at all.')
                else:
                    old_version = _read(old_file, 'versionNumber', notes)
                    old_latest = _read(old_file, 'latestVersionNumber', notes)
                    notes.append('')
                    if old_latest == open_latest:
                        notes.append('  VERDICT: LINEAGE-WIDE. latestVersionNumber')
                        notes.append('  on an old version reports the tip ({}).'
                                     .format(old_latest))
                        notes.append('  The versionId fallback is SAFE.')
                    elif old_latest == old_version:
                        notes.append('  VERDICT: NOT lineage-wide — it reports its')
                        notes.append('  OWN version ({}), not the tip ({}).'
                                     .format(old_latest, open_latest))
                        notes.append('  The versionId fallback would report every')
                        notes.append('  closed mother as up to date. REMOVE IT or')
                        notes.append('  mark its result as unknown.')
                    else:
                        notes.append('  VERDICT: neither — old latest={!r}, open '
                                     'latest={!r}, old version={!r}.'
                                     .format(old_latest, open_latest, old_version))
                        notes.append('  Report these three numbers.')
            except Exception as err:
                notes.append('  findFileById(old versionId) RAISED: {}: {}'.format(
                    type(err).__name__, err))
                notes.append('  -> the fallback cannot work; treat it as unknown.')

        notes.append('')
        notes.append('=== Q4. DOES AN OPEN DOCUMENT KNOW IT WAS JUST SAVED? ===')
        notes.append('Update Children refuses to drive a mother whose open version')
        notes.append('is behind its newest, so children are never built from a')
        notes.append('version the dialog did not advertise. That is only safe if')
        notes.append('an open document\'s DataFile keeps up with its own saves.')
        notes.append('')
        notes.append('  right now: versionNumber={!r}, latestVersionNumber={!r}'
                     .format(open_version, open_latest))
        if open_version == open_latest:
            notes.append('  -> equal, so nothing is refused in this state.')
        else:
            notes.append('  -> ALREADY UNEQUAL. If this document is genuinely open')
            notes.append('     at an older version, that is correct. If it is at')
            notes.append('     the newest, the guard is WRONG and must go.')
        notes.append('')
        notes.append('  NOW DO THIS, which is the workflow that matters:')
        notes.append('   1. change a parameter in this mother and SAVE it')
        notes.append('   2. leave it open')
        notes.append('   3. run this script again')
        notes.append('  If versionNumber and latestVersionNumber are still EQUAL')
        notes.append('  afterwards, the guard is safe and can also protect Fill')
        notes.append('  Placeholders. If versionNumber lags, the guard would refuse')
        notes.append('  the commonest workflow there is — report that, because it')
        notes.append('  then has to be removed rather than extended.')

        text = '\n'.join(notes)
        ui.messageBox(text[:9000])
        print(text)   # full text in the Text Commands palette
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
