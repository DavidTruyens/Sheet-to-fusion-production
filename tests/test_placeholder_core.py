import math
import pytest
import placeholder_core as pc


def test_default_mother_setup_shape():
    s = pc.default_mother_setup()
    assert s["v"] == 1
    assert s["front"] == "-Y"
    assert s["params"] == {"width": "", "depth": "", "height": ""}


def test_migrate_fills_missing_fields():
    s = pc.migrate_mother_setup({"anchor": "SV_Anchor"})
    assert s["anchor"] == "SV_Anchor"
    assert s["front"] == "-Y"
    assert s["params"]["width"] == ""


def test_migrate_rejects_unknown_front_axis():
    assert pc.migrate_mother_setup({"front": "+Z"})["front"] == "-Y"
    assert pc.migrate_mother_setup({"front": "+X"})["front"] == "+X"


def test_migrate_handles_none_and_garbage():
    assert pc.migrate_mother_setup(None)["v"] == 1
    assert pc.migrate_mother_setup("nonsense")["v"] == 1
    assert pc.migrate_mother_setup({"params": "nonsense"})["params"]["depth"] == ""


def test_validate_reports_every_missing_piece():
    errs = pc.validate_mother_setup({})
    assert len(errs) == 4
    assert any("anchor" in e for e in errs)
    assert any("width" in e for e in errs)


def test_validate_passes_a_complete_setup():
    assert pc.validate_mother_setup({
        "anchor": "SV_Anchor", "front": "-Y",
        "params": {"width": "cab_W", "depth": "cab_D", "height": "cab_H"},
    }) == []


def test_attr_round_trip():
    s = pc.migrate_mother_setup({"anchor": "A", "front": "+X",
                                 "params": {"width": "w", "depth": "d", "height": "h"}})
    assert pc.loads_attr(pc.dumps_attr(s), pc.migrate_mother_setup) == s


def test_loads_attr_survives_corrupt_json():
    assert pc.loads_attr("{not json", pc.migrate_mother_setup)["v"] == 1
    assert pc.loads_attr(None, pc.migrate_mother_setup)["v"] == 1


def test_new_slot_id_is_prefixed_and_unique():
    a, b = pc.new_slot_id(), pc.new_slot_id()
    assert a.startswith("slot-") and b.startswith("slot-")
    assert a != b


def _recipe():
    return pc.new_child_recipe(
        slot_id="slot-abc",
        mother={"fileId": "urn:x", "name": "base-cabinet.f3d", "version": 12},
        config="Base_2drawer",
        sheet_url="https://sheet", tab="Cabinets",
        dims_cm=(60.0, 58.0, 72.0),
        bodies=["Carcass::Left", "Carcass::Right"],
        built_at="2026-08-08T14:22:00")


def test_new_child_recipe_shape():
    r = _recipe()
    assert r["v"] == 1
    assert r["slotId"] == "slot-abc"
    assert r["mother"]["version"] == 12
    assert r["dims_cm"] == {"w": 60.0, "d": 58.0, "h": 72.0}
    assert r["bodies"] == ["Carcass::Left", "Carcass::Right"]


def test_child_recipe_round_trips_through_attribute():
    r = _recipe()
    assert pc.loads_attr(pc.dumps_attr(r), pc.migrate_child_recipe) == r


def test_migrate_child_recipe_fills_missing_fields():
    r = pc.migrate_child_recipe({"slotId": "slot-x"})
    assert r["slotId"] == "slot-x"
    assert r["mother"]["version"] is None
    assert r["bodies"] == []
    assert r["dims_cm"] == {"w": 0.0, "d": 0.0, "h": 0.0}


def test_migrate_child_recipe_handles_garbage():
    r = pc.migrate_child_recipe({"mother": "nope", "bodies": "nope", "dims_cm": 7})
    assert r["mother"]["fileId"] == ""
    assert r["bodies"] == []
    assert r["dims_cm"]["h"] == 0.0


def test_migrate_child_recipe_coerces_dims_to_float():
    r = pc.migrate_child_recipe({"dims_cm": {"w": "60", "d": 58, "h": 72.5}})
    assert r["dims_cm"] == {"w": 60.0, "d": 58.0, "h": 72.5}


def test_new_child_recipe_coerces_a_string_version_to_none():
    r = pc.new_child_recipe(
        slot_id="s", mother={"fileId": "x", "name": "n", "version": "12"},
        config="c", sheet_url="u", tab="t", dims_cm=(1, 2, 3), bodies=[],
        built_at="")
    assert r["mother"]["version"] is None


def test_new_child_recipe_coerces_a_bool_version_to_none():
    r = pc.new_child_recipe(
        slot_id="s", mother={"fileId": "x", "name": "n", "version": True},
        config="c", sheet_url="u", tab="t", dims_cm=(1, 2, 3), bodies=[],
        built_at="")
    assert r["mother"]["version"] is None


def test_new_child_recipe_keeps_a_real_int_version():
    r = pc.new_child_recipe(
        slot_id="s", mother={"fileId": "x", "name": "n", "version": 12},
        config="c", sheet_url="u", tab="t", dims_cm=(1, 2, 3), bodies=[],
        built_at="")
    assert r["mother"]["version"] == 12


def test_migrate_child_recipe_coerces_a_string_version_to_none():
    r = pc.migrate_child_recipe({"mother": {"version": "12"}})
    assert r["mother"]["version"] is None


def test_migrate_child_recipe_coerces_a_bool_version_to_none():
    r = pc.migrate_child_recipe({"mother": {"version": True}})
    assert r["mother"]["version"] is None


def test_migrate_child_recipe_keeps_a_real_int_version():
    r = pc.migrate_child_recipe({"mother": {"version": 12}})
    assert r["mother"]["version"] == 12


