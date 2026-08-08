# Export Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single whole-model export with named export profiles (whole model / named components), each producing its own new Fusion design, one component per variant.

**Architecture:** Extract all pure, Fusion-free logic into a new `sheet_core.py` module that is unit-tested with pytest. `SheetVariants.py` keeps the Fusion-API code (dialog, geometry copy, build loop), imports `sheet_core`, and drives a multi-profile build that recomputes each variant once and feeds every enabled profile. Profiles are edited in a combined Build dialog (`TableCommandInput`) and persisted to `settings.json`.

**Tech Stack:** Python 3 (Fusion's bundled interpreter), Autodesk Fusion API (`adsk.core`, `adsk.fusion`), stdlib only for runtime (`urllib`, `csv`, `io`, `json`, `re`), pytest for tests.

## Global Constraints

- **Runtime code is stdlib-only.** `sheet_core.py` and `SheetVariants.py` import no third-party packages (they run under Fusion's bundled Python, which can't easily install packages). pytest is allowed strictly as a **dev/test dependency**, never imported by runtime code.
- **`sheet_core.py` must never import `adsk`.** It must be importable in a plain Python process so tests run without Fusion.
- **Personal-licence-safe.** Geometry is copied in-memory via `TemporaryBRepManager`; no SAT/STEP/DXF file export anywhere.
- **`adsk` is imported at module top of `SheetVariants.py`**, so that file cannot be imported outside Fusion — never write a test that imports it.
- **Commits require the user's go-ahead.** Per the user's workflow: test first, then ask before committing. Tasks 5–7 touch the Fusion API and **cannot be auto-verified** — they are verified manually by the user inside Fusion. Do not claim they work until the user confirms. Steps below labelled *(manual, user-run)* must not be marked complete on the basis of `py_compile`/`pyflakes` alone.
- **Component matching is by component name** (a `str`); a saved profile that references a name absent from the open design is warned about at run time, never a hard failure.

---

### Task 1: Test harness + `sheet_core` scaffold + URL candidate logic

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_sheet_core.py`
- Create: `SheetVariants/sheet_core.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `sheet_core.csv_url_candidates(url: str) -> list[str]` — turns a share/edit/publish Google Sheet link into an ordered list of CSV-export URLs to try.

- [ ] **Step 1: Add the dev dependency and test harness**

Create `requirements-dev.txt`:

```text
pytest>=8
```

Create `tests/conftest.py` (puts the add-in folder on `sys.path` so tests can `import sheet_core` without Fusion):

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "SheetVariants"))
```

Append to `.gitignore`:

```text
# Test artifacts
.pytest_cache/
```

Install pytest:

```bash
python3 -m pip install --upgrade -r requirements-dev.txt
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_sheet_core.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'sheet_core'`.

- [ ] **Step 4: Write minimal implementation**

Create `SheetVariants/sheet_core.py`:

```python
# sheet_core.py
# Pure, Fusion-free logic for the SheetVariants add-in. This module MUST NOT
# import adsk so it can be imported and unit-tested outside Fusion.

import re

SHARING_HELP = (
    'Make sure the sheet is shared so anyone with the link can read it: in Google '
    'Sheets, Share > General access > "Anyone with the link" > Viewer. '
    '(Or publish it: File > Share > Publish to web.) Then paste that link here.')


def csv_url_candidates(url):
    """Turn a share / edit / publish link into one or more CSV-export links.

    Uses the ``/export?format=csv`` endpoint, which returns cell values exactly
    as typed. For sheets shared as "anyone with the link", supplying a ``gid``
    makes the signed redirect fail with HTTP 400, so the default first tab is
    requested without a gid; a gid is only added when the link explicitly points
    at a non-first tab.
    """
    url = url.strip()
    if 'output=csv' in url or 'format=csv' in url:
        return [url]
    if re.search(r'/spreadsheets/d/e/[^/]+/pub', url):
        sep = '&' if '?' in url else '?'
        return [url + sep + 'output=csv']
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    if m:
        sheet_id = m.group(1)
        base = 'https://docs.google.com/spreadsheets/d/{}/export?format=csv'.format(sheet_id)
        gid_match = re.search(r'[#&?]gid=(\d+)', url)
        gid = gid_match.group(1) if gid_match else None
        if gid and gid != '0':
            return [base + '&gid=' + gid, base]
        return [base]
    return [url]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit** *(ask the user first)*

