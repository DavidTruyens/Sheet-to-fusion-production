# Better Google Sheet Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the add-in list a Google Sheet's tabs, pin the correct data tab, validate that every parameter is mapped, and test a single variant against the live model.

**Architecture:** Split all Fusion-free logic into a new `SheetVariants/sheet_source.py` (URL parsing, XLSX/CSV reading, validation) so it can be unit-tested with `pytest` on CI. The `adsk`-coupled UI in `SheetVariants/SheetVariants.py` imports it, adds a tab dropdown + inline validation report to the Build command, and adds a new **Test Variant Row** command.

**Tech Stack:** Python 3.11 (Fusion bundled), stdlib only (`urllib`, `zipfile`, `xml.etree.ElementTree`, `csv`, `re`, `json`); `pytest` for CI tests. Autodesk Fusion API (`adsk.core`, `adsk.fusion`).

## Global Constraints

- **stdlib only** in the add-in — no Google API key, no pip packages at runtime. `pytest` is a CI-only dev dependency.
- **`sheet_source.py` MUST NOT import `adsk`** (so CI can import it). All model access stays in `SheetVariants.py`.
- **Fusion Personal licence must keep working** — no file export; geometry stays copied in-memory (unchanged build path).
- **Commits are gated.** Do NOT run `git commit` automatically. Each "Commit" step is a checkpoint: pause and ask the user for explicit approval first (project rule: "only commit if I ask").
- **No unverified success claims.** Never state that a Fusion-side behaviour "works" until the user has confirmed it in Fusion. Automated `pytest` results may be reported as passing when they actually pass.
- **Backward compatibility:** published-to-web (`/d/e/<id>/pub`) and direct-CSV links must still build as they do today (single tab, no picker).

---

## File Structure

- **Create `SheetVariants/sheet_source.py`** — pure logic: `extract_spreadsheet_id`, `xlsx_export_url`, `fetch_bytes`, `parse_workbook_tabs`, `read_tab_rows`, `csv_url_candidates`, `parse_csv_bytes`, `normalize_number`, `classify_value`, `validate_mapping`, `ValidationReport`.
- **Modify `SheetVariants/SheetVariants.py`** — import `sheet_source`; add per-sheet pin + test-snapshot settings helpers; add tab dropdown + Load-tabs button + validation textbox + OK gating to the Build command; add the **Test Variant Row** command and register its panel button.
- **Create `tests/test_sheet_source.py`** — pytest suite; includes a `_build_xlsx()` helper that synthesises Google-style XLSX bytes in-memory (no binary fixtures committed).
- **Modify `.github/workflows/ci.yml`** — add a `pytest` step.
- **Modify `README.md`** — document tab selection, validation, and Test Variant Row.

---

## Task 1: `sheet_source` — spreadsheet-id & export URL

**Files:**
- Create: `SheetVariants/sheet_source.py`
- Test: `tests/test_sheet_source.py`

**Interfaces:**
- Produces:
  - `extract_spreadsheet_id(url: str) -> str | None` — the `/d/<id>/` id, or `None` for published `/d/e/<id>/pub` and non-Sheets URLs.
  - `xlsx_export_url(spreadsheet_id: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sheet_source.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "SheetVariants"))
import sheet_source as ss


def test_extract_id_from_edit_url():
    url = "https://docs.google.com/spreadsheets/d/1x-p9znWXejdvPQ/edit#gid=5"
    assert ss.extract_spreadsheet_id(url) == "1x-p9znWXejdvPQ"


def test_extract_id_from_share_url():
    url = "https://docs.google.com/spreadsheets/d/ABC_123-xyz/edit?usp=sharing"
    assert ss.extract_spreadsheet_id(url) == "ABC_123-xyz"


def test_published_url_has_no_extractable_id():
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-abc/pubhtml"
    assert ss.extract_spreadsheet_id(url) is None


def test_non_sheets_url_returns_none():
    assert ss.extract_spreadsheet_id("https://example.com/foo") is None


def test_xlsx_export_url():
    assert ss.xlsx_export_url("ABC") == (
        "https://docs.google.com/spreadsheets/d/ABC/export?format=xlsx")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sheet_source.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheet_source'`.

- [ ] **Step 3: Write minimal implementation**

```python
# SheetVariants/sheet_source.py
"""Fusion-free helpers for reading and validating Google Sheet variant tables.

This module MUST NOT import adsk: it is unit-tested on CI where adsk is absent.
"""
import io
import csv
import re
import zipfile
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKGREL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def extract_spreadsheet_id(url):
    """Return the /d/<id>/ spreadsheet id, or None for published /d/e/ links
    and anything that is not a standard Sheets URL."""
    url = (url or "").strip()
    if re.search(r"/spreadsheets/d/e/", url):
        return None  # published-to-web: different id space, no xlsx export
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else None


def xlsx_export_url(spreadsheet_id):
    return ("https://docs.google.com/spreadsheets/d/{}/export?format=xlsx"
            .format(spreadsheet_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sheet_source.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/sheet_source.py tests/test_sheet_source.py
git commit -m "feat(sheet): url id extraction + xlsx export url"
```

---

## Task 2: `sheet_source` — XLSX tab enumeration

