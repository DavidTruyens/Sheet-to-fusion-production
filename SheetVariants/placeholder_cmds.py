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
            # Fusion executes a PRE-EMPTED command "as if the user clicked OK" by
            # default, and switching documents pre-empts. Writing this mother's
            # setup attribute because someone changed tabs is not acceptable.
            cmd.isExecutedWhenPreEmpted = False
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
                    'This model has no joint origins. Put one on the centre of '
                    "this model's FRONT face — that is the point placed at the "
                    "centre of a placeholder box's front face. Use Assemble > "
                    'Joint Origin, then run this again.',
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
            dimension_drops = []
            for input_id, label, key in (('pWidth', 'Width parameter', 'width'),
                                         ('pDepth', 'Depth parameter', 'depth'),
                                         ('pHeight', 'Height parameter', 'height')):
                drop, matched = _add_dropdown(inputs, input_id, label, params,
                                              setup['params'][key])
                dimension_drops.append(drop)
                if not matched:
                    missing.append(key)

            if missing:
                inputs.addTextBoxCommandInput(
                    'missing', '',
                    'Previously saved selections no longer exist in this model '
                    'and have been reset: {}. Check every dropdown before '
                    'clicking OK.'.format(', '.join(missing)),
                    3, True)
            # With nothing stored yet every dropdown falls back to the FIRST
            # parameter, so all three start out identical. On a model whose
            # parameters are named d1/d2/d3 that is easy to miss, and clicking
            # OK would save a mother that drives one parameter for all three
            # dimensions — every child then comes out a cube, with no error.
            # Warn rather than block: a square-plan unit legitimately drives
            # width and depth from one parameter.
            # Read what the dropdowns actually SHOW, not what was stored — on a
            # first run nothing is stored and the shown values come from the
            # fallback, which is precisely the case this warns about.
            picked = []
            for drop in dimension_drops:
                try:
                    picked.append(drop.selectedItem.name if drop.selectedItem else '')
                except Exception:
                    picked.append('')
            chosen = [p for p in picked if p]
            if len(set(chosen)) < len(chosen):
                inputs.addTextBoxCommandInput(
                    'dupe', '',
                    'Two or more dimensions are mapped to the same parameter. '
                    'That is only right if this model really is driven that way '
                    '— otherwise pick a different parameter for each.',
                    3, True)
            inputs.addTextBoxCommandInput(
                'hint', '',
                "The anchor lands on the centre of the placeholder box's FRONT "
                'face — so put the joint origin on your model\'s front face. To '
                'shift the model within its box, move the joint origin.',
                4, True)   # 3 rows clipped this mid-sentence in practice

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
                'Prepared "{}".\n\nanchor: {} (lands on the centre of the '
                "placeholder box's front face)\nfront: {}\n"
                'width: {}\ndepth: {}\nheight: {}\n\n'
                'Save the document to keep this.'
                .format(design.parentDocument.name, setup['anchor'],
                        setup['front'],
                        setup['params']['width'], setup['params']['depth'],
                        setup['params']['height']))
        except Exception:
            ui.messageBox('Prepare Mother Model failed:\n' + traceback.format_exc())


FILL_CMD_ID = 'sheetVariantsFillPlaceholdersCmd'
FILL_CMD_NAME = 'Fill Placeholders'
FILL_CMD_DESC = ('Assign a prepared mother model to the selected placeholder '
                 'boxes. Each box drives its own width, depth and height; a '
                 'sheet config is optional and sets everything else.')

# Config dropdown labels. NO_CONFIG_LABEL is a real CHOICE — size-only, no sheet
# read at all — and is the default. The other two are unset states. All three
# start with an em dash, so code must compare against NO_CONFIG_LABEL by value
# rather than treating every dashed label as "nothing selected".
NO_CONFIG_LABEL = '— none (size only) —'
LOAD_CONFIGS_LABEL = '— press Load configs —'
NO_ROWS_LABEL = '— no named rows —'


def _body_vertices(body):
    """World (x, y, z) of every vertex of ``body``, in centimetres."""
    verts = body.vertices
    out = []
    for i in range(verts.count):
        point = verts.item(i).geometry
        out.append((point.x, point.y, point.z))
    return out


def _flat_face_normals(body):
    """Unit normals of every FLAT face of ``body``, in the same space its vertices
    are read in.

    Curved faces are skipped rather than approximated: a fillet says nothing about
    which way a box is turned, and treating one as if it did is what reported
    every filleted placeholder as rotated. Only parallelism is tested downstream,
    so an inward-pointing normal is as good as an outward one.
    """
    normals = []
    faces = body.faces
    for i in range(faces.count):
        try:
            plane = adsk.core.Plane.cast(faces.item(i).geometry)
            if not plane:
                continue
            normal = plane.normal
            normals.append((normal.x, normal.y, normal.z))
        except Exception:
            # One unreadable face must not decide the whole body's orientation;
            # the remaining flat faces still answer the question.
            continue
    return normals


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
            # The placement matrix is NOT built here. Composing it needs the
            # mother's anchor, and no mother has been chosen at this point —
            # Phase 2 builds it once the mother's setup is known.
            'centre': centre,
            'frame': frame,
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
            sheet_url = _own_sheet_url(other)
            # A multi-tab config sheet's rows live on whatever tab the user
            # pinned for it in the Build dialog — an empty tab makes
            # get_rows() fall through to the CSV export of the sheet's FIRST
            # tab (I6), which can be a completely different table.
            spreadsheet_id = sheet_core.extract_spreadsheet_id(sheet_url)
            tab = (SheetVariants.load_pinned_tab(settings, spreadsheet_id)
                   if spreadsheet_id else '')
            if not tab:
                # Nothing pinned for THIS sheet (never "Load tabs"-ed in the
                # Build dialog, or a single-tab/CSV link with no tabs to pin)
                # must not blank out a tab this mother was already known to
                # use — keep whatever the cache above already has for it
                # rather than stomping a real value with ''.
                cached = options.get(doc.dataFile.id)
                tab = cached['tab'] if cached else ''
            options[doc.dataFile.id] = {
                # dataFile.name, NOT doc.name: an open document's name carries a
                # version suffix, so doc.name is 'mother1 v16' and every heading
                # built from it read "mother1 v16 — v16" as though the version
                # had been printed twice.
                'fileId': doc.dataFile.id, 'name': doc.dataFile.name,
                'sheetUrl': sheet_url, 'tab': tab}
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

# fileIds this add-in has driven and RESTORED CLEANLY (unrestored_values() came
# back empty every time) at least once in this Fusion session. See _open_mother
# for why this exists: Fusion's isModified flag cannot by itself distinguish
# the user's own unsaved work from dirt a drive-then-restore cycle leaves
# behind even when every parameter came back exactly as captured.
_cleanly_restored_file_ids = set()


class FillCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            # THE important one. Pre-emption defaults to executing the command,
            # and executing this one opens the mother document, drives its
            # parameters and builds geometry. Switching documents must never do
            # that. See CommandCreatedHandler in SheetVariants.py.
            cmd.isExecutedWhenPreEmpted = False
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
            config.listItems.add(NO_CONFIG_LABEL, True)
            config.listItems.add(LOAD_CONFIGS_LABEL, False)
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
            if not inputs.itemById('mother'):
                return  # dialog stopped at "no prepared mother"; nothing built yet
            if changed.id == 'faces':
                selection = inputs.itemById('faces')
                faces = [selection.selection(i).entity
                         for i in range(selection.selectionCount)]
                slots, problems = resolve_slots(faces)
                inputs.itemById('report').formattedText = _describe(slots, problems)
            elif changed.id == 'mother':
                # A different mother's configs do not apply to whatever was
                # picked before — reset to the sentinel so OK cannot silently
                # build the new mother against a config that only happens to
                # share a name with one of its rows (I3).
                config = inputs.itemById('config')
                config.listItems.clear()
                config.listItems.add(NO_CONFIG_LABEL, True)
                config.listItems.add(LOAD_CONFIGS_LABEL, False)
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
                # Keep "none" first and selected: loading the list is not the
                # same as choosing a row, and size-only stays the default.
                config.listItems.add(NO_CONFIG_LABEL, True)
                for row in rows[1:]:
                    name = (row[0] or '').strip()
                    if name:
                        config.listItems.add(name, False)
                if config.listItems.count == 1:
                    config.listItems.add(NO_ROWS_LABEL, False)
        except RuntimeError as err:
            # Sheet-reading failures (network, sharing, format) carry a
            # carefully worded, user-actionable message — show it plainly
            # rather than wrapped in a stack trace (I4).
            ui.messageBox(str(err))
        except Exception:
            ui.messageBox('Fill Placeholders failed:\n' + traceback.format_exc())


class FillExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            if not inputs.itemById('mother'):
                return  # dialog stopped at "no prepared mother"; nothing built yet
            selection = inputs.itemById('faces')
            faces = [selection.selection(i).entity
                     for i in range(selection.selectionCount)]
            slots, problems = resolve_slots(faces)
            mother = _selected_mother(inputs)
            item = inputs.itemById('config').selectedItem
            label = item.name if item else ''
            # NO_CONFIG_LABEL is a real choice, not an unset placeholder: it
            # means "drive only width/depth/height from the box and leave every
            # other parameter at the mother's current value". The OTHER dashed
            # labels ("press Load configs", "no named rows") ARE unset states
            # and must not reach _row_values as a config name (I3).
            if label == NO_CONFIG_LABEL:
                config = ''
            elif label.startswith('—'):
                ui.messageBox('Pick a config, or leave it on "{}" to drive only '
                              'the size from each box.'.format(NO_CONFIG_LABEL))
                return
            else:
                config = label
            if not mother:
                ui.messageBox('Pick a mother model first.')
                return
            report = build_children(slots, mother, config)
            import sheet_core
            import SheetVariants
            settings = sheet_core.load_settings(SheetVariants.SETTINGS_FILE)
            sheet_core.remember_mother(settings, mother)
            sheet_core.save_settings(SheetVariants.SETTINGS_FILE, settings)
            lines = report + ['! ' + p for p in problems]
            ui.messageBox('\n'.join(lines) if lines else 'Nothing was built.')
        except RuntimeError as err:
            # build_children raises RuntimeError for whole-run preconditions
            # ("unsaved changes", "not fully prepared", a stale config, a
            # column that maps to no parameter) with a message already
            # written for the user — show it plainly, not as a traceback (I4).
            ui.messageBox(str(err))
        except Exception:
            ui.messageBox('Fill Placeholders failed:\n' + traceback.format_exc())


UPDATE_CMD_ID = 'sheetVariantsUpdateChildrenCmd'
UPDATE_CMD_NAME = 'Update Children'
UPDATE_CMD_DESC = ('Rebuild children whose mother model has moved on, or whose '
                   'placeholder box has been moved or resized.')

# The survey is resolved when the dialog opens and reused by the execute handler,
# so opening the dialog does its data-panel lookups exactly once.
_survey = []


class UpdateCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            # Executing a pre-empted command rebuilds geometry by default in
            # Fusion, and switching documents pre-empts. This command must
            # never rebuild silently — see PrepareCreatedHandler/FillCreatedHandler.
            cmd.isExecutedWhenPreEmpted = False
            inputs = cmd.commandInputs
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                inputs.addTextBoxCommandInput('err', '', 'Open a layout design first.',
                                              2, True)
                return

            global _survey
            _survey = survey_children(design)
            if not _survey:
                inputs.addTextBoxCommandInput(
                    'err', '',
                    'This design has no children yet. Run Fill Placeholders first.',
                    2, True)
                return

            # The status column is the widest because it carries whole
            # instructions ("rotated — re-run Fill Placeholders"), which Fusion
            # truncates mid-word rather than wrapping, hiding the very advice
            # that tells you what to do about the row.
            table = inputs.addTableCommandInput('children', 'Children', 4, '1:3:2:7')
            table.maximumVisibleRows = 14
            table.minimumVisibleRows = 6
            # Break groups on the heading KEY, not on its text. Two distinct
            # mother files sharing a name and a version render identical text, so
            # comparing text merged them into one group as though they were the
            # same model — see placeholder_core.mother_heading_key.
            last_mother = object()
            for index, row in enumerate(_survey):
                key = placeholder_core.mother_heading_key(row)
                heading = placeholder_core.mother_heading_for_row(row)
                if key != last_mother:
                    last_mother = key
                    label = inputs.addTextBoxCommandInput(
                        'head{}'.format(index), '', '<b>{}</b>'.format(heading), 1, True)
                    table.addCommandInput(label, table.rowCount, 0, 0, 3)

                tick = inputs.addBoolValueInput(
                    'tick{}'.format(index), '', True, '', row['status']['tick'])
                tick.isEnabled = not row['status']['problem']
                name = inputs.addTextBoxCommandInput(
                    'name{}'.format(index), '', row['name'], 1, True)
                config = inputs.addTextBoxCommandInput(
                    'cfg{}'.format(index), '', row['recipe']['config'], 1, True)
                state = inputs.addTextBoxCommandInput(
                    'st{}'.format(index), '',
                    placeholder_core.status_label(row['status']), 1, True)
                table_row = table.rowCount
                table.addCommandInput(tick, table_row, 0)
                table.addCommandInput(name, table_row, 1)
                table.addCommandInput(config, table_row, 2)
                table.addCommandInput(state, table_row, 3)

            handler = UpdateExecuteHandler()
            cmd.execute.add(handler)
            _handlers.append(handler)
            cmd.setDialogInitialSize(560, 520)
        except Exception:
            if ui:
                ui.messageBox('Update Children failed:\n' + traceback.format_exc())


def _ticked_rows(inputs):
    picked = []
    for index, row in enumerate(_survey):
        tick = inputs.itemById('tick{}'.format(index))
        if tick and tick.value and not row['status']['problem']:
            picked.append(row)
    return picked


class UpdateExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            if not inputs.itemById('children'):
                return  # dialog stopped at an error text box; nothing built
            picked = _ticked_rows(inputs)
            if not picked:
                ui.messageBox('Nothing ticked — nothing to update.')
                return
            report = update_children(picked)
            ui.messageBox('\n'.join(report) if report else 'Nothing was updated.')
        except Exception:
            ui.messageBox('Update Children failed:\n' + traceback.format_exc())


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
    (UPDATE_CMD_ID, UPDATE_CMD_NAME, UPDATE_CMD_DESC, UpdateCreatedHandler),
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
        control = (panel.controls.itemById(cmd_id)
                   or panel.controls.addCommand(definition))
        if control:
            # Without this the button is added to the panel's OVERFLOW ("...")
            # menu rather than the panel itself, so it looks like the command
            # was never registered at all. run() promotes its own two commands
            # the same way; this module was not doing it and the buttons were
            # invisible in practice.
            control.isPromoted = True
            control.isPromotedByDefault = True


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


def find_children(design):
    """(``{slot id: (occurrence, recipe)}``, ``{slot id: message}``) for every
    child in ``design`` — the second dict is slots whose child was found but
    cannot be rebuilt because it has been moved out of the top level.

    findAttributes returns the whole set in one call, so no occurrence tree is
    walked for that part. The attribute is written on the component, so its
    occurrence is found by matching component names against the root's DIRECT
    occurrences only — never ``allOccurrences`` (recursive/document-wide):
    build_children composes a WORLD matrix per slot and applies it straight to
    ``occurrence.transform2``, but a nested occurrence's ``transform2`` is
    relative to its PARENT occurrence, not world. Resolving through
    ``allOccurrences`` would silently place a nested child wrongly rather than
    fail loudly.

    That means a child a designer has grouped into a sub-assembly (e.g. a
    `Cabinets` component) is invisible to the direct-occurrence lookup even
    though its recipe attribute is found document-wide. Silently falling
    through to "unfilled" there would build a SECOND child on top of the
    first (I8) — so ``allOccurrences`` IS still consulted, but only to tell
    "exists, just not at the top level" apart from "does not exist at all",
    and only to produce a clear per-slot failure instead of a silent
    duplicate.

    Both loops guard per-item, matching find_slot_bodies' pattern: one dead
    occurrence or one unreadable attribute must not collapse this whole
    lookup to {}, which would read every already-filled slot as unfilled and
    duplicate it instead of rebuilding it in place.
    """
    found = {}
    moved = {}
    by_component = {}
    for occurrence in design.rootComponent.occurrences:
        try:
            by_component.setdefault(occurrence.component.name, occurrence)
        except Exception:
            continue
    nested_names = None  # computed lazily: only needed when a name misses above
    nested_unavailable = False
    for attribute in attribute_list(design.findAttributes(
            placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR)):
        try:
            recipe = placeholder_core.loads_attr(attribute.value,
                                                 placeholder_core.migrate_child_recipe)
            component_name = attribute.parent.name
        except Exception:
            continue
        if not recipe['slotId']:
            continue
        occurrence = by_component.get(component_name)
        if occurrence:
            found[recipe['slotId']] = (occurrence, recipe)
            continue
        if nested_names is None and not nested_unavailable:
            nested_names = set()
            try:
                for occ in design.rootComponent.allOccurrences:
                    try:
                        nested_names.add(occ.component.name)
                    except Exception:
                        continue
            except Exception:
                # The COLLECTION access itself failed, not one item. Guarding
                # only per-item would let this escape find_children entirely,
                # collapsing both dicts and reading every already-filled slot as
                # unfilled — which builds a SECOND child on top of each existing
                # one and strands the designer's downstream features in the
                # orphan. Refusing is the safe degradation: without this list we
                # cannot tell "moved into a sub-assembly" from "deleted", and
                # wrongly refusing a slot is loud and recoverable where wrongly
                # duplicating one is neither.
                nested_names = None
                nested_unavailable = True
        if nested_unavailable:
            moved[recipe['slotId']] = (
                'its child "{}" could not be located — Fusion did not return the '
                'component list, so it was left alone rather than risk building '
                'a duplicate on top of it'.format(component_name))
            continue
        if component_name in nested_names:
            moved[recipe['slotId']] = (
                'its child "{}" has been moved into a sub-assembly — move it '
                'back to the top level of the design to rebuild it'
                .format(component_name))
    return found, moved


