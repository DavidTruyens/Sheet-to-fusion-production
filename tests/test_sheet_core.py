import pytest
import sheet_core


def test_already_csv_is_returned_as_is():
    url = "https://docs.google.com/spreadsheets/d/e/ABC/pub?output=csv"
    assert sheet_core.csv_url_candidates(url) == [url]


def test_published_url_gets_output_csv():
    url = "https://docs.google.com/spreadsheets/d/e/ABC/pub"
    assert sheet_core.csv_url_candidates(url) == [url + "?output=csv"]


def test_edit_url_first_tab_no_gid():
    url = "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=0"
    assert sheet_core.csv_url_candidates(url) == [
        "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv"
    ]


def test_edit_url_non_first_tab_tries_gid_then_default():
    url = "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=42"
    base = "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv"
    assert sheet_core.csv_url_candidates(url) == [base + "&gid=42", base]


def test_parses_rows_and_skips_blank_rows():
    raw = "Name,length\r\nA,10 mm\r\n,\r\nB,20 mm\r\n"
    assert sheet_core.parse_sheet_csv(raw) == [
        ["Name", "length"], ["A", "10 mm"], ["B", "20 mm"]
    ]


def test_html_page_raises():
    with pytest.raises(RuntimeError):
        sheet_core.parse_sheet_csv("<!DOCTYPE html><html><body>Sign in</body></html>")


def test_too_few_rows_raises():
    with pytest.raises(RuntimeError):
        sheet_core.parse_sheet_csv("Name,length\r\n")


def test_unquote_strips_single_quotes():
    assert sheet_core.unquote_text("'A-6'") == "A-6"


def test_unquote_leaves_numeric_untouched():
    assert sheet_core.unquote_text("50 mm") == "50 mm"


def test_unquote_handles_none():
    assert sheet_core.unquote_text(None) is None


def test_missing_profiles_gets_default():
    out = sheet_core.migrate_settings({"sheet_url": "x"})
    assert len(out["profiles"]) == 1
    assert out["profiles"][0]["rule"] == "whole_model"
    assert out["profiles"][0]["enabled"] is True
    assert out["profiles"][0]["components"] == []


def test_empty_profiles_list_gets_default():
    out = sheet_core.migrate_settings({"profiles": []})
    assert len(out["profiles"]) == 1


def test_profile_fields_are_normalized():
    out = sheet_core.migrate_settings({"profiles": [
        {"name": "P", "rule": "bogus", "components": ["A", "", "B"]},
    ]})
    p = out["profiles"][0]
    assert p["rule"] == "whole_model"      # unknown rule falls back
    assert p["components"] == ["A", "B"]    # blanks dropped
    assert "id" in p
    assert p["enabled"] is True            # defaults to enabled


def test_named_rule_preserved():
    out = sheet_core.migrate_settings({"profiles": [
        {"name": "P", "rule": "named_components", "components": ["Gordijnplaat"]},
    ]})
    assert out["profiles"][0]["rule"] == "named_components"


def test_load_missing_file_returns_defaults():
    data = sheet_core.load_settings("/no/such/file.json")
    assert len(data["profiles"]) == 1


def test_save_then_load_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    sheet_core.save_settings(path, {"sheet_url": "u", "spacing_mm": 100.0,
                                    "profiles": sheet_core.default_profiles()})
    data = sheet_core.load_settings(path)
    assert data["sheet_url"] == "u"
    assert data["spacing_mm"] == 100.0
    assert len(data["profiles"]) == 1


def test_next_profile_id_first():
    assert sheet_core.next_profile_id([]) == "p1"


def test_next_profile_id_skips_used():
    assert sheet_core.next_profile_id(["p1", "p2"]) == "p3"


def test_next_profile_id_fills_gap():
    assert sheet_core.next_profile_id(["p1", "p3"]) == "p2"