def test_string_version_round_trips_to_none_through_the_attribute():
    # A future caller handing a non-int version must not produce a recipe that
    # silently fails to round-trip: written and re-read versions must agree.
    r = pc.new_child_recipe(
        slot_id="s", mother={"fileId": "x", "name": "n", "version": "12"},
        config="c", sheet_url="u", tab="t", dims_cm=(1, 2, 3), bodies=[],
        built_at="")
    reloaded = pc.loads_attr(pc.dumps_attr(r), pc.migrate_child_recipe)
    assert reloaded == r
    assert reloaded["mother"]["version"] is None


def _close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_target_frame_for_a_face_pointing_minus_y():
    w, d, u = pc.target_frame((0.0, -1.0, 0.0))
    assert _close(d, (0.0, 1.0, 0.0))     # depth runs INTO the box
    assert _close(u, (0.0, 0.0, 1.0))
    assert _close(w, (1.0, 0.0, 0.0))


def test_target_frame_is_right_handed():
    w, d, u = pc.target_frame((0.0, -1.0, 0.0))
    assert _close(pc.cross(w, d), u)


def test_target_frame_for_a_rotated_face():
    n = (math.sqrt(0.5), -math.sqrt(0.5), 0.0)
    w, d, u = pc.target_frame(n)
    assert _close(d, (-n[0], -n[1], 0.0))
    assert _close(pc.cross(w, d), u)
    assert abs(pc.dot(w, d)) < 1e-9


def test_target_frame_normalizes_a_long_normal():
    w, d, u = pc.target_frame((0.0, -7.0, 0.0))
    assert _close(d, (0.0, 1.0, 0.0))


def test_target_frame_flattens_an_accepted_tilt_to_orthonormal():
    # A normal tilted just under the tolerance is accepted, but must not carry
    # its tilt into the frame: w, d, u must stay mutually orthogonal and unit
    # length, or local_matrix's transpose-as-inverse shortcut silently drifts.
    w, d, u = pc.target_frame((0.0, -1.0, 5e-5))
    assert abs(pc.dot(w, d)) < 1e-9
    assert abs(pc.dot(d, u)) < 1e-9
    assert abs(pc.dot(w, u)) < 1e-9
    assert abs(math.sqrt(pc.dot(w, w)) - 1.0) < 1e-9
    assert abs(math.sqrt(pc.dot(d, d)) - 1.0) < 1e-9
    assert abs(math.sqrt(pc.dot(u, u)) - 1.0) < 1e-9


def test_target_frame_rejects_a_horizontal_face():
    with pytest.raises(ValueError) as e:
        pc.target_frame((0.0, 0.0, 1.0))
    assert "vertical" in str(e.value)


def test_target_frame_tolerance_boundary_is_pinned():
    # Pins _HORIZONTAL_TOLERANCE itself: 0.0 would reject every real face (which
    # is never exactly vertical) and 0.5 would accept faces that are nowhere
    # near vertical. Neither extreme is caught by any other test.
    pc.target_frame((0.0, -1.0, 5e-5))
    with pytest.raises(ValueError):
        pc.target_frame((0.0, -1.0, 1e-3))


def test_target_frame_rejects_a_zero_normal():
    with pytest.raises(ValueError):
        pc.target_frame((0.0, 0.0, 0.0))


def test_mother_frame_minus_y_matches_a_minus_y_face():
    assert pc.mother_frame("-Y") == pc.target_frame((0.0, -1.0, 0.0))


def test_mother_frame_plus_x():
    w, d, u = pc.mother_frame("+X")
    assert _close(d, (-1.0, 0.0, 0.0))
    assert _close(pc.cross(w, d), u)


def test_mother_frame_rejects_a_vertical_axis():
    with pytest.raises(ValueError) as e:
        pc.mother_frame("+Z")
    assert "+X" in str(e.value)


def _box_vertices(x0, y0, z0, x1, y1, z1):
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def test_extents_of_an_axis_aligned_box():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    w, d, h, centre = pc.extents_in_frame(_box_vertices(0, 0, 0, 60, 58, 72), frame)
    assert (round(w, 9), round(d, 9), round(h, 9)) == (60.0, 58.0, 72.0)
    assert _close(centre, (30.0, 29.0, 36.0), 1e-9)


def test_extents_swap_when_the_front_face_faces_x():
    frame = pc.target_frame((-1.0, 0.0, 0.0))
    w, d, h, _ = pc.extents_in_frame(_box_vertices(0, 0, 0, 60, 58, 72), frame)
    assert (round(w, 9), round(d, 9), round(h, 9)) == (58.0, 60.0, 72.0)


def test_extents_of_a_rotated_box_are_not_inflated():
    # A 60x58x72 box rotated 45 degrees about Z. A world-aligned bounding box
    # would report ~83 wide; measuring in the frame must still report 60x58.
    import math as m
    c = m.cos(m.pi / 4)
    frame = pc.target_frame((c, -c, 0.0))
    verts = []
    for lx, ly, lz in _box_vertices(-30, -29, 0, 30, 29, 72):
        verts.append((lx * c - ly * c, lx * c + ly * c, lz))
    w, d, h, centre = pc.extents_in_frame(verts, frame)
    assert abs(w - 60.0) < 1e-9
    assert abs(d - 58.0) < 1e-9
    assert abs(h - 72.0) < 1e-9
    assert _close(centre, (0.0, 0.0, 36.0), 1e-9)


def test_extents_of_a_rotated_box_translated_off_origin():
    # Same rotated box as above, but shifted +100 in X so mid[0] and mid[1] are
    # both nonzero. That is what distinguishes a correct centre reconstruction
    # (sum(mid[i] * axes[i][k])) from the transposed mutant (axes[k][i]): the two
    # agree whenever the frame is identity or the midpoint is at the origin, and
    # disagree only here.
    import math as m
    c = m.cos(m.pi / 4)
    frame = pc.target_frame((c, -c, 0.0))
    verts = []
    for lx, ly, lz in _box_vertices(-30, -29, 0, 30, 29, 72):
        verts.append((lx * c - ly * c + 100.0, lx * c + ly * c, lz))
    w, d, h, centre = pc.extents_in_frame(verts, frame)
    assert abs(w - 60.0) < 1e-9
    assert abs(d - 58.0) < 1e-9
    assert abs(h - 72.0) < 1e-9
    assert _close(centre, (100.0, 0.0, 36.0), 1e-9)