def rebuild_child(design, occurrence, recipe, snaps, matrix16):
    """Swap a child's geometry and re-place it, keeping the component and anything
    the designer built on top of it.

    Returns ``(ok, line)``: ``line`` is always a human-readable report line,
    ``ok`` says whether the swap actually happened. Callers must branch on
    ``ok`` rather than on ``line``'s wording — dispatching control flow on a
    prose substring would couple a caller to this function's message text.
    When ``ok`` is False the geometry may be in a bad state, so nothing here
    re-places or re-skins the child; the caller must not treat it as rebuilt
    either (no new recipe, no touching the placeholder box).
    """
    component = occurrence.component
    base = build_engine.find_base_feature(component)
    if base is None:
        return False, '{} — cannot rebuild: its base feature was deleted'.format(
            component.name)
    ops = placeholder_core.pair_bodies(recipe['bodies'], [s['name'] for s in snaps])
    failure = build_engine.rebuild_base_feature(component, base, snaps, ops)
    if failure:
        return False, '{} — rebuild failed: {}'.format(component.name, failure)
    # reapply_looks pairs component.bRepBodies.item(i) with snaps[i] positionally
    # (its contract, unchanged — build_exports' fresh-build path depends on it,
    # and there snaps order IS collection order). On THIS path it is not: an
    # 'add' in ops always lands at the tail of the physical collection, not at
    # wherever pair_bodies happened to list it within snaps (see
    # resulting_body_names). Reorder snaps into that physical order first, or a
    # body ends up wearing a sibling's material/appearance (I1).
    physical_snaps = placeholder_core.resulting_snap_order(recipe['bodies'], snaps, ops)
    build_engine.reapply_looks(design, component, physical_snaps)
    matrix = adsk.core.Matrix3D.create()
    matrix.setWithArray(matrix16)
    occurrence.transform2 = matrix
    changed = sum(1 for op in ops if op[0] != 'update')
    return True, '{} — rebuilt {} bodies{}'.format(
        component.name, len(snaps),
        ', {} added or removed'.format(changed) if changed else '')


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


def _refuse_stale_open_version(doc, data_file):
    """Refuse to drive a mother that is OPEN at an older version than its newest.

    Update Children compares children against the lineage's latest version, so a
    dialog reading "built from v14, now v16" that then drove a v14 document would
    report success, stamp v14 back onto every child, and pre-tick the same rows
    next time — telling someone their children match v16 when they carry v14
    geometry.

    Applied to Update Children ONLY, deliberately, even though Fill Placeholders
    shares _open_mother and has a milder version of the same exposure. This rests
    on an open document's DataFile.versionNumber tracking the tip immediately
    after the user saves that document in the same session, and nothing here has
    measured that (spikes/SVSpike6VersionIds asks it). If Fusion hands back the
    pre-save DataFile, this refuses on the single most common workflow there is —
    edit the mother, save, leave it open, fill — and Fill has no graceful way to
    carry on: it aborts the whole run. Update Children catches the raise per
    mother and turns it into that mother's rows failing, so a wrong guess there
    costs a diagnosable message rather than the command. Once measured, this can
    move into _open_mother for both.

    Stays silent when the numbers will not read. Nothing can be proven then, and
    refusing on an unreadable property would block the ordinary case offline.
    """
    open_at = _int_or_none(data_file, 'versionNumber')
    latest = _int_or_none(data_file, 'latestVersionNumber')
    if open_at is None or latest is None or open_at >= latest:
        return
    # BEHIND, not merely different. A mother saved to v18 was seen with a
    # DataFile still reporting v17, so open_at can legitimately exceed latest —
    # and refusing on that would have thrown "open at v18, but v17 is the newest",
    # which is both nonsense and a dead end.
    raise RuntimeError(
        'The mother "{}" is open at v{}, but v{} is the newest version. Close it '
        'and run this again, so children are built from the newest version.'
        .format(_file_name(data_file) or doc.name, open_at, latest))


def _open_mother(file_id, require_latest=False):
    """(document, opened_by_us). Reuses an already-open document; refuses one with
    unsaved changes, because a run edits and restores its parameters and a crash
    partway would leave someone else's work in a variant state.

    Deliberately does NOT accept a recipe's recorded versionId as a fallback key,
    even though _resolve_mother_file does and findFileById can refuse a lineage
    id. documents.open() opens the version its DataFile names, so resolving
    through a versionId recorded at fill time would silently open and drive the
    OLD mother — rebuilding children off v14 when the point of the run is v16.
    Refusing with actionable advice beats quietly building the wrong thing."""
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        try:
            data_file = doc.dataFile
        except Exception:
            # Matches _mother_options' guard on the same access: an untitled
            # scratch document can raise something other than AttributeError
            # here, and one such document open anywhere in the session must not
            # abort Fill entirely.
            continue
        if data_file and data_file.id == file_id:
            if doc.isModified and file_id not in _cleanly_restored_file_ids:
                # isModified alone cannot tell the user's unsaved work apart
                # from dirt THIS add-in's own drive-then-restore cycle left
                # behind: restore_values() writes every driven parameter's
                # expression back exactly as captured, but Fusion still marks
                # the document modified because a write happened — not
                # because anything about the model actually changed. Refusing
                # unconditionally would trip on the very first Fill run after
                # Prepare (which itself writes a document attribute), or on a
                # second Fill in the same session after a first one drove and
                # cleanly restored the mother. And "just save it" is bad
                # advice here: saving mints a new cloud version of a
                # geometrically unchanged mother, staling every child already
                # built off the current one (I5).
                #
                # So a fileId only ever enters _cleanly_restored_file_ids once
                # build_children has driven it and confirmed EVERY restore
                # came back clean (see the unrestored_names check there) — a
                # genuinely dirty document still refuses the first time in a
                # session, and a run whose restore did NOT come back clean
                # never gets added, so the next attempt keeps refusing too.
                raise RuntimeError(
                    'The mother "{}" has unsaved changes. Save or discard them '
                    'before filling placeholders.'.format(doc.name))
            if require_latest:
                _refuse_stale_open_version(doc, data_file)
            return doc, False
    reason = ''
    try:
        data_file = app.data.findFileById(file_id)
    except Exception as err:
        # findFileById RAISES "3 : file not found" rather than returning None for
        # a lineage id it will not answer for (spike 5), so the bare call cannot
        # stand in for a None check. The message is kept rather than swallowed:
        # a permission, hub or network failure reads nothing like a missing file,
        # and reporting all of them as "not found" hides the real cause.
        data_file, reason = None, ' ({})'.format(_exc_text(err))
    if not data_file:
        # Actionable, because the likeliest cause is not a deleted file: Fusion's
        # findFileById has been seen refusing a perfectly valid lineage id, and
        # opening the mother yourself sidesteps the lookup entirely.
        raise RuntimeError(
            'The mother model could not be found in your projects{}. If the file '
            'does still exist, open it in Fusion and run this again.'.format(reason))
    return app.documents.open(data_file), True


def _snapshot_for(setup, values, dims_cm, unrestored_names):
    """Drive the mother to one config-and-size and snapshot its solids, already
    transformed into the child's local space with the anchor at the origin.

    Takes no ``design`` argument — every read below re-derives the design
    fresh from ``app.activeProduct`` instead. On the 2nd+ distinct size in a
    run, a handle from an earlier call has already survived one or more
    recomputes, which is exactly what build_engine._design()'s docstring
    warns can invalidate a held collection. The anchor read further down,
    after apply_values(), already re-derives its own fresh handle too.

    ``unrestored_names`` is a ``set`` the caller owns across the whole run:
    any parameter this call could not restore is added to it here rather than
    surfaced with a message box in this function. Collecting into one set and
    letting the caller show a single box once the progress dialog is hidden
    avoids popping a modal warning while another modal dialog is still on
    screen.
    """
    frame = placeholder_core.mother_frame(setup['front'])
    design = adsk.fusion.Design.cast(app.activeProduct)
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
        try:
            adsk.doEvents()
        except Exception:
            pass
        # restore_values() is deliberately best-effort per parameter, so a
        # failed write is otherwise invisible. Verify it actually happened —
        # even when the try above raised — because a mother silently left
        # holding a driven value is a document that isModified will then push
        # the user to SAVE, permanently baking that driven value in. Guarded:
        # a throw here must not replace whatever exception the try above may
        # already be propagating, and must not stop the caller's own cleanup
        # (progress.hide(), returning to the layout, closing the mother).
        try:
            unrestored_names.update(build_engine.unrestored_values(original))
        except Exception:
            pass
    build_engine.transform_snapshot(
        snaps, placeholder_core.local_matrix((point.x, point.y, point.z), frame))
    return snaps


