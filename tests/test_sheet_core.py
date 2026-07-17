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