def test_extents_rejects_an_empty_vertex_list():
    with pytest.raises(ValueError):
        pc.extents_in_frame([], pc.target_frame((0.0, -1.0, 0.0)))


def test_extents_rejects_a_single_vertex():
    # A single vertex has zero extent on all three axes. Left unchecked this
    # returns (0, 0, 0, that point) and downstream becomes a baffling
    # "0.000000 cm" parameter, attributed to the user's box rather than to a
    # degenerate selection.
    frame = pc.target_frame((0.0, -1.0, 0.0))
    with pytest.raises(ValueError):
        pc.extents_in_frame([(1.0, 2.0, 3.0)], frame)


def test_extents_rejects_a_zero_thickness_box():
    # A real box collapsed flat on one axis (e.g. depth == 0) is just as
    # degenerate as a single point and must be rejected the same way.
    frame = pc.target_frame((0.0, -1.0, 0.0))
    flat = _box_vertices(0, 0, 0, 60, 0, 72)
    with pytest.raises(ValueError):
        pc.extents_in_frame(flat, frame)


def test_occurrence_matrix_places_the_origin_at_the_centre():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    m = pc.occurrence_matrix((10.0, 20.0, 30.0), frame)
    assert len(m) == 16
    assert [m[3], m[7], m[11]] == [10.0, 20.0, 30.0]
    assert m[12:] == [0.0, 0.0, 0.0, 1.0]
    # Identity rotation for a -Y-facing frame: columns are w, d, u.
    assert [m[0], m[1], m[2]] == [1.0, 0.0, 0.0]
    assert [m[4], m[5], m[6]] == [0.0, 1.0, 0.0]


def test_occurrence_matrix_rotation_for_an_x_facing_frame():
    frame = pc.target_frame((-1.0, 0.0, 0.0))
    m = pc.occurrence_matrix((0.0, 0.0, 0.0), frame)
    # depth is +X, so the matrix's second column must be (1, 0, 0).
    assert [m[1], m[5], m[9]] == [1.0, 0.0, 0.0]


def test_local_matrix_sends_the_anchor_to_the_origin():
    frame = pc.mother_frame("-Y")
    m = pc.local_matrix((5.0, 6.0, 7.0), frame)
    assert [m[3], m[7], m[11]] == [-5.0, -6.0, -7.0]


def test_local_matrix_is_the_inverse_of_the_mother_frame():
    frame = pc.mother_frame("+X")
    anchor = (5.0, 6.0, 7.0)
    m = pc.local_matrix(anchor, frame)
    # Applying it to the anchor point must land exactly on the origin.
    def apply(mat, p):
        return tuple(mat[r * 4 + 0] * p[0] + mat[r * 4 + 1] * p[1]
                     + mat[r * 4 + 2] * p[2] + mat[r * 4 + 3] for r in range(3))
    assert _close(apply(m, anchor), (0.0, 0.0, 0.0), 1e-9)
    # And a point one unit along the mother's depth axis must land at (0, 1, 0).
    w, d, u = frame
    ahead = tuple(anchor[i] + d[i] for i in range(3))
    assert _close(apply(m, ahead), (0.0, 1.0, 0.0), 1e-9)


def test_qualified_body_name():
    assert pc.qualified_body_name("Carcass", "Left side") == "Carcass::Left side"


def test_pair_bodies_identical_lists_are_all_updates():
    ops = pc.pair_bodies(["A", "B"], ["A", "B"])
    assert ops == [("update", 0, 0), ("update", 1, 1)]


def test_pair_bodies_reordered_lists_track_by_name():
    ops = pc.pair_bodies(["A", "B"], ["B", "A"])
    assert ops == [("update", 0, 1), ("update", 1, 0)]


def test_pair_bodies_added_body():
    ops = pc.pair_bodies(["A"], ["A", "B"])
    assert ops == [("update", 0, 0), ("add", None, 1)]


def test_pair_bodies_removed_body():
    ops = pc.pair_bodies(["A", "B"], ["A"])
    assert ops == [("update", 0, 0), ("remove", 1, None)]


def test_pair_bodies_orders_updates_then_adds_then_removes():
    ops = pc.pair_bodies(["A", "X"], ["A", "B"])
    assert [o[0] for o in ops] == ["update", "add", "remove"]


def test_pair_bodies_duplicate_names_pair_by_ordinal():
    ops = pc.pair_bodies(["A", "A", "A"], ["A", "A"])
    assert ops == [("update", 0, 0), ("update", 1, 1), ("remove", 2, None)]


def test_pair_bodies_from_empty_is_all_adds():
    assert pc.pair_bodies([], ["A", "B"]) == [("add", None, 0), ("add", None, 1)]


def test_pair_bodies_to_empty_is_all_removes():
    assert pc.pair_bodies(["A", "B"], []) == [("remove", 0, None), ("remove", 1, None)]


def test_pair_bodies_handles_none():
    assert pc.pair_bodies(None, None) == []


def test_resulting_body_names_identical_lists_are_unchanged():
    ops = pc.pair_bodies(["A", "B"], ["A", "B"])
    assert pc.resulting_body_names(["A", "B"], ["A", "B"], ops) == ["A", "B"]


def test_resulting_body_names_reorder_does_not_move_bodies():
    # Fusion only ever writes updates in place; a name reorder in new_names
    # does not reorder the physical collection.
    ops = pc.pair_bodies(["A", "B"], ["B", "A"])
    assert pc.resulting_body_names(["A", "B"], ["B", "A"], ops) == ["A", "B"]


