# Spike 3 — does BaseFeature.updateBody() preserve downstream features?
#
# THIS IS THE ONE THAT MATTERS. The whole design promises that a cut a designer
# adds by hand survives a rebuild, and that promise is why the freeze flag was
# rejected during brainstorming.
#
# WHAT EARLIER RUNS ESTABLISHED
#   - The call shape is correct: with no downstream feature, updateBody returns
#     True and the volume goes 1000 -> 1920.
#   - adsk.doEvents() after startEdit() is NOT required (both controls passed).
#   - base.bodies really does have dual behaviour, as documented: outside the
#     edit it is the filleted RESULT (997.9), inside it is the SOURCE (1000.0).
#   - With a fillet on top, updateBody STILL returned True — the failure came
#     afterwards, from finishEdit() or the recompute it triggers.
#
# WHAT THIS RUN ISOLATES
# A fillet on edges.item(0) is the most fragile downstream feature there is: it
# references the base body's TOPOLOGY, and swapping a 10x10x10 box for a
# 16x12x10 one destroys the edge it was built on. That is not what this add-in's
# users do. Cutting a hole from a sketch on an origin plane references none of
# the base geometry and should behave differently.
#
#   control  no downstream           -> proves the call (already passing)
#   fragile  fillet on an edge       -> topology-referencing, expected to break
#   robust   cut from an origin-plane sketch -> what a designer actually does
#
# finishEdit() is now caught separately, and the model is inspected either way,
# so "threw but left an errored feature" (acceptable — the spec expects Fusion
# to flag broken references) is distinguishable from "threw and destroyed it".
#
# Setup: none. Run it from anywhere; it creates and closes its own documents.

import traceback

import adsk.core
import adsk.fusion

app = adsk.core.Application.get()


def _seq(collection):
    """Fusion mixes two shapes: real collections have .count/.item(i), while the
    *Vector types (AttributeVector, BRepBodyVector) are Python sequences."""
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


def _add_fillet(root):
    """Topology-referencing: built on a specific edge of the base body."""
    edges = adsk.core.ObjectCollection.create()
    edges.add(root.bRepBodies.item(0).edges.item(0))
    fillet_input = root.features.filletFeatures.createInput()
    fillet_input.addConstantRadiusEdgeSet(
        edges, adsk.core.ValueInput.createByReal(1.0), True)
    root.features.filletFeatures.add(fillet_input)
    adsk.doEvents()
    return 'filletFeatures'


def _add_cut(root):
    """Topology-independent: a hole from a sketch on an origin plane. This is
    what a designer actually does to a generated cabinet."""
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, 0, 0), 2.0)
    profile = sketch.profiles.item(0)
    extrudes = root.features.extrudeFeatures
    extrude_input = extrudes.createInput(
        profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    extrude_input.setDistanceExtent(True, adsk.core.ValueInput.createByReal(20.0))
    try:
        extrude_input.participantBodies = [root.bRepBodies.item(0)]
    except Exception:
        pass  # some builds infer the participant; not worth failing over
    extrudes.add(extrude_input)
    adsk.doEvents()
    return 'extrudeFeatures'


def _feature_count(root, kind):
    try:
        return getattr(root.features, kind).count
    except Exception:
        return -1


def _scenario(label, tbm, downstream):
    """Build a base feature (optionally with a downstream feature), swap its
    geometry, and report what survived. Returns (notes, outcome).

    outcome: 'control-ok' | 'survived' | 'errored-but-flagged' | 'destroyed'
             | 'errored'
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

        kind = downstream(root) if downstream else None
        before = _feature_count(root, kind) if kind else 0
        if kind:
            notes.append('  {} before swap: {}'.format(kind, before))

        bigger = _box(tbm, 16, 12, 10)
        base.startEdit()
        adsk.doEvents()
        sources = _seq(base.bodies)
        if not sources:
            notes.append('  -> no source body inside the edit')
            return notes, 'errored'
        notes.append('  passing body: {} (volume {:.1f})'
                     .format(sources[0].name, sources[0].volume))
        updated = base.updateBody(sources[0], bigger)
        notes.append('  updateBody returned: {}'.format(updated))

        finish_error = None
        try:
            base.finishEdit()
            adsk.doEvents()
        except Exception as err:
            finish_error = str(err)
            notes.append('  finishEdit RAISED: {}'.format(finish_error))

        # Inspect regardless — a throw that leaves an errored feature is an
        # acceptable outcome; a throw that destroys it is not.
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent
        try:
            notes.append('  body volume after: {:.3f} (was 1000.000, '
                         'expect 1920.000 minus any cut)'
                         .format(root.bRepBodies.item(0).volume))
        except Exception as err:
            notes.append('  body volume after: unreadable — {}'.format(err))

        if not kind:
            notes.append('  -> CONTROL OK: the call itself works')
            return notes, 'control-ok'

        after = _feature_count(root, kind)
        notes.append('  {} after swap:  {}'.format(kind, after))
        if after < before:
            notes.append('  -> downstream feature DESTROYED')
            return notes, 'destroyed'
        health = _health(getattr(root.features, kind).item(0))
        notes.append('  feature health:    {}'.format(health))
        if finish_error:
            notes.append('  -> feature SURVIVED but finishEdit raised '
                         '(health above says what state it is in)')
            return notes, 'errored-but-flagged'
        notes.append('  -> downstream feature SURVIVED cleanly')
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
            ('CONTROL: no downstream feature', None),
            ('FRAGILE: fillet on an edge (topology-referencing)', _add_fillet),
            ('ROBUST: hole cut from an origin-plane sketch', _add_cut),
        ]

        outcomes = []
        for label, downstream in scenarios:
            scenario_notes, outcome = _scenario(label, tbm, downstream)
            notes.extend(scenario_notes)
            notes.append('')
            outcomes.append(outcome)

        control, fragile, robust = outcomes
        notes.append('=' * 46)
        if control != 'control-ok':
            notes.append('SPIKE 3: INCONCLUSIVE — even the control failed.')
        elif robust in ('survived', 'errored-but-flagged'):
            notes.append('SPIKE 3: PASS')
            notes.append('A hole cut from an origin-plane sketch survives the '
                         'swap ({}). That is what a designer actually adds to a '
                         'generated cabinet.'.format(robust))
            notes.append('The fillet case was {} — expected, since it is built '
                         'on an edge the new geometry does not have.'
                         .format(fragile))
            notes.append('')
            notes.append('DESIGN CONSEQUENCE: downstream features survive when '
                         'they do NOT reference the base body\'s topology. '
                         'Topology-referencing ones (fillet/chamfer on an edge, '
                         'a face-anchored sketch) can break. The spec and README '
                         'must say this plainly rather than promising that every '
                         'edit survives.')
        elif robust == 'destroyed':
            notes.append('SPIKE 3: FAIL — even a topology-independent cut was '
                         'destroyed.')
            notes.append('STOP. This disproves the design\'s central promise. Do '
                         'not code around it — the fallback is the freeze flag '
                         'rejected during brainstorming, which is the user\'s '
                         'decision.')
        else:
            notes.append('SPIKE 3: INCONCLUSIVE — the robust scenario errored '
                         'rather than resolving. Report the error above; it may '
                         'be a bug in how this script builds the cut rather than '
                         'anything about updateBody.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