```bash
git add requirements-dev.txt tests/ SheetVariants/sheet_core.py .gitignore
git commit -m "Add pytest harness and sheet_core CSV URL logic"
```

---

### Task 2: CSV parsing + text unquoting in `sheet_core`

**Files:**
- Modify: `SheetVariants/sheet_core.py`
- Modify: `tests/test_sheet_core.py`

**Interfaces:**
- Produces: `sheet_core.parse_sheet_csv(raw: str) -> list[list[str]]` — parses CSV text into non-empty rows; raises `RuntimeError` if the text is an HTML page or has fewer than 2 rows.
- Produces: `sheet_core.unquote_text(expression: str) -> str` — strips surrounding single/double quotes from a parameter expression.

- [ ] **Step 1: Write the failing test**

At the top of `tests/test_sheet_core.py`, add `import pytest` above `import sheet_core`. Then append:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: FAIL — `AttributeError: module 'sheet_core' has no attribute 'parse_sheet_csv'`.

- [ ] **Step 3: Write minimal implementation**

In `SheetVariants/sheet_core.py`, add two imports below the existing `import re` (do **not** re-add `re`):

```python
import io
import csv
```

Append:

```python
def parse_sheet_csv(raw):
    """Parse downloaded CSV text into a list of non-empty rows.

    Raises RuntimeError if the text looks like an HTML page (usually a sign-in
    wall) or does not contain at least a header plus one data row.
    """
    head = raw.lstrip()[:200].lower()
    if head.startswith('<!doctype html') or '<html' in head:
        raise RuntimeError(
            'That URL returned a web page instead of CSV, which usually means the '
            'sheet is not readable without signing in.\n\n' + SHARING_HELP)
    rows = [r for r in csv.reader(io.StringIO(raw)) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise RuntimeError('The sheet needs a header row plus at least one variant row.')
    return rows


def unquote_text(expression):
    """Strip surrounding single/double quotes from a text-parameter expression
    (e.g. 'A-6' -> A-6). Leaves numeric expressions like '50 mm' untouched and
    passes None through unchanged."""
    s = (expression or '').strip()
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    return expression
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: PASS (10 tests total).

- [ ] **Step 5: Commit** *(ask the user first)*

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "Add CSV parsing and text unquoting to sheet_core"
```

---

### Task 3: Settings + profiles model in `sheet_core`

**Files:**
- Modify: `SheetVariants/sheet_core.py`
- Modify: `tests/test_sheet_core.py`

**Interfaces:**
- Produces: `sheet_core.default_profiles() -> list[dict]` — the single default "Full model" whole-model profile.
- Produces: `sheet_core.migrate_settings(data: dict) -> dict` — normalizes a settings dict so `profiles` is a list of well-formed profile dicts (`id`, `name`, `enabled`, `rule`, `components`).
- Produces: `sheet_core.load_settings(path: str) -> dict` and `sheet_core.save_settings(path: str, data: dict) -> None`.
- Produces: `sheet_core.next_profile_id(existing_ids) -> str` — smallest free `p{n}` id.
- A profile dict shape: `{"id": str, "name": str, "enabled": bool, "rule": "whole_model"|"named_components", "components": list[str]}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sheet_core.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: FAIL — `AttributeError: module 'sheet_core' has no attribute 'migrate_settings'`.

- [ ] **Step 3: Write minimal implementation**

In `SheetVariants/sheet_core.py` add `import json` below the other imports, then append:

```python
VALID_RULES = ("whole_model", "named_components")


def default_profiles():
    return [{"id": "p1", "name": "Full model", "enabled": True,
             "rule": "whole_model", "components": []}]


def _normalize_profile(raw, fallback_id):
    raw = raw if isinstance(raw, dict) else {}
    rule = raw.get("rule") if raw.get("rule") in VALID_RULES else "whole_model"
    comps = [str(c).strip() for c in (raw.get("components") or []) if str(c).strip()]
    return {
        "id": str(raw.get("id") or fallback_id),
        "name": str(raw.get("name") or "Export"),
        "enabled": bool(raw.get("enabled", True)),
        "rule": rule,
        "components": comps,
    }


def migrate_settings(data):
    """Return a copy of the settings dict with a well-formed 'profiles' list.
    Missing/empty profiles yield the single default whole-model profile so
    upgrading users reproduce today's behaviour exactly."""
    data = dict(data or {})
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        data["profiles"] = default_profiles()
    else:
        data["profiles"] = [_normalize_profile(p, "p%d" % (i + 1))
                            for i, p in enumerate(profiles)]
    return data