def build_children(slots, mother, config):
    """Phases 1 and 2: drive the mother once per distinct size, then create a child
    component per slot in the layout document.

    The mother we opened is closed only at the very end, AFTER Phase 2 — not at
    the end of Phase 1. Phase 1's snapshot_bodies() captures LIVE Appearance and
    Material objects owned by the mother's bodies, and Phase 2's reapply_looks()
    dereferences them (addByCopy() needs the live source). Closing the mother
    between the two phases, as an earlier draft did, invalidates those objects
    exactly the way activating another document invalidates every other live
    reference to this one — build_exports() gets away with the same pattern only
    because it never closes its source document.

    Returns one report line per slot. A slot that cannot be built contributes a
    failure line and is skipped; it never aborts the run, so one bad box does not
    cost you the whole kitchen. Whole-run preconditions — the mother not being
    prepared, unsaved changes in the mother, or a sheet column that maps to no
    parameter — still abort the entire run before anything is touched.
    """
    layout_doc = app.activeDocument
    import SheetVariants
    if config:
        rows_url, rows_tab = mother['sheetUrl'], mother['tab'] or None
        values = _row_values(SheetVariants.get_rows(rows_url, rows_tab), config)
    else:
        # Size-only: the box drives width/depth/height and every other parameter
        # keeps the mother's current value. No sheet is read, so a mother that
        # has never been linked to one is perfectly usable this way.
        rows_url, rows_tab = '', ''
        values = {}

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

    failures = []
    report = []
    by_size = {}
    doc = None
    opened_by_us = False
    version = None
    version_id = ''
    file_name = ''
    cancelled_at = None
    unrestored_names = set()

    # The progress dialog covers Phase 1 only: driving and recomputing the mother
    # is the slow part, while Phase 2 just copies snapshots that are already made.
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True

    try:
        # Phase 1 — everything that needs the mother, with the layout in the
        # background. show() and _open_mother() are both inside this try, with
        # hide() in its finally, so the most likely abort in normal use — the
        # mother having unsaved changes — hides the dialog instead of orphaning
        # it in front of the error message box.
        try:
            progress.show('Filling placeholders', 'Placeholder %v of %m', 0,
                          len(slots), 0)
            doc, opened_by_us = _open_mother(mother['fileId'])
            version = doc.dataFile.versionNumber if doc.dataFile else None
            # Guarded on its own: versionId is only a fallback lookup key for a
            # LATER run, so a DataFile that will not answer for it must not
            # abort this fill, which needs nothing from it.
            try:
                version_id = doc.dataFile.versionId if doc.dataFile else ''
            except Exception:
                version_id = ''
            # From the FILE, not from mother['name']: a mother that was closed
            # when this dialog opened is described by the settings cache, whose
            # names were written under the old doc.name behaviour and so carry a
            # version suffix ('mother1 v16'). The document is open by now, so the
            # real name is available and worth recording instead.
            file_name = _file_name(doc.dataFile)
            if file_name:
                # Written back into the caller's own descriptor, which is what
                # remember_mother persists — otherwise settings.json keeps the
                # old doc.name-derived 'mother1 v16' indefinitely and the
                # dropdown shows it for every closed mother.
                mother['name'] = file_name
            doc.activate()
            adsk.doEvents()
            mother_design = adsk.fusion.Design.cast(app.activeProduct)
            setup = placeholder_core.migrate_mother_setup(
                read_mother_setup(mother_design))
            errors = placeholder_core.validate_mother_setup(setup)
            if errors:
                raise RuntimeError('"{}" is not fully prepared:\n• {}'
                                   .format(mother['name'], '\n• '.join(errors)))
            # A renamed or deleted mother parameter must fail loudly up front,
            # matching build_exports' own check — not silently build a
            # wrongly-sized or wrongly-configured child that reads as a success.
            missing_columns = sorted(
                name for name in values
                if not mother_design.allParameters.itemByName(name))
            if missing_columns:
                raise RuntimeError(
                    'These columns do not match any parameter in "{}": {}'
                    .format(mother['name'], ', '.join(missing_columns)))

            # One drive per DISTINCT size: a run of identical units costs one
            # recompute. A cancel stops driving further sizes but does not raise
            # — a deliberate cancel must read as a cancellation in the final
            # report, not as a crash.
            for index, slot in enumerate(slots):
                if progress.wasCancelled:
                    cancelled_at = index
                    break
                key = tuple(round(v, 6) for v in slot['dims_cm'])
                if key not in by_size:
                    try:
                        by_size[key] = _snapshot_for(setup, values, slot['dims_cm'],
                                                     unrestored_names)
                    except Exception as err:
                        # One unusable slot must not cost the whole run.
                        failures.append('{} — {}'.format(slot['name'], err))
                progress.progressValue = index + 1
        finally:
            try:
                progress.hide()
            except Exception:
                pass

        # Surface any restore failures ONE time, now that the progress dialog
        # is (or at least was attempted to be) off screen — not per size, and
        # not while a modal progress dialog is still up, which would just
        # reintroduce the orphaned-dialog problem at a new site.
        if unrestored_names:
            # A mother THIS RUN opened is discarded via close(False) in the
            # outer finally moments after this would show, regardless of what
            # could not be restored — its on-disk file was never touched, so
            # "close it without saving" would be both unactionable (it is
            # already closed by the time anyone could act on it) and
            # needlessly alarming. Only a mother the user already had open
            # stays open and modified after this function returns, which is
            # the one case where the warning is both true and useful.
            if not opened_by_us:
                ui.messageBox(
                    'Fill Placeholders could not restore {} to its original value '
                    'in "{}" after this run.\n\nThis mother is left MODIFIED with '
                    'a driven value still applied. Close it WITHOUT SAVING — '
                    'saving now would make that value permanent.'
                    .format(', '.join(sorted(unrestored_names)), mother['name']))
        else:
            # Every value driven in this run came back exactly as captured —
            # any "modified" flag Fusion now shows on this mother is dirt this
            # add-in's own drive-and-restore left behind, not unsaved user
            # work. Let _open_mother's isModified check trust that for the
            # rest of this session (I5).
            _cleanly_restored_file_ids.add(mother['fileId'])

        # Phase 2 — back in the layout, but the mother is STILL OPEN: its
        # Appearance/Material objects, referenced live from the snapshots in
        # by_size, must stay alive until reapply_looks() has copied them into
        # the layout's design. The mother is only closed in the outer finally,
        # once this phase is done.
        layout_doc.activate()
        adsk.doEvents()
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent
        tbm = adsk.fusion.TemporaryBRepManager.get()
        built_at = datetime.datetime.now().isoformat(timespec='seconds')
        # Re-resolve the placeholder bodies AFTER the document switch. The
        # references captured in Phase 0 are dead; these are looked up fresh by
        # the slot ids stamped above. Guarded: one throw here must not lose the
        # whole run after the mother has already been opened, driven and
        # (about to be) closed — it only costs the "hide the box" step below.
        try:
            slot_bodies = find_slot_bodies(design)
        except Exception as err:
            slot_bodies = {}
            failures.append('Could not re-find placeholder bodies to hide them: {}'
                            .format(err))
        # Already-filled slots are rebuilt in place rather than recreated (see
        # rebuild_child); this must not lose the whole run if it fails, so a
        # slot whose child cannot be found this way is just treated as unfilled
        # and built fresh below, at the cost of possibly duplicating a child
        # that already exists.
        try:
            children, moved_children = find_children(design)
        except Exception as err:
            children, moved_children = {}, {}
            failures.append('Could not look up already-filled slots ({}); any '
                            'that exist will be duplicated instead of rebuilt.'
                            .format(err))

        for index, slot in enumerate(slots):
            if cancelled_at is not None and index >= cancelled_at:
                failures.append('{} — cancelled before it was built.'
                                .format(slot['name']))
                continue
            key = tuple(round(v, 6) for v in slot['dims_cm'])
            template = by_size.get(key)
            if template is None:
                continue  # its failure is already recorded
            if not template:
                failures.append('{} — the mother produced no solid bodies at '
                                'that size.'.format(slot['name']))
                continue
            if not slot['slotId']:
                failures.append('{} — no slot id was stamped, so its recipe '
                                'would not be usable later; skipped.'
                                .format(slot['name']))
                continue
            if slot['slotId'] in moved_children:
                # Better a clear refusal than the silent duplicate building it
                # fresh below would create (I8): its recipe attribute exists,
                # so it is NOT unfilled, but find_children could not resolve
                # it to a top-level occurrence it can safely rebuild.
                failures.append('{} — {}.'.format(slot['name'], moved_children[slot['slotId']]))
                continue

            # Phase 2 is isolated per slot: an occurrence is only ever left
            # behind once it has a full recipe attribute. A throw partway
            # through — add_snapshot, reapply_looks, the attribute write — must
            # not abort every remaining slot, and must not leave the half-built
            # occurrence it was working on: an empty component with no recipe
            # is exactly the half-built child this design forbids.
            occurrence = None
            created = False
            try:
                # Compose the placement HERE, not in resolve_slots: it needs the
                # mother, which was not chosen when the faces were resolved.
                # anchor_target gives the centre of the box's front face;
                # occurrence_matrix then puts the child's local origin (the
                # anchor, after local_matrix) there.
                slot_matrix = placeholder_core.occurrence_matrix(
                    placeholder_core.anchor_target(
                        slot['centre'], slot['frame'], slot['dims_cm']),
                    slot['frame'])
                # Copy again per slot: identical units share one recompute, not
                # one body.
                snaps = [{'temp': tbm.copy(s['temp']), 'appearance': s['appearance'],
                          'material': s['material'], 'name': s['name']}
                         for s in template]

                existing = children.get(slot['slotId']) if slot['slotId'] else None
                new_names = [s['name'] for s in snaps]
                if existing:
                    # Already filled: swap the geometry in place inside its base
                    # feature (rebuild_child / rebuild_base_feature) instead of
                    # recreating the component, so downstream features the
                    # designer added survive. rebuild_child reports an expected
                    # failure (an old base feature, a stale recipe, a downstream
                    # feature that could not recompute) via its (ok, line)
                    # return rather than raising, so branch on ok — not on line's
                    # wording, which is prose for the user, not a control signal.
                    occurrence, old_recipe = existing
                    ok, line = rebuild_child(design, occurrence, old_recipe, snaps,
                                             slot_matrix)
                    if not ok:
                        # The geometry may be in a bad state: do not stamp a new
                        # recipe over it or touch the box below. Leave the last
                        # known-good recipe in place for the user to inspect.
                        failures.append(line)
                        continue
                    # The base feature's PHYSICAL body order after the swap is
                    # not necessarily new_names' order: an 'add' always lands at
                    # the tail of the real collection, wherever pair_bodies
                    # happened to list it within new_names. Recording new_names
                    # here instead would corrupt the NEXT rebuild's pairing
                    # silently — no exception, no failure line — because that
                    # rebuild's old_index values would then point at whatever
                    # body actually sits at each position, not the one the
                    # recipe claims.
                    body_names = placeholder_core.resulting_body_names(
                        old_recipe['bodies'], new_names,
                        placeholder_core.pair_bodies(old_recipe['bodies'], new_names))
                else:
                    matrix = adsk.core.Matrix3D.create()
                    matrix.setWithArray(slot_matrix)
                    occurrence = root.occurrences.addNewComponent(matrix)
                    created = True
                    occurrence.component.name = _unique_component_name(root, slot['name'])
                    build_engine.add_snapshot(occurrence.component, snaps)
                    build_engine.reapply_looks(design, occurrence.component, snaps)
                    # A brand-new component starts empty, so snaps order IS
                    # collection order — no reordering to account for here,
                    # unlike the rebuild branch above.
                    body_names = new_names
                    line = '{} — built {} bodies'.format(slot['name'], len(snaps))

                recipe = placeholder_core.new_child_recipe(
                    slot_id=slot['slotId'],
                    mother={'fileId': mother['fileId'],
                            'name': file_name or mother['name'],
                            'version': version},
                    # rows_url/rows_tab are '' for a size-only child, so the
                    # recipe records that no sheet was involved and a later
                    # rebuild knows not to look for one.
                    config=config, sheet_url=rows_url, tab=(rows_tab or ''),
                    dims_cm=slot['dims_cm'],
                    bodies=body_names,
                    built_at=built_at,
                    version_id=version_id)
                occurrence.component.attributes.add(
                    placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR,
                    placeholder_core.dumps_attr(recipe))
                body = slot_bodies.get(slot['slotId'])
                if body is not None:
                    try:
                        body.isLightBulbOn = False
                    except Exception:
                        pass
                # Appended only now, after every step that could still throw and
                # leave the child half-updated — so a slot never ends up with
                # both a "built"/"rebuilt" line and a failure line in the same
                # report (I5): if the recipe write or box hide above throws, the
                # except block below records the failure and this line, having
                # never been appended, does not also claim success.
                report.append(line)
            except Exception as err:
                # Only ever delete an occurrence THIS iteration created. An
                # already-filled slot's occurrence pre-dates this run — deleting
                # it because a later step (the recipe write, the box hide) threw
                # would destroy the designer's real component, recipe and all,
                # which is exactly what rebuilding in place exists to prevent.
                if created and occurrence is not None:
                    try:
                        occurrence.deleteMe()
                    except Exception:
                        pass
                failures.append('{} — {}'.format(slot['name'], err))
    finally:
        # Always return to the layout — on success, on a whole-run failure, and
        # on cancellation alike — so the user is never left staring at the
        # mother, whether or not it was ever activated. Unconditional rather
        # than guarded by an activeDocument comparison: re-activating a
        # document that is already active is harmless, and the Fusion API's
        # wrapper objects are not guaranteed to compare equal by identity.
        try:
            layout_doc.activate()
            adsk.doEvents()
        except Exception:
            pass
        # Close the mother LAST, now that Phase 2 no longer needs its live
        # Appearance/Material objects, and only if this run is the one that
        # opened it — never a document the user already had open. Guarded so a
        # throw here cannot mask whatever real exception is already propagating.
        if opened_by_us and doc is not None:
            try:
                doc.close(False)
            except Exception:
                pass
        try:
            adsk.doEvents()
        except Exception:
            pass

    return report + failures


