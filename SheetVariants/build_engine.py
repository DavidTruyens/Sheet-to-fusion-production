# build_engine.py
# The Fusion-side geometry core shared by the sheet-variants build and the
# placeholder-instantiation feature: apply parameter values, snapshot solids as
# temporary BReps, and put those snapshots into a component's base feature.
#
# This module imports adsk and therefore cannot be unit-tested; every rule that
# can be expressed without Fusion belongs in sheet_core.py or placeholder_core.py.
#
# The phase ordering these functions assume is documented in build_exports():
# creating or activating a document invalidates live references to any other
# design, so all reading must finish before any output work begins.

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


def _design():
    """The active design, re-derived fresh. Never cache this across a parameter
    write: setting a driving dimension recomputes the model, which can invalidate
    a held collection so the object from the previous call is already dead."""
    return adsk.fusion.Design.cast(app.activeProduct)


def apply_expression(param, raw):
    """Write a sheet cell into a parameter's expression.

    Text parameters need a single-quoted string expression (e.g. 'A-6'), but a
    sheet usually supplies the bare text — sometimes with a stray quote left
    over from a spreadsheet's text-prefix (so "1-1" can arrive as "1-1'"). We
    detect text parameters from their current expression and re-quote the value;
    numeric parameters get the value as-is.
    """
    raw = raw.strip()
    if not raw:
        return
    current = (param.expression or '').strip()
    if current[:1] in ("'", '"'):                     # existing text parameter
        param.expression = "'" + raw.strip('\'"') + "'"
        return
    try:
        param.expression = raw
    except Exception:
        try:                                          # maybe an unquoted text param
            param.expression = "'" + raw.strip('\'"') + "'"
        except Exception:
            raise RuntimeError(
                'Could not set parameter "{}" to "{}". Numeric values may need a '
                'unit (e.g. "50 mm"); text values are quoted automatically.'
                .format(param.name, raw))


def apply_values(values):
    """Write {parameter name: expression} into the active design. Blank values are
    skipped, leaving that parameter unchanged."""
    for name, raw in values.items():
        if not (raw or '').strip():
            continue
        param = _design().allParameters.itemByName(name)
        if param:
            apply_expression(param, raw)


def capture_values(names):
    """{name: current expression} for the named parameters, for later restoration."""
    params = _design().allParameters
    captured = {}
    for name in names:
        param = params.itemByName(name)
        if param:
            captured[name] = param.expression
    return captured


def restore_values(values):
    """Put captured expressions back. Best-effort per parameter: a failure on one
    must not leave the rest of the model in a variant state."""
    for name, expression in values.items():
        try:
            param = _design().allParameters.itemByName(name)
            if param:
                param.expression = expression
        except Exception:
            pass


def unrestored_values(values):
    """Names in ``values`` whose current expression does not match what was
    captured, i.e. parameters ``restore_values`` silently failed to put back.

    ``restore_values`` is deliberately best-effort per parameter — one failure
    must not stop the rest from being restored — but that means nothing else
    notices when a restore did not actually happen. A caller that drove a
    document's parameters and cannot confirm they came back must know: the
    document is left MODIFIED with a driven value still in place, which is a
    materially different, and worse, situation than "restore raised and was
    ignored" would suggest.

    This is a plain STRING comparison (current expression vs. captured
    expression), and it is sound only because of a round-trip invariant:
    ``expected`` is exactly the string this module's own ``capture_values``
    read from ``param.expression`` before anything was driven, and
    ``restore_values`` writes that SAME string back into ``param.expression``
    — never a reformatted, reparsed, or unit-converted version of it.
    Whitespace, unit suffixes, numeric precision and locale decimal
    separators all cancel out because they were already baked into the one
    string this compares against itself. If a future change ever routes
    ``restore_values`` through ``apply_expression`` (which re-quotes text
    values) or captures/restores via ``param.value`` instead of
    ``param.expression`` (a float, reformatted back into a string), this
    comparison would start flagging clean restores as failures — a false
    "your model is corrupted" message with nothing wrong underneath. Keep
    ``restore_values`` writing back the exact captured expression string
    verbatim if this function is to stay trustworthy.

    Each parameter read is individually guarded: one parameter that cannot be
    read (design gone stale, name no longer resolvable, etc.) is treated as
    unrestored — failing toward a warning rather than toward silence — rather
    than aborting the check for every other parameter.
    """
    design = _design()
    all_params = design.allParameters
    bad = []
    for name, expected in values.items():
        try:
            param = all_params.itemByName(name)
            current = param.expression if param else None
        except Exception:
            current = None
        if current != expected:
            bad.append(name)
    return bad