def test_resulting_body_names_add_at_the_tail():
    ops = pc.pair_bodies(["A"], ["A", "B"])
    assert pc.resulting_body_names(["A"], ["A", "B"], ops) == ["A", "B"]


def test_resulting_body_names_add_in_the_middle():
    # The exact corruption case: pair_bodies lists the add as index 1 of
    # new_names, but component.bRepBodies.add() always appends to the tail of
    # the CURRENT collection, so the physical order is A, C, B -- not A, B, C.
    old, new = ["A", "C"], ["A", "B", "C"]
    ops = pc.pair_bodies(old, new)
    assert pc.resulting_body_names(old, new, ops) == ["A", "C", "B"]


def test_resulting_body_names_remove():
    ops = pc.pair_bodies(["A", "B"], ["A"])
    assert pc.resulting_body_names(["A", "B"], ["A"], ops) == ["A"]


def test_resulting_body_names_mixed_add_and_remove():
    old, new = ["A", "X"], ["A", "B"]
    ops = pc.pair_bodies(old, new)
    assert pc.resulting_body_names(old, new, ops) == ["A", "B"]


def test_resulting_body_names_empty_to_n():
    ops = pc.pair_bodies([], ["A", "B"])
    assert pc.resulting_body_names([], ["A", "B"], ops) == ["A", "B"]


def test_resulting_body_names_n_to_empty():
    ops = pc.pair_bodies(["A", "B"], [])
    assert pc.resulting_body_names(["A", "B"], [], ops) == []


def test_resulting_body_names_multiple_removes_use_original_positions():
    # Two removes must be resolved against their positions in the ORIGINAL
    # old_names, not by deleting one at a time and letting later indices
    # shift down -- deleteMe() is applied to a materialized list, not a live
    # collection that renumbers itself as this function computes survivors.
    old, new = ["A", "B", "C", "D"], ["A", "C"]
    ops = pc.pair_bodies(old, new)
    assert pc.resulting_body_names(old, new, ops) == ["A", "C"]


def test_resulting_snap_order_identical_lists_are_unchanged():
    ops = pc.pair_bodies(["A", "B"], ["A", "B"])
    assert pc.resulting_snap_order(["A", "B"], ["snapA", "snapB"], ops) == ["snapA", "snapB"]


def test_resulting_snap_order_reorder_does_not_move_items():
    # Mirrors test_resulting_body_names_reorder_does_not_move_bodies: the new
    # list names B before A, but Fusion only ever updates bodies in place, so
    # the item that lands at physical position 0 is still whatever pairs with
    # old position 0 (A), not whatever is first in new_items.
    ops = pc.pair_bodies(["A", "B"], ["B", "A"])
    assert pc.resulting_snap_order(["A", "B"], ["snapB", "snapA"], ops) == ["snapA", "snapB"]


def test_resulting_snap_order_add_in_the_middle():
    # The I1 regression case: an oak carcass (A) plus a new middle body (B)
    # plus an existing side (C). pair_bodies lists the add at new_names index
    # 1, but component.bRepBodies.add() appends to the tail, so the physical
    # order is A, C, B -- the look for B must follow it there, not stay at
    # logical position 1.
    old, new = ["A", "C"], ["A", "B", "C"]
    ops = pc.pair_bodies(old, new)
    items = ["snapA", "snapB", "snapC"]
    assert pc.resulting_snap_order(old, items, ops) == ["snapA", "snapC", "snapB"]


def test_resulting_snap_order_remove():
    ops = pc.pair_bodies(["A", "B"], ["A"])
    assert pc.resulting_snap_order(["A", "B"], ["snapA"], ops) == ["snapA"]


def test_resulting_snap_order_mixed_add_and_remove():
    old, new = ["A", "X"], ["A", "B"]
    ops = pc.pair_bodies(old, new)
    assert pc.resulting_snap_order(old, ["snapA", "snapB"], ops) == ["snapA", "snapB"]


def test_resulting_snap_order_empty_to_n():
    ops = pc.pair_bodies([], ["A", "B"])
    assert pc.resulting_snap_order([], ["snapA", "snapB"], ops) == ["snapA", "snapB"]


def test_resulting_snap_order_n_to_empty():
    ops = pc.pair_bodies(["A", "B"], [])
    assert pc.resulting_snap_order(["A", "B"], [], ops) == []


def test_resulting_snap_order_matches_resulting_body_names_positions():
    # The property that actually matters for I1: whichever position a name
    # ends up at via resulting_body_names, resulting_snap_order must put that
    # same name's item at the same position, for a whole spread of cases.
    cases = [
        (["A", "C"], ["A", "B", "C"]),
        (["A", "B", "C"], ["C", "A"]),
        (["A", "B"], ["A", "B", "C"]),
        ([], ["A", "B"]),
        (["A", "B", "C", "D"], ["A", "C"]),
    ]
    for old, new in cases:
        ops = pc.pair_bodies(old, new)
        names = pc.resulting_body_names(old, new, ops)
        items = pc.resulting_snap_order(old, ["item_" + n for n in new], ops)
        assert items == ["item_" + n for n in names], (old, new, names, items)


def test_pair_bodies_fed_resulting_names_is_a_stable_no_op():
    # The property that actually matters: recording the ACTUAL resulting
    # order (not new_names) as the next rebuild's "old" bodies means a second
    # pairing against the same target produces nothing but updates -- no
    # adds, no removes -- because every body is already there, just possibly
    # in a different order. This is the exact invariant Critical 1 broke.
    cases = [
        (["A", "C"], ["A", "B", "C"]),
        (["A", "B", "C"], ["C", "A"]),
        (["A", "B"], ["A", "B", "C"]),
        ([], ["A", "B"]),
        (["A", "B", "C", "D"], ["A", "C"]),
    ]
    for old, new in cases:
        ops = pc.pair_bodies(old, new)
        resulting = pc.resulting_body_names(old, new, ops)
        ops2 = pc.pair_bodies(resulting, new)
        kinds = [op[0] for op in ops2]
        assert kinds == ["update"] * len(new), (old, new, resulting, ops2)


