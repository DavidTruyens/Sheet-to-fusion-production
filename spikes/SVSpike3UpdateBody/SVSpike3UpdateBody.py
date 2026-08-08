# Spike 3 — does BaseFeature.updateBody() preserve downstream features?
#
# THIS IS THE ONE THAT MATTERS. The whole design promises that a cut a designer
# adds by hand survives a rebuild, and that promise is why the freeze flag was
# rejected during brainstorming. If updateBody does not hold, do not work around
# it — the alternative is a materially worse feature and the user's call.
#
# History of this spike, because the errors were informative:
#   attempt 1: root.bRepBodies.item(0) fetched INSIDE the edit
#              -> RuntimeError: 3 : Bad index parameter
#              startEdit() rolls the timeline back, invalidating collections.
#   attempt 2: base.bodies.item(0) captured BEFORE the edit
#              -> "Invalid argument sourceBody. Not a source body for this base
#              feature". base.bodies is what the feature PRODUCES in the current
#              timeline state — after a fillet that is the filleted result, not
#              the geometry fed in. updateBody wants the SOURCE body.
#
# So this version probes what the base feature actually exposes, then tries the
# source-body candidates. Each attempt runs in its OWN fresh document: sharing
# one document let a failed edit poison the next attempt.
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
    Normalise both so callers stop having to guess.
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


def _fresh_document():
    """A new parametric design, so no attempt inherits another's broken edit."""
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    adsk.doEvents()
    design = adsk.fusion.Design.cast(
        doc.products.itemByProductType('DesignProductType'))
    return doc, design


def _build_scenario(design, tbm):
    """A base feature holding a 10x10x10 box, plus a fillet on it standing in for
    the designer's hand-made edit. Returns the base feature."""
    root = design.rootComponent
    base = root.features.baseFeatures.add()
    base.startEdit()
    try:
        root.bRepBodies.add(_box(tbm, 10, 10, 10), base)
    finally:
        base.finishEdit()
    adsk.doEvents()

    edges = adsk.core.ObjectCollection.create()
    edges.add(root.bRepBodies.item(0).edges.item(0))
    fillet_input = root.features.filletFeatures.createInput()
    fillet_input.addConstantRadiusEdgeSet(
        edges, adsk.core.ValueInput.createByReal(1.0), True)
    root.features.filletFeatures.add(fillet_input)
    adsk.doEvents()
    return base


def _dump(base, when):
    """What the base feature exposes, and whether each collection is readable."""
    lines = ['  {}:'.format(when)]
    for attr in ('bodies', 'sourceBodies'):
        if not hasattr(base, attr):
            lines.append('    {}: NOT PRESENT on this API version'.format(attr))
            continue
        try:
            items = _seq(getattr(base, attr))
            lines.append('    {}: count={} {}'
                         .format(attr, len(items), [b.name for b in items]))
        except Exception as err:
            lines.append('    {}: unreadable — {}'.format(attr, err))
    return lines


def _attempt(label, tbm, pick):
    """Build a scenario in a fresh document and swap its geometry.

    ``pick(base, inside)`` returns the body to hand to updateBody; it is called
    once before startEdit() and once inside, and whichever call returns a body is
    used — that is how the two orderings are distinguished.

    Returns (notes, outcome) where outcome is 'survived', 'destroyed' or 'errored'.
    These are NOT the same result: only 'destroyed' says anything about the design.
    """
    notes = ['--- {} ---'.format(label)]
    doc = None
    try:
        doc, design = _fresh_document()
        root = design.rootComponent
        base = _build_scenario(design, tbm)
        fillets_before = root.features.filletFeatures.count
        notes.extend(_dump(base, 'before startEdit'))
        notes.append('  fillets before swap: {}'.format(fillets_before))

        bigger = _box(tbm, 16, 12, 10)
        target = pick(base, False)
        base.startEdit()
        try:
            notes.extend(_dump(base, 'inside the edit'))
            if target is None:
                target = pick(base, True)
            if target is None:
                notes.append('  -> no candidate body available')
                return notes, 'errored'
            notes.append('  passing body: {}'.format(target.name))
            base.updateBody(target, bigger)
        finally:
            base.finishEdit()
        adsk.doEvents()

        fillets_after = root.features.filletFeatures.count
        notes.append('  fillets after swap:  {}'.format(fillets_after))
        if fillets_after < fillets_before:
            notes.append('  -> downstream feature DESTROYED')
            return notes, 'destroyed'
        fillet = root.features.filletFeatures.item(0)
        notes.append('  fillet health:       {}'.format(_health(fillet)))
        notes.append('  body volume:         {:.3f} (was 1000.000)'
                     .format(root.bRepBodies.item(0).volume))
        notes.append('  -> updateBody WORKED with this ordering')
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

        def source(base, want_inside, inside):
            if inside != want_inside:
                return None
            items = _seq(base.sourceBodies)
            return items[0] if items else None

        attempts = [
            ('sourceBodies, captured BEFORE the edit',
             lambda base, inside: source(base, False, inside)),
            ('sourceBodies, fetched INSIDE the edit',
             lambda base, inside: source(base, True, inside)),
            ('bodies, fetched INSIDE the edit',
             lambda base, inside: (_seq(base.bodies)[0]
                                   if inside and _seq(base.bodies) else None)),
        ]

        winner = None
        outcomes = []
        for label, pick in attempts:
            attempt_notes, outcome = _attempt(label, tbm, pick)
            notes.extend(attempt_notes)
            notes.append('')
            outcomes.append(outcome)
            if outcome == 'survived':
                winner = label
                break

        notes.append('=' * 40)
        if winner:
            notes.append('SPIKE 3: PASS')
            notes.append('3c — use this in build_engine.rebuild_base_feature():')
            notes.append('     {}'.format(winner))
            notes.append('')
            notes.append('A warning/error fillet health is an ACCEPTABLE partial '
                         'pass — the spec expects Fusion to flag broken '
                         'references. Report the health value.')
        elif 'destroyed' in outcomes:
            notes.append('SPIKE 3: FAIL — updateBody ran but DESTROYED the '
                         'downstream feature.')
            notes.append('STOP. This disproves the design\'s central promise. Do '
                         'not code around it — the fallback is the freeze flag '
                         'rejected during brainstorming, which is the user\'s '
                         'decision to make.')
        else:
            notes.append('SPIKE 3: INCONCLUSIVE — every attempt errored before '
                         'updateBody did any work.')
            notes.append('This says nothing about whether downstream features '
                         'survive; it means we have not found the right way to '
                         'call it yet. Report the dumps above — they show what '
                         'the base feature actually exposes.')
        ui.messageBox('\n'.join(notes))
    except Exception:
        ui.messageBox('\n'.join(notes) + '\n\nUnhandled:\n' + traceback.format_exc())
