# placeholder_core.py
# Pure, Fusion-free logic for the placeholder-instantiation feature: attribute
# schemas, frame construction, extents, matrices and body pairing. This module
# MUST NOT import adsk so it can be imported and unit-tested outside Fusion.
#
# Kept separate from sheet_core.py deliberately: that module is about reading
# Google Sheets, this one is about geometry and stored schemas.

import json
import math
import uuid

ATTR_GROUP = "SheetVariants"
MOTHER_SETUP_ATTR = "motherSetup"
CHILD_RECIPE_ATTR = "childRecipe"
SLOT_ID_ATTR = "slotId"

# Which model axis points OUT of the mother's front, as a face normal would.
FRONT_AXES = ("+X", "-X", "+Y", "-Y")


def dumps_attr(data):
    """Serialize an attribute payload. Sorted and compact so an unchanged value
    round-trips to an identical string and does not dirty the document."""
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def loads_attr(text, migrate):
    """Parse an attribute payload through its migration function. A missing or
    corrupt value yields the migrated default rather than raising, so a hand-edited
    or truncated attribute degrades to 'not set up' instead of breaking a build."""
    try:
        data = json.loads(text) if text else {}
    except (TypeError, ValueError):
        data = {}
    return migrate(data)


def anchor_target(centre, frame, dims_cm):
    """The world point the mother's anchor lands on: the centre of the box's
    FRONT face.

    There is deliberately no choice here. Placing a child is a rigid transform;
    the frame fixes its rotation, leaving three translation degrees of freedom —
    and the author already controls all three by where they put the joint origin.
    So one fixed rule plus a freely-placed anchor expresses every placement a
    menu of reference points could, with nothing extra to get wrong. Where a
    model does not fill its driven volume — a plinth below the driven height, an
    overhanging worktop — the author nudges the joint origin, which they would be
    doing anyway.

    The front face is the one to fix on because Fusion snaps a joint origin to a
    face centre readily (an earlier version required the model's CENTRE, which
    Fusion gives you no way to snap to, and every child landed half a depth out),
    and because it is the same face already picked in the layout.

    This holds only because the box drives width, depth AND height, so the
    model's driven volume matches the box and aligning one consistent reference
    aligns everything. A future feature that let a mother ignore one of those
    dimensions would need this revisited.

    "Front" is the -depth end: depth runs INTO the volume from the selected face.
    """
    _width, depth, _up = frame
    _w, d, _h = dims_cm
    return tuple(centre[k] - depth[k] * (d / 2.0) for k in range(3))


def default_mother_setup():
    return {"v": 1, "anchor": "", "front": "-Y",
            "params": {"width": "", "depth": "", "height": ""}}


def migrate_mother_setup(data):
    """Return a well-formed motherSetup from whatever was stored."""
    data = data if isinstance(data, dict) else {}
    params = data.get("params")
    params = params if isinstance(params, dict) else {}
    front = data.get("front")
    return {
        "v": 1,
        "anchor": str(data.get("anchor") or ""),
        "front": front if front in FRONT_AXES else "-Y",
        "params": {k: str(params.get(k) or "")
                   for k in ("width", "depth", "height")},
    }


def validate_mother_setup(data):
    """Human-readable reasons this mother cannot be used. Empty list means usable."""
    setup = migrate_mother_setup(data)
    errors = []
    if not setup["anchor"]:
        errors.append("No anchor joint origin is set.")
    for key in ("width", "depth", "height"):
        if not setup["params"][key]:
            errors.append('No parameter is mapped to {}.'.format(key))
    return errors


def new_slot_id():
    """A stable identity for a placeholder box, stamped on the body itself so it
    survives renaming the body — which a name-based key would not."""
    return "slot-" + uuid.uuid4().hex[:8]