# --- anchor_target: always the centre of the box's front face ---------------

def _frame_and_box():
    """A -Y-facing frame and a 60 x 58 x 72 box centred at (10, 20, 36)."""
    frame = pc.target_frame((0.0, -1.0, 0.0))   # w=+X, d=+Y, u=+Z
    return frame, (10.0, 20.0, 36.0), (60.0, 58.0, 72.0)


def test_anchor_target_is_the_front_face_centre():
    frame, centre, dims = _frame_and_box()
    # depth runs +Y, so the box's FRONT is at the -Y end: 20 - 58/2.
    assert _close(pc.anchor_target(centre, frame, dims), (10.0, 20.0 - 29.0, 36.0))


def test_anchor_target_does_not_move_across_width_or_height():
    frame, centre, dims = _frame_and_box()
    got = pc.anchor_target(centre, frame, dims)
    assert _close((got[0], got[2]), (centre[0], centre[2]))


def test_anchor_target_follows_a_rotated_frame():
    # Front face pointing +X, so depth runs -X and the box's front is at +X.
    frame = pc.target_frame((1.0, 0.0, 0.0))
    got = pc.anchor_target((0.0, 0.0, 0.0), frame, (60.0, 58.0, 72.0))
    assert _close(got, (29.0, 0.0, 0.0))


def test_anchor_target_of_a_zero_depth_box_is_the_centre():
    frame, centre, _dims = _frame_and_box()
    assert _close(pc.anchor_target(centre, frame, (60.0, 0.0, 72.0)), centre)


def test_mother_setup_no_longer_carries_an_anchor_rule():
    # One fixed rule: the author positions by moving the joint origin, so there
    # is nothing per-mother to store and nothing to get wrong.
    assert "anchorAt" not in pc.migrate_mother_setup({})
    assert "anchorAt" not in pc.migrate_mother_setup({"anchorAt": "centre"})


def test_child_recipe_no_longer_carries_an_anchor_rule():
    assert "anchorAt" not in pc.migrate_child_recipe({})
    assert "anchorAt" not in pc.migrate_child_recipe({"anchorAt": "centre"})


# --- staleness, change detection and status labels --------------------------

def test_staleness_compares_versions():
    assert pc.staleness(12, 14) == pc.STALE_OUT_OF_DATE
    assert pc.staleness(12, 12) == pc.STALE_CURRENT


def test_staleness_flags_a_reverted_mother_too():
    assert pc.staleness(14, 12) == pc.STALE_OUT_OF_DATE


def test_staleness_is_unknown_without_both_versions():
    assert pc.staleness(None, 12) == pc.STALE_UNKNOWN
    assert pc.staleness(12, None) == pc.STALE_UNKNOWN
    assert pc.staleness("12", 12) == pc.STALE_UNKNOWN


def test_staleness_excludes_bool_from_either_side():
    # bool is an int subclass, but a stored/current version of True or False is
    # not a real version number — it must read as unknown, not as a match or a
    # mismatch, on both sides of the comparison.
    assert pc.staleness(True, 1) == pc.STALE_UNKNOWN
    assert pc.staleness(1, True) == pc.STALE_UNKNOWN


def test_frame_from_matrix_round_trips_occurrence_matrix():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    m = pc.occurrence_matrix((3.0, 4.0, 5.0), frame)
    assert pc.frame_from_matrix(m) == frame


def test_frame_from_matrix_round_trips_a_rotated_frame():
    import math as m
    c = m.cos(m.pi / 4)
    frame = pc.target_frame((c, -c, 0.0))
    got = pc.frame_from_matrix(pc.occurrence_matrix((0.0, 0.0, 0.0), frame))
    for axis, expected in zip(got, frame):
        assert _close(axis, expected, 1e-12)


def test_matrices_differ_detects_a_translation():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    a = pc.occurrence_matrix((0.0, 0.0, 0.0), frame)
    b = pc.occurrence_matrix((0.0, 20.0, 0.0), frame)
    assert pc.matrices_differ(a, b)
    assert not pc.matrices_differ(a, list(a))


def test_matrices_differ_ignores_floating_point_noise():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    a = pc.occurrence_matrix((1.0, 2.0, 3.0), frame)
    b = [v + 1e-12 for v in a]
    assert not pc.matrices_differ(a, b)


def test_matrices_differ_on_missing_input():
    assert pc.matrices_differ(None, [0.0] * 16)
    assert pc.matrices_differ([0.0] * 16, [0.0] * 4)


_BOX_NORMALS = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)]


def _rotate_z(normals, radians):
    import math as m
    c, s = m.cos(radians), m.sin(radians)
    return [(x * c - y * s, x * s + y * c, z) for x, y, z in normals]


def test_is_axis_aligned_true_for_a_box_in_its_own_frame():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    assert pc.is_axis_aligned(_BOX_NORMALS, frame)


def test_is_axis_aligned_false_for_a_rotated_box():
    import math as m
    frame = pc.target_frame((0.0, -1.0, 0.0))
    assert not pc.is_axis_aligned(_rotate_z(_BOX_NORMALS, m.pi / 4), frame)


def test_a_filleted_box_is_not_reported_as_rotated():
    # THE BUG: rounding a placeholder's edges put vertices at the fillet tangent
    # points, so the old vertex-based check saw four distinct coordinates per
    # axis instead of two and called a perfectly aligned box rotated — for good,
    # since re-running Fill Placeholders cannot change the geometry. A fillet
    # adds CURVED faces, which say nothing about orientation, so the six flat
    # faces still decide it.
    frame = pc.target_frame((0.0, -1.0, 0.0))
    assert pc.is_axis_aligned(_BOX_NORMALS, frame)   # flat faces survive filleting