def _exc_text(err):
    """A report-line-safe rendering of an exception: never blank, so a caller
    formatting '{} — {}'.format(name, _exc_text(err)) can't produce a dangling
    em dash when str(err) is empty. That is more likely to happen here than
    elsewhere in this module now that several of update_children's catches
    are deliberately broad `except Exception` — not just the narrow,
    message-carrying RuntimeErrors this add-in usually raises. The type name
    substitutes ONLY when str(err) is blank — every other exception-to-report
    site in this module prints the bare message, and a carefully worded
    RuntimeError (e.g. one of _row_values' own) should keep reading that way
    rather than gaining a needless 'RuntimeError: ' prefix."""
    text = str(err)
    return text if text else type(err).__name__


def update_children(rows):
    """Rebuild the given children, phased exactly as build_children is: everything
    needing a mother happens with that mother active, then the layout is
    reactivated once and every child is swapped in place.

    Children are grouped by mother so each mother is opened once, and within a
    mother by (config, sheet, size) so identical units share one recompute —
    the same two-level grouping build_children uses, just with several
    mothers instead of one. One failing mother's children fail only that
    mother's children — every other mother's children still get their turn —
    and one failing child fails only that child, never the run.

    Each row already carries its own recipe (what to drive the mother to) and
    its own current matrix/dims_cm (survey_children's fresh read of the box) —
    unlike build_children there is no Phase 0 to resolve, since the survey
    already did it. What survey_children could NOT hand over is a live
    Occurrence: Phase 1 activates one or more mother documents before Phase 2
    ever runs, and activating a document invalidates every live reference to
    another one, so a row never carries an occurrence at all (see
    survey_children's own comment on the point). Phase 2 re-resolves every
    occurrence fresh via find_children instead, exactly as build_children's
    own Phase 2 does.
    """
    layout_doc = app.activeDocument
    import SheetVariants

    by_mother = {}
    for row in rows:
        by_mother.setdefault(row['recipe']['mother']['fileId'], []).append(row)

    snapshots, versions, version_ids, mother_names, failures = {}, {}, {}, {}, []
    # {fileId: (doc, opened_by_us)} — closed only in the OUTER finally, after
    # Phase 2, because reapply_looks() (called from rebuild_child) still needs
    # each mother's live Appearance/Material objects until then. Copies
    # build_children's structure, just keyed by mother since there can be
    # several open at once here.
    mother_docs = {}
    unrestored_by_mother = {}
    # id(row), not the row itself: rows are plain dicts (unhashable), and this
    # function never copies or replaces any row in `rows` — every row stays
    # the same object for the whole call, in both by_mother's groups and the
    # flat `rows` list Phase 2 iterates, so identity-by-id is a safe, stable
    # key across both phases.
    attempted = set()
    cancelled = False
    report = []
    # (url, tab) -> sheet_rows, so several children sharing a mother's linked
    # sheet cost one HTTP read for the whole run rather than one per distinct
    # key, and all of them see the same revision even if the sheet is edited
    # mid-run.
    sheet_cache = {}
    # key -> failure text. A key that has already failed once is not retried
    # for a later child that happens to share it — the failure (a stale
    # config, a column that no longer maps to a parameter) is exactly as
    # doomed the second time, and retrying would silently re-run an expensive
    # drive-and-recompute for every sibling. Recording the message here is
    # what still gives every affected child its own report line.
    failed_keys = {}

    # The progress dialog covers Phase 1 only: driving and recomputing each
    # mother is the slow part, while Phase 2 just copies snapshots that are
    # already made — matching build_children's own split.
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True

    try:
        try:
            progress.show('Updating children', 'Child %v of %m', 0, len(rows), 0)
            done = 0
            for file_id, group in by_mother.items():
                if cancelled:
                    break
                # The survey's resolved name, falling back to the recorded one:
                # a child built before the name fix recorded the document name
                # ('mother1 v16'), and every message below would otherwise quote
                # it back — the same stale text the headings no longer show.
                mother_name = (group[0].get('mother_name')
                               or group[0]['recipe']['mother']['name'])
                try:
                    doc, opened_by_us = _open_mother(file_id, require_latest=True)
                except Exception as err:
                    # Broader than _open_mother's documented RuntimeError: a
                    # Fusion API failure opening ONE mother must not sink every
                    # other mother's children in the same run.
                    for row in group:
                        attempted.add(id(row))
                        failures.append('{} — {}'.format(row['name'], _exc_text(err)))
                        done += 1
                        progress.progressValue = done
                    continue
                mother_docs[file_id] = (doc, opened_by_us)
                try:
                    doc.activate()
                    adsk.doEvents()
                    # Document.activate() returns a bool this add-in has
                    # never checked — build_children gets away with that
                    # because it only ever activates ONE mother per run. This
                    # loop activates SEVERAL in sequence inside one execute
                    # handler: if a later activate() silently no-ops,
                    # app.activeProduct keeps describing whatever mother was
                    # active before it, and every read below —
                    # mother_design, read_mother_setup,
                    # validate_mother_setup, and _snapshot_for's own drive —
                    # would then work against the WRONG mother while this
                    # group's version and config are stamped onto its
                    # children regardless. That is silently wrong geometry
                    # with no loud edge, so confirm the switch actually
                    # landed before trusting anything read from
                    # app.activeProduct. Raising here is caught by this
                    # try's own except below, which fails every not-yet-
                    # attempted row in THIS mother's group without aborting
                    # any other mother's — matching how _open_mother's own
                    # refusal just above is handled.
                    active = app.activeDocument
                    try:
                        # Guarded: a scratch document with no saved file
                        # raising here must not be mistaken for the real
                        # failure this check exists to catch — it simply
                        # cannot be the mother asked for either way, so it
                        # falls through to the mismatch below.
                        active_file = active.dataFile if active else None
                    except Exception:
                        active_file = None
                    if not active_file or active_file.id != file_id:
                        raise RuntimeError(
                            'could not switch to the mother "{}" — another '
                            'document was active instead'.format(mother_name))
                    mother_design = adsk.fusion.Design.cast(app.activeProduct)
                    setup = read_mother_setup(mother_design)
                    errors = placeholder_core.validate_mother_setup(setup)
                    if errors:
                        for row in group:
                            attempted.add(id(row))
                            failures.append('{} — mother not prepared: {}'.format(
                                row['name'], '; '.join(errors)))
                            done += 1
                            progress.progressValue = done
                        continue
                    versions[file_id] = (doc.dataFile.versionNumber
                                        if doc.dataFile else None)
                    try:
                        version_ids[file_id] = (doc.dataFile.versionId
                                                if doc.dataFile else '')
                    except Exception:
                        # See build_children: a fallback key for a later run is
                        # never worth failing this mother's children over.
                        version_ids[file_id] = ''
                    # Re-read from the FILE, so a rebuild heals a name recorded
                    # from the document ('mother1 v16') instead of carrying it
                    # forward forever. Copying recipe['mother']['name'] here is
                    # what made that stale name immortal.
                    mother_names[file_id] = _file_name(doc.dataFile)
                    mother_unrestored = set()
                    drove_ok = False   # at least one clean _snapshot_for (M7)
                    for row in group:
                        if progress.wasCancelled:
                            cancelled = True
                            break
                        attempted.add(id(row))
                        recipe = row['recipe']
                        key = None
                        try:
                            # Everything the dedup key depends on lives INSIDE
                            # this try, not just the drive that follows it: a
                            # malformed dims_cm must fail this one child, not
                            # blow up the whole loop with a bare traceback.
                            # sheetUrl/tab are part of the key (not just
                            # config+size) because they are per-child recorded
                            # data too — two children of the same mother at
                            # the same config name and size but pointing at
                            # different spreadsheets must not collide and
                            # silently share one child's values.
                            key = (file_id, recipe['config'], recipe['sheetUrl'],
                                  recipe['tab'],
                                  tuple(round(v, 6) for v in row['dims_cm']))
                            if key in failed_keys:
                                failures.append('{} — {}'.format(
                                    row['name'], failed_keys[key]))
                            elif key not in snapshots:
                                # A config is OPTIONAL (since 1.15.0): an empty
                                # config means size-only — no sheet exists to
                                # read, and recipe['sheetUrl']/['tab'] are ''
                                # too, so calling get_rows would fail on a
                                # perfectly valid child.
                                if recipe['config']:
                                    cache_key = (recipe['sheetUrl'] or '',
                                                recipe['tab'] or None)
                                    if cache_key not in sheet_cache:
                                        sheet_cache[cache_key] = SheetVariants.get_rows(
                                            cache_key[0], cache_key[1])
                                    values = _row_values(sheet_cache[cache_key],
                                                         recipe['config'])
                                else:
                                    values = {}
                                # A renamed or deleted mother parameter must
                                # fail loudly here, per child, exactly as
                                # build_children fails loudly up front for its
                                # one config — not silently drive the
                                # mother's CURRENT value instead of the
                                # config's and report a rebuilt child as a
                                # success that the next survey then reads as
                                # "up to date". Checked per child (not once
                                # per run, as build_children does) because
                                # different children of the same mother can
                                # carry different configs.
                                # Re-derived fresh here, not read off the
                                # `mother_design` captured before this loop
                                # started: by the 2nd or later distinct key, a
                                # prior row's _snapshot_for has already
                                # driven and recomputed the model at least
                                # once, and build_engine._design()'s
                                # docstring is explicit that a Design handle
                                # held across a parameter write can already
                                # be dead — this check would then fail loudly
                                # on a live mother for no real reason, and
                                # refuse every sibling sharing the same key
                                # too (see failed_keys).
                                current_design = adsk.fusion.Design.cast(
                                    app.activeProduct)
                                missing_columns = sorted(
                                    name for name in values
                                    if not current_design.allParameters.itemByName(name))
                                if missing_columns:
                                    raise RuntimeError(
                                        'these columns do not match any parameter '
                                        'in "{}": {}'.format(
                                            mother_name, ', '.join(missing_columns)))
                                snapshots[key] = _snapshot_for(
                                    setup, values, row['dims_cm'], mother_unrestored)
                                drove_ok = True
                        except Exception as err:
                            # One unusable child must not cost the whole run.
                            text = _exc_text(err)
                            if key is not None:
                                failed_keys[key] = text
                            failures.append('{} — {}'.format(row['name'], text))
                        done += 1
                        progress.progressValue = done
                    if mother_unrestored:
                        unrestored_by_mother[file_id] = (mother_name, mother_unrestored)
                    elif drove_ok:
                        # At least one value driven for THIS mother in this
                        # run came back exactly as captured — any "modified"
                        # flag Fusion now shows on it is dirt this add-in's
                        # own drive-and-restore left behind, not unsaved user
                        # work. Let _open_mother's isModified check trust that
                        # for the rest of this session, so a second Update (or
                        # a Fill) can reuse this mother without a false
                        # "unsaved changes" refusal. Gated on drove_ok, not
                        # just on mother_unrestored being empty: if nothing
                        # was actually driven — every child cancelled or
                        # failed before reaching _snapshot_for — there is no
                        # evidence this session left the mother clean, only
                        # that it was never touched.
                        _cleanly_restored_file_ids.add(file_id)
                except Exception as err:
                    # Something unexpected went wrong driving this mother, not
                    # a per-child snapshot failure (already handled above) —
                    # fail whatever in this group has not yet been attempted
                    # rather than aborting every other mother's children.
                    for row in group:
                        if id(row) not in attempted:
                            attempted.add(id(row))
                            failures.append('{} — {}'.format(row['name'], _exc_text(err)))
                            done += 1
                            progress.progressValue = done
        finally:
            try:
                progress.hide()
            except Exception:
                pass

        # Surface any restore failures ONE time, now that the progress dialog
        # is (or at least was attempted to be) off screen — not per mother,
        # and not while a modal progress dialog is still up, which would just
        # reintroduce the orphaned-dialog problem at a new site (see
        # build_children's identical comment).
        #
        # Only a mother this run did NOT open belongs in this warning: one we
        # opened ourselves is discarded via close(False) in the outer finally
        # regardless of what could not be restored — its on-disk file was
        # never touched — so telling the user to close it without saving
        # would be both unactionable (already closed by the time anyone could
        # act) and needlessly alarming. A mother the user already had open
        # stays open and modified after we return, which is the one case
        # this warning is for.
        already_open = {fid: pair for fid, pair in unrestored_by_mother.items()
                        if not mother_docs.get(fid, (None, False))[1]}
        if already_open:
            lines = ['Update Children could not restore every parameter it '
                    'drove back to its original value in one or more mothers '
                    'you already had open:', '']
            for name, names in sorted(already_open.values(), key=lambda pair: pair[0]):
                lines.append('"{}": {}'.format(name, ', '.join(sorted(names))))
            lines.append('')
            lines.append('These are left MODIFIED with a driven value still '
                         'applied. Close them WITHOUT SAVING — saving now '
                         'would make that value permanent.')
            ui.messageBox('\n'.join(lines))

        # Phase 2 — back in the layout, but every mother opened above is STILL
        # OPEN: its Appearance/Material objects, referenced live from the
        # snapshots in `snapshots`, must stay alive until reapply_looks()
        # (called from rebuild_child) has copied them into the layout's
        # design. Mothers are only closed in the outer finally, once this
        # phase is done.
        layout_doc.activate()
        adsk.doEvents()
        design = adsk.fusion.Design.cast(app.activeProduct)
        tbm = adsk.fusion.TemporaryBRepManager.get()
        built_at = datetime.datetime.now().isoformat(timespec='seconds')

        # Re-resolve every child's occurrence AFTER the document switch. Phase
        # 1 activated one or more mother documents above, which invalidates
        # every live reference to the layout — which is exactly why
        # survey_children never put one on a row to begin with. One
        # attribute scan for the whole run, exactly matching build_children's
        # own Phase 2 re-lookup (find_slot_bodies/find_children).
        try:
            children, moved = find_children(design)
        except Exception as err:
            children, moved = {}, {}
            failures.append('Could not re-find children after returning to '
                            'the layout: {}'.format(_exc_text(err)))

        for row in rows:
            if id(row) not in attempted:
                # Cancellation stopped Phase 1 before this row was ever looked
                # at — a deliberate cancel must read as a cancellation in the
                # final report, not as a crash.
                failures.append('{} — cancelled before it was built.'
                                .format(row['name']))
                continue

            # Phase 2 is isolated per child, matching build_children's own
            # Phase 2: a throw partway through must fail only this one child.
            # The dedup key is computed INSIDE this try too, not before it —
            # a malformed dims_cm must fail this one child, not abort every
            # remaining one with a bare traceback.
            try:
                recipe = row['recipe']
                file_id = recipe['mother']['fileId']
                key = (file_id, recipe['config'], recipe['sheetUrl'],
                      recipe['tab'], tuple(round(v, 6) for v in row['dims_cm']))
                template = snapshots.get(key)
                if template is None:
                    continue  # already recorded in failures
                if not template:
                    failures.append('{} — the mother produced no solid bodies '
                                    'at that size.'.format(row['name']))
                    continue

                fresh = children.get(recipe['slotId'])
                if not fresh:
                    if recipe['slotId'] in moved:
                        # A better, more actionable reason than the generic
                        # one below: the child still exists, it has just been
                        # dragged into a sub-assembly between the dialog
                        # opening and OK, matching build_children's own
                        # wording for the same situation.
                        failures.append('{} — {}.'.format(
                            row['name'], moved[recipe['slotId']]))
                    else:
                        failures.append(
                            '{} — its occurrence could not be re-found in the '
                            'layout after switching back from the mother; '
                            'skipped.'.format(row['name']))
                    continue
                occurrence, _current_recipe = fresh

                snaps = [{'temp': tbm.copy(s['temp']), 'appearance': s['appearance'],
                         'material': s['material'], 'name': s['name']}
                        for s in template]
                # rebuild_child reports an expected failure (an old base
                # feature, a stale recipe, a downstream feature that could not
                # recompute) via its (ok, line) return rather than raising, so
                # branch on ok — not on line's wording, which is prose for the
                # user, not a control signal.
                ok, line = rebuild_child(design, occurrence, recipe, snaps,
                                         row['matrix'])
                if not ok:
                    # The geometry may be in a bad state: never stamp a fresh
                    # recipe over a swap that failed. The child keeps its last
                    # known-good recipe in place for the user to inspect.
                    failures.append(line)
                    continue
                # The base feature's PHYSICAL body order after the swap is not
                # necessarily new_names' order — see resulting_body_names.
                # Recording new_names directly here would corrupt the NEXT
                # rebuild's pairing silently, the same trap build_children's
                # own rebuild branch guards against.
                new_names = [s['name'] for s in snaps]
                body_names = placeholder_core.resulting_body_names(
                    recipe['bodies'], new_names,
                    placeholder_core.pair_bodies(recipe['bodies'], new_names))
                updated = placeholder_core.new_child_recipe(
                    slot_id=recipe['slotId'],
                    mother={'fileId': file_id,
                            'name': (mother_names.get(file_id)
                                     or recipe['mother']['name']),
                            'version': versions.get(file_id)},
                    config=recipe['config'], sheet_url=recipe['sheetUrl'],
                    tab=recipe['tab'], dims_cm=row['dims_cm'],
                    bodies=body_names, built_at=built_at,
                    # `or`, not a default: a DataFile that would not answer for
                    # versionId leaves '' in the dict, and writing that over a
                    # key the recipe already holds would discard the fallback
                    # permanently. migrate_child_recipe guarantees the key exists.
                    version_id=(version_ids.get(file_id)
                                or recipe['versionId']))
                occurrence.component.attributes.add(
                    placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR,
                    placeholder_core.dumps_attr(updated))
                report.append(line)
            except Exception as err:
                failures.append('{} — {}'.format(row['name'], _exc_text(err)))
    finally:
        # Always return to the layout — on success, on a whole-run failure,
        # and on cancellation alike — matching build_children's own
        # unconditional return.
        try:
            layout_doc.activate()
            adsk.doEvents()
        except Exception:
            pass
        # Close only the mothers THIS run opened, now that Phase 2 no longer
        # needs their live Appearance/Material objects. Guarded so a throw
        # here cannot mask whatever real exception is already propagating.
        for doc, opened_by_us in mother_docs.values():
            if opened_by_us:
                try:
                    doc.close(False)
                except Exception:
                    pass
        try:
            adsk.doEvents()
        except Exception:
            pass

    return report + failures