def _float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _version(value):
    """Normalise a stored mother version: a real int, or None.

    ``bool`` is excluded even though it subclasses ``int`` — a stored
    ``true``/``false`` is not a version number, and letting it through would
    make a later staleness comparison behave unpredictably. Used by both
    ``new_child_recipe`` and ``migrate_child_recipe`` so a string or float
    version normalises to None the same way on write as on read, instead of
    only being caught on the next migration and silently failing to round-trip
    until then."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def new_child_recipe(slot_id, mother, config, sheet_url, tab, dims_cm,
                     bodies, built_at):
    """The record a child carries so it can be rebuilt later.

    ``built_at`` is supplied by the caller rather than generated here, so this
    module stays free of wall-clock dependencies and its tests stay deterministic.
    """
    mother = mother if isinstance(mother, dict) else {}
    w, d, h = dims_cm
    return {
        "v": 1,
        "slotId": str(slot_id or ""),
        "mother": {"fileId": str(mother.get("fileId") or ""),
                   "name": str(mother.get("name") or ""),
                   "version": _version(mother.get("version"))},
        "config": str(config or ""),
        "sheetUrl": str(sheet_url or ""),
        "tab": str(tab or ""),
        "dims_cm": {"w": _float(w), "d": _float(d), "h": _float(h)},
        "bodies": [str(b) for b in (bodies or [])],
        "builtAt": str(built_at or ""),
    }


def migrate_child_recipe(data):
    """Return a well-formed childRecipe from whatever was stored."""
    data = data if isinstance(data, dict) else {}
    mother = data.get("mother")
    mother = mother if isinstance(mother, dict) else {}
    dims = data.get("dims_cm")
    dims = dims if isinstance(dims, dict) else {}
    bodies = data.get("bodies")
    bodies = bodies if isinstance(bodies, list) else []
    return new_child_recipe(
        slot_id=data.get("slotId"),
        mother={"fileId": mother.get("fileId"), "name": mother.get("name"),
                "version": _version(mother.get("version"))},
        config=data.get("config"),
        sheet_url=data.get("sheetUrl"),
        tab=data.get("tab"),
        dims_cm=(_float(dims.get("w")), _float(dims.get("d")), _float(dims.get("h"))),
        bodies=bodies,
        built_at=data.get("builtAt"))


UP = (0.0, 0.0, 1.0)

_AXIS_VECTORS = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
                 "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}

# A face normal from real geometry is never exactly horizontal, so the "is this
# face vertical?" test needs slack. 1e-4 accepts ordinary floating-point noise
# while still rejecting a face tilted by even a hundredth of a degree.
_HORIZONTAL_TOLERANCE = 1e-4

# Below this, an extent is floating-point noise around zero rather than a real
# dimension — well under any placeholder anyone would build, in cm.
_MIN_EXTENT_CM = 1e-6


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def normalize(v):
    length = math.sqrt(dot(v, v))
    if length < 1e-12:
        raise ValueError("Could not read a direction from that face.")
    return (v[0] / length, v[1] / length, v[2] / length)


def _frame_from_outward(outward):
    """(width, depth, up) unit axes for a frame whose front points along
    ``outward``. Depth runs INTO the volume, opposite the outward direction; up is
    world +Z; width is depth x up, making the frame right-handed (w x d == u)."""
    n = normalize(outward)
    if abs(n[2]) > _HORIZONTAL_TOLERANCE:
        raise ValueError(
            "The front face must be vertical — pick a side of the box, not its "
            "top or bottom.")
    # A real face normal that survives the check above is still tilted by up to
    # _HORIZONTAL_TOLERANCE, not exactly horizontal. Flattening it onto the z=0
    # plane before building the frame keeps (w, d, u) exactly orthonormal, which
    # local_matrix's docstring relies on to use a transpose instead of a general
    # inverse; left tilted, a 60x58x210 box measures depth 58.021 instead of 58.
    n = normalize((n[0], n[1], 0.0))
    depth = (-n[0], -n[1], 0.0)
    return (cross(depth, UP), depth, UP)


def target_frame(face_normal):
    """The layout-side frame implied by the selected front face's outward normal."""
    return _frame_from_outward(face_normal)


