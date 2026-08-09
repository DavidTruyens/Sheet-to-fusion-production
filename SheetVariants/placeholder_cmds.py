# placeholder_cmds.py
# The placeholder-instantiation commands: Prepare Mother Model (records how a
# mother is driven and oriented) and Fill Placeholders (generates children).
#
# Imports adsk, so nothing here is unit-tested; the schemas, frames, extents,
# matrices and body pairing all live in placeholder_core.py, which is.

import os
import sys

import adsk.core
import adsk.fusion

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
    """A single-select dropdown pre-set to ``selected`` when it is present."""
    drop = inputs.addDropDownCommandInput(
        input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    for option in options:
        drop.listItems.add(option, option == selected)
    if drop.listItems.count and not drop.selectedItem:
        drop.listItems.item(0).isSelected = True
    return drop


class PrepareCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = args.command
        inputs = cmd.commandInputs
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            inputs.addTextBoxCommandInput(
                'err', '', 'Open a parametric design first.', 2, True)
            return

        # Without a saved file there is no id to reference and no version number
        # to compare, so a child could never say whether its mother had moved on.
        if not design.parentDocument.dataFile:
            inputs.addTextBoxCommandInput(
                'err', '',
                'Save this document to your Fusion project first — a mother model '
                'must be a saved file so children can reference it and compare '
                'versions.', 4, True)
            return

        setup = read_mother_setup(design)
        origins = joint_origin_names(design)
        if not origins:
            inputs.addTextBoxCommandInput(
                'err', '',
                'This model has no joint origins. Create one at the point that '
                'should land at the centre of a placeholder box (Assemble > Joint '
                'Origin), then run this command again.', 4, True)
            return

        params = [p.name for p in design.allParameters]
        _add_dropdown(inputs, 'anchor', 'Anchor joint origin', origins, setup['anchor'])
        _add_dropdown(inputs, 'front', 'Front faces along',
                      list(placeholder_core.FRONT_AXES), setup['front'])
        _add_dropdown(inputs, 'pWidth', 'Width parameter', params,
                      setup['params']['width'])
        _add_dropdown(inputs, 'pDepth', 'Depth parameter', params,
                      setup['params']['depth'])
        _add_dropdown(inputs, 'pHeight', 'Height parameter', params,
                      setup['params']['height'])
        inputs.addTextBoxCommandInput(
            'hint', '',
            'The anchor is the point that lands at the centre of the placeholder '
            'box. To shift the model within its box, move the joint origin.',
            3, True)

        handler = PrepareExecuteHandler()
        cmd.execute.add(handler)
        _handlers.append(handler)


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
            import traceback
            ui.messageBox('Prepare Mother Model failed:\n' + traceback.format_exc())


_handlers = []


def register(panel):
    """Create the command definitions and add them to ``panel``. Handlers are kept
    in this module's _handlers list so Python does not garbage-collect them."""
    existing = ui.commandDefinitions.itemById(PREPARE_CMD_ID)
    if existing:
        existing.deleteMe()
    definition = ui.commandDefinitions.addButtonDefinition(
        PREPARE_CMD_ID, PREPARE_CMD_NAME, PREPARE_CMD_DESC)
    handler = PrepareCreatedHandler()
    definition.commandCreated.add(handler)
    _handlers.append(handler)
    panel.controls.addCommand(definition)


def unregister():
    """Remove this module's command definitions and controls."""
    for cmd_id in (PREPARE_CMD_ID,):
        definition = ui.commandDefinitions.itemById(cmd_id)
        if definition:
            definition.deleteMe()
    _handlers[:] = []