def _open_datafiles():
    """{lineage id: DataFile} for every open document.

    An open document's own DataFile answers latestVersionNumber directly, with no
    data-panel lookup at all — the reliable path, and the normal case for this
    dialog, since you have usually just been editing the mother.
    """
    files = {}
    for index in range(app.documents.count):
        try:
            data_file = app.documents.item(index).dataFile
            if data_file:
                files[data_file.id] = data_file
        except Exception:
            # Same guard as _mother_options and _open_mother use on the same
            # access: an untitled scratch document open anywhere in the session
            # can raise here and must not take the whole survey down with it.
            continue
    return files


def _resolve_mother_file(file_id, version_id, open_files):
    """A mother's DataFile via whichever of its two ids answers, or None.

    findFileById cannot be the only route: it has been observed raising
    "3 : file not found" for the lineage urn a document reported about ITSELF,
    both offline and after a restart while online (spike 5). So an already-open
    document is preferred — no service call — then the version-specific id, then
    the lineage id.

    None means "could not resolve", which is NOT the same as "the mother is
    gone"; callers must not report it as a missing file.

    For READING version numbers only. Do not open the result: it may be an old
    version's DataFile, and documents.open() would open that old version — see
    _open_mother, which resolves the lineage id itself for exactly this reason.
    """
    already_open = open_files.get(file_id)
    if already_open is not None:
        return already_open
    # Lineage id FIRST. Its DataFile is the tip by definition, so latestVersionNumber
    # off it is certainly right. The versionId path is only a workaround for
    # findFileById refusing a lineage id, and it rests on latestVersionNumber being
    # a lineage-wide property even on an old version's DataFile — plausible, but
    # NOT measured by any spike here. Trying it second confines that assumption to
    # the case where there is no alternative. If it turns out false, the symptom is
    # a closed mother's children reading "up to date" forever.
    for candidate in (file_id, version_id):
        if not candidate:
            continue
        try:
            found = app.data.findFileById(candidate)
        except Exception:
            found = None
        if found:
            return found
    return None


