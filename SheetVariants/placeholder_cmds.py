# placeholder_cmds.py
# The placeholder-instantiation commands: Prepare Mother Model (records how a
# mother is driven and oriented) and Fill Placeholders (generates children).
#
# Imports adsk, so nothing here is unit-tested; the schemas, frames, extents,
# matrices and body pairing all live in placeholder_core.py, which is.

import datetime
import os
import sys
import traceback

import adsk.core
import adsk.fusion

import build_engine

_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
sys.modules.pop('placeholder_core', None)
import placeholder_core

app = adsk.core.Application.get()
ui = app.userInterface

PREPARE_CMD_ID = 'sheetVariantsPrepareMotherCmd'
PREPARE_CMD_NAME = 'Prepare Mother Model'
PREPARE_CMD_DESC = ('Record which parameters this model\'s width, depth and height '
                    'map to, where its anchor is, and which way it faces — so it '
                    'can be assigned to placeholder boxes in a layout.')


def read_mother_setup(design):
    """The motherSetup stored on ``design``, migrated. A design that was never
    prepared yields the default, which validate_mother_setup() will reject with a
    readable reason."""
    text = ''
    try:
        attr = design.attributes.itemByName(placeholder_core.ATTR_GROUP,
                                            placeholder_core.MOTHER_SETUP_ATTR)
        if attr:
            text = attr.value
    except Exception:
        pass
    return placeholder_core.loads_attr(text, placeholder_core.migrate_mother_setup)


def write_mother_setup(design, setup):
    design.attributes.add(placeholder_core.ATTR_GROUP,
                          placeholder_core.MOTHER_SETUP_ATTR,
                          placeholder_core.dumps_attr(setup))


def joint_origin_names(design):
    """Joint origin names in the root component. A joint origin is used as the
    anchor rather than a face because it is a named entity that survives the
    parameter changes this feature makes; a face reference would not."""
    names = []
    try:
        origins = design.rootComponent.jointOrgins
        for i in range(origins.count):
            name = origins.item(i).name
            if name:
                names.append(name)
    except Exception:
        pass
    return names


