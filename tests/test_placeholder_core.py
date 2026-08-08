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