def mother_frame(front_axis):
    """The mother-side frame implied by its stored front axis, which points out of
    the front exactly as a face normal does."""
    if front_axis not in _AXIS_VECTORS:
        raise ValueError(
            "The mother's front axis must be one of {}.".format(", ".join(FRONT_AXES)))
    return _frame_from_outward(_AXIS_VECTORS[front_axis])


def extents_in_frame(vertices, frame):
    """Measure ``vertices`` along ``frame``'s axes: (width, depth, height, centre).

    Vertices are world (x, y, z) tuples — a placeholder box has eight. Measuring by
    projection rather than by reading an axis-aligned bounding box is what lets a
    corner cabinet rotated 45 degrees report its true size instead of the much
    larger world-aligned box around it.

    Exact for any flat-faced solid. A placeholder with curved faces would
    under-measure, since only vertices are considered; that is accepted, because a
    placeholder is a box.
    """
    if not vertices:
        raise ValueError("The placeholder has no vertices to measure.")
    axes = frame
    projected = [tuple(dot(v, axis) for axis in axes) for v in vertices]
    lo = [min(p[i] for p in projected) for i in range(3)]
    hi = [max(p[i] for p in projected) for i in range(3)]
    extents = [hi[i] - lo[i] for i in range(3)]
    if any(e < _MIN_EXTENT_CM for e in extents):
        raise ValueError(
            "The placeholder is flat or degenerate along one axis — pick a box "
            "with real width, depth and height.")
    mid = [(lo[i] + hi[i]) / 2.0 for i in range(3)]
    centre = tuple(sum(mid[i] * axes[i][k] for i in range(3)) for k in range(3))
    return (extents[0], extents[1], extents[2], centre)


def occurrence_matrix(centre, frame):
    """Row-major local-to-world matrix for a child occurrence: the frame's axes as
    rotation columns, translated to the box centre.

    The placement lives here, on the occurrence — never baked into the bodies.
    The designer's downstream features are defined in the component's local space,
    so moving geometry inside the component would leave their cuts behind."""
    w, d, u = frame
    return [w[0], d[0], u[0], centre[0],
            w[1], d[1], u[1], centre[1],
            w[2], d[2], u[2], centre[2],
            0.0, 0.0, 0.0, 1.0]


def local_matrix(anchor, frame):
    """Row-major world-to-anchor-local matrix, applied to snapshotted bodies so
    they arrive with the mother's anchor at the child's origin.

    This is the inverse of the mother's anchor frame. Because the frame is
    orthonormal, the inverse rotation is its transpose and the inverse translation
    is -(transpose . anchor) — no general matrix inversion needed."""
    w, d, u = frame
    return [w[0], w[1], w[2], -dot(w, anchor),
            d[0], d[1], d[2], -dot(d, anchor),
            u[0], u[1], u[2], -dot(u, anchor),
            0.0, 0.0, 0.0, 1.0]


def qualified_body_name(component_name, body_name):
    """A body's name qualified by its owning component, so two components can both
    hold a body called 'Side' without the two being confused during a rebuild."""
    return "{}::{}".format(component_name or "", body_name or "")


def _ordinal_keys(names):
    """Pair each name with how many times it has already been seen, so repeated
    names still match one-to-one rather than all collapsing onto the first."""
    seen, keys = {}, []
    for name in names:
        index = seen.get(name, 0)
        seen[name] = index + 1
        keys.append((name, index))
    return keys