def _get(obj, attribute):
    """One property, or None if it is unset OR will not read. Both mean "nothing
    to copy from here", and the caller carries on up the chain either way."""
    try:
        return getattr(obj, attribute)
    except Exception:
        return None


def _occurrence_chain(body):
    """The occurrences enclosing ``body``, nearest first.

    Empty for a body owned by the root component — it sits in no occurrence, so
    there is nothing above it to inherit from. Bounded rather than `while True`:
    a malformed assemblyContext cycle would otherwise hang the add-in, and no
    real assembly is anywhere near this deep.
    """
    chain = []
    occurrence = _get(body, 'assemblyContext')
    while occurrence is not None and len(chain) < 64:
        chain.append(occurrence)
        occurrence = _get(occurrence, 'assemblyContext')
    return chain


def effective_appearance(body):
    """The appearance the body actually SHOWS, not merely its own override.

    Reading only body.appearance meant a colour applied to a component or an
    occurrence — the quickest way to colour a model — had nothing to copy, and
    children came out plain. The chain follows Fusion's own precedence, and
    because inherited_look returns the FIRST value that is set, a body carrying
    its own override resolves exactly as it always did.
    """
    return placeholder_core.inherited_look(
        [_get(body, 'appearance')]
        + [_get(occurrence, 'appearance') for occurrence in _occurrence_chain(body)])


def effective_material(body):
    """The material the body actually shows. Same idea as effective_appearance,
    one link shorter: a material comes from the body or from the component that
    owns it, and occurrences do not override it."""
    return placeholder_core.inherited_look(
        [_get(body, 'material'), _get(_get(body, 'parentComponent'), 'material')])


def snapshot_bodies(bodies):
    """Copy each body to a temporary BRep, keeping its qualified name and the
    appearance and material it actually SHOWS — its own override where it has
    one, otherwise whatever it inherits from an enclosing occurrence or its
    component. Bodies that cannot be copied are skipped rather than failing the
    run."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    snaps = []
    for body in bodies:
        try:
            temp = tbm.copy(body)
        except Exception:
            continue
        component_name = body_name = ''
        appearance = effective_appearance(body)
        material = effective_material(body)
        try:
            component_name = body.parentComponent.name
        except Exception:
            pass
        try:
            body_name = body.name
        except Exception:
            pass
        snaps.append({
            'temp': temp,
            'appearance': appearance,
            'material': material,
            'name': placeholder_core.qualified_body_name(component_name, body_name),
        })
    return snaps


def transform_snapshot(snaps, matrix16):
    """Move every snapshotted body by a row-major 16-float matrix, in place."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    matrix = adsk.core.Matrix3D.create()
    matrix.setWithArray(matrix16)
    for snap in snaps:
        tbm.transform(snap['temp'], matrix)


def add_snapshot(component, snaps):
    """Add snapshotted bodies to ``component`` inside a new base feature. Returns
    the base feature."""
    base = component.features.baseFeatures.add()
    base.startEdit()
    try:
        for snap in snaps:
            component.bRepBodies.add(snap['temp'], base)
    finally:
        base.finishEdit()
    return base


def appearance_in(design, src_appr):
    """The appearance named like ``src_appr`` inside ``design``, copied in once if
    needed. Lets a copied body show the source body's appearance (temporary BReps
    lose it). Returns None if it can't be copied."""
    try:
        existing = design.appearances.itemByName(src_appr.name)
        return existing or design.appearances.addByCopy(src_appr, src_appr.name)
    except Exception:
        return None


def material_in(design, src_mat):
    """The material named like ``src_mat`` inside ``design``, copied in once if
    needed. Returns None if it can't be copied."""
    try:
        existing = design.materials.itemByName(src_mat.name)
        return existing or design.materials.addByCopy(src_mat, src_mat.name)
    except Exception:
        return None


def reapply_looks(design, component, snaps):
    """Re-apply the source material and appearance to a component's bodies.

    Temporary BReps lose both, and the body objects returned during a base-feature
    edit go stale after finishEdit(), so fetch the component's bodies fresh and
    match them by index. Best-effort: the geometry is already built, so a failure
    just leaves the default look rather than breaking the build.
    """
    bodies = component.bRepBodies
    for index, snap in enumerate(snaps):
        if index >= bodies.count:
            break
        body = bodies.item(index)
        try:
            # `is not None`, not truthiness: a Fusion object that happened to
            # be falsy would be silently skipped and the body left default —
            # see placeholder_core.inherited_look, which avoids the same trap.
            if snap['material'] is not None:
                material = material_in(design, snap['material'])
                if material is not None:
                    body.material = material
            if snap['appearance'] is not None:
                appearance = appearance_in(design, snap['appearance'])
                if appearance is not None:
                    body.appearance = appearance
        except Exception:
            pass  # geometry is built; a failed look just stays default