def load_settings(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    return migrate_settings(data)


def save_settings(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def next_profile_id(existing_ids):
    existing = set(existing_ids or [])
    n = 1
    while ("p%d" % n) in existing:
        n += 1
    return "p%d" % n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit** *(ask the user first)*

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "Add settings/profile model and migration to sheet_core"
```

---

### Task 4: Selection matching + result summary in `sheet_core`

**Files:**
- Modify: `SheetVariants/sheet_core.py`
- Modify: `tests/test_sheet_core.py`

**Interfaces:**
- Produces: `sheet_core.select_component_names(present: list[str], targets: list[str]) -> tuple[list[str], list[str]]` — returns `(included, missing)` preserving `targets` order.
- Produces: `sheet_core.summarize_results(results: list[dict]) -> str` — builds the end-of-run message from result dicts shaped `{"name": str, "built": int, "warnings": list[str], "skipped": bool}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sheet_core.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: FAIL — `AttributeError: module 'sheet_core' has no attribute 'select_component_names'`.

- [ ] **Step 3: Write minimal implementation**

Append to `SheetVariants/sheet_core.py`:

```python
def select_component_names(present, targets):
    """Split target component names into (included, missing) against the names
    present in the design, preserving the order of ``targets``."""
    present_set = set(present or [])
    included, missing = [], []
    for name in (targets or []):
        (included if name in present_set else missing).append(name)
    return included, missing


def summarize_results(results):
    """Build the end-of-run message box text from per-profile result dicts."""
    lines = []
    built = [r for r in results if not r.get("skipped")]
    if built:
        lines.append("Built:")
        for r in built:
            warn = (" — " + "; ".join(r["warnings"])) if r.get("warnings") else ""
            lines.append("  • {} ({} variant(s)){}".format(r.get("name", "Export"),
                                                           r.get("built", 0), warn))
    skipped = [r for r in results if r.get("skipped")]
    if skipped:
        lines.append("Skipped:")
        for r in skipped:
            reason = "; ".join(r["warnings"]) if r.get("warnings") else "nothing to export"
            lines.append("  • {} — {}".format(r.get("name", "Export"), reason))
    return "\n".join(lines) if lines else "Nothing was built."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sheet_core.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit** *(ask the user first)*

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "Add component-name matching and result summary to sheet_core"
```

---

### Task 5: Rewire `SheetVariants.py` onto `sheet_core` (no behaviour change)

**Files:**
- Modify: `SheetVariants/SheetVariants.py`

**Interfaces:**
- Consumes: everything in `sheet_core` from Tasks 1–4.
- Produces: no new public interface; this is a refactor that removes duplicated logic and wires the main file to `sheet_core`. `build_assembly` remains for now (replaced in Task 6).

This task touches Fusion glue and is verified with `py_compile` + `pyflakes` and a **manual Fusion smoke test by the user** — behaviour must be unchanged.

- [ ] **Step 1: Add the sibling-module import**

Near the top of `SheetVariants/SheetVariants.py`, after `import urllib.error`, add:

```python
import sys

# Make this add-in's folder importable so the pure-logic module resolves
# regardless of Fusion's current working directory.
_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
import sheet_core
```

- [ ] **Step 2: Delete the now-duplicated `SHARING_HELP` and `csv_url_candidates`**

Remove the `SHARING_HELP = (...)` block and the entire `csv_url_candidates` function from `SheetVariants.py` (they now live in `sheet_core`).

- [ ] **Step 3: Rewrite `fetch_rows` to delegate to `sheet_core`**

Replace the whole `fetch_rows` function with:

```python
def fetch_rows(url):
    candidates = sheet_core.csv_url_candidates(url)
    raw = None
    last_err = None
    for csv_url in candidates:
        req = urllib.request.Request(csv_url, headers={'User-Agent': 'Mozilla/5.0 (FusionAddin)'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8-sig', errors='replace')
            break
        except urllib.error.HTTPError as e:
            last_err = 'HTTP {} {}'.format(e.code, e.reason)
        except urllib.error.URLError as e:
            last_err = str(e.reason)

    if raw is None:
        raise RuntimeError('Could not download the sheet ({}).\n\n{}'.format(
            last_err or 'unknown error', sheet_core.SHARING_HELP))
    return sheet_core.parse_sheet_csv(raw)
```

- [ ] **Step 4: Delete the duplicated `unquote_text` and repoint its caller**

Remove the `unquote_text` function from `SheetVariants.py`. In `create_template`, change the example-row line to:

```python
    example = ['Variant_1'] + [sheet_core.unquote_text(p.expression) for p in params]
```

- [ ] **Step 5: Replace `load_setting`/`save_setting` with the whole-dict helpers**

Delete the `load_setting` and `save_setting` functions. In `CommandCreatedHandler.notify`, replace the settings reads with:

```python
            settings = sheet_core.load_settings(SETTINGS_FILE)
            url_in = inputs.addStringValueInput('sheetUrl', 'Google Sheet URL',
                                                settings.get('sheet_url', ''))
            url_in.tooltip = 'Share link or published-to-web CSV link of the sheet that holds your variants.'

            default_mm = float(settings.get('spacing_mm', 100.0))
```

In `CommandExecuteHandler.notify`, replace the `save_setting(...)` call with:

```python
            sheet_core.save_settings(SETTINGS_FILE, {
                'sheet_url': url,
                'spacing_mm': spacing_cm * 10.0,
                'profiles': sheet_core.default_profiles(),
            })
```

(The full profiles wiring arrives in Tasks 6–7; this keeps a valid settings file in the interim.)

- [ ] **Step 6: Byte-compile and lint**

Run:

```bash
python3 -m py_compile SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
python3 -m pip install --quiet --upgrade pyflakes
python3 -m pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
```

Expected: no output (success). Fix any undefined-name or unused-import findings.

- [ ] **Step 7: Manual Fusion smoke test** *(manual, user-run)*

Ask the user to reload the add-in in Fusion and confirm the current behaviour is unchanged: **Create Variant Sheet Template** still writes a CSV, and **Build Variants Assembly from Sheet** still builds one design with one component per variant. Do not proceed until the user confirms.

- [ ] **Step 8: Commit** *(ask the user first, after their manual confirmation)*

```bash
git add SheetVariants/SheetVariants.py
git commit -m "Move pure logic into sheet_core and delegate from the add-in"
```

---

### Task 6: Multi-profile build engine + selection resolvers

**Files:**
- Modify: `SheetVariants/SheetVariants.py`

**Interfaces:**
- Consumes: `sheet_core.select_component_names`, `sheet_core.summarize_results`, existing `iter_solid_bodies`, `apply_expression`, `fetch_rows`.
- Produces:
  - `component_names(design) -> list[str]` — distinct component names in the active design.
  - `RESOLVERS: dict[str, callable]` where each resolver is `fn(design, profile) -> (bodies, warnings)`.
  - `build_exports(sheet_url, spacing_cm, profiles) -> list[dict]` — builds one new design per enabled, non-skipped profile; returns per-profile result dicts shaped for `sheet_core.summarize_results`.

This task is verified with `py_compile` + `pyflakes` and a **manual Fusion test by the user**.

- [ ] **Step 1: Add component enumeration and selection resolvers**

After `iter_solid_bodies` in `SheetVariants.py`, add:

```python
def component_names(design):
    """Distinct component names in the active design (order of first appearance)."""
    names, seen = [], set()
    for occ in design.rootComponent.allOccurrences:
        try:
            n = occ.component.name
        except Exception:
            continue
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    return names


def resolve_whole_model(design, profile):
    """Every solid body in the design (root plus all occurrences)."""
    return list(iter_solid_bodies(design)), []


def _component_solid_bodies(design, included_names):
    """Solid bodies of the selected components — one representative occurrence
    per component name, so a part exports once rather than once per instance."""
    wanted = set(included_names)
    got = {}
    for occ in design.rootComponent.allOccurrences:
        try:
            cname = occ.component.name
        except Exception:
            continue
        if cname in wanted and cname not in got:
            bodies = [b for b in occ.bRepBodies if b.isSolid]
            if bodies:
                got[cname] = bodies
    out = []
    for name in included_names:
        out.extend(got.get(name, []))
    return out


def resolve_named_components(design, profile):
    present = component_names(design)
    included, missing = sheet_core.select_component_names(present, profile.get('components', []))
    warnings = []
    if missing:
        warnings.append("component(s) not found: " + ", ".join(missing))
    return _component_solid_bodies(design, included), warnings


RESOLVERS = {
    'whole_model': resolve_whole_model,
    'named_components': resolve_named_components,
}
```

- [ ] **Step 2: Add `build_exports`**

After the resolvers, add:

```python
def build_exports(sheet_url, spacing_cm, profiles):
    """Build one new design per enabled profile. Recomputes each variant once
    and feeds every profile. Returns per-profile result dicts for reporting."""
    rows = fetch_rows(sheet_url)
    header = [h.strip() for h in rows[0]]
    if not header or not header[0]:
        raise RuntimeError('The first header cell must be "Name".')
    param_names = header[1:]

    src_design = adsk.fusion.Design.cast(app.activeProduct)
    if not src_design:
        raise RuntimeError('Open the parametric source model as the active design before running this command.')

    all_params = src_design.allParameters
    missing = [p for p in param_names if not all_params.itemByName(p)]
    if missing:
        raise RuntimeError('These columns do not match any parameter in the model: ' + ', '.join(missing))

    enabled = [p for p in profiles if p.get('enabled')]
    if not enabled:
        raise RuntimeError('No export profiles are enabled. Enable at least one profile and run again.')

    original = {p: all_params.itemByName(p).expression for p in param_names}
    tbm = adsk.fusion.TemporaryBRepManager.get()

    # One build context per enabled profile; pre-validate selections.
    present = component_names(src_design)
    contexts = []
    for prof in enabled:
        ctx = {'profile': prof, 'name': prof.get('name') or 'Export', 'design': None,
               'root': None, 'x_cursor': 0.0, 'built': 0, 'warnings': [], 'skipped': False}
        if prof.get('rule') not in RESOLVERS:
            ctx['skipped'] = True
            ctx['warnings'] = ["unknown rule '{}'".format(prof.get('rule'))]
        elif prof.get('rule') == 'named_components':
            included, miss = sheet_core.select_component_names(present, prof.get('components', []))
            if miss:
                ctx['warnings'].append("component(s) not found: " + ", ".join(miss))
            if not included:
                ctx['skipped'] = True
                ctx['warnings'] = ['no matching components in this design']
        contexts.append(ctx)

    active = [c for c in contexts if not c['skipped']]
    if not active:
        return contexts

    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show('Building exports', 'Variant %v of %m', 0, len(rows) - 1, 0)

    try:
        for i, row in enumerate(rows[1:]):
            if progress.wasCancelled:
                raise RuntimeError('Cancelled by user.')

            raw_name = row[0].strip() if len(row) > 0 else ''
            name = raw_name or 'Variant_{}'.format(i + 1)
            safe_name = re.sub(r'[^A-Za-z0-9_\- ]', '_', name).strip() or 'Variant_{}'.format(i + 1)

            for col, pname in enumerate(param_names, start=1):
                if col < len(row):
                    val = row[col].strip()
                    if val:
                        apply_expression(all_params.itemByName(pname), val)
            adsk.doEvents()  # single recompute shared by all profiles

            for ctx in active:
                resolver = RESOLVERS[ctx['profile']['rule']]
                src_bodies, _warn = resolver(src_design, ctx['profile'])
                temp_bodies = []
                for body in src_bodies:
                    try:
                        temp_bodies.append(tbm.copy(body))
                    except Exception:
                        pass
                if not temp_bodies:
                    continue

                if ctx['design'] is None:   # create output design lazily
                    new_doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
                    nd = adsk.fusion.Design.cast(new_doc.products.itemByProductType('DesignProductType'))
                    ctx['design'] = nd
                    ctx['root'] = nd.rootComponent
                    try:
                        nd.rootComponent.name = ctx['name']
                    except Exception:
                        pass

                root = ctx['root']
                min_x = min(tb.boundingBox.minPoint.x for tb in temp_bodies)
                max_x = max(tb.boundingBox.maxPoint.x for tb in temp_bodies)
                transform = adsk.core.Matrix3D.create()
                transform.translation = adsk.core.Vector3D.create(ctx['x_cursor'] - min_x, 0.0, 0.0)
                occ = root.occurrences.addNewComponent(transform)
                occ.component.name = safe_name
                base = occ.component.features.baseFeatures.add()
                base.startEdit()
                try:
                    for tb in temp_bodies:
                        occ.component.bRepBodies.add(tb, base)
                finally:
                    base.finishEdit()
                ctx['x_cursor'] += (max_x - min_x) + spacing_cm
                ctx['built'] += 1

            progress.progressValue = i + 1
    finally:
        for p, expr in original.items():
            try:
                all_params.itemByName(p).expression = expr
            except Exception:
                pass
        adsk.doEvents()
        progress.hide()

    for ctx in active:
        if ctx['built'] == 0 and not ctx['skipped']:
            ctx['skipped'] = True
            if not ctx['warnings']:
                ctx['warnings'] = ['no solid bodies matched']

    return contexts
```

- [ ] **Step 3: Point the execute handler at `build_exports` temporarily**

In `CommandExecuteHandler.notify`, replace the `count = build_assembly(url, spacing_cm)` / message-box lines with:

```python
            profiles = sheet_core.load_settings(SETTINGS_FILE)['profiles']
            sheet_core.save_settings(SETTINGS_FILE, {
                'sheet_url': url, 'spacing_mm': spacing_cm * 10.0, 'profiles': profiles})
            results = build_exports(url, spacing_cm, profiles)
            ui.messageBox(sheet_core.summarize_results(results))
```

(The dialog still only offers URL + gap; profiles come from settings. Full table UI is Task 7.)

- [ ] **Step 4: Delete the obsolete `build_assembly`**

Remove the entire `build_assembly` function — `build_exports` replaces it.

- [ ] **Step 5: Byte-compile and lint**

Run:

```bash
python3 -m py_compile SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
python3 -m pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
```

Expected: no output.

- [ ] **Step 6: Manual Fusion test** *(manual, user-run)*

Ask the user to: open the assembly model, run **Build Variants Assembly from Sheet** (default profile = whole model), confirm one new design with one component per variant. Then hand-edit `SheetVariants/settings.json` to add a `named_components` profile targeting one real component (e.g. `Gordijnplaat`) and run again; confirm a **second** new design containing only that component per variant, and that a bogus component name produces a "Skipped" line, not a crash. Do not proceed until confirmed.

- [ ] **Step 7: Commit** *(ask the user first, after their manual confirmation)*

```bash
git add SheetVariants/SheetVariants.py
git commit -m "Add multi-profile build engine and selection resolvers"
```

---

### Task 7: Combined Build dialog with profiles table

**Files:**
- Modify: `SheetVariants/SheetVariants.py`

**Interfaces:**
- Consumes: `sheet_core.load_settings`, `sheet_core.save_settings`, `sheet_core.next_profile_id`, `component_names`, `build_exports`, `sheet_core.summarize_results`.
- Produces: the profiles `TableCommandInput` and its add/remove/rule-toggle behaviour, plus a `_read_profiles(table)` helper that reads the table back into profile dicts.

This is the most Fusion-API-heavy task; verified by `py_compile` + `pyflakes` and a **manual Fusion test by the user**. If the in-table checkbox-dropdown proves unreliable, fall back to a separate "Edit profile…" sub-dialog (Approach B) — `build_exports` is unchanged either way.

- [ ] **Step 1: Add a module-level cache and row-builder helpers**

Near the top of `SheetVariants.py` (after `_handlers = []`), add:

```python
# Component names of the active design at the moment the Build dialog opened,
# used to populate each named-components profile's checkbox-dropdown.
_component_name_cache = []
```

After the resolvers/`build_exports`, add these UI helpers:

```python
def _rule_is_named(rule_input):
    item = rule_input.selectedItem
    return bool(item and item.name.startswith('Named'))


def _add_profile_row(table, profile):
    """Append one profile as a table row: [enabled | name | rule | components]."""
    ci = table.commandInputs
    pid = profile['id']
    row = table.rowCount

    en = ci.addBoolValueInput('en_' + pid, 'Enabled', True, '', bool(profile.get('enabled', True)))
    nm = ci.addStringValueInput('nm_' + pid, 'Name', profile.get('name', ''))
    rl = ci.addDropDownCommandInput('rl_' + pid, 'Rule', adsk.core.DropDownStyles.TextListDropDownStyle)
    is_named = profile.get('rule') == 'named_components'
    rl.listItems.add('Whole model', not is_named)
    rl.listItems.add('Named components', is_named)

    cp = ci.addDropDownCommandInput('cp_' + pid, 'Components', adsk.core.DropDownStyles.CheckBoxDropDownStyle)
    selected = set(profile.get('components', []))
    for cn in _component_name_cache:
        cp.listItems.add(cn, cn in selected)
    for cn in profile.get('components', []):   # keep saved-but-absent names visible
        if cn not in _component_name_cache:
            cp.listItems.add(cn + ' (missing)', True)
    cp.isVisible = is_named

    table.addCommandInput(en, row, 0)
    table.addCommandInput(nm, row, 1)
    table.addCommandInput(rl, row, 2)
    table.addCommandInput(cp, row, 3)


def _read_profiles(table):
    """Read the table back into a list of profile dicts."""
    profiles = []
    for r in range(table.rowCount):
        en = table.getInputAtPosition(r, 0)
        nm = table.getInputAtPosition(r, 1)
        rl = table.getInputAtPosition(r, 2)
        cp = table.getInputAtPosition(r, 3)
        pid = nm.id[3:]   # strip 'nm_'
        rule = 'named_components' if _rule_is_named(rl) else 'whole_model'
        comps = []
        for k in range(cp.listItems.count):
            it = cp.listItems.item(k)
            if it.isSelected:
                comps.append(it.name.replace(' (missing)', ''))
        profiles.append({'id': pid, 'name': nm.value or ('Export ' + pid),
                         'enabled': en.value, 'rule': rule, 'components': comps})
    return profiles
```

- [ ] **Step 2: Rewrite `CommandCreatedHandler.notify` to build the combined dialog**

Replace the body of `CommandCreatedHandler.notify` with:

```python
        try:
            global _component_name_cache
            cmd = args.command
            cmd.setDialogInitialSize(560, 360)
            inputs = cmd.commandInputs

            settings = sheet_core.load_settings(SETTINGS_FILE)

            url_in = inputs.addStringValueInput('sheetUrl', 'Google Sheet URL', settings.get('sheet_url', ''))
            url_in.tooltip = 'Share link or published-to-web CSV link of the sheet that holds your variants.'

            default_mm = float(settings.get('spacing_mm', 100.0))
            spacing_in = inputs.addValueInput('spacing', 'Gap between variants (mm)', 'mm',
                                              adsk.core.ValueInput.createByReal(default_mm / 10.0))
            spacing_in.tooltip = ('Clear space left between each variant\'s bounding box along X. '
                                  'Set 0 to butt them together.')

            # Cache the active design's component names for the checkbox-dropdowns.
            src = adsk.fusion.Design.cast(app.activeProduct)
            _component_name_cache = component_names(src) if src else []

            table = inputs.addTableCommandInput('profiles', 'Export profiles', 4, '1:3:2:3')
            table.minimumVisibleRows = 2
            table.maximumVisibleRows = 8
            table.columnSpacing = 1
            table.rowSpacing = 1

            add_btn = inputs.addBoolValueInput('profileAdd', 'Add', False, '', False)
            add_btn.tooltip = 'Add an export profile'
            del_btn = inputs.addBoolValueInput('profileDelete', 'Remove', False, '', False)
            del_btn.tooltip = 'Remove the selected export profile'
            table.addToolbarCommandInput(add_btn)
            table.addToolbarCommandInput(del_btn)

            for profile in settings['profiles']:
                _add_profile_row(table, profile)

            if not _component_name_cache:
                note = inputs.addTextBoxCommandInput('compNote', '', '', 2, True)
                note.text = ('Open your source design before running to pick components '
                             'for "Named components" profiles.')

            on_exec = CommandExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)

            on_changed = BuildInputChangedHandler()
            cmd.inputChanged.add(on_changed)
            _handlers.append(on_changed)
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
```

- [ ] **Step 3: Add the `BuildInputChangedHandler`**

Add this class next to the other handlers:

```python
class BuildInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            changed = args.input
            table = args.inputs.itemById('profiles')
            if table is None:
                return
            if changed.id == 'profileAdd':
                existing = [table.getInputAtPosition(r, 1).id[3:] for r in range(table.rowCount)]
                pid = sheet_core.next_profile_id(existing)
                _add_profile_row(table, {'id': pid, 'name': 'Export ' + pid,
                                         'enabled': True, 'rule': 'whole_model', 'components': []})
            elif changed.id == 'profileDelete':
                if table.selectedRow >= 0:
                    table.deleteRow(table.selectedRow)
            elif changed.id.startswith('rl_'):
                pid = changed.id[3:]
                for r in range(table.rowCount):
                    cp = table.getInputAtPosition(r, 3)
                    if cp.id == 'cp_' + pid:
                        cp.isVisible = _rule_is_named(changed)
                        break
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
```

- [ ] **Step 4: Update `CommandExecuteHandler.notify` to read the table**

Replace its body with:

```python
        try:
            inputs = args.command.commandInputs
            url = inputs.itemById('sheetUrl').value.strip()
            spacing_cm = inputs.itemById('spacing').value
            if not url:
                ui.messageBox('Please paste the Google Sheet URL.')
                return

            profiles = _read_profiles(inputs.itemById('profiles'))
            sheet_core.save_settings(SETTINGS_FILE, {
                'sheet_url': url, 'spacing_mm': spacing_cm * 10.0, 'profiles': profiles})

            results = build_exports(url, spacing_cm, profiles)
            ui.messageBox(sheet_core.summarize_results(results))
        except Exception:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
```

- [ ] **Step 5: Byte-compile and lint**

Run:

```bash
python3 -m py_compile SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
python3 -m pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
```

Expected: no output.

- [ ] **Step 6: Manual Fusion test** *(manual, user-run)*

Ask the user to reload the add-in and verify in Fusion:
1. Build dialog shows URL, gap, and a profiles table with the default "Full model" row.
2. **Add** creates a new row; setting its rule to **Named components** reveals the components checkbox-dropdown populated from the open design; ticking `Gordijnplaat` and running produces a second design with only that component per variant.
3. **Remove** deletes the selected row.
4. Settings persist across dialog re-opens (profiles reload from `settings.json`).
5. A profile with no enabled rows / no matching components is reported in the summary, not crashed.

Do not proceed until the user confirms.

- [ ] **Step 7: Commit** *(ask the user first, after their manual confirmation)*

```bash
git add SheetVariants/SheetVariants.py
git commit -m "Add combined Build dialog with editable export profiles table"
```

---

### Task 8: CI test step + docs

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `SheetVariants/SheetVariants.py` (module header comment, lines 1–14)

**Interfaces:**
- Consumes: the `tests/` suite and `sheet_core` from Tasks 1–4.

- [ ] **Step 1: Add a pytest step to CI and lint both files**

In `.github/workflows/ci.yml`, update the pyflakes step to lint both files and add a test step after it:

```yaml
      - name: Lint for real errors (pyflakes)
        run: |
          python -m pip install --upgrade pyflakes
          pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py

      - name: Run unit tests
        run: |
          python -m pip install --upgrade -r requirements-dev.txt
          python -m pytest tests/ -v
```

- [ ] **Step 2: Verify the full check suite locally**

Run:

```bash
python3 -m py_compile SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
python3 -m json.tool SheetVariants/SheetVariants.manifest > /dev/null
python3 -m pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py
python3 -m pytest tests/ -v
```

Expected: all pass, pytest reports all tests passing.

- [ ] **Step 3: Update the README**

In `README.md`, update the **Features** and **Workflow** sections to describe export profiles: multiple named profiles (whole model / named components), each producing its own new design, edited in the Build dialog. Replace the outdated "one component per variant into a new design" single-behaviour wording. Add a short "Export profiles" subsection explaining the profiles table and that missing components are warned, not fatal.

- [ ] **Step 4: Fix the stale module header comment**

The top-of-file comment in `SheetVariants.py` still says it exports each variant "as SAT". Update lines 1–14 to describe the profile-based, in-memory multi-design behaviour (no SAT export).

- [ ] **Step 5: Commit** *(ask the user first)*

```bash
git add .github/workflows/ci.yml README.md SheetVariants/SheetVariants.py
git commit -m "Run unit tests in CI and document export profiles"
```

---

## Notes for the implementer

- **Fusion sibling import:** `sheet_core` resolves because Task 5 inserts the add-in folder onto `sys.path`. During development, Fusion caches modules across add-in stop/start; if you change `sheet_core.py` and don't see the change, fully restart Fusion (or the add-in) so the module reloads.
- **Table child input ids** must be globally unique within the command. They are suffixed with the profile `id` (`en_p1`, `nm_p1`, …); `next_profile_id` guarantees fresh ids for added rows.
- **The pure/impure split is the safety net:** anything that can be tested without Fusion lives in `sheet_core` and is covered by pytest; the Fusion-API code is thin and exercised manually. Keep new logic on the pure side wherever possible.
- **Future rules** (`sheet_metal`, `thickness`) plug into `RESOLVERS` plus a UI affordance and a `VALID_RULES` entry — no change to `build_exports`.