**Files:**
- Modify: `SheetVariants/sheet_source.py`
- Test: `tests/test_sheet_source.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `parse_workbook_tabs(xlsx_bytes: bytes) -> list[str]` — tab names in workbook order.
  - Test helper `_build_xlsx(sheets)` where `sheets` is a list of `(name, rows)` and `rows` is a list of lists of cell values (str or int/float). Empty-string cells are omitted from the XML to exercise gap handling.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_sheet_source.py
import zipfile, io


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
            .format(ns=_MAIN_NS, b="".join(body)))

    sheets_tags = "".join(
        '<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>'.format(n=name, i=i)
        for i, (name, _rows) in enumerate(sheets, start=1))
    workbook = ('<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="{r}">'
                '<sheets>{s}</sheets></workbook>'
                ).format(ns=_MAIN_NS, r=_REL_NS, s=sheets_tags)
    rels = ['<Relationship Id="rIdSS" Type="{t}/sharedStrings" Target="sharedStrings.xml"/>'
            .format(t=_REL_NS)]
    for i, (_name, _rows) in enumerate(sheets, start=1):
        rels.append('<Relationship Id="rId{i}" Type="{t}/worksheet" '
                    'Target="worksheets/sheet{i}.xml"/>'.format(i=i, t=_REL_NS))
    workbook_rels = ('<?xml version="1.0"?><Relationships xmlns="{p}">{r}</Relationships>'
                     ).format(p=_PKGREL_NS, r="".join(rels))
    sst_items = "".join("<si><t>{}</t></si>".format(s) for s in strings)
    sst = ('<?xml version="1.0"?><sst xmlns="{ns}" count="{c}" uniqueCount="{c}">{i}</sst>'
           ).format(ns=_MAIN_NS, c=len(strings), i=sst_items)

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
    assert ss.parse_workbook_tabs(xlsx) == ["rubber_variants", "helper", "lookups"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sheet_source.py::test_parse_workbook_tabs_in_order -q`
Expected: FAIL — `AttributeError: module 'sheet_source' has no attribute 'parse_workbook_tabs'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to SheetVariants/sheet_source.py
def parse_workbook_tabs(xlsx_bytes):
    """Return worksheet (tab) names in workbook order."""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = []
    for sheet in wb.findall(".//{%s}sheet" % _MAIN_NS):
        name = sheet.get("name")
        if name:
            names.append(name)
    return names
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sheet_source.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/sheet_source.py tests/test_sheet_source.py
git commit -m "feat(sheet): enumerate xlsx tabs"
```

---

## Task 3: `sheet_source` — read a tab's rows

**Files:**
- Modify: `SheetVariants/sheet_source.py`
- Test: `tests/test_sheet_source.py`

**Interfaces:**
- Consumes: `parse_workbook_tabs`, `_build_xlsx` (test helper).
- Produces:
  - `normalize_number(text: str) -> str` — `"18.0" -> "18"`, `"18.5" -> "18.5"`, non-numbers unchanged.
  - `read_tab_rows(xlsx_bytes: bytes, tab_name: str) -> list[list[str]]` — rows of the named tab as strings, cells positioned by column (A=0), gaps filled with `""`, fully-empty rows dropped. Raises `RuntimeError` if the tab is not found.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_sheet_source.py
def test_read_tab_rows_preserves_text_and_gaps():
    xlsx = _build_xlsx([
        ("data", [
            ["Name", "diameter", "hoogte"],
            ["Variant_1", "18 mm", "5 mm"],
            ["Variant_2", "18,2", ""],      # comma text + trailing empty
            ["Variant_3", "", "5mm"],       # gap in the middle (col B omitted)
        ]),
    ])
    rows = ss.read_tab_rows(xlsx, "data")
    assert rows[0] == ["Name", "diameter", "hoogte"]
    assert rows[1] == ["Variant_1", "18 mm", "5 mm"]
    assert rows[2] == ["Variant_2", "18,2", ""]
    assert rows[3] == ["Variant_3", "", "5mm"]


def test_read_tab_rows_normalizes_pure_numbers():
    xlsx = _build_xlsx([("data", [["Name", "diameter"], ["V1", 18.0]])])
    rows = ss.read_tab_rows(xlsx, "data")
    assert rows[1] == ["V1", "18"]


def test_read_tab_rows_unknown_tab_raises():
    xlsx = _build_xlsx([("data", [["Name"]])])
    try:
        ss.read_tab_rows(xlsx, "nope")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_normalize_number():
    assert ss.normalize_number("18.0") == "18"
    assert ss.normalize_number("18.50") == "18.5"
    assert ss.normalize_number("18.2") == "18.2"
    assert ss.normalize_number("abc") == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sheet_source.py::test_read_tab_rows_preserves_text_and_gaps -q`
Expected: FAIL — `AttributeError: module 'sheet_source' has no attribute 'read_tab_rows'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to SheetVariants/sheet_source.py
def normalize_number(text):
    """Render a spreadsheet number without a spurious trailing zero/dot.
    Leaves non-numeric text untouched."""
    try:
        f = float(text)
    except (TypeError, ValueError):
        return text
    if f == int(f):
        return str(int(f))
    return repr(f).rstrip("0").rstrip(".") if "." in str(f) else str(f)


def _col_index(cell_ref):
    """'A1' -> 0, 'B2' -> 1, 'AA3' -> 26."""
    letters = re.match(r"[A-Z]+", cell_ref or "")
    if not letters:
        return 0
    idx = 0
    for ch in letters.group(0):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _shared_strings(z):
    try:
        sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in sst.findall("{%s}si" % _MAIN_NS):
        out.append("".join(t.text or "" for t in si.iter("{%s}t" % _MAIN_NS)))
    return out


def _worksheet_path_for(z, tab_name):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rid = None
    for sheet in wb.findall(".//{%s}sheet" % _MAIN_NS):
        if sheet.get("name") == tab_name:
            rid = sheet.get("{%s}id" % _REL_NS)
            break
    if rid is None:
        raise RuntimeError('Tab "{}" was not found in the sheet.'.format(tab_name))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("{%s}Relationship" % _PKGREL_NS):
        if rel.get("Id") == rid:
            target = rel.get("Target")
            return target if target.startswith("xl/") else "xl/" + target
    raise RuntimeError('Could not locate data for tab "{}".'.format(tab_name))