def _file_name(data_file):
    """A DataFile's own name, or ''. Guarded because not every DataFile property
    answers — spike 5 found `versions` raising on a live file — and a name is only
    display text, never worth failing a survey over."""
    try:
        return (data_file.name or '') if data_file else ''
    except Exception:
        return ''


def _latest_version(data_file, is_open):
    """The lineage's newest version number, or None if it cannot be determined.

    latestVersionNumber, not versionNumber: the question is whether a NEWER
    version exists than the child was built from, and a DataFile resolved from an
    old versionId reports its own versionNumber as that old version — which would
    make every child look up to date however far the mother had moved on.

    For an ALREADY-OPEN document, versionNumber is the fallback: it is local data,
    while latestVersionNumber can need the service and fail offline — which is the
    state that started all of this, and where every row read "unknown version" and
    nothing could be pre-ticked. An open document is normally at its newest
    version, so the fallback is usually exact and errs toward under-reporting
    staleness rather than inventing it. Not used for a closed file, where the
    number would be whatever version the lookup happened to land on.
    """
    if data_file is None:
        return None
    latest = _int_or_none(data_file, 'latestVersionNumber')
    if not is_open:
        return latest
    # For an OPEN document, whichever number is further ahead. Measured in real
    # use: a mother saved to v18 still had a DataFile reporting v17, so trusting
    # latestVersionNumber alone under-reports staleness right after a save — the
    # moment someone runs Update Children. versionNumber is local data and needs
    # no service, which also answers the offline case that started all of this.
    # Taking the max errs toward offering a rebuild rather than hiding one, and
    # is exact both for a document open at an older version and for one just
    # saved past a lagging lineage record.
    open_at = _int_or_none(data_file, 'versionNumber')
    candidates = [v for v in (latest, open_at) if v is not None]
    return max(candidates) if candidates else None


