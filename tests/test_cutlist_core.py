import cutlist_core as cc


# --------------------------------------------------------------------------- #
# Units and formatting.
# --------------------------------------------------------------------------- #
def test_cm_to_mm_scales_fusion_internal_units():
    assert cc.cm_to_mm(1.8) == 18.0
    assert cc.cm_to_mm(0) == 0.0


def test_format_mm_always_shows_two_decimals():
    assert cc.format_mm(600) == "600.00"
    assert cc.format_mm(17.9999999) == "18.00"


def test_format_mm_never_emits_negative_zero():
    assert cc.format_mm(-0.0) == "0.00"
    assert cc.format_mm(-0.001) == "0.00"


# --------------------------------------------------------------------------- #
# Blank dimensions: sort longest -> shortest, offset the two larger sides only.
# --------------------------------------------------------------------------- #
def test_blank_dims_sorts_longest_middle_shortest():
    assert cc.blank_dims(18.0, 600.0, 720.0, 0.0) == (720.0, 600.0, 18.0)


def test_blank_dims_adds_offset_to_both_sides_of_x_and_y():
    assert cc.blank_dims(600.0, 720.0, 18.0, 10.0) == (740.0, 620.0, 18.0)


def test_blank_dims_leaves_thickness_untouched():
    """Z is the stock thickness you filter on, so it never grows."""
    _, _, z = cc.blank_dims(600.0, 400.0, 18.0, 25.0)
    assert z == 18.0


def test_blank_dims_offsets_before_a_cube_could_reorder():
    """Offsetting must not let the third dimension overtake the second."""
    x, y, z = cc.blank_dims(20.0, 20.0, 20.0, 5.0)
    assert (x, y, z) == (30.0, 30.0, 20.0)


# --------------------------------------------------------------------------- #
# Combining the per-body boxes of one part.
# --------------------------------------------------------------------------- #
def test_union_extents_of_a_single_box_is_that_box():
    assert cc.union_extents([(0.0, 60.0, 0.0, 40.0, 0.0, 1.8)]) == (60.0, 40.0, 1.8)


def test_union_extents_spans_bodies_that_sit_apart():
    """Two 10-wide bodies 30 apart span 40, not 20."""
    boxes = [(0.0, 10.0, 0.0, 10.0, 0.0, 2.0),
             (30.0, 10.0, 0.0, 10.0, 0.0, 2.0)]
    assert cc.union_extents(boxes) == (40.0, 10.0, 2.0)


def test_union_extents_spans_bodies_stacked_in_z():
    """Parts at different heights is the case that started all this."""
    boxes = [(0.0, 10.0, 0.0, 10.0, 0.0, 2.0),
             (0.0, 10.0, 0.0, 10.0, 5.0, 2.0)]
    assert cc.union_extents(boxes) == (10.0, 10.0, 7.0)


def test_union_extents_of_nothing_is_none():
    assert cc.union_extents([]) is None


# --------------------------------------------------------------------------- #
# Tilt detection: the blank follows the design's axes, so a part that is
# neither flat nor upright gets an oversized one and has to be reported.
# --------------------------------------------------------------------------- #
def test_a_face_lying_flat_is_not_tilted():
    assert cc.is_tilted(1.0) is False
    assert cc.is_tilted(-1.0) is False


def test_an_upright_face_is_not_tilted():
    assert cc.is_tilted(0.0) is False


def test_a_face_on_a_slope_is_tilted():
    assert cc.is_tilted(0.5) is True


def test_tilt_tolerance_forgives_modelling_noise():
    assert cc.is_tilted(0.999999) is False


# --------------------------------------------------------------------------- #
# Grouping identical blanks, and the CSV those rows become.
# --------------------------------------------------------------------------- #
def test_group_parts_collapses_identical_blanks_and_counts_them():
    rows = cc.group_parts([("side A", 600.0, 400.0, 18.0),
                           ("side B", 600.0, 400.0, 18.0)])
    assert len(rows) == 1
    assert rows[0] == ("side A; side B", "600.00", "400.00", "18.00", 2)


def test_group_parts_keeps_different_sizes_apart():
    rows = cc.group_parts([("shelf", 600.0, 400.0, 18.0),
                           ("door", 600.0, 400.0, 22.0)])
    assert len(rows) == 2


def test_group_parts_groups_on_the_rounded_values():
    """Two identical parts can measure a hair apart; they are still one blank."""
    rows = cc.group_parts([("a", 600.0001, 400.0, 18.0),
                           ("b", 599.9998, 400.0, 18.0)])
    assert len(rows) == 1
    assert rows[0][4] == 2


def test_group_parts_sorts_longest_first():
    rows = cc.group_parts([("small", 100.0, 50.0, 18.0),
                           ("big", 900.0, 50.0, 18.0)])
    assert [r[0] for r in rows] == ["big", "small"]


def test_group_parts_breaks_a_length_tie_on_width_then_thickness():
    rows = cc.group_parts([("narrow", 600.0, 100.0, 18.0),
                           ("wide", 600.0, 400.0, 18.0),
                           ("thick", 600.0, 400.0, 22.0)])
    assert [r[0] for r in rows] == ["thick", "wide", "narrow"]


def test_group_parts_names_a_repeated_name_once():
    """Four instances of one component read better than the name four times."""
    rows = cc.group_parts([("leg", 700.0, 40.0, 40.0)] * 4)
    assert rows[0][0] == "leg"
    assert rows[0][4] == 4


def test_group_parts_of_nothing_is_empty():
    assert cc.group_parts([]) == []


def test_csv_rows_start_with_the_header():
    assert cc.csv_rows([])[0] == ["Name", "X", "Y", "Z", "Qty"]


def test_csv_rows_render_every_field_as_text():
    rows = cc.csv_rows([("shelf", 600.0, 400.0, 18.0)])
    assert rows[1] == ["shelf", "600.00", "400.00", "18.00", "1"]
