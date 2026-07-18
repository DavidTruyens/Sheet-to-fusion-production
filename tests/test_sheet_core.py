import io
import zipfile

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


def test_migrate_dedupes_colliding_ids():
    out = sheet_core.migrate_settings({"profiles": [
        {"id": "p2", "name": "A"},
        {"name": "B"},
    ]})
    ids = [p["id"] for p in out["profiles"]]
    assert len(ids) == len(set(ids))
    assert ids[0] == "p2"


def test_select_splits_present_and_missing_preserving_order():
    included, missing = sheet_core.select_component_names(
        ["Nis", "Gordijnplaat"], ["Gordijnplaat", "Ghost"])
    assert included == ["Gordijnplaat"]
    assert missing == ["Ghost"]


def test_select_empty_targets():
    assert sheet_core.select_component_names(["A"], []) == ([], [])


def test_summarize_built_and_skipped():
    text = sheet_core.summarize_results([
        {"name": "Full model", "built": 5, "warnings": [], "skipped": False},
        {"name": "Prod", "built": 0, "warnings": ["component(s) not found: X"],
         "skipped": True},
    ])
    assert "Full model" in text
    assert "5" in text
    assert "Skipped" in text
    assert "X" in text


def test_summarize_nothing_built():
    assert sheet_core.summarize_results([]) == "Nothing was built."


def test_extract_id_from_edit_url():
    url = "https://docs.google.com/spreadsheets/d/1x-p9znWXejdvPQ/edit#gid=5"
    assert sheet_core.extract_spreadsheet_id(url) == "1x-p9znWXejdvPQ"


def test_extract_id_from_share_url():
    url = "https://docs.google.com/spreadsheets/d/ABC_123-xyz/edit?usp=sharing"
    assert sheet_core.extract_spreadsheet_id(url) == "ABC_123-xyz"


def test_published_url_has_no_extractable_id():
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-abc/pubhtml"
    assert sheet_core.extract_spreadsheet_id(url) is None


def test_non_sheets_url_returns_none():
    assert sheet_core.extract_spreadsheet_id("https://example.com/foo") is None


def test_xlsx_export_url():
    assert sheet_core.xlsx_export_url("ABC") == (
        "https://docs.google.com/spreadsheets/d/ABC/export?format=xlsx")


def _col_letter(i):  # 0 -> A, 1 -> B, ...
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _build_xlsx(sheets):
    """Synthesise a Google-style .xlsx (shared strings for text, bare numbers
    for int/float, omitted cells for '') and return the bytes."""
    strings, index = [], {}

    def sid(text):
        if text not in index:
            index[text] = len(strings)
            strings.append(text)
        return index[text]

    sheet_xml = []
    for si, (_name, rows) in enumerate(sheets, start=1):
        body = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, val in enumerate(row):
                if val == "" or val is None:
                    continue
                ref = "{}{}".format(_col_letter(c), r)
                if isinstance(val, (int, float)):
                    cells.append('<c r="{}"><v>{}</v></c>'.format(ref, val))
                else:
                    cells.append('<c r="{}" t="s"><v>{}</v></c>'.format(ref, sid(str(val))))
            body.append('<row r="{}">{}</row>'.format(r, "".join(cells)))
        sheet_xml.append(
            '<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{b}</sheetData></worksheet>'
            .format(ns=sheet_core._MAIN_NS, b="".join(body)))

    sheets_tags = "".join(
        '<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>'.format(n=name, i=i)
        for i, (name, _rows) in enumerate(sheets, start=1))
    workbook = ('<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="{r}">'
                '<sheets>{s}</sheets></workbook>'
                ).format(ns=sheet_core._MAIN_NS, r=sheet_core._REL_NS, s=sheets_tags)
    rels = ['<Relationship Id="rIdSS" Type="{t}/sharedStrings" Target="sharedStrings.xml"/>'
            .format(t=sheet_core._REL_NS)]
    for i, (_name, _rows) in enumerate(sheets, start=1):
        rels.append('<Relationship Id="rId{i}" Type="{t}/worksheet" '
                    'Target="worksheets/sheet{i}.xml"/>'.format(i=i, t=sheet_core._REL_NS))
    workbook_rels = ('<?xml version="1.0"?><Relationships xmlns="{p}">{r}</Relationships>'
                     ).format(p=sheet_core._PKGREL_NS, r="".join(rels))
    sst_items = "".join("<si><t>{}</t></si>".format(s) for s in strings)
    sst = ('<?xml version="1.0"?><sst xmlns="{ns}" count="{c}" uniqueCount="{c}">{i}</sst>'
           ).format(ns=sheet_core._MAIN_NS, c=len(strings), i=sst_items)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/sharedStrings.xml", sst)
        for i, xml in enumerate(sheet_xml, start=1):
            z.writestr("xl/worksheets/sheet{}.xml".format(i), xml)
    return buf.getvalue()


