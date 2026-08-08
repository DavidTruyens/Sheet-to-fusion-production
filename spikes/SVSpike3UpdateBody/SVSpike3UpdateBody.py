# Spike 3 — does BaseFeature.updateBody() preserve downstream features?
#
# THIS IS THE ONE THAT MATTERS. The whole design promises that a cut a designer
# adds by hand survives a rebuild, and that promise is why the freeze flag was
# rejected during brainstorming. If updateBody does not hold, do not work around
# it — the alternative is a materially worse feature and the user's call.
#
# It also probes BaseFeature.bodies, which build_engine.base_feature_bodies()
# needs in order to know WHICH bodies to update once downstream features exist.
#
# Setup: an EMPTY parametric document. The script builds the whole scenario.
# Run it once; it reports everything.

import traceback

import adsk.core
import adsk.fusion


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
    box = adsk.core.OrientedBoundingBox3D.create(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Vector3D.create(1, 0, 0),
        adsk.core.Vector3D.create(0, 1, 0),
        length, width, height)
    return tbm.createBox(box)


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    notes = []
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open a design first.')
            return
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            ui.messageBox('This design is in direct-modelling mode. Base features '
                          'need a parametric timeline: right-click the top browser '
                          'node and turn "Do not capture Design History" off.')
            return

        root = design.rootComponent
        tbm = adsk.fusion.TemporaryBRepManager.get()

        # 1. A base feature holding a 10 x 10 x 10 box.
        base = root.features.baseFeatures.add()
        base.startEdit()
        try:
            root.bRepBodies.add(_box(tbm, 10, 10, 10), base)
        finally:
            base.finishEdit()
        adsk.doEvents()
        notes.append('base feature created, {} body(s)'.format(root.bRepBodies.count))

        try:
            notes.append('base.bodies.count before downstream: {}'
                         .format(base.bodies.count))
        except Exception as err:
            notes.append('base.bodies unreadable before downstream — {}'.format(err))

        # 2. The "designer's" downstream feature: a fillet on one edge.
        target = root.bRepBodies.item(0)
        edges = adsk.core.ObjectCollection.create()
        edges.add(target.edges.item(0))
        fillet_input = root.features.filletFeatures.createInput()
        fillet_input.addConstantRadiusEdgeSet(
            edges, adsk.core.ValueInput.createByReal(1.0), True)
        root.features.filletFeatures.add(fillet_input)
        adsk.doEvents()
        fillets_before = root.features.filletFeatures.count
        notes.append('fillets before swap: {}'.format(fillets_before))

        # base.bodies AFTER a downstream feature exists is the question
        # build_engine.base_feature_bodies() has to answer.
        try:
            notes.append('base.bodies.count after downstream:  {}'
                         .format(base.bodies.count))
        except Exception as err:
            notes.append('base.bodies unreadable after downstream — {}'.format(err))
        notes.append('component bRepBodies.count:            {}'
                     .format(root.bRepBodies.count))

        # 3. Swap the base feature's geometry for a BIGGER box.
        bigger = _box(tbm, 16, 12, 10)
        base.startEdit()
        try:
            base.updateBody(root.bRepBodies.item(0), bigger)
        finally:
            base.finishEdit()
        adsk.doEvents()

        fillets_after = root.features.filletFeatures.count
        notes.append('fillets after swap:  {}'.format(fillets_after))
        survived = fillets_after == fillets_before
        health = _health(root.features.filletFeatures.item(0)) if fillets_after else 'gone'
        notes.append('fillet health:       {}'.format(health))
        notes.append('body volume:         {:.3f} (was 1000.000)'
                     .format(root.bRepBodies.item(0).volume))

        # A warning or error health state is an ACCEPTABLE partial pass: the spec
        # already says Fusion marking a broken reference is the expected outcome.
        # Vanishing silently, or updateBody throwing, is not.
        verdict = 'PASS' if survived else 'FAIL'
        notes.append('')
        notes.append('SPIKE 3: ' + verdict)
        if survived and health != 'healthy':
            notes.append('(partial: the feature survived but is {} — acceptable, '
                         'the spec expects Fusion to flag broken references)'
                         .format(health))
        if not survived:
            notes.append('The downstream feature was destroyed. STOP — do not code '
                         'around this. The fallback is the freeze flag rejected '
                         'during brainstorming, which is the user\'s decision.')
        notes.append('')
        notes.append('Record base.bodies.count after downstream: if it is 1, '
                     'build_engine.base_feature_bodies() can use base.bodies; '
                     'if it is 0 or errors, it must use the positional fallback.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nSPIKE 3: FAIL (exception)\n'
                      + traceback.format_exc())
