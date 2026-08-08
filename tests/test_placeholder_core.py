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