def test_parse_workbook_tabs_in_order():
    xlsx = _build_xlsx([("rubber_variants", [["Name"]]),
                        ("helper", [["x"]]),
                        ("lookups", [["y"]])])
    assert sheet_core.parse_workbook_tabs(xlsx) == ["rubber_variants", "helper", "lookups"]


def test_read_tab_rows_preserves_text_and_gaps():
    xlsx = _build_xlsx([
        ("data", [
            ["Name", "diameter", "hoogte"],
            ["Variant_1", "18 mm", "5 mm"],
            ["Variant_2", "18,2", ""],      # comma text + trailing empty
            ["Variant_3", "", "5mm"],       # gap in the middle (col B omitted)
        ]),
    ])
    rows = sheet_core.read_tab_rows(xlsx, "data")
    assert rows[0] == ["Name", "diameter", "hoogte"]
    assert rows[1] == ["Variant_1", "18 mm", "5 mm"]
    assert rows[2] == ["Variant_2", "18,2", ""]
    assert rows[3] == ["Variant_3", "", "5mm"]


def test_read_tab_rows_normalizes_pure_numbers():
    xlsx = _build_xlsx([("data", [["Name", "diameter"], ["V1", 18.0]])])
    rows = sheet_core.read_tab_rows(xlsx, "data")
    assert rows[1] == ["V1", "18"]


def test_read_tab_rows_unknown_tab_raises():
    xlsx = _build_xlsx([("data", [["Name"]])])
    try:
        sheet_core.read_tab_rows(xlsx, "nope")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_normalize_number():
    assert sheet_core.normalize_number("18.0") == "18"
    assert sheet_core.normalize_number("18.50") == "18.5"
    assert sheet_core.normalize_number("18.2") == "18.2"
    assert sheet_core.normalize_number("abc") == "abc"


def test_classify_value():
    assert sheet_core.classify_value("18 mm") == "ok"
    assert sheet_core.classify_value("5mm") == "ok"
    assert sheet_core.classify_value("") == "empty"
    assert sheet_core.classify_value("18,2") == "comma_decimal"
    assert sheet_core.classify_value("18.2") == "unitless"
    assert sheet_core.classify_value("18") == "unitless"


def test_validate_column_not_a_parameter_is_error():
    header = ["Name", "diameter", "bogus"]
    rows = [["V1", "18 mm", "3 mm"]]
    rep = sheet_core.validate_mapping(header, rows, {"diameter", "hoogte"}, ["diameter", "hoogte"])
    assert not rep.ok
    assert any("bogus" in e for e in rep.errors)


def test_validate_uncovered_param_is_warning():
    header = ["Name", "diameter"]
    rows = [["V1", "18 mm"]]
    rep = sheet_core.validate_mapping(header, rows, {"diameter", "hoogte"}, ["diameter", "hoogte"])
    assert rep.ok  # warnings only
    assert any("hoogte" in w for w in rep.warnings)


def test_validate_comma_decimal_is_error_with_cell_ref():
    header = ["Name", "diameter"]
    rows = [["V1", "18 mm"], ["V2", "18,2"]]
    rep = sheet_core.validate_mapping(header, rows, {"diameter"}, ["diameter"])
    assert not rep.ok
    assert any("18,2" in e and "B3" in e for e in rep.errors)


def test_validate_missing_name_header_is_error():
    rep = sheet_core.validate_mapping(["Naam", "diameter"], [], {"diameter"}, ["diameter"])
    assert not rep.ok
    assert any("Name" in e for e in rep.errors)


def test_validate_clean_sheet_summary():
    header = ["Name", "diameter", "hoogte"]
    rows = [["V1", "18 mm", "5 mm"], ["V2", "20 mm", "6 mm"]]
    rep = sheet_core.validate_mapping(header, rows, {"diameter", "hoogte"}, ["diameter", "hoogte"])
    assert rep.ok
    assert "2 columns mapped" in rep.summary()
