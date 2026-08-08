# Spike 3 — does BaseFeature.updateBody() preserve downstream features?
#
# THIS IS THE ONE THAT MATTERS. The whole design promises that a cut a designer
# adds by hand survives a rebuild, and that promise is why the freeze flag was
# rejected during brainstorming. If updateBody does not hold, do not work around
# it — the alternative is a materially worse feature and the user's call.
#
# The documented contract (help.autodesk.com, BaseFeature.updateBody):
#   sourceBody — "The source BRepBody to update. The source bodies of a
#                 BaseFeature are only available from the bodies collection of
#                 the BaseFeature WHEN THE BASEFEATURE IS IN EDIT MODE."
#   bodies     — "When editing, it returns bodies owned by or used by the base
#                 feature. When inactive, it returns result bodies."
#   startEdit  — "Set the USER-INTERFACE so that the base body is in edit mode."
#
# Earlier runs dumped `bodies` before and inside the edit and got IDENTICAL
# output, which means edit mode had not actually engaged — startEdit() is a UI
# operation and needs adsk.doEvents() to take effect. That is the variable this
# version isolates.
#
# It also adds the CONTROL that was missing: a base feature with NO downstream
# feature. Earlier runs varied the call shape and the downstream feature at the
# same time, so a failure could not be attributed to either.
#
#   control, no fillet, doEvents   -> is the CALL right?
#   control, no fillet, no doEvents -> is doEvents the reason?
#   with fillet,        doEvents   -> does the downstream feature SURVIVE?
#
# Only the third scenario says anything about the design. The first two say
# whether we are calling the API correctly.
#
# Setup: none. Run it from anywhere; it creates and closes its own documents.

import traceback

import adsk.core
import adsk.fusion

app = adsk.core.Application.get()


def _seq(collection):
    """Fusion returns TWO shapes and mixes them on the same object.

    Real collections have .count / .item(i) — base.bodies is one. The *Vector
    types are Python sequences with neither: AttributeVector (spike 2) and
    BRepBodyVector (base.sourceBodies) both raise AttributeError on .count.
    """
    try:
        return [collection.item(i) for i in range(collection.count)]
    except AttributeError:
        return [collection[i] for i in range(len(collection))]


def _health(feature):
    try:
        state = feature.healthState
    except Exception as err:
        return 'unreadable ({})'.format(err)
    names = {
        adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState: 'healthy',
        adsk.fusion.FeatureHealthStates.WarningFeatureHealthState: 'warning',
        adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState: 'error',
        adsk.fusion.FeatureHealthStates.SuppressedFeatureHealthState: 'suppressed',
        adsk.fusion.FeatureHealthStates.UnknownFeatureHealthState: 'unknown',
    }
    return names.get(state, 'code {}'.format(state))


def _box(tbm, length, width, height):
    return tbm.createBox(adsk.core.OrientedBoundingBox3D.create(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Vector3D.create(1, 0, 0),
        adsk.core.Vector3D.create(0, 1, 0),
        length, width, height))


def _fingerprint(base):
    """Enough to tell whether `bodies` switched from result bodies to source
    bodies. If edit mode engaged, these should differ inside vs outside."""
    out = []
    for attr in ('bodies', 'sourceBodies'):
        try:
            items = _seq(getattr(base, attr))
            out.append('{}={}x[{}]'.format(
                attr, len(items),
                ','.join('{}:{:.1f}'.format(b.name, b.volume) for b in items)))
        except Exception as err:
            out.append('{}=unreadable({})'.format(attr, err))
    return '  '.join(out)