def test_a_chamfered_box_is_not_reported_as_rotated():
    # A chamfer's faces ARE flat but sit at 45 degrees. They are extra faces, not
    # missing ones, so every frame axis is still covered by a real face.
    import math as m
    frame = pc.target_frame((0.0, -1.0, 0.0))
    c = m.sqrt(0.5)
    chamfers = [(c, c, 0.0), (-c, c, 0.0), (c, -c, 0.0), (-c, -c, 0.0)]
    assert pc.is_axis_aligned(_BOX_NORMALS + chamfers, frame)


def test_is_axis_aligned_false_for_a_degenerate_body():
    # A zero-thickness sheet has flat faces facing the up axis only, leaving the
    # other two uncovered — so it is still rejected rather than measured.
    frame = pc.target_frame((0.0, -1.0, 0.0))
    assert not pc.is_axis_aligned([(0.0, 0.0, 1.0), (0.0, 0.0, -1.0)], frame)


def test_is_axis_aligned_false_when_only_one_axis_is_covered():
    # A box turned about X keeps its side faces facing width, but nothing faces
    # depth or up any more.
    import math as m
    frame = pc.target_frame((0.0, -1.0, 0.0))
    c, s = m.cos(m.pi / 6), m.sin(m.pi / 6)
    turned = [(x, y * c - z * s, y * s + z * c) for x, y, z in _BOX_NORMALS]
    assert not pc.is_axis_aligned(turned, frame)


def test_a_body_that_is_not_a_box_is_not_measured():
    # A square tube: flat faces facing width and depth, inner and outer, but
    # nothing facing up at all. Every frame axis has to be covered, not just the
    # two a rotation would disturb — a body this far from a box is reported
    # rather than measured, since nothing here can vouch for its height.
    frame = pc.target_frame((0.0, -1.0, 0.0))
    tube = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0)]
    assert not pc.is_axis_aligned(tube, frame)


def test_is_axis_aligned_accepts_a_box_turned_a_full_quarter_turn():
    # A quarter turn maps each axis onto another, so the faces still face the
    # frame's axes and the extents measured there are the box's real extents.
    import math as m
    frame = pc.target_frame((0.0, -1.0, 0.0))
    assert pc.is_axis_aligned(_rotate_z(_BOX_NORMALS, m.pi / 2), frame)


def _stored(version=12, dims=(60.0, 58.0, 72.0)):
    return pc.new_child_recipe(
        slot_id="slot-abc",
        mother={"fileId": "urn:x", "name": "m.f3d", "version": version},
        config="C", sheet_url="", tab="", dims_cm=dims,
        bodies=[], built_at="2026-08-08T00:00:00")


def test_child_status_up_to_date_is_not_ticked():
    s = pc.child_status(_stored(), 12, (60.0, 58.0, 72.0), False, False, True, True)
    assert s["staleness"] == pc.STALE_CURRENT
    assert s["tick"] is False
    assert pc.status_label(s) == "up to date"


def test_child_status_out_of_date_is_ticked():
    s = pc.child_status(_stored(), 14, (60.0, 58.0, 72.0), False, False, True, True)
    assert s["tick"] is True
    assert pc.status_label(s) == "out of date"


def test_child_status_detects_a_resize():
    s = pc.child_status(_stored(), 12, (100.0, 58.0, 72.0), False, False, True, True)
    assert s["resized"] is True
    assert s["tick"] is True
    assert "resized" in pc.status_label(s)


def test_child_status_ignores_a_sub_micron_dimension_difference():
    s = pc.child_status(_stored(), 12, (60.00000001, 58.0, 72.0),
                        False, False, True, True)
    assert s["resized"] is False


def test_child_status_combines_flags_in_the_label():
    s = pc.child_status(_stored(), 14, (100.0, 58.0, 72.0), True, False, True, True)
    assert pc.status_label(s) == "out of date, resized, moved"


def test_child_status_moved_alone_still_ticks():
    # Version unchanged and dims unchanged — moved is the only reason to rebuild,
    # so it alone must be enough to tick the row and to appear in the label.
    s = pc.child_status(_stored(), 12, (60.0, 58.0, 72.0), True, False, True, True)
    assert s["tick"] is True
    assert pc.status_label(s) == "moved"


def test_child_status_missing_mother_is_a_problem_and_not_ticked():
    s = pc.child_status(_stored(), None, (60.0, 58.0, 72.0), False, False, False, True)
    assert s["problem"] == "mother not found"
    assert s["tick"] is False
    assert pc.status_label(s) == "mother not found"


def test_child_status_missing_mother_problem_matches_exported_constant():
    # placeholder_cmds._mother_heading dispatches on PROBLEM_MOTHER_NOT_FOUND
    # instead of a literal copy of this prose (see that constant's own
    # docstring). Pin that child_status actually sets the exported constant's
    # value, so rewording the message here cannot silently decouple from that
    # caller without this test failing first.
    s = pc.child_status(_stored(), None, (60.0, 58.0, 72.0), False, False, False, True)
    assert s["problem"] == pc.PROBLEM_MOTHER_NOT_FOUND


def test_child_status_missing_placeholder_is_a_problem():
    s = pc.child_status(_stored(), 12, None, False, False, True, False)
    assert s["problem"] == "placeholder missing"
    assert s["tick"] is False


def test_child_status_missing_mother_takes_precedence_over_missing_box():
    # A child whose mother is gone cannot be rebuilt no matter what state its own
    # box is in — the more fundamental failure must win the message.
    s = pc.child_status(_stored(), None, None, False, False, False, False)
    assert s["problem"] == "mother not found"


def test_child_status_rotated_is_a_problem_not_a_rebuild():
    s = pc.child_status(_stored(), 12, (60.0, 58.0, 72.0), False, True, True, True)
    assert s["tick"] is False
    assert "re-run Fill Placeholders" in pc.status_label(s)


# --- childRecipe records a versionId as a second lookup key -------------------