def find_base_feature(component):
    """The component's first base feature — the one this add-in created to hold
    the mother's geometry. Returns None if it has been deleted."""
    features = component.features.baseFeatures
    return features.item(0) if features.count else None


def base_feature_bodies(component, base):
    """The bodies the base feature owns.

    Spike 3 confirmed ``base.bodies`` stays populated once downstream features
    exist (count 1 with a fillet on top), so it is the exact answer. The
    positional fallback assumes the base feature's bodies are the component's
    first N in creation order, which only holds while downstream features modify
    rather than add bodies — it is a safety net, not the intended path.
    """
    try:
        if base.bodies.count:
            return [base.bodies.item(i) for i in range(base.bodies.count)]
    except Exception:
        pass
    return [component.bRepBodies.item(i) for i in range(component.bRepBodies.count)]


def rebuild_base_feature(component, base, snaps, ops):
    """Swap a base feature's geometry in place so downstream features recompute
    against the new bodies instead of being deleted along with the old ones.

    ``ops`` comes from placeholder_core.pair_bodies and is already ordered
    update-then-add-then-remove, so bodies are only deleted after every op that
    still needs to read them.

    Body references are resolved INSIDE the edit (base.startEdit() is now inside
    this same try, so a raw failure there also comes back as a proper "rebuild
    failed:" reason rather than an uncaught exception) and materialised into a
    plain Python list rather than re-read from a live collection at each index:
    a 'remove' calls deleteMe() on one of those bodies, and re-querying the live
    collection afterward would renumber around the hole it left, silently
    shifting every later op's old_index onto the wrong body. Snapshotting once,
    up front, keeps every index in ``ops`` pointing at what it meant when
    placeholder_core.pair_bodies computed it, for the whole of this edit.

    Spike 3 established that base.bodies must be read INSIDE the edit: the
    documented dual behaviour is real, and outside the edit it returns the
    downstream RESULT body (a filleted 997.9) rather than the SOURCE body (1000.0)
    that updateBody demands. Passing the result body fails with "Invalid argument
    sourceBody. Not a source body for this base feature".

    Before touching anything, the resolved body count is checked against what
    ``ops`` expects to find (one 'update' or 'remove' per original body). A
    mismatch — a stale or corrupted recipe, or base_feature_bodies() having
    fallen back to ALL of the component's bodies because base.bodies came back
    empty, which can include a body the designer added downstream — refuses the
    whole rebuild instead of letting an unvalidated 'remove' call deleteMe() on
    whatever happens to sit at that index.

    finishEdit() is where the designer's downstream features recompute, and it CAN
    RAISE — spike 3 measured InternalValidationError when a fillet built on an edge
    of the old geometry could not be rebuilt on the new. Raising there destroys
    that feature and leaves the body unreadable. That is a per-child failure, not a
    run-ending one, so it is caught and returned rather than propagated.

    Returns "" on success, or a human-readable reason the rebuild failed.
    """
    def _safe_finish():
        try:
            base.finishEdit()
        except Exception:
            pass

    try:
        base.startEdit()
        # Inside the edit: base.bodies is now the base feature's SOURCE bodies.
        existing = base_feature_bodies(component, base)
        expected = sum(1 for kind, _, _ in ops if kind in ('update', 'remove'))
        if len(existing) != expected:
            _safe_finish()
            return ("the child's recorded bodies ({}) no longer match what its "
                    "base feature actually holds ({}) — its recipe may be stale, "
                    "or a body was added or removed outside this add-in."
                    .format(expected, len(existing)))
        for kind, old_index, new_index in ops:
            if kind == 'update':
                base.updateBody(existing[old_index], snaps[new_index]['temp'])
            elif kind == 'add':
                component.bRepBodies.add(snaps[new_index]['temp'], base)
            elif kind == 'remove':
                existing[old_index].deleteMe()
    except Exception as err:
        _safe_finish()
        return 'geometry swap failed: {}'.format(err)
    try:
        base.finishEdit()
    except Exception as err:
        # A feature the designer built on the OLD geometry's topology (a fillet or
        # chamfer on an edge, a sketch on a generated face) could not be recomputed
        # against the new shape. Fusion destroys it and leaves the body unreadable.
        return ('a feature built on the old geometry could not be recomputed '
                '({}). Anchor cuts to origin planes rather than to generated '
                'faces or edges.'.format(err))
    return ''