def _scenario(label, tbm, with_fillet, do_events):
    """Build a base feature (optionally with a fillet on top) in a fresh document,
    then swap its geometry. Returns (notes, outcome).

    outcome is 'survived' | 'destroyed' | 'errored' | 'control-ok'.
    Only 'destroyed' says anything about the design.
    """
    notes = ['--- {} ---'.format(label)]
    doc = None
    try:
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        adsk.doEvents()
        design = adsk.fusion.Design.cast(
            doc.products.itemByProductType('DesignProductType'))
        root = design.rootComponent

        base = root.features.baseFeatures.add()
        base.startEdit()
        try:
            root.bRepBodies.add(_box(tbm, 10, 10, 10), base)
        finally:
            base.finishEdit()
        adsk.doEvents()

        if with_fillet:
            edges = adsk.core.ObjectCollection.create()
            edges.add(root.bRepBodies.item(0).edges.item(0))
            fillet_input = root.features.filletFeatures.createInput()
            fillet_input.addConstantRadiusEdgeSet(
                edges, adsk.core.ValueInput.createByReal(1.0), True)
            root.features.filletFeatures.add(fillet_input)
            adsk.doEvents()
        fillets_before = root.features.filletFeatures.count
        notes.append('  fillets before swap: {}'.format(fillets_before))
        notes.append('  outside edit: {}'.format(_fingerprint(base)))

        bigger = _box(tbm, 16, 12, 10)
        base.startEdit()
        try:
            if do_events:
                adsk.doEvents()          # <-- the variable under test
            notes.append('  inside edit:  {}'.format(_fingerprint(base)))
            sources = _seq(base.bodies)
            if not sources:
                notes.append('  -> no source body available inside the edit')
                return notes, 'errored'
            notes.append('  passing body: {} (volume {:.1f})'
                         .format(sources[0].name, sources[0].volume))
            result = base.updateBody(sources[0], bigger)
            notes.append('  updateBody returned: {}'.format(result))
        finally:
            base.finishEdit()
        adsk.doEvents()

        volume = root.bRepBodies.item(0).volume
        notes.append('  body volume after:   {:.3f} (was 1000.000, '
                     'expect 1920.000)'.format(volume))
        if not with_fillet:
            notes.append('  -> CONTROL OK: the call itself works')
            return notes, 'control-ok'

        fillets_after = root.features.filletFeatures.count
        notes.append('  fillets after swap:  {}'.format(fillets_after))
        if fillets_after < fillets_before:
            notes.append('  -> downstream feature DESTROYED')
            return notes, 'destroyed'
        notes.append('  fillet health:       {}'
                     .format(_health(root.features.filletFeatures.item(0))))
        notes.append('  -> downstream feature SURVIVED')
        return notes, 'survived'
    except Exception as err:
        notes.append('  -> errored: {}'.format(err))
        return notes, 'errored'
    finally:
        if doc is not None:
            try:
                doc.close(False)
                adsk.doEvents()
            except Exception:
                pass


def run(context):
    ui = app.userInterface
    notes = []
    try:
        tbm = adsk.fusion.TemporaryBRepManager.get()
        scenarios = [
            ('CONTROL: no fillet, doEvents after startEdit', False, True),
            ('CONTROL: no fillet, NO doEvents', False, False),
            ('THE REAL TEST: fillet on top, doEvents after startEdit', True, True),
        ]

        results = {}
        for label, with_fillet, do_events in scenarios:
            scenario_notes, outcome = _scenario(label, tbm, with_fillet, do_events)
            notes.extend(scenario_notes)
            notes.append('')
            results[label] = outcome

        control_ok = results[scenarios[0][0]] == 'control-ok'
        control_no_events = results[scenarios[1][0]]
        real = results[scenarios[2][0]]

        notes.append('=' * 46)
        if not control_ok:
            notes.append('SPIKE 3: INCONCLUSIVE')
            notes.append('The control failed, so we still are not calling '
                         'updateBody correctly. This says NOTHING about whether '
                         'downstream features survive. Stop guessing and report '
                         'the fingerprints above.')
        elif real == 'survived':
            notes.append('SPIKE 3: PASS — the downstream feature survived.')
            notes.append('Report the fillet health: warning/error is an acceptable '
                         'partial pass, since the spec expects Fusion to flag a '
                         'broken reference.')
        elif real == 'destroyed':
            notes.append('SPIKE 3: FAIL — updateBody worked but DESTROYED the '
                         'downstream feature.')
            notes.append('STOP. This disproves the design\'s central promise. Do '
                         'not code around it — the fallback is the freeze flag '
                         'rejected during brainstorming, which is the user\'s '
                         'decision.')
        else:
            notes.append('SPIKE 3: INCONCLUSIVE — the control passed but the '
                         'fillet scenario errored rather than resolving.')
            notes.append('A downstream feature changes how updateBody behaves. '
                         'Report the error above.')

        notes.append('')
        notes.append('doEvents after startEdit was {}'.format(
            'REQUIRED — the no-doEvents control {}'.format(
                'also passed, so it is not the cause'
                if control_no_events == 'control-ok' else 'failed')))
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