def test_new_child_recipe_records_a_version_id():
    r = pc.new_child_recipe(
        slot_id="s", mother={"fileId": "urn:lineage", "name": "m", "version": 16},
        config="", sheet_url="", tab="", dims_cm=(1.0, 2.0, 3.0), bodies=[],
        built_at="t", version_id="urn:vf?version=16")
    assert r["versionId"] == "urn:vf?version=16"


def test_child_recipe_version_id_round_trips():
    r = pc.new_child_recipe(
        slot_id="s", mother={}, config="", sheet_url="", tab="",
        dims_cm=(1.0, 2.0, 3.0), bodies=[], built_at="t",
        version_id="urn:vf?version=2")
    assert pc.loads_attr(pc.dumps_attr(r), pc.migrate_child_recipe) == r


def test_migrate_child_recipe_defaults_version_id_to_empty():
    # A child built before this field existed simply has no second lookup key;
    # the lineage id it does have is still tried.
    assert pc.migrate_child_recipe({})["versionId"] == ""


def test_child_status_unknown_version_is_not_a_missing_mother():
    # The dialog cannot prove a mother is gone — findFileById is unreliable — so
    # an unresolvable version must leave the row REBUILDABLE and merely say the
    # comparison is unavailable. Reporting it as a missing mother disabled the
    # row and made the feature unusable offline.
    s = pc.child_status(_stored(), None, (60.0, 58.0, 72.0),
                        False, False, True, True)
    assert s["problem"] == ""
    assert s["staleness"] == pc.STALE_UNKNOWN
    assert pc.status_label(s) == "unknown version"


# --- the mother heading is a property of the MOTHER, not of one child ---------

def test_mother_heading_names_both_versions_when_out_of_date():
    # "v16 is out of date" gave the reader nothing to compare against. Name the
    # version built from AND the version now available.
    assert pc.mother_heading("mother1", 16, 17) == \
        "mother1 — built from v16, now v17"


def test_mother_heading_is_quiet_when_up_to_date():
    assert pc.mother_heading("mother1", 16, 16) == "mother1 — v16"


def test_mother_heading_flags_a_reverted_mother_too():
    # Any difference counts, not just a mother that moved forward.
    assert pc.mother_heading("mother1", 16, 14) == \
        "mother1 — built from v16, now v14"


def test_mother_heading_says_so_when_the_current_version_is_unknown():
    assert pc.mother_heading("mother1", 16, None) == \
        "mother1 — built from v16, current version unknown"


def test_mother_heading_handles_an_unknown_stored_version():
    assert pc.mother_heading("mother1", None, 16) == \
        "mother1 — built from an unknown version, now v16"


def test_mother_heading_marks_a_missing_mother():
    assert pc.mother_heading("mother1", 16, None, found=False) == \
        "mother1 — missing"


def test_mother_heading_falls_back_when_the_name_was_never_recorded():
    assert pc.mother_heading("", 16, 16) == "(unnamed) — v16"


# --- grouping: one heading per mother, and never two mothers under one --------

def _row(name, file_id, stored, current, problem="", mother_name="Base",
         recorded_name="Base"):
    """A survey row shaped the way survey_children builds it.

    ``mother_name`` is the name RESOLVED from the file — survey_children resolves
    it once per fileId, so siblings always share it. ``recorded_name`` is what the
    recipe stored, which siblings CAN differ on, and which is only displayed when
    the file could not be resolved and mother_name is ''.
    """
    return {
        "name": name,
        "recipe": pc.new_child_recipe(
            slot_id=name, mother={"fileId": file_id, "name": recorded_name,
                                  "version": stored},
            config="", sheet_url="", tab="", dims_cm=(1.0, 1.0, 1.0),
            bodies=[], built_at="t"),
        "current_version": current,
        "mother_name": mother_name,
        "status": dict(problem=problem, staleness=pc.STALE_UNKNOWN,
                       resized=False, moved=False, rotated=False, tick=False),
    }


def _headings(rows):
    """Replay the dialog's real emit-on-key-change loop, returning
    (heading text, [row names]) in display order."""
    groups, last_key = [], object()
    for row in sorted(rows, key=pc.mother_sort_key):
        key = pc.mother_heading_key(row)
        if key != last_key:
            last_key = key
            groups.append((pc.mother_heading_for_row(row), []))
        groups[-1][1].append(row["name"])
    return groups


def test_a_childs_own_problem_does_not_split_its_mothers_heading():
    # THE BUG: the heading was derived from the row's staleness, which
    # child_status leaves at STALE_UNKNOWN when it returns early for a rotated
    # box. One mother rendered "mother1 — v16" above the rotated child and
    # "mother1 — v16 is out of date" above its siblings, and the heading
    # re-emitted mid-group.
    rows = [_row("Body1", "urn:L1", 16, 17, problem="rotated — re-run Fill"),
            _row("Body2", "urn:L1", 16, 17),
            _row("Body3", "urn:L1", 16, 17)]
    assert _headings(rows) == [
        ("Base — built from v16, now v17", ["Body1", "Body2", "Body3"])]


def test_a_resolved_name_heals_two_differently_recorded_siblings():
    # A child built before the name fix recorded the DOCUMENT name ("mother1
    # v16"); a newer sibling recorded the file name. Resolving the name from the
    # file overrides both, so they share one heading with the correct name — and
    # nobody has to rebuild to get it.
    rows = [_row("Old", "urn:L1", 16, 17, mother_name="mother1",
                 recorded_name="mother1 v16"),
            _row("New", "urn:L1", 16, 17, mother_name="mother1",
                 recorded_name="mother1")]
    assert _headings(rows) == [
        ("mother1 — built from v16, now v17", ["New", "Old"])]