def _int_or_none(obj, name):
    """One integer property, or None if it will not read or is not an integer.
    bool is excluded for the same reason placeholder_core._version excludes it."""
    try:
        value = getattr(obj, name)
    except Exception:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _resolve_mothers(recipes, open_files, into=None):
    """{fileId: {'version': latest or None, 'name': resolved or ''}}, resolving
    each mother exactly once. A kitchen has a handful of mothers, so one lookup
    each is cheap; doing it per child would not be. ``into`` extends an existing
    result so a second batch of recipes reuses what is already resolved.

    The NAME matters as much as the version: a child built before the name fix
    recorded the DOCUMENT name ('mother1 v16') rather than the file name, and
    reading it from the file heals every such heading without a rebuild.
    """
    resolved = {} if into is None else into
    for recipe in recipes:
        file_id = recipe['mother']['fileId']
        if not file_id or file_id in resolved:
            continue
        data_file = _resolve_mother_file(file_id, recipe.get('versionId'),
                                        open_files)
        resolved[file_id] = {
            'version': _latest_version(data_file, file_id in open_files),
            'name': _file_name(data_file)}
    return resolved


def survey_children(design):
    """Everything the Update dialog needs, resolved once.

    Each child's front direction is recovered from its own occurrence transform,
    because the face the user picked at fill time is not stored. That is exact for
    a box that moved or resized; a rotated box is detected by is_axis_aligned and
    reported rather than silently mis-measured.
    """
    found, moved_out = find_children(design)
    slot_bodies = find_slot_bodies(design)
    # Scanned once and shared by every resolution below, so a layout with several
    # mothers walks the open-document list a single time.
    open_files = _open_datafiles()
    mothers = _resolve_mothers([recipe for _occ, recipe in found.values()],
                               open_files)

    rows = []
    for slot_id, (occurrence, recipe) in found.items():
        body = slot_bodies.get(slot_id)
        mother = mothers.get(recipe['mother']['fileId']) or {}
        current = mother.get('version')
        # NOT `current is not None`. A version we could not resolve is not a
        # mother that does not exist, and conflating them reported every child
        # as "mother not found" — which DISABLES its row, so the dialog became
        # unusable rather than merely uninformative, and did so exactly when
        # findFileById refused a valid lineage id. Since nothing here can prove
        # a file is absent, only a recipe with no fileId at all is treated as
        # missing; anything else gets a live row whose staleness reads
        # "unknown version", and a rebuild that genuinely cannot find the
        # mother reports it from _open_mother, where the truth is known.
        mother_found = bool(recipe['mother']['fileId'])
        dims = matrix = None
        rotated = False

        if body is not None:
            try:
                live = list(occurrence.transform2.asArray())
                frame = placeholder_core.frame_from_matrix(live)
                vertices = _body_vertices(body)
                rotated = not placeholder_core.is_axis_aligned(
                    _flat_face_normals(body), frame)
                if not rotated:
                    width, depth, height, centre = placeholder_core.extents_in_frame(
                        vertices, frame)
                    dims = (width, depth, height)
                    # The anchor lands on the centre of the box's FRONT FACE, not
                    # its geometric centre — anchor_target, not the bare centre.
                    # Comparing against the centre directly would report every
                    # child as moved, since the two only coincide by accident.
                    matrix = placeholder_core.occurrence_matrix(
                        placeholder_core.anchor_target(centre, frame, dims), frame)
            except Exception:
                body = None

        moved = bool(matrix) and placeholder_core.matrices_differ(
            matrix, list(occurrence.transform2.asArray()))
        rows.append({
            # occurrence/body are used only above, to measure THIS row right
            # now — deliberately not carried on it. update_children's Phase 1
            # activates one or more mother documents before its own Phase 2
            # ever runs, which invalidates every live reference to the layout
            # captured here, occurrence and body included; keeping either on
            # the row would be exactly the stale-handle hazard
            # build_children's own slot.pop('body', ...) exists to avoid.
            # update_children's Phase 2 re-resolves both fresh via
            # find_children instead.
            'recipe': recipe,
            'dims_cm': dims,
            'matrix': matrix,
            'name': occurrence.component.name,
            # Both carried so the group heading is built from the MOTHER's own
            # facts rather than from this row's staleness, which child_status
            # suppresses whenever it returns early for a per-child problem —
            # see placeholder_core.mother_heading_for_row.
            'current_version': current,
            'mother_name': mother.get('name', ''),
            'status': placeholder_core.child_status(
                recipe, current, dims, moved, rotated,
                mother_found, body is not None),
        })

    # find_children's second dict is DISJOINT from its first: its loop puts each
    # slot id into `found` OR `moved`, never both (each branch `continue`s), so
    # `found.get(slot_id)` here would always miss and silently drop the row.
    # find_children's internal scan already parsed each of these recipes once to
    # build its message, but does not hand the recipe back — so it is re-read
    # here, the only way to get the mother name (for sorting) and child name (for
    # the row) without reaching into find_children's internals. Skipped entirely
    # when nothing is moved out, so the common case costs no extra attribute scan.
    if moved_out:
        moved_info = {}
        for attribute in attribute_list(design.findAttributes(
                placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR)):
            try:
                recipe = placeholder_core.loads_attr(
                    attribute.value, placeholder_core.migrate_child_recipe)
                if recipe['slotId'] in moved_out:
                    moved_info[recipe['slotId']] = (recipe, attribute.parent.name)
            except Exception:
                continue
        _resolve_mothers([info[0] for info in moved_info.values()],
                         open_files, into=mothers)
        for slot_id, message in moved_out.items():
            info = moved_info.get(slot_id)
            if not info:
                continue
            recipe, name = info
            rows.append({
                'recipe': recipe, 'dims_cm': None, 'matrix': None, 'name': name,
                # mother_found/box_found are fixed here rather than resolved: this
                # row can never be rebuilt regardless of either, and both early
                # returns inside child_status leave every other field (staleness,
                # resized, moved, rotated, tick) at the same default — only
                # "problem" differs, which is overwritten right below anyway.
                'status': dict(placeholder_core.child_status(
                    recipe, None, None, False, False, True, False),
                    problem=message),
                # The mother's real facts, not blanks: this row's heading has to
                # match its siblings' or it splits the group, and being moved out
                # of the top level says nothing about its mother. Resolved just
                # above, because a mother ALL of whose children sit in
                # sub-assemblies is not in `found` and so was never looked up.
                'current_version': (mothers.get(
                    recipe['mother']['fileId']) or {}).get('version'),
                'mother_name': (mothers.get(
                    recipe['mother']['fileId']) or {}).get('name', ''),
            })

    # Ordering and heading identity are one problem, so they live together in
    # placeholder_core where they are tested: the dialog emits a heading only
    # when mother_heading_key changes, so the sort MUST leave every group
    # contiguous or a heading re-emits mid-group.
    rows.sort(key=placeholder_core.mother_sort_key)
    return rows
