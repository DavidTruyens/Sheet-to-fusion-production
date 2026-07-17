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