def test_an_unresolvable_mother_never_interleaves_with_another():
    # When the file resolves for NEITHER id, mother_name is '' and the recorded
    # names show through — and siblings genuinely differ on those. The display
    # name leads the ordering, so a third mother sorting between the two names
    # used to split one mother's group in half and emit a contradictory heading
    # over each part. Two groups here is honest; a re-emitted heading is not.
    rows = [_row("Box1", "urn:LA", 16, None, mother_name="",
                 recorded_name="mother1"),
            _row("Box3", "urn:LA", 16, None, mother_name="",
                 recorded_name="mother1 v16"),
            _row("Box2", "urn:LB", 12, None, mother_name="",
                 recorded_name="mother1 copy")]
    groups = _headings(rows)
    keys = [heading for heading, _names in groups]
    assert len(keys) == len(set(keys)), "a heading was emitted twice"
    assert [names for _heading, names in groups] == [["Box1"], ["Box2"], ["Box3"]]


def test_two_different_mothers_sharing_a_name_are_not_merged():
    # Two distinct files both called "Base", both at v1 — indistinguishable by
    # name and version, so a name-keyed heading merged them into one group.
    rows = [_row("A1", "urn:LA", 1, 1), _row("A2", "urn:LA", 1, 1),
            _row("B1", "urn:LB", 1, 1)]
    groups = _headings(rows)
    assert len(groups) == 2
    assert sorted(g[1] for g in groups) == [["A1", "A2"], ["B1"]]


def test_one_mother_filled_across_two_versions_gets_two_headings():
    # Genuinely separate groups: fill some boxes, save the mother, fill more.
    rows = [_row("Early", "urn:L1", 12, 14), _row("Late", "urn:L1", 14, 14)]
    assert _headings(rows) == [
        ("Base — built from v12, now v14", ["Early"]),
        ("Base — v14", ["Late"])]


def test_a_missing_mother_never_re_emits_mid_group():
    # mother_heading's missing branch ignores both versions, so without the
    # found flag in the key two rows could share a key and render differently.
    rows = [_row("a", "", 16, None, problem=pc.PROBLEM_MOTHER_NOT_FOUND),
            _row("b", "", 16, None, problem=pc.PROBLEM_MOTHER_NOT_FOUND),
            _row("c", "urn:L1", 16, None)]
    for heading, names in _headings(rows):
        assert len(set(names)) == len(names)
    assert len(_headings(rows)) == 2


def test_a_missing_mothers_children_form_one_group_across_versions():
    # The missing branch prints no version, so keying on versions here emitted two
    # consecutive headings reading exactly the same thing. Whatever versions its
    # children were built from, a mother that cannot be found is one group.
    rows = [_row("Early", "", 12, None, problem=pc.PROBLEM_MOTHER_NOT_FOUND),
            _row("Late", "", 14, None, problem=pc.PROBLEM_MOTHER_NOT_FOUND)]
    assert _headings(rows) == [("Base — missing", ["Early", "Late"])]


def test_same_group_key_always_means_same_heading_text():
    # The invariant the dialog depends on: it emits a heading only when the key
    # changes, so any two rows sharing a key MUST render identical text or one
    # group would silently display under another's heading.
    # Every axis the heading text reads, INCLUDING both names. Pinning the name
    # to one value is what let the key omit it: the test looked exhaustive and
    # could not fail on the only broken dimension.
    rows = [_row(n, f, stored, current, problem=p, mother_name=m,
                 recorded_name=r)
            for n, f in (("x", "urn:LA"), ("y", "urn:LA"), ("z", "urn:LB"))
            for stored in (12, 14, None)
            for current in (14, None)
            for p in ("", "rotated", pc.PROBLEM_MOTHER_NOT_FOUND)
            for m in ("Base", "Base v16", "")
            for r in ("Base", "Base v12")]
    by_key = {}
    for row in rows:
        key = pc.mother_heading_key(row)
        text = pc.mother_heading_for_row(row)
        assert by_key.setdefault(key, text) == text


def test_sorting_leaves_every_heading_group_contiguous():
    # If a group's rows are not contiguous after sorting, its heading re-emits.
    rows = [_row(n, f, stored, current, mother_name=m, recorded_name=r)
            for n, f in (("x", "urn:LA"), ("y", "urn:LB"), ("z", "urn:LA"))
            for stored in (12, 14)
            for current in (14,)
            for m in ("Base", "Base copy", "")
            for r in ("Base", "Base v16")]
    seen, previous = set(), None
    for row in sorted(rows, key=pc.mother_sort_key):
        key = pc.mother_heading_key(row)
        if key != previous:
            assert key not in seen, "group {} re-emitted".format(key)
            seen.add(key)
            previous = key


# --- inherited_look: a colour applied above the body still gets copied --------

class _Look:
    """Stands in for a Fusion Appearance/Material. Deliberately FALSY, to prove
    the resolver tests for 'is set' rather than truthiness — a real object that
    happened to be falsy would otherwise be skipped and read as no colour."""
    def __init__(self, name):
        self.name = name

    def __bool__(self):
        return False

    def __repr__(self):
        return "_Look({!r})".format(self.name)


def test_inherited_look_prefers_the_bodys_own_override():
    body, occurrence = _Look("body"), _Look("occ")
    assert pc.inherited_look([body, occurrence]) is body


def test_inherited_look_falls_back_to_the_enclosing_occurrence():
    occurrence = _Look("occ")
    assert pc.inherited_look([None, occurrence]) is occurrence


def test_inherited_look_takes_the_nearest_of_several_ancestors():
    near, far = _Look("near"), _Look("far")
    assert pc.inherited_look([None, near, far]) is near


def test_inherited_look_is_none_when_nothing_is_set():
    assert pc.inherited_look([None, None, None]) is None
    assert pc.inherited_look([]) is None


def test_inherited_look_returns_a_falsy_look_rather_than_skipping_it():
    # THE TRAP: `if candidate:` instead of `is not None` would walk straight past
    # a real appearance and report the body as having no colour.
    falsy = _Look("set-but-falsy")
    assert bool(falsy) is False
    assert pc.inherited_look([falsy, _Look("outer")]) is falsy