def read_tab_rows(xlsx_bytes, tab_name):
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
        strings = _shared_strings(z)
        path = _worksheet_path_for(z, tab_name)
        sheet = ET.fromstring(z.read(path))

    rows = []
    for row_el in sheet.findall(".//{%s}row" % _MAIN_NS):
        cells = {}
        maxcol = -1
        for c in row_el.findall("{%s}c" % _MAIN_NS):
            j = _col_index(c.get("r", ""))
            t = c.get("t")
            if t == "inlineStr":
                is_el = c.find("{%s}is" % _MAIN_NS)
                val = "".join(x.text or "" for x in is_el.iter("{%s}t" % _MAIN_NS)) if is_el is not None else ""
            else:
                v = c.find("{%s}v" % _MAIN_NS)
                raw = v.text if v is not None else ""
                if t == "s":
                    val = strings[int(raw)] if raw != "" else ""
                elif t in (None, "n"):
                    val = normalize_number(raw)
                else:  # 'str' (formula), 'b', etc.
                    val = raw or ""
            cells[j] = val
            if j > maxcol:
                maxcol = j
        row = [cells.get(j, "") for j in range(maxcol + 1)]
        if any(v.strip() for v in row):
            rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sheet_source.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/sheet_source.py tests/test_sheet_source.py
git commit -m "feat(sheet): read a named tab's rows from xlsx"
```

---

## Task 4: `sheet_source` — network fetch + CSV fallback (move existing logic)

**Files:**
- Modify: `SheetVariants/sheet_source.py`
- Test: `tests/test_sheet_source.py`

**Interfaces:**
- Produces:
  - `fetch_bytes(url: str, opener=urllib.request.urlopen) -> bytes` — GET with a browser UA; raises `RuntimeError` (with `SHARING_HELP`) on HTTP/URL errors. `opener` is injectable for tests.
  - `csv_url_candidates(url: str) -> list[str]` — moved verbatim from `SheetVariants.py`.
  - `parse_csv_bytes(raw: bytes) -> list[list[str]]` — decode utf-8-sig, reject HTML, return non-empty rows.
  - `SHARING_HELP` (moved constant).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_sheet_source.py
def test_parse_csv_bytes_strips_empty_rows():
    raw = b"Name,diameter\r\nV1,18 mm\r\n,\r\nV2,20 mm\r\n"
    rows = ss.parse_csv_bytes(raw)
    assert rows == [["Name", "diameter"], ["V1", "18 mm"], ["V2", "20 mm"]]


def test_parse_csv_bytes_rejects_html():
    try:
        ss.parse_csv_bytes(b"<!DOCTYPE html><html>login</html>")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_fetch_bytes_uses_injected_opener():
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"hello"

    def fake_opener(req, timeout=0):
        return FakeResp()

    assert ss.fetch_bytes("http://x", opener=fake_opener) == b"hello"


def test_csv_url_candidates_specific_gid():
    url = "https://docs.google.com/spreadsheets/d/ABC/edit#gid=42"
    cands = ss.csv_url_candidates(url)
    assert cands[0].endswith("export?format=csv&gid=42")
    assert cands[1].endswith("export?format=csv")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sheet_source.py -q`
Expected: FAIL — attributes `parse_csv_bytes` / `fetch_bytes` / `csv_url_candidates` missing.

- [ ] **Step 3: Write minimal implementation**

Move `SHARING_HELP` and `csv_url_candidates` out of `SheetVariants.py` into `sheet_source.py` unchanged, then add:

```python
# add to SheetVariants/sheet_source.py
SHARING_HELP = (
    'Make sure the sheet is shared so anyone with the link can read it: in Google '
    'Sheets, Share > General access > "Anyone with the link" > Viewer. '
    '(Or publish it: File > Share > Publish to web.) Then paste that link here.')


def fetch_bytes(url, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (FusionAddin)"})
    try:
        with opener(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("Could not download the sheet (HTTP {} {}).\n\n{}"
                           .format(e.code, e.reason, SHARING_HELP))
    except urllib.error.URLError as e:
        raise RuntimeError("Could not download the sheet ({}).\n\n{}"
                           .format(e.reason, SHARING_HELP))


def parse_csv_bytes(raw):
    text = raw.decode("utf-8-sig", errors="replace")
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype html") or "<html" in head:
        raise RuntimeError(
            "That URL returned a web page instead of CSV, which usually means the "
            "sheet is not readable without signing in.\n\n" + SHARING_HELP)
    return [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
```