def pair_bodies(old_names, new_names):
    """Ops that turn a base feature holding ``old_names`` into one holding
    ``new_names``, matched by qualified name.

    Matching by name rather than by position is what lets a config change alter
    the body count — a two-drawer front becoming three — without scrambling which
    body is replaced by which.

    Ops are returned update-first, then adds, then removes, so a caller can apply
    them in order: every deletion happens after every op that still needs to read
    the old bodies.
    """
    old_keys = _ordinal_keys(old_names or [])
    new_keys = _ordinal_keys(new_names or [])
    new_positions = {key: i for i, key in enumerate(new_keys)}

    updates, removes, matched = [], [], set()
    for old_index, key in enumerate(old_keys):
        new_index = new_positions.get(key)
        if new_index is None:
            removes.append(("remove", old_index, None))
        else:
            updates.append(("update", old_index, new_index))
            matched.add(new_index)
    adds = [("add", None, i) for i in range(len(new_keys)) if i not in matched]
    return updates + adds + removes


def resulting_body_names(old_names, new_names, ops):
    """The order ``old_names`` will actually be in once ``ops`` (from
    ``pair_bodies``) are applied by the Fusion consumer — NOT the same thing
    as ``new_names``.

    This distinction is the whole reason this function exists: an 'add' in
    ``ops`` is positioned wherever ``pair_bodies`` happened to place its
    unmatched name in ``new_names``, but the Fusion API this drives
    (``component.bRepBodies.add()``) always appends to the TAIL of the
    collection as it stands at that moment — never inserts at the add's
    ``new_index`` position. An 'update' writes in place at ``old_index`` and
    changes nothing about position. So whenever an add is not already at the
    tail, the physical collection order diverges from ``new_names``' order.

    Recording *this* function's return value — not ``new_names`` — as a
    child's next recipe is what keeps a second rebuild's ``old_index``
    values pointing at the bodies they actually mean: caught the hard way,
    the alternative corrupts a rebuild two runs later, silently, with no
    exception and no failure line, because index N in a wrongly-recorded
    recipe would name a different body than index N in the real collection.

    Removes are resolved against their ORIGINAL positions in ``old_names``
    (every ``old_index`` in ``ops`` is relative to it, never to a partially
    trimmed list), which is why survivors are computed in one pass rather
    than by deleting one at a time and letting later indices shift down —
    that shift is exactly the bug this function exists to avoid reproducing.
    """
    working = list(old_names or [])
    for kind, old_index, new_index in ops:
        if kind == 'update':
            working[old_index] = new_names[new_index]
    removed = {old_index for kind, old_index, _ in ops if kind == 'remove'}
    survivors = [name for i, name in enumerate(working) if i not in removed]
    adds = [new_names[new_index] for kind, _, new_index in ops if kind == 'add']
    return survivors + adds


def resulting_snap_order(old_names, new_items, ops):
    """``new_items`` (parallel to the ``new_names`` passed into ``pair_bodies``)
    reordered into the PHYSICAL order ``ops`` leaves the real Fusion collection
    in — the exact same reordering ``resulting_body_names`` performs on the
    names themselves, kept as a separate function because a caller (reapplying
    a material/appearance per body) needs the object that goes WITH each name,
    not just the name string ``resulting_body_names`` returns.

    Re-deriving that mapping by matching ``resulting_body_names``' output back
    onto ``new_items`` by name would have to re-disambiguate duplicate
    qualified names a second time; working from ``ops`` directly needs no such
    step, because each op's ``new_index`` already identifies the exact item —
    it is the same index ``pair_bodies`` used to build ``new_names`` in the
    first place.

    See ``resulting_body_names`` for why the physical order differs from
    ``new_items``'s order at all: an 'add' always lands at the tail of the
    live collection, never at its ``new_index`` position.
    """
    working = [None] * len(old_names or [])
    for kind, old_index, new_index in ops:
        if kind == 'update':
            working[old_index] = new_items[new_index]
    removed = {old_index for kind, old_index, _ in ops if kind == 'remove'}
    survivors = [item for i, item in enumerate(working) if i not in removed]
    adds = [new_items[new_index] for kind, _, new_index in ops if kind == 'add']
    return survivors + adds
