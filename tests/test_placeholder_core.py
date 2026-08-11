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


# --- anchor_target: what point of the box the mother's anchor lands on --------

def _frame_and_box():
    """A -Y-facing frame and a 60 x 58 x 72 box centred at (10, 20, 36)."""
    frame = pc.target_frame((0.0, -1.0, 0.0))   # w=+X, d=+Y, u=+Z
    return frame, (10.0, 20.0, 36.0), (60.0, 58.0, 72.0)


def test_anchor_target_centre_is_the_box_centre():
    frame, centre, dims = _frame_and_box()
    assert _close(pc.anchor_target(centre, frame, dims, pc.ANCHOR_CENTRE), centre)


def test_anchor_target_front_centre_moves_against_the_depth_axis():
    frame, centre, dims = _frame_and_box()
    got = pc.anchor_target(centre, frame, dims, pc.ANCHOR_FRONT_CENTRE)
    # depth axis is +Y, so the FRONT of the box is at the -Y end: 20 - 58/2.
    assert _close(got, (10.0, 20.0 - 29.0, 36.0))


def test_anchor_target_bottom_centre_moves_down_by_half_the_height():
    frame, centre, dims = _frame_and_box()
    got = pc.anchor_target(centre, frame, dims, pc.ANCHOR_BOTTOM_CENTRE)
    assert _close(got, (10.0, 20.0, 36.0 - 36.0))


def test_anchor_target_bottom_front_centre_moves_on_both_axes():
    frame, centre, dims = _frame_and_box()
    got = pc.anchor_target(centre, frame, dims, pc.ANCHOR_BOTTOM_FRONT_CENTRE)
    assert _close(got, (10.0, 20.0 - 29.0, 36.0 - 36.0))


def test_anchor_target_follows_a_rotated_frame():
    # Front face pointing +X, so depth runs -X and the box's front is at +X.
    frame = pc.target_frame((1.0, 0.0, 0.0))
    got = pc.anchor_target((0.0, 0.0, 0.0), frame, (60.0, 58.0, 72.0),
                           pc.ANCHOR_FRONT_CENTRE)
    assert _close(got, (29.0, 0.0, 0.0))


def test_anchor_target_unknown_choice_falls_back_to_centre():
    frame, centre, dims = _frame_and_box()
    assert _close(pc.anchor_target(centre, frame, dims, "nonsense"), centre)


def test_mother_setup_defaults_anchor_at_to_centre():
    assert pc.migrate_mother_setup({})["anchorAt"] == pc.ANCHOR_CENTRE


def test_mother_setup_keeps_a_known_anchor_at():
    s = pc.migrate_mother_setup({"anchorAt": pc.ANCHOR_BOTTOM_FRONT_CENTRE})
    assert s["anchorAt"] == pc.ANCHOR_BOTTOM_FRONT_CENTRE


def test_mother_setup_rejects_an_unknown_anchor_at():
    assert pc.migrate_mother_setup({"anchorAt": "sideways"})["anchorAt"] == pc.ANCHOR_CENTRE