(`csv_url_candidates` is the existing function, pasted verbatim.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sheet_source.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/sheet_source.py tests/test_sheet_source.py
git commit -m "refactor(sheet): move fetch + csv parsing into sheet_source"
```

---

## Task 5: `sheet_source` — validation

**Files:**
- Modify: `SheetVariants/sheet_source.py`
- Test: `tests/test_sheet_source.py`

**Interfaces:**
- Produces:
  - `classify_value(text: str) -> str` — one of `"ok"`, `"empty"`, `"comma_decimal"`, `"unitless"`.
  - `class ValidationReport` with attributes `errors: list[str]`, `warnings: list[str]`, property `ok -> bool` (True when no errors), `summary() -> str`, `to_html() -> str`.
  - `validate_mapping(header, rows, known_param_names, driveable_param_names) -> ValidationReport`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_sheet_source.py
def test_classify_value():
    assert ss.classify_value("18 mm") == "ok"
    assert ss.classify_value("5mm") == "ok"
    assert ss.classify_value("") == "empty"
    assert ss.classify_value("18,2") == "comma_decimal"
    assert ss.classify_value("18.2") == "unitless"
    assert ss.classify_value("18") == "unitless"


def test_validate_column_not_a_parameter_is_error():
    header = ["Name", "diameter", "bogus"]
    rows = [["V1", "18 mm", "3 mm"]]
    rep = ss.validate_mapping(header, rows, {"diameter", "hoogte"}, ["diameter", "hoogte"])
    assert not rep.ok
    assert any("bogus" in e for e in rep.errors)


def test_validate_uncovered_param_is_warning():
    header = ["Name", "diameter"]
    rows = [["V1", "18 mm"]]
    rep = ss.validate_mapping(header, rows, {"diameter", "hoogte"}, ["diameter", "hoogte"])
    assert rep.ok  # warnings only
    assert any("hoogte" in w for w in rep.warnings)


def test_validate_comma_decimal_is_error_with_cell_ref():
    header = ["Name", "diameter"]
    rows = [["V1", "18 mm"], ["V2", "18,2"]]
    rep = ss.validate_mapping(header, rows, {"diameter"}, ["diameter"])
    assert not rep.ok
    assert any("18,2" in e and "B3" in e for e in rep.errors)


def test_validate_missing_name_header_is_error():
    rep = ss.validate_mapping(["Naam", "diameter"], [], {"diameter"}, ["diameter"])
    assert not rep.ok
    assert any("Name" in e for e in rep.errors)


def test_validate_clean_sheet_summary():
    header = ["Name", "diameter", "hoogte"]
    rows = [["V1", "18 mm", "5 mm"], ["V2", "20 mm", "6 mm"]]
    rep = ss.validate_mapping(header, rows, {"diameter", "hoogte"}, ["diameter", "hoogte"])
    assert rep.ok
    assert "2 columns mapped" in rep.summary()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sheet_source.py -q`
Expected: FAIL — `classify_value` / `validate_mapping` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# add to SheetVariants/sheet_source.py
_COMMA_DECIMAL = re.compile(r"^\s*[+-]?\d+,\d+\s*$")
_UNITLESS = re.compile(r"^\s*[+-]?\d+(\.\d+)?\s*$")


def classify_value(text):
    s = (text or "").strip()
    if s == "":
        return "empty"
    if _COMMA_DECIMAL.match(s):
        return "comma_decimal"
    if _UNITLESS.match(s):
        return "unitless"
    return "ok"


def _cell_ref(col_index, row_number):
    letters = ""
    n = col_index + 1
    while n:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return "{}{}".format(letters, row_number)


class ValidationReport:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.mapped_columns = 0
        self.row_count = 0

    @property
    def ok(self):
        return not self.errors

    def summary(self):
        if self.ok and not self.warnings:
            return "✓ {} columns mapped, {} rows OK".format(
                self.mapped_columns, self.row_count)
        if self.ok:
            return "✓ {} columns mapped, {} rows — {} warning(s)".format(
                self.mapped_columns, self.row_count, len(self.warnings))
        return "✗ {} error(s), {} warning(s) — fix before building".format(
            len(self.errors), len(self.warnings))

    def to_html(self):
        lines = ["<b>{}</b>".format(self.summary())]
        for e in self.errors:
            lines.append('<font color="#c0392b">✗ {}</font>'.format(e))
        for w in self.warnings:
            lines.append('<font color="#b9770e">⚠ {}</font>'.format(w))
        return "<br/>".join(lines)


def validate_mapping(header, rows, known_param_names, driveable_param_names):
    rep = ValidationReport()
    rep.row_count = len(rows)
    header = [h.strip() for h in header]

    if not header or header[0] != "Name":
        rep.errors.append('The first column header must be "Name".')
        return rep

    columns = header[1:]
    known = set(known_param_names)
    for name in columns:
        if name in known:
            rep.mapped_columns += 1
        else:
            rep.errors.append('Column "{}" matches no parameter in the model.'.format(name))

    covered = set(columns)
    for pname in driveable_param_names:
        if pname not in covered:
            rep.warnings.append('Parameter "{}" has no column — keeps its current value.'.format(pname))

    empty_count = 0
    for ri, row in enumerate(rows, start=2):  # row 2 = first data row in the sheet
        for ci, name in enumerate(columns, start=1):
            if name not in known:
                continue
            val = row[ci] if ci < len(row) else ""
            kind = classify_value(val)
            if kind == "comma_decimal":
                rep.errors.append(
                    'Cell {} ("{}") looks like a comma decimal — use a dot and a unit, e.g. "18.2 mm".'
                    .format(_cell_ref(ci, ri), val.strip()))
            elif kind == "empty":
                empty_count += 1
    if empty_count:
        rep.warnings.append("{} empty cell(s) left unchanged.".format(empty_count))
    return rep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sheet_source.py -q`
Expected: PASS (all tests to date).

- [ ] **Step 5: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/sheet_source.py tests/test_sheet_source.py
git commit -m "feat(sheet): mapping + value validation report"
```

---

## Task 6: CI runs pytest

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:** none (build infra).

- [ ] **Step 1: Add the pytest step**

Append after the pyflakes step in the `check` job:

```yaml
      - name: Unit tests
        run: |
          python -m pip install --upgrade pytest
          python -m pytest tests/ -q
```

- [ ] **Step 2: Verify locally**

Run: `python -m pytest tests/ -q`
Expected: PASS (same suite CI will run).

- [ ] **Step 3: Verify the add-in still byte-compiles and lints**

Run:
```bash
python -m py_compile SheetVariants/SheetVariants.py SheetVariants/sheet_source.py
python -m pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_source.py
```
Expected: no output (clean).

- [ ] **Step 4: Commit** *(gated — ask the user first)*

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest suite"
```

---

## Task 7: Wire `sheet_source` into the add-in + settings helpers

**Files:**
- Modify: `SheetVariants/SheetVariants.py`

**Interfaces:**
- Consumes: everything from `sheet_source`.
- Produces (module-level helpers in `SheetVariants.py`):
  - `get_rows(url, tab_name=None) -> list[list[str]]` — unified reader: if `extract_spreadsheet_id(url)` and `tab_name`, fetch xlsx once (cached), `read_tab_rows`; else CSV fallback via `csv_url_candidates`/`fetch_bytes`/`parse_csv_bytes`. Raises `RuntimeError` if `< 2` rows.
  - `list_tabs(url) -> list[str]` — xlsx tabs, or `[]` when no spreadsheet id.
  - `load_pinned_tab(spreadsheet_id) -> str`, `save_pinned_tab(spreadsheet_id, tab)`.
  - `driveable_param_names(design) -> list[str]` and `known_param_names(design) -> list[str]`.
  - In-memory cache: `_xlsx_cache = {"url": None, "bytes": None}`.

- [ ] **Step 1: Replace the old fetch/CSV internals with `sheet_source`**

At the top of `SheetVariants.py`, after the existing imports:

```python
import sys
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sheet_source
```

Delete the now-moved `SHARING_HELP`, `csv_url_candidates`, and `fetch_rows` from `SheetVariants.py`. Add:

```python
_xlsx_cache = {"url": None, "bytes": None}


def _xlsx_bytes_for(url):
    if _xlsx_cache["url"] != url or _xlsx_cache["bytes"] is None:
        sid = sheet_source.extract_spreadsheet_id(url)
        _xlsx_cache["bytes"] = sheet_source.fetch_bytes(sheet_source.xlsx_export_url(sid))
        _xlsx_cache["url"] = url
    return _xlsx_cache["bytes"]


def list_tabs(url):
    if not sheet_source.extract_spreadsheet_id(url):
        return []
    return sheet_source.parse_workbook_tabs(_xlsx_bytes_for(url))


def get_rows(url, tab_name=None):
    sid = sheet_source.extract_spreadsheet_id(url)
    if sid and tab_name:
        rows = sheet_source.read_tab_rows(_xlsx_bytes_for(url), tab_name)
    else:
        raw, last_err = None, None
        for cand in sheet_source.csv_url_candidates(url):
            try:
                raw = sheet_source.fetch_bytes(cand)
                break
            except RuntimeError as e:
                last_err = e
        if raw is None:
            raise last_err or RuntimeError("Could not download the sheet.")
        rows = sheet_source.parse_csv_bytes(raw)
    if len(rows) < 2:
        raise RuntimeError("The sheet needs a header row plus at least one variant row.")
    return rows


def known_param_names(design):
    return [p.name for p in design.allParameters]


def driveable_param_names(design):
    favs = [p.name for p in design.allParameters if getattr(p, "isFavorite", False)]
    if favs:
        return favs
    return [p.name for p in design.userParameters]
```

Add the settings helpers (near `load_setting`/`save_setting`):

```python
def load_pinned_tab(spreadsheet_id):
    return load_setting("pinned_tabs", {}).get(spreadsheet_id, "")


def save_pinned_tab(spreadsheet_id, tab):
    pinned = load_setting("pinned_tabs", {})
    pinned[spreadsheet_id] = tab
    save_setting({"pinned_tabs": pinned})
```

Update `build_assembly(sheet_url, spacing_cm)` to take an optional tab and use `get_rows`: change its signature to `build_assembly(sheet_url, spacing_cm, tab_name=None)` and replace `rows = fetch_rows(sheet_url)` with `rows = get_rows(sheet_url, tab_name)`.

- [ ] **Step 2: Verify it byte-compiles & lints**

Run:
```bash
python -m py_compile SheetVariants/SheetVariants.py
python -m pyflakes SheetVariants/SheetVariants.py
```
Expected: no output.

- [ ] **Step 3: Verify the pure suite still passes**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 4: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/SheetVariants.py
git commit -m "refactor(addin): route sheet access through sheet_source"
```

---

## Task 8: Build dialog — tab dropdown, Load-tabs, inline validation, OK gating

**Files:**
- Modify: `SheetVariants/SheetVariants.py` (`CommandCreatedHandler`, `CommandExecuteHandler`; new `InputChangedHandler`, `ValidateInputsHandler`).

**Interfaces:**
- Consumes: `list_tabs`, `get_rows`, `load_pinned_tab`, `save_pinned_tab`, `known_param_names`, `driveable_param_names`, `sheet_source.extract_spreadsheet_id`, `sheet_source.validate_mapping`.
- Produces: module state `_build_report = {"ok": True}` read by `ValidateInputsHandler`.

**This task is `adsk`-coupled: it cannot be pytest-tested. It is verified by byte-compile + pyflakes and the manual Fusion checklist at the end of this plan.**

- [ ] **Step 1: Add inputs in `CommandCreatedHandler.notify`**

After the existing `sheetUrl` input, before the `spacing` input:

```python
            tab_dd = inputs.addDropDownCommandInput(
                "tab", "Tab", adsk.core.DropDownStyles.TextListDropDownStyle)
            tab_dd.tooltip = "Which worksheet tab holds your variant rows."
            tab_dd.listItems.add("— click Load tabs —", True)

            load_btn = inputs.addBoolValueInput("loadTabs", "Load tabs", False, "", False)
            load_btn.tooltip = "Fetch the sheet and list its tabs."

            report = inputs.addTextBoxCommandInput("report", "Check", "", 6, True)
            report.isFullWidth = True
```

Pre-populate the tab list if a URL + pin already exist:

```python
            url0 = load_setting("sheet_url", "")
            sid0 = sheet_source.extract_spreadsheet_id(url0)
            if sid0:
                pinned = load_pinned_tab(sid0)
                if pinned:
                    tab_dd.listItems.clear()
                    tab_dd.listItems.add(pinned, True)
```

Register the two new handlers (keep them referenced in `_handlers`):

```python
            on_changed = InputChangedHandler()
            cmd.inputChanged.add(on_changed)
            _handlers.append(on_changed)

            on_validate = ValidateInputsHandler()
            cmd.validateInputs.add(on_validate)
            _handlers.append(on_validate)
```

Also enlarge the dialog: `cmd.setDialogInitialSize(520, 380)`.

- [ ] **Step 2: Add the `InputChangedHandler` class**

```python
def _run_build_validation(inputs):
    """Refresh the report textbox + _build_report flag from current inputs."""
    url = inputs.itemById("sheetUrl").value.strip()
    tab_item = inputs.itemById("tab").selectedItem
    tab = tab_item.name if tab_item else ""
    report_box = inputs.itemById("report")
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        report_box.formattedText = "Open your parametric source model to validate."
        _build_report["ok"] = True
        return
    if not tab or tab.startswith("—"):
        report_box.formattedText = "Pick a tab to validate the mapping."
        _build_report["ok"] = True
        return
    try:
        rows = get_rows(url, tab)
    except Exception as e:
        report_box.formattedText = '<font color="#c0392b">{}</font>'.format(str(e))
        _build_report["ok"] = False
        return
    rep = sheet_source.validate_mapping(
        rows[0], rows[1:], known_param_names(design), driveable_param_names(design))
    report_box.formattedText = rep.to_html()
    _build_report["ok"] = rep.ok


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            changed = args.input
            inputs = args.inputs
            if changed.id == "loadTabs" and changed.value:
                changed.value = False  # reset the button
                url = inputs.itemById("sheetUrl").value.strip()
                tab_dd = inputs.itemById("tab")
                try:
                    tabs = list_tabs(url)
                except Exception as e:
                    inputs.itemById("report").formattedText = \
                        '<font color="#c0392b">{}</font>'.format(str(e))
                    return
                tab_dd.listItems.clear()
                if not tabs:
                    tab_dd.listItems.add("— not a multi-tab link —", True)
                    inputs.itemById("report").formattedText = \
                        "This link has no selectable tabs; it will be read as a single CSV."
                    return
                pinned = load_pinned_tab(sheet_source.extract_spreadsheet_id(url))
                for i, name in enumerate(tabs):
                    tab_dd.listItems.add(name, name == pinned or (not pinned and i == 0))
                _run_build_validation(inputs)
            elif changed.id in ("tab", "sheetUrl"):
                _run_build_validation(inputs)
        except Exception:
            if ui:
                ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
```

Add near the other module state (top of file): `_build_report = {"ok": True}`.

- [ ] **Step 3: Add the `ValidateInputsHandler` class**

```python
class ValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            args.areInputsValid = _build_report.get("ok", True)
        except Exception:
            args.areInputsValid = True
```

- [ ] **Step 4: Use the selected tab in `CommandExecuteHandler.notify`**

Replace the body that calls `build_assembly` so it passes the tab and pins it:

```python
            tab_item = inputs.itemById("tab").selectedItem
            tab = tab_item.name if tab_item and not tab_item.name.startswith("—") else None

            save_setting({"sheet_url": url, "spacing_mm": spacing_cm * 10.0})
            sid = sheet_source.extract_spreadsheet_id(url)
            if sid and tab:
                save_pinned_tab(sid, tab)

            count = build_assembly(url, spacing_cm, tab)
```

- [ ] **Step 5: Verify it byte-compiles & lints**

Run:
```bash
python -m py_compile SheetVariants/SheetVariants.py
python -m pyflakes SheetVariants/SheetVariants.py
```
Expected: no output.

- [ ] **Step 6: Commit** *(gated — ask the user first, and only after the manual Fusion check in Step 7 if you prefer to test first)*

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat(addin): tab picker + inline validation in Build dialog"
```

- [ ] **Step 7: Manual verification (in Fusion — user runs this)**

1. Load the add-in; open a parametric model; run **Build Variants Assembly from Sheet**.
2. Paste the sheet link, click **Load tabs** → the Tab dropdown lists the real tabs.
3. Select the data tab → the Check box shows the mapping report; a comma-decimal row shows a red ✗ and **OK is greyed out**.
4. Fix the sheet, reload, reselect → report goes green, **OK enables**, Build produces the assembly, and the source model is restored.

---

## Task 9: Build — deep value check before building

**Files:**
- Modify: `SheetVariants/SheetVariants.py` (`build_assembly`).

**Interfaces:**
- Consumes: `sheet_source` (none new); uses live `all_params`.
- Produces: `deep_check_values(all_params, header, rows) -> list[str]` returning human-readable rejection messages (empty list = all good).

**`adsk`-coupled — verified by byte-compile/pyflakes + manual checklist.**

- [ ] **Step 1: Add the deep check and call it in `build_assembly`**

Add the helper:

```python
def deep_check_values(all_params, param_names, rows):
    """Try-set each distinct (param, value) and restore; collect rejections."""
    rejects = []
    seen = set()
    originals = {}
    try:
        for row in rows:
            for col, pname in enumerate(param_names, start=1):
                if col >= len(row):
                    continue
                val = row[col].strip()
                if not val or (pname, val) in seen:
                    continue
                seen.add((pname, val))
                param = all_params.itemByName(pname)
                if not param:
                    continue
                if pname not in originals:
                    originals[pname] = param.expression
                try:
                    apply_expression(param, val)
                except Exception as e:
                    rejects.append('{} = "{}": {}'.format(pname, val, str(e).splitlines()[0]))
    finally:
        for pname, expr in originals.items():
            try:
                all_params.itemByName(pname).expression = expr
            except Exception:
                pass
    return rejects
```

In `build_assembly`, after the `missing` check and before snapshotting `original`, add:

```python
    rejects = deep_check_values(all_params, param_names, rows[1:])
    if rejects:
        raise RuntimeError(
            "These cell values were rejected by Fusion:\n  " + "\n  ".join(rejects))
```

- [ ] **Step 2: Verify byte-compile & lint**

Run:
```bash
python -m py_compile SheetVariants/SheetVariants.py
python -m pyflakes SheetVariants/SheetVariants.py
```
Expected: no output.

- [ ] **Step 3: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat(addin): definitive pre-build value check"
```

- [ ] **Step 4: Manual verification (in Fusion — user runs this)**

Build with a deliberately bad unit (e.g. `18 xyz`) → Build aborts naming that cell, and the model is unchanged afterward.

---

## Task 10: Test Variant Row command

**Files:**
- Modify: `SheetVariants/SheetVariants.py` (new command def + handlers + panel button + cleanup id).

**Interfaces:**
- Consumes: `list_tabs`, `get_rows`, `load_pinned_tab`, `apply_expression`, `load_setting`, `save_setting`.
- Produces: constants `TEST_CMD_ID = "sheetVariantsTestRowCmd"`, etc.; snapshot stored under settings key `test_snapshot`.

**`adsk`-coupled — verified by byte-compile/pyflakes + manual checklist.**

- [ ] **Step 1: Add command constants**

Near the other command ids:

```python
TEST_CMD_ID = "sheetVariantsTestRowCmd"
TEST_CMD_NAME = "Test Variant Row"
TEST_CMD_DESC = ("Applies one variant row from the sheet to the current model so you "
                 "can inspect it, then lets you restore the original values.")
```

Reuse `BUILD_ICON_FOLDER` for its icon.

- [ ] **Step 2: Add snapshot helpers**

```python
def save_test_snapshot(snapshot):
    save_setting({"test_snapshot": snapshot})


def load_test_snapshot():
    return load_setting("test_snapshot", {})


def clear_test_snapshot():
    save_setting({"test_snapshot": {}})
```

- [ ] **Step 3: Add the created/changed/execute handlers**

```python
class TestRowCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.setDialogInitialSize(460, 240)
            inputs = cmd.commandInputs

            url_in = inputs.addStringValueInput("sheetUrl", "Google Sheet URL",
                                                load_setting("sheet_url", ""))
            url_in.tooltip = "Same sheet you build from."

            tab_dd = inputs.addDropDownCommandInput(
                "tab", "Tab", adsk.core.DropDownStyles.TextListDropDownStyle)
            tab_dd.listItems.add("— click Load tabs —", True)

            inputs.addBoolValueInput("loadTabs", "Load tabs", False, "", False)

            inputs.addDropDownCommandInput(
                "row", "Variant row", adsk.core.DropDownStyles.TextListDropDownStyle
            ).listItems.add("— load a tab first —", True)

            if load_test_snapshot():
                inputs.addBoolValueInput("restore", "Restore original values",
                                         True, "", False)

            on_changed = TestRowChangedHandler()
            cmd.inputChanged.add(on_changed)
            _handlers.append(on_changed)
            on_exec = TestRowExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
        except Exception:
            if ui:
                ui.messageBox("Failed:\n{}".format(traceback.format_exc()))


class TestRowChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            changed = args.input
            inputs = args.inputs
            if changed.id == "loadTabs" and changed.value:
                changed.value = False
                url = inputs.itemById("sheetUrl").value.strip()
                tab_dd = inputs.itemById("tab")
                tabs = list_tabs(url)
                tab_dd.listItems.clear()
                if not tabs:
                    tab_dd.listItems.add("— single-CSV link —", True)
                else:
                    pinned = load_pinned_tab(sheet_source.extract_spreadsheet_id(url))
                    for i, name in enumerate(tabs):
                        tab_dd.listItems.add(name, name == pinned or (not pinned and i == 0))
                _reload_rows(inputs)
            elif changed.id == "tab":
                _reload_rows(inputs)
        except Exception:
            if ui:
                ui.messageBox("Failed:\n{}".format(traceback.format_exc()))


def _reload_rows(inputs):
    url = inputs.itemById("sheetUrl").value.strip()
    tab_item = inputs.itemById("tab").selectedItem
    tab = tab_item.name if tab_item else ""
    row_dd = inputs.itemById("row")
    row_dd.listItems.clear()
    if not tab or tab.startswith("—"):
        row_dd.listItems.add("— load a tab first —", True)
        return
    try:
        rows = get_rows(url, tab)
    except Exception:
        row_dd.listItems.add("— could not read tab —", True)
        return
    for i, row in enumerate(rows[1:]):
        label = (row[0].strip() if row else "") or "Variant_{}".format(i + 1)
        row_dd.listItems.add(label, i == 0)


class TestRowExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox("Open your parametric source model first.")
                return
            all_params = design.allParameters

            restore_in = inputs.itemById("restore")
            if restore_in and restore_in.value:
                snap = load_test_snapshot()
                for pname, expr in snap.items():
                    p = all_params.itemByName(pname)
                    if p:
                        try:
                            p.expression = expr
                        except Exception:
                            pass
                adsk.doEvents()
                clear_test_snapshot()
                ui.messageBox("Restored {} parameter(s) to their original values."
                              .format(len(snap)))
                return

            url = inputs.itemById("sheetUrl").value.strip()
            tab_item = inputs.itemById("tab").selectedItem
            tab = tab_item.name if tab_item and not tab_item.name.startswith("—") else None
            row_item = inputs.itemById("row").selectedItem
            if not row_item or row_item.name.startswith("—"):
                ui.messageBox("Pick a variant row to test.")
                return

            rows = get_rows(url, tab)
            header = [h.strip() for h in rows[0]]
            param_names = header[1:]
            data = rows[1:]
            idx = inputs.itemById("row").selectedItem.index
            row = data[idx]

            # Snapshot only the params this row touches (from the true original,
            # unless a snapshot already exists from an earlier untested-restore).
            snapshot = load_test_snapshot()
            failures = []
            for col, pname in enumerate(param_names, start=1):
                if col >= len(row):
                    continue
                val = row[col].strip()
                if not val:
                    continue
                param = all_params.itemByName(pname)
                if not param:
                    continue
                if pname not in snapshot:
                    snapshot[pname] = param.expression
                try:
                    apply_expression(param, val)
                except Exception as e:
                    failures.append('{}: "{}" ({})'.format(pname, val, str(e).splitlines()[0]))
            save_test_snapshot(snapshot)
            adsk.doEvents()

            msg = "Applied variant \"{}\" to the model.".format(row_item.name)
            if failures:
                msg += "\n\nSome cells were rejected:\n  " + "\n  ".join(failures)
            msg += ("\n\nInspect the model, then reopen \"Test Variant Row\" and tick "
                    "\"Restore original values\" to put it back.")
            ui.messageBox(msg)
        except Exception:
            if ui:
                ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
```

- [ ] **Step 4: Register the command in `run()` and clean it up**

In `run()`, after the template button is created, add a third button:

```python
        test_def = cmd_defs.addButtonDefinition(TEST_CMD_ID, TEST_CMD_NAME,
                                                TEST_CMD_DESC, BUILD_ICON_FOLDER)
        on_test_created = TestRowCreatedHandler()
        test_def.commandCreated.add(on_test_created)
        _handlers.append(on_test_created)
```

Extend the panel-control loop to include the new command:

```python
            for cmd_id, definition in ((CMD_ID, cmd_def),
                                       (TEST_CMD_ID, test_def),
                                       (TEMPLATE_CMD_ID, tmpl_def)):
```

In `cleanup_ui`, add `TEST_CMD_ID` to `cmd_ids`:

```python
    cmd_ids = (CMD_ID, TEMPLATE_CMD_ID, TEST_CMD_ID)
```

- [ ] **Step 5: Verify byte-compile & lint**

Run:
```bash
python -m py_compile SheetVariants/SheetVariants.py
python -m pyflakes SheetVariants/SheetVariants.py
```
Expected: no output.

- [ ] **Step 6: Commit** *(gated — ask the user first)*

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat(addin): Test Variant Row command with apply/restore"
```

- [ ] **Step 7: Manual verification (in Fusion — user runs this)**

1. Run **Test Variant Row** → Load tabs → pick tab → pick a row → OK. The model rebuilds to that config; a message explains how to restore.
2. Reopen **Test Variant Row** → tick **Restore original values** → OK. The touched parameters return to their originals.
3. Confirm no parameter outside the tested row's columns was changed.

---

## Task 11: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:** none.

- [ ] **Step 1: Update the README**

- Add a **Selecting a tab** subsection under "Sheet layout": explain Load tabs, pinning, and that published/CSV links are single-tab.
- Add a **Validating before you build** subsection: columns↔params, uncovered params, comma-decimal/units, OK disabled on errors.
- Add a **Test Variant Row** subsection describing apply + restore.
- Note in "How the Google connection works" that multi-tab sheets are fetched once as XLSX (stdlib `zipfile`), single-tab links still use CSV.

- [ ] **Step 2: Commit** *(gated — ask the user first)*

```bash
git add README.md
git commit -m "docs: tab selection, validation, test-row"
```

---

## Self-Review

**Spec coverage:**
- XLSX enabler → Tasks 2–3, 7. ✓
- `sheet_source` / `SheetVariants` split → Tasks 1–5 (pure) vs 7–10 (adsk). ✓
- Tab select + pin → Tasks 7 (helpers), 8 (UI). ✓
- Validation tier 1 (static) → Task 5 + Task 8 wiring. ✓
- Validation tier 2 (deep) → Task 9. ✓
- Test Variant Row → Task 10. ✓
- Build integration / backward-compat CSV → Task 7 (`get_rows`), Task 8. ✓
- pytest + CI → Tasks 1–6. ✓
- Manual-in-Fusion checklist → Tasks 8, 9, 10 Step 7 + spec checklist. ✓
- Settings model (`pinned_tabs`, `test_snapshot`) → Tasks 7, 10. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `get_rows(url, tab_name)`, `list_tabs(url)`, `validate_mapping(header, rows, known, driveable)`, `ValidationReport.ok/.summary()/.to_html()`, `read_tab_rows(bytes, name)`, `classify_value` return strings used consistently across Tasks 5/8. `_build_report` written in Task 8 Step 2, read in Step 3. ✓

**Note on ordering:** Tasks 1–6 are fully TDD-testable and safe to complete first. Tasks 7–11 are `adsk`-coupled; they are gated behind the user's manual Fusion verification before any "works" claim, per Global Constraints.