def _add_dropdown(inputs, input_id, label, options, selected):
    """A single-select dropdown pre-set to ``selected`` when it is present.

    Returns ``(drop, matched)``. ``matched`` is False when ``selected`` was a
    non-empty stored value that is no longer among ``options`` — e.g. the
    parameter or joint origin it named was renamed or deleted. In that case the
    dropdown still falls back to selecting the first item (it must select
    something), but that fallback is visually indistinguishable from a real,
    intentional selection, so the caller uses ``matched`` to warn the user
    instead of silently writing the wrong mapping back out."""
    drop = inputs.addDropDownCommandInput(
        input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    for option in options:
        drop.listItems.add(option, option == selected)
    matched = (not selected) or (selected in options)
    if drop.listItems.count and not drop.selectedItem:
        drop.listItems.item(0).isSelected = True
    return drop, matched


class PrepareCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                inputs.addTextBoxCommandInput(
                    'err', '', 'Open a parametric design first.', 2, True)
                return

            # Without a saved file there is no id to reference and no version
            # number to compare, so a child could never say whether its mother
            # had moved on.
            if not design.parentDocument.dataFile:
                inputs.addTextBoxCommandInput(
                    'err', '',
                    'Save this document to your Fusion project first — a mother '
                    'model must be a saved file so children can reference it and '
                    'compare versions.', 4, True)
                return

            setup = read_mother_setup(design)
            origins = joint_origin_names(design)
            if not origins:
                inputs.addTextBoxCommandInput(
                    'err', '',
                    'This model has no joint origins. Create one at the point '
                    'that should land at the centre of a placeholder box '
                    '(Assemble > Joint Origin), then run this command again.',
                    4, True)
                return

            params = [p.name for p in design.allParameters]
            missing = []
            _, matched = _add_dropdown(inputs, 'anchor', 'Anchor joint origin',
                                       origins, setup['anchor'])
            if not matched:
                missing.append('anchor')
            _add_dropdown(inputs, 'front', 'Front faces along',
                          list(placeholder_core.FRONT_AXES), setup['front'])
            _, matched = _add_dropdown(inputs, 'pWidth', 'Width parameter', params,
                                       setup['params']['width'])
            if not matched:
                missing.append('width')
            _, matched = _add_dropdown(inputs, 'pDepth', 'Depth parameter', params,
                                       setup['params']['depth'])
            if not matched:
                missing.append('depth')
            _, matched = _add_dropdown(inputs, 'pHeight', 'Height parameter', params,
                                       setup['params']['height'])
            if not matched:
                missing.append('height')

            if missing:
                inputs.addTextBoxCommandInput(
                    'missing', '',
                    'Previously saved selections no longer exist in this model '
                    'and have been reset: {}. Check every dropdown before '
                    'clicking OK.'.format(', '.join(missing)),
                    3, True)
            inputs.addTextBoxCommandInput(
                'hint', '',
                'The anchor is the point that lands at the centre of the '
                'placeholder box. To shift the model within its box, move the '
                'joint origin.',
                3, True)

            handler = PrepareExecuteHandler()
            cmd.execute.add(handler)
            _handlers.append(handler)
        except Exception:
            if ui:
                ui.messageBox('Prepare Mother Model failed:\n' + traceback.format_exc())


class PrepareExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            if not inputs.itemById('anchor'):
                return  # an error text box was shown instead of the form
            design = adsk.fusion.Design.cast(app.activeProduct)

            def picked(input_id):
                item = inputs.itemById(input_id).selectedItem
                return item.name if item else ''

            setup = placeholder_core.migrate_mother_setup({
                'anchor': picked('anchor'),
                'front': picked('front'),
                'params': {'width': picked('pWidth'),
                           'depth': picked('pDepth'),
                           'height': picked('pHeight')},
            })
            errors = placeholder_core.validate_mother_setup(setup)
            if errors:
                ui.messageBox('This mother cannot be used yet:\n\n• '
                              + '\n• '.join(errors))
                return
            write_mother_setup(design, setup)
            ui.messageBox(
                'Prepared "{}".\n\nanchor: {}\nfront: {}\nwidth: {}\ndepth: {}\n'
                'height: {}\n\nSave the document to keep this.'
                .format(design.parentDocument.name, setup['anchor'], setup['front'],
                        setup['params']['width'], setup['params']['depth'],
                        setup['params']['height']))
        except Exception:
            ui.messageBox('Prepare Mother Model failed:\n' + traceback.format_exc())


FILL_CMD_ID = 'sheetVariantsFillPlaceholdersCmd'
FILL_CMD_NAME = 'Fill Placeholders'
FILL_CMD_DESC = ('Assign a prepared mother model, at a chosen config, to the '
                 'selected placeholder boxes. Each box drives its own width, '
                 'depth and height.')


def _body_vertices(body):
    """World (x, y, z) of every vertex of ``body``, in centimetres."""
    verts = body.vertices
    out = []
    for i in range(verts.count):
        point = verts.item(i).geometry
        out.append((point.x, point.y, point.z))
    return out


def _body_identity(body):
    """A stable identity for ``body``, for deduplicating repeated selections.

    Prefers Fusion's persistent ``entityToken`` — unlike ``body.name``, which is
    mutable and not unique, so two distinct bodies sharing a name (renamed, or
    copy-pasted across components) would otherwise be wrongly collapsed into
    "one box", silently dropping one of the user's selected placeholders. Falls
    back to the qualified component::body name if the token is unavailable or
    empty.
    """
    try:
        token = body.entityToken
        if token:
            return token
    except Exception:
        pass
    try:
        component_name = body.parentComponent.name
    except Exception:
        component_name = ''
    return placeholder_core.qualified_body_name(component_name, body.name)


def read_slot_id(body):
    try:
        attr = body.attributes.itemByName(placeholder_core.ATTR_GROUP,
                                          placeholder_core.SLOT_ID_ATTR)
        return attr.value if attr else ''
    except Exception:
        return ''


def ensure_slot_id(body):
    """This body's slot id, stamping a new one the first time it is filled."""
    existing = read_slot_id(body)
    if existing:
        return existing
    slot_id = placeholder_core.new_slot_id()
    body.attributes.add(placeholder_core.ATTR_GROUP,
                        placeholder_core.SLOT_ID_ATTR, slot_id)
    return slot_id


def resolve_slots(faces):
    """Phase 0: turn selected front faces into plain-data build recipes.

    Everything a later phase needs is copied out into plain Python here, because
    activating another document invalidates every live Fusion reference. Returns
    (slots, problems); a face that cannot be resolved contributes a problem and no
    slot, so one bad pick does not lose the whole selection.
    """
    slots, problems, seen = [], [], set()
    for face in faces:
        body = face.body
        name = body.name
        key = _body_identity(body)
        if key in seen:
            problems.append('"{}" was selected more than once — using the first '
                            'face only.'.format(name))
            continue
        try:
            normal = face.geometry.normal
            frame = placeholder_core.target_frame((normal.x, normal.y, normal.z))
            width, depth, height, centre = placeholder_core.extents_in_frame(
                _body_vertices(body), frame)
        except Exception as err:
            problems.append('"{}": {}'.format(name, err))
            continue
        seen.add(key)
        slots.append({
            'body': body,
            'slotId': read_slot_id(body),
            'dims_cm': (width, depth, height),
            'matrix': placeholder_core.occurrence_matrix(centre, frame),
            'name': name,
        })
    return slots, problems


def _own_sheet_url(design):
    """This design's own linked-sheet URL, with NO fallback.

    Deliberately does not use ``SheetVariants.load_design_url`` — that function
    falls back to the app-level last-used sheet URL when the design has no
    attribute of its own, which here would let an unrelated document's
    last-used sheet masquerade as this mother's link: a never-linked mother
    would silently report a non-empty sheetUrl, skipping the "no sheet link
    yet" warning and then loading configs from the wrong spreadsheet.
    """
    try:
        import SheetVariants
        attr = design.attributes.itemByName(SheetVariants.DESIGN_ATTR_GROUP,
                                            SheetVariants.DESIGN_ATTR_URL)
        return attr.value if attr else ''
    except Exception:
        return ''


def _mother_options(design):
    """Cached mothers plus any prepared document currently open, keyed by fileId
    so an open document supersedes its cache entry."""
    import sheet_core
    import SheetVariants
    settings = sheet_core.load_settings(SheetVariants.SETTINGS_FILE)
    options = {m['fileId']: m for m in sheet_core.known_mothers(settings)}
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        try:
            other = adsk.fusion.Design.cast(
                doc.products.itemByProductType('DesignProductType'))
            if not other or not doc.dataFile:
                continue
            setup = read_mother_setup(other)
            if placeholder_core.validate_mother_setup(setup):
                continue
            options[doc.dataFile.id] = {
                'fileId': doc.dataFile.id, 'name': doc.name,
                'sheetUrl': _own_sheet_url(other), 'tab': ''}
        except Exception:
            continue
    return sorted(options.values(), key=lambda m: m['name'])


# Populated by FillCreatedHandler.notify, in the exact order the mother
# dropdown's items are added, so _selected_mother can index into it directly:
# no re-reading settings.json / re-scanning every open document on every
# dropdown interaction, and no ambiguity when two mothers share a display name
# (matching by name, as an earlier version did, resolves to whichever one
# _mother_options happens to sort first).
_mother_cache = []


class FillCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                inputs.addTextBoxCommandInput('err', '', 'Open a design first.', 2, True)
                return

            selection = inputs.addSelectionInput(
                'faces', 'Front faces', 'Select the front face of each placeholder box')
            selection.addSelectionFilter('PlanarFaces')
            selection.setSelectionLimits(1, 0)

            global _mother_cache
            mothers = _mother_options(design)
            _mother_cache = mothers
            if not mothers:
                inputs.addTextBoxCommandInput(
                    'nomother', '',
                    'No prepared mother models found. Open one and run Prepare Mother '
                    'Model first.', 3, True)
                return
            drop = inputs.addDropDownCommandInput(
                'mother', 'Mother model', adsk.core.DropDownStyles.TextListDropDownStyle)
            for index, mother in enumerate(mothers):
                drop.listItems.add(mother['name'], index == 0)

            config = inputs.addDropDownCommandInput(
                'config', 'Config', adsk.core.DropDownStyles.TextListDropDownStyle)
            config.listItems.add('— press Load configs —', True)
            inputs.addBoolValueInput('loadConfigs', 'Load configs', False, '', False)
            inputs.addTextBoxCommandInput('report', 'Resolved', '', 6, True)

            for handler_class, event in ((FillInputChangedHandler, cmd.inputChanged),
                                         (FillExecuteHandler, cmd.execute)):
                handler = handler_class()
                event.add(handler)
                _handlers.append(handler)

            cmd.setDialogInitialSize(460, 460)
        except Exception:
            if ui:
                ui.messageBox('Fill Placeholders failed:\n' + traceback.format_exc())


def _selected_mother(inputs):
    """The currently chosen mother, indexed out of ``_mother_cache`` by the
    dropdown's selected position rather than matched by display name (see
    ``_mother_cache``'s comment)."""
    drop = inputs.itemById('mother')
    item = drop.selectedItem if drop else None
    if not item or item.index < 0 or item.index >= len(_mother_cache):
        return None
    return _mother_cache[item.index]


def _describe(slots, problems):
    lines = []
    for slot in slots:
        width, depth, height = slot['dims_cm']
        lines.append('{} — {:.0f} x {:.0f} x {:.0f} mm'.format(
            slot['name'], width * 10, depth * 10, height * 10))
    for problem in problems:
        lines.append('! ' + problem)
    return '<br/>'.join(lines) if lines else 'Nothing selected yet.'


class FillInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            changed = args.input
            if changed.id == 'faces':
                selection = inputs.itemById('faces')
                faces = [selection.selection(i).entity
                         for i in range(selection.selectionCount)]
                slots, problems = resolve_slots(faces)
                inputs.itemById('report').formattedText = _describe(slots, problems)
            elif changed.id == 'loadConfigs' and changed.value:
                changed.value = False
                mother = _selected_mother(inputs)
                if not mother or not mother['sheetUrl']:
                    ui.messageBox('That mother has no sheet link yet. Open it and '
                                  'run Build Variants Assembly from Sheet once to '
                                  'link its sheet.')
                    return
                import SheetVariants
                rows = SheetVariants.get_rows(mother['sheetUrl'], mother['tab'] or None)
                config = inputs.itemById('config')
                config.listItems.clear()
                for index, row in enumerate(rows[1:]):
                    name = (row[0] or '').strip()
                    if name:
                        config.listItems.add(name, config.listItems.count == 0)
                if not config.listItems.count:
                    config.listItems.add('— no named rows —', True)
        except Exception:
            import traceback
            ui.messageBox('Fill Placeholders failed:\n' + traceback.format_exc())


class FillExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            selection = inputs.itemById('faces')
            if not selection:
                return
            faces = [selection.selection(i).entity
                     for i in range(selection.selectionCount)]
            slots, problems = resolve_slots(faces)
            mother = _selected_mother(inputs)
            item = inputs.itemById('config').selectedItem
            config = item.name if item else ''
            if not mother or not config:
                ui.messageBox('Pick a mother model and a config first.')
                return
            report = build_children(slots, mother, config)
            import sheet_core
            import SheetVariants
            settings = sheet_core.load_settings(SheetVariants.SETTINGS_FILE)
            sheet_core.remember_mother(settings, mother)
            sheet_core.save_settings(SheetVariants.SETTINGS_FILE, settings)
            lines = report + ['! ' + p for p in problems]
            ui.messageBox('\n'.join(lines) if lines else 'Nothing was built.')
        except Exception:
            import traceback
            ui.messageBox('Fill Placeholders failed:\n' + traceback.format_exc())


_handlers = []

# Panel this module last registered its controls into, so unregister() can find
# and remove them even if it is not the add-in's own MANAGE panel — get_manage_
# panel() in SheetVariants.py falls back to the native SolidScriptsAddinsPanel
# when the MANAGE tab can't be found (e.g. a non-English Fusion), and that panel
# is never deleted wholesale on reload the way the add-in's own panel is.
_panel = None

# (cmd_id, name, description, CommandCreatedEventHandler class) for every
# command this module registers. register() and unregister() both loop over this.
_COMMANDS = (
    (PREPARE_CMD_ID, PREPARE_CMD_NAME, PREPARE_CMD_DESC, PrepareCreatedHandler),
    (FILL_CMD_ID, FILL_CMD_NAME, FILL_CMD_DESC, FillCreatedHandler),
)


def register(panel):
    """Create the command definitions and add them to ``panel``. Handlers are kept
    in this module's _handlers list so Python does not garbage-collect them."""
    global _panel
    _panel = panel
    for cmd_id, name, desc, created_handler_cls in _COMMANDS:
        existing = ui.commandDefinitions.itemById(cmd_id)
        if existing:
            existing.deleteMe()
        definition = ui.commandDefinitions.addButtonDefinition(cmd_id, name, desc)
        handler = created_handler_cls()
        definition.commandCreated.add(handler)
        _handlers.append(handler)
        if not panel.controls.itemById(cmd_id):
            panel.controls.addCommand(definition)


def unregister():
    """Remove this module's command controls and definitions. Safe to call
    repeatedly, and safe even if the panel this module registered into has since
    been deleted (deleteMe() on a command definition does not remove the panel
    control that references it, so both are removed here explicitly, each
    independently guarded so one missing piece cannot stop the other from being
    cleaned up)."""
    global _panel
    for cmd_id, _name, _desc, _cls in _COMMANDS:
        if _panel:
            try:
                control = _panel.controls.itemById(cmd_id)
                if control:
                    control.deleteMe()
            except Exception:
                pass
        try:
            definition = ui.commandDefinitions.itemById(cmd_id)
            if definition:
                definition.deleteMe()
        except Exception:
            pass
    _handlers[:] = []
    _panel = None


def attribute_list(found):
    """Design.findAttributes() returns an **AttributeVector**, which is NOT a
    Fusion collection — it has no .count or .item(i), and using them raises
    AttributeError. Spike 2 confirmed this; len()/index is the working shape.
    The .count branch is kept as a fallback for builds that expose the collection
    shape instead."""
    try:
        return [found[i] for i in range(len(found))]
    except (TypeError, AttributeError):
        return [found.item(i) for i in range(found.count)]


def find_slot_bodies(design):
    """{slot id: body} for every placeholder in ``design``, in one call.

    Used to re-find placeholder bodies AFTER a document switch has invalidated
    the references captured during Phase 0."""
    bodies = {}
    for attribute in attribute_list(design.findAttributes(
            placeholder_core.ATTR_GROUP, placeholder_core.SLOT_ID_ATTR)):
        try:
            bodies[attribute.value] = attribute.parent
        except Exception:
            continue
    return bodies


def _unique_component_name(root, wanted):
    """``wanted``, suffixed _2, _3, ... if a component already has that name.

    A child is named after its placeholder body so the browser reads like the
    layout, but two boxes in different components may share a name and Fusion will
    not silently disambiguate them for us."""
    taken = set()
    for occurrence in root.occurrences:
        try:
            taken.add(occurrence.component.name)
        except Exception:
            continue
    if wanted not in taken:
        return wanted
    index = 2
    while '{}_{}'.format(wanted, index) in taken:
        index += 1
    return '{}_{}'.format(wanted, index)


def _row_values(rows, config):
    """{parameter name: cell} for the row whose Name column is ``config``."""
    header = [h.strip() for h in rows[0]]
    for row in rows[1:]:
        if (row[0] or '').strip() == config:
            return {name: (row[i].strip() if i < len(row) else '')
                    for i, name in enumerate(header) if i > 0 and name}
    raise RuntimeError('Config "{}" is no longer in the sheet.'.format(config))


def _cm(value):
    """A parameter expression for a length in Fusion's internal centimetres."""
    return '{:.6f} cm'.format(value)


def _open_mother(file_id):
    """(document, opened_by_us). Reuses an already-open document; refuses one with
    unsaved changes, because a run edits and restores its parameters and a crash
    partway would leave someone else's work in a variant state."""
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        try:
            if doc.dataFile and doc.dataFile.id == file_id:
                if doc.isModified:
                    raise RuntimeError(
                        'The mother "{}" has unsaved changes. Save or discard them '
                        'before filling placeholders.'.format(doc.name))
                return doc, False
        except AttributeError:
            continue
    data_file = app.data.findFileById(file_id)
    if not data_file:
        raise RuntimeError('The mother model could not be found in your projects.')
    return app.documents.open(data_file), True


def _snapshot_for(design, setup, values, dims_cm):
    """Drive the mother to one config-and-size and snapshot its solids, already
    transformed into the child's local space with the anchor at the origin."""
    frame = placeholder_core.mother_frame(setup['front'])
    origins = design.rootComponent.jointOrgins
    origin = origins.itemByName(setup['anchor'])
    if not origin:
        raise RuntimeError(
            'The anchor joint origin "{}" is missing from this mother.'
            .format(setup['anchor']))

    driven = dict(values)
    driven[setup['params']['width']] = _cm(dims_cm[0])
    driven[setup['params']['depth']] = _cm(dims_cm[1])
    driven[setup['params']['height']] = _cm(dims_cm[2])
    for key in ('width', 'depth', 'height'):
        if not design.allParameters.itemByName(setup['params'][key]):
            raise RuntimeError('The mapped {} parameter "{}" is missing from this '
                               'mother.'.format(key, setup['params'][key]))

    original = build_engine.capture_values(list(driven.keys()))
    try:
        build_engine.apply_values(driven)
        adsk.doEvents()
        fresh = adsk.fusion.Design.cast(app.activeProduct)
        # The anchor moves with the model, so read it AFTER the recompute.
        point = fresh.rootComponent.jointOrgins.itemByName(
            setup['anchor']).geometry.origin
        bodies = []
        for occurrence in fresh.rootComponent.allOccurrences:
            bodies.extend(b for b in occurrence.bRepBodies if b.isSolid)
        bodies.extend(b for b in fresh.rootComponent.bRepBodies if b.isSolid)
        snaps = build_engine.snapshot_bodies(bodies)
    finally:
        build_engine.restore_values(original)
        adsk.doEvents()
    build_engine.transform_snapshot(
        snaps, placeholder_core.local_matrix((point.x, point.y, point.z), frame))
    return snaps


def build_children(slots, mother, config):
    """Phases 1 and 2: drive the mother once per distinct size, then create a child
    component per slot in the layout document.

    Returns one report line per slot. A slot that cannot be built contributes a
    failure line and is skipped; it never aborts the run, so one bad box does not
    cost you the whole kitchen.
    """
    layout_doc = app.activeDocument
    rows_url, rows_tab = mother['sheetUrl'], mother['tab'] or None
    import SheetVariants
    values = _row_values(SheetVariants.get_rows(rows_url, rows_tab), config)

    # Stamp slot ids NOW, while the layout is still active and Phase 0's body
    # references are still alive. Opening the mother below invalidates every live
    # reference to this design, so this is the last moment those bodies can be
    # touched. From here on a slot is identified only by its id string, and the
    # body is re-found by attribute in Phase 2.
    for slot in slots:
        try:
            slot['slotId'] = ensure_slot_id(slot['body'])
        except Exception:
            slot['slotId'] = ''
        slot.pop('body', None)   # dead weight from here on — never dereference it

    # The progress dialog covers Phase 1 only: driving and recomputing the mother
    # is the slow part, while Phase 2 just copies snapshots that are already made.
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show('Filling placeholders', 'Placeholder %v of %m', 0, len(slots), 0)
    failures = []

    # Phase 1 — everything that needs the mother, with the layout in the background.
    doc, opened_by_us = _open_mother(mother['fileId'])
    version = doc.dataFile.versionNumber if doc.dataFile else None
    by_size = {}
    try:
        doc.activate()
        adsk.doEvents()
        mother_design = adsk.fusion.Design.cast(app.activeProduct)
        setup = placeholder_core.migrate_mother_setup(read_mother_setup(mother_design))
        errors = placeholder_core.validate_mother_setup(setup)
        if errors:
            raise RuntimeError('"{}" is not fully prepared:\n• {}'
                               .format(mother['name'], '\n• '.join(errors)))
        # One drive per DISTINCT size: a run of identical units costs one recompute.
        for index, slot in enumerate(slots):
            if progress.wasCancelled:
                raise RuntimeError('Cancelled by user.')
            key = tuple(round(v, 6) for v in slot['dims_cm'])
            if key not in by_size:
                try:
                    by_size[key] = _snapshot_for(mother_design, setup, values,
                                                 slot['dims_cm'])
                except Exception as err:
                    # One unusable slot must not cost the whole run.
                    failures.append('{} — {}'.format(slot['name'], err))
            progress.progressValue = index + 1
    finally:
        if opened_by_us:
            doc.close(False)
        adsk.doEvents()
        progress.hide()

    # Phase 2 — back in the layout, with every snapshot already in hand.
    layout_doc.activate()
    adsk.doEvents()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    tbm = adsk.fusion.TemporaryBRepManager.get()
    built_at = datetime.datetime.now().isoformat(timespec='seconds')
    # Re-resolve the placeholder bodies AFTER the document switch. The references
    # captured in Phase 0 are dead; these are looked up fresh by the slot ids
    # stamped above.
    slot_bodies = find_slot_bodies(design)
    report = []
    for slot in slots:
        key = tuple(round(v, 6) for v in slot['dims_cm'])
        template = by_size.get(key)
        if template is None:
            continue  # its failure is already recorded
        # Copy again per slot: identical units share one recompute, not one body.
        snaps = [{'temp': tbm.copy(s['temp']), 'appearance': s['appearance'],
                  'material': s['material'], 'name': s['name']} for s in template]

        matrix = adsk.core.Matrix3D.create()
        matrix.setWithArray(slot['matrix'])
        occurrence = root.occurrences.addNewComponent(matrix)
        occurrence.component.name = _unique_component_name(root, slot['name'])
        build_engine.add_snapshot(occurrence.component, snaps)
        build_engine.reapply_looks(design, occurrence.component, snaps)

        recipe = placeholder_core.new_child_recipe(
            slot_id=slot['slotId'],
            mother={'fileId': mother['fileId'], 'name': mother['name'],
                    'version': version},
            config=config, sheet_url=rows_url, tab=mother['tab'],
            dims_cm=slot['dims_cm'],
            bodies=[s['name'] for s in snaps],
            built_at=built_at)
        occurrence.component.attributes.add(
            placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR,
            placeholder_core.dumps_attr(recipe))
        body = slot_bodies.get(slot['slotId'])
        if body is not None:
            try:
                body.isLightBulbOn = False
            except Exception:
                pass
        report.append('{} — built {} bodies'.format(slot['name'], len(snaps)))
    return report + failures
