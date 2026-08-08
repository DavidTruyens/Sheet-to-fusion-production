# Spike 3 — does BaseFeature.updateBody() preserve downstream features?
#
# THIS IS THE ONE THAT MATTERS. The whole design promises that a cut a designer
# adds by hand survives a rebuild, and that promise is why the freeze flag was
# rejected during brainstorming. If updateBody does not hold, do not work around
# it — the alternative is a materially worse feature and the user's call.
#
# It answers two questions:
#   3  does the downstream feature survive the swap?
#   3b where must the body reference passed to updateBody() come from?
#
# 3b matters because startEdit() rolls the timeline back to the base feature,
# which recomputes and can invalidate a collection fetched across it. A first
# attempt that called root.bRepBodies.item(0) INSIDE the edit died with
# "RuntimeError: 3 : Bad index parameter", so the two orderings are tried as
# independent scenarios and the working one is reported.
#
# Setup: an EMPTY parametric document. The script builds everything.

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


def _box(tbm, offset_x, length, width, height):
    return tbm.createBox(adsk.core.OrientedBoundingBox3D.create(
        adsk.core.Point3D.create(offset_x, 0, 0),
        adsk.core.Vector3D.create(1, 0, 0),
        adsk.core.Vector3D.create(0, 1, 0),
        length, width, height))


def _build_scenario(root, tbm, offset_x):
    """A base feature holding a 10x10x10 box, plus a fillet on it standing in for
    the designer's hand-made edit. Returns (base, fillet_count_before)."""
    base = root.features.baseFeatures.add()
    base.startEdit()
    try:
        root.bRepBodies.add(_box(tbm, offset_x, 10, 10, 10), base)
    finally:
        base.finishEdit()
    adsk.doEvents()

    body = base.bodies.item(0)
    edges = adsk.core.ObjectCollection.create()
    edges.add(body.edges.item(0))
    fillet_input = root.features.filletFeatures.createInput()
    fillet_input.addConstantRadiusEdgeSet(
        edges, adsk.core.ValueInput.createByReal(1.0), True)
    root.features.filletFeatures.add(fillet_input)
    adsk.doEvents()
    return base, root.features.filletFeatures.count


def _swap(base, tbm, offset_x, capture_before):
    """Swap the base feature's geometry for a bigger box.

    ``capture_before`` decides where the body reference comes from: True takes it
    BEFORE startEdit() (what Plan 1's rebuild_base_feature does), False re-fetches
    it inside the edit.
    """
    bigger = _box(tbm, offset_x, 16, 12, 10)
    target = base.bodies.item(0) if capture_before else None
    base.startEdit()
    try:
        if target is None:
            target = base.bodies.item(0)
        base.updateBody(target, bigger)
    finally:
        base.finishEdit()
    adsk.doEvents()


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

        strategies = [
            ('body captured BEFORE startEdit  (what Plan 1 does)', True),
            ('body re-fetched INSIDE the edit', False),
        ]

        winner = None
        for index, (label, capture_before) in enumerate(strategies):
            offset_x = index * 30
            notes.append('--- {} ---'.format(label))
            try:
                base, fillets_before = _build_scenario(root, tbm, offset_x)
                notes.append('base.bodies.count after downstream: {}'
                             .format(base.bodies.count))
                notes.append('fillets before swap: {}'.format(fillets_before))

                _swap(base, tbm, offset_x, capture_before)

                fillets_after = root.features.filletFeatures.count
                notes.append('fillets after swap:  {}'.format(fillets_after))
                survived = fillets_after >= fillets_before
                fillet = (root.features.filletFeatures.item(fillets_after - 1)
                          if fillets_after else None)
                notes.append('fillet health:       {}'
                             .format(_health(fillet) if fillet else 'gone'))
                notes.append('body volume:         {:.3f} (was 1000.000)'
                             .format(base.bodies.item(0).volume))
                if survived:
                    winner = label
                    notes.append('-> updateBody WORKED with this ordering')
                    notes.append('')
                    break
                notes.append('-> downstream feature was DESTROYED')
            except Exception as err:
                notes.append('-> FAILED: {}'.format(err))
            notes.append('')

        notes.append('SPIKE 3: ' + ('PASS' if winner else 'FAIL'))
        if winner:
            notes.append('3b — use this ordering in build_engine.'
                         'rebuild_base_feature():')
            notes.append('     {}'.format(winner))
            notes.append('     and base.bodies IS populated, so '
                         'base_feature_bodies() can use it rather than the '
                         'positional fallback.')
            notes.append('')
            notes.append('A warning/error fillet health is an ACCEPTABLE partial '
                         'pass — the spec expects Fusion to flag broken '
                         'references. Report the health value.')
        else:
            notes.append('Neither ordering preserved the downstream feature.')
            notes.append('STOP — do not code around this. The fallback is the '
                         'freeze flag rejected during brainstorming, which is '
                         'the user\'s decision to make.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
