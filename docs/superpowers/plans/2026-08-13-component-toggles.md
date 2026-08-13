# Component on/off columns — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a sheet row switch a top-level component off for that variant, using a column whose header is the component's name and `TRUE`/`FALSE` in the cells.

**Architecture:** All header/cell interpretation lives in `sheet_core.py` as pure functions with unit tests. The Fusion side changes one thing structurally: geometry collection stops flattening the assembly with `allOccurrences` and becomes a recursive walk from `root.occurrences` that prunes an off component's whole subtree. Both export resolvers go through that walk, which is what makes "off wins over a profile's include list" structural rather than a second rule.

**Tech Stack:** Python 3 (Fusion's bundled interpreter — standard library only), pytest, Autodesk Fusion API (`adsk.core`, `adsk.fusion`).

**Spec:** [`docs/superpowers/specs/2026-08-12-component-toggles-design.md`](../specs/2026-08-12-component-toggles-design.md)

## Global Constraints

- `sheet_core.py` **MUST NOT** import `adsk` — it is imported and unit-tested outside Fusion.
- Standard library only. No new dependencies; Fusion's bundled Python cannot easily install packages.
- The source model must never be modified by a build. No suppression, no visibility change, nothing to restore. (The Test tab preview is the sole exception, and it reverts.)
- Existing sheets must keep working byte-identically. A column that matched a parameter before still matches a parameter.
- `validate_mapping`'s two new arguments **MUST** have empty defaults so existing call sites and tests are unaffected.
- Accepted on-words: `true`, `1`, `yes`, `y`, `on`. Off-words: `false`, `0`, `no`, `n`, `off`. Case-insensitive, whitespace stripped.
- Blank toggle cell → component stays **in**.
- Unrecognised toggle value → Check **error**, build blocked.
- Run `python3 -m pytest -q` from the repo root. Baseline is **144 passing**.
- Commit after each task (this is not firmware; no HIL gate applies).

## Deviation from the spec (accepted)

The spec's sub-component error message names the parent: `Column "Side_L" is a sub-component of "Carcass"`. This plan drops the parent from the message:

> `Column "Side_L" is a sub-component — only top-level components can be switched on or off.`

Reason: a component can be nested under more than one parent, so naming a single parent can state something false. The name alone is enough for the designer to find it, and a message that cannot lie is worth more than one that is slightly more specific.

## Note on component-name uniqueness

Fusion component names are unique within a design, so an off name identifies exactly one component wherever it appears in the tree. The walk therefore checks the off-set at **every** depth, not only at depth 1. If `Drawer` sits both at the top level and nested inside `Carcass`, switching it off removes both — they are the same component.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `SheetVariants/sheet_core.py` | Pure sheet interpretation, settings, validation | Add `parse_toggle`, `classify_columns`, `row_toggles`; extend `validate_mapping`, `ValidationReport`, `summarize_results` |
| `SheetVariants/SheetVariants.py` | Fusion UI + geometry collection | Add `top_level_component_names`, `_occurrence_solid_bodies`; rewrite `iter_solid_bodies`, `_component_solid_bodies`; wire resolvers, `build_exports`, `_run_build_validation`, `_preview_test_row`, `create_template` |
| `tests/test_sheet_core.py` | Unit tests for the pure layer | Add tests per task |
| `README.md` | User documentation | Document toggle columns |
| `docs/superpowers/plans/2026-08-13-component-toggles-verification.md` | Manual Fusion checklist | Create |

---

### Task 1: `parse_toggle` — cell value semantics

**Files:**
- Modify: `SheetVariants/sheet_core.py` (add after `classify_value`, ~line 308)
- Test: `tests/test_sheet_core.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_toggle(text) -> True | False | None`. `None` means unrecognised. Blank/whitespace returns `True`.

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_sheet_core.py`:

```python
def test_parse_toggle_on_words():
    for text in ("TRUE", "true", " True ", "1", "yes", "Y", "on", "ON"):
        assert sheet_core.parse_toggle(text) is True, text


def test_parse_toggle_off_words():
    for text in ("FALSE", "false", " False ", "0", "no", "N", "off", "OFF"):
        assert sheet_core.parse_toggle(text) is False, text


def test_parse_toggle_blank_keeps_the_component():
    # A blank cell must mean "in", matching the existing rule that a blank
    # parameter cell leaves that parameter unchanged.
    assert sheet_core.parse_toggle("") is True
    assert sheet_core.parse_toggle("   ") is True
    assert sheet_core.parse_toggle(None) is True


def test_parse_toggle_unrecognised_is_none():
    # None is distinct from False: a typo must be reportable as an error
    # rather than silently removing a component.
    for text in ("maybe", "2", "-1", "true-ish", "aan"):
        assert sheet_core.parse_toggle(text) is None, text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_sheet_core.py -k parse_toggle -q`
Expected: FAIL — `AttributeError: module 'sheet_core' has no attribute 'parse_toggle'`

- [ ] **Step 3: Write the implementation**

Add to `SheetVariants/sheet_core.py`, immediately after `classify_value`:

```python
TOGGLE_ON = ("true", "1", "yes", "y", "on")
TOGGLE_OFF = ("false", "0", "no", "n", "off")


def parse_toggle(text):
    """Read a component on/off cell.

    Returns True (component stays in), False (component is dropped for this
    variant), or None for a value that is neither — which the caller must
    report as an error rather than guess at. A blank cell returns True,
    matching the existing rule that a blank parameter cell leaves things
    unchanged; the alternative would make adding a column to a long sheet
    mean editing every row.

    None is deliberately distinct from False. A typo that silently meant
    "off" would be invisible in the output, because a missing part looks
    exactly like a part you meant to remove.
    """
    s = (text or "").strip().lower()
    if s == "":
        return True
    if s in TOGGLE_ON:
        return True
    if s in TOGGLE_OFF:
        return False
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_sheet_core.py -k parse_toggle -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 148 passed

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "feat: read a component on/off cell"
```

---

### Task 2: `classify_columns` — header interpretation

**Files:**
- Modify: `SheetVariants/sheet_core.py` (add after `parse_toggle`)
- Test: `tests/test_sheet_core.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent).
- Produces:

```python
classify_columns(header, param_names, top_level_names, all_component_names=()) -> dict
```

Returns a dict with exactly these five keys:

| Key | Type | Meaning |
|---|---|---|
| `"parameters"` | `[(col_index, name), ...]` | Parameter columns. `col_index` indexes the **row**, so column A is 0 and the first header after `Name` is 1 |
| `"toggles"` | `[(col_index, name), ...]` | Component on/off columns, same indexing |
| `"unknown"` | `[name, ...]` | Headers matching neither a parameter nor any component |
| `"sub_components"` | `[name, ...]` | Headers matching a component that is not top-level |
| `"collisions"` | `[name, ...]` | Headers matching both a parameter and a top-level component; these appear in `"parameters"` |

Column A (`header[0]`) is never classified — it is the variant name.

- [ ] **Step 1: Write the failing tests**

```python
def test_classify_columns_splits_parameters_and_toggles():
    cols = sheet_core.classify_columns(
        ["Name", "length", "Drawer"],
        param_names={"length"},
        top_level_names=["Carcass", "Drawer"])
    assert cols["parameters"] == [(1, "length")]
    assert cols["toggles"] == [(2, "Drawer")]
    assert cols["unknown"] == []
    assert cols["sub_components"] == []
    assert cols["collisions"] == []


def test_classify_columns_parameter_wins_a_collision():
    # Preserves today's behaviour: a column that matched a parameter before
    # this feature existed must still be read as a parameter.
    cols = sheet_core.classify_columns(
        ["Name", "Door"],
        param_names={"Door"},
        top_level_names=["Door"])
    assert cols["parameters"] == [(1, "Door")]
    assert cols["toggles"] == []
    assert cols["collisions"] == ["Door"]


def test_classify_columns_flags_a_sub_component():
    cols = sheet_core.classify_columns(
        ["Name", "Side_L"],
        param_names=set(),
        top_level_names=["Carcass"],
        all_component_names=["Carcass", "Side_L"])
    assert cols["sub_components"] == ["Side_L"]
    assert cols["toggles"] == []
    assert cols["unknown"] == []


def test_classify_columns_flags_an_unknown_header():
    cols = sheet_core.classify_columns(
        ["Name", "Drawr"],
        param_names={"length"},
        top_level_names=["Drawer"],
        all_component_names=["Drawer"])
    assert cols["unknown"] == ["Drawr"]
    assert cols["sub_components"] == []


def test_classify_columns_ignores_column_a_and_strips_whitespace():
    cols = sheet_core.classify_columns(
        ["Name", " length ", " Drawer "],
        param_names={"length"},
        top_level_names=["Drawer"])
    assert cols["parameters"] == [(1, "length")]
    assert cols["toggles"] == [(2, "Drawer")]


def test_classify_columns_with_no_components_matches_todays_behaviour():
    # Called with the defaults, every non-parameter column is unknown, exactly
    # as before this feature existed.
    cols = sheet_core.classify_columns(
        ["Name", "length", "bogus"], param_names={"length"}, top_level_names=[])
    assert cols["parameters"] == [(1, "length")]
    assert cols["unknown"] == ["bogus"]
    assert cols["toggles"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_sheet_core.py -k classify_columns -q`
Expected: FAIL — `AttributeError: module 'sheet_core' has no attribute 'classify_columns'`

- [ ] **Step 3: Write the implementation**

Add to `SheetVariants/sheet_core.py`, after `parse_toggle`:

```python
def classify_columns(header, param_names, top_level_names, all_component_names=()):
    """Decide what each header column after "Name" means, against the model.

    A header is a parameter column, a component on/off column, or a problem.
    Precedence is deliberate: a name that is BOTH a parameter and a top-level
    component is read as a parameter, so no sheet that worked before this
    feature can change meaning. The collision is reported so the designer is
    not left guessing which way it went.

    A header naming a component that exists but is not top-level is separated
    from a header naming nothing at all, because they need different advice:
    one is "this cannot be switched off", the other is "this is a typo".

    Column indices are into the ROW, so column A ("Name") is 0 and the first
    header after it is 1. That is what row_toggles and the build loop index
    with, so no caller has to remember an offset.
    """
    params = set(param_names or ())
    top_level = set(top_level_names or ())
    all_components = set(all_component_names or ()) | top_level

    out = {"parameters": [], "toggles": [], "unknown": [],
           "sub_components": [], "collisions": []}
    for index, raw in enumerate(header or []):
        if index == 0:
            continue                      # column A is the variant name
        name = (raw or "").strip()
        if not name:
            continue
        if name in params:
            out["parameters"].append((index, name))
            if name in top_level:
                out["collisions"].append(name)
        elif name in top_level:
            out["toggles"].append((index, name))
        elif name in all_components:
            out["sub_components"].append(name)
        else:
            out["unknown"].append(name)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_sheet_core.py -k classify_columns -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 154 passed

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "feat: classify a sheet header into parameter and component columns"
```

---

### Task 3: `row_toggles` — one row's off-set

**Files:**
- Modify: `SheetVariants/sheet_core.py` (add after `classify_columns`)
- Test: `tests/test_sheet_core.py`

**Interfaces:**
- Consumes: `parse_toggle` (Task 1); the `"toggles"` list shape from `classify_columns` (Task 2) — `[(col_index, name), ...]`.
- Produces: `row_toggles(row, toggle_columns) -> {component_name: bool}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_row_toggles_reads_each_column():
    result = sheet_core.row_toggles(
        ["Unit_S", "500 mm", "FALSE", "TRUE"],
        [(2, "Drawer"), (3, "Door")])
    assert result == {"Drawer": False, "Door": True}


def test_row_toggles_treats_a_short_row_as_blank():
    # Trailing blank cells are often omitted entirely; a missing cell must
    # mean "in", the same as an explicitly blank one.
    result = sheet_core.row_toggles(["Unit_S", "500 mm"], [(2, "Drawer")])
    assert result == {"Drawer": True}


def test_row_toggles_keeps_the_component_on_an_unrecognised_value():
    # Check blocks the build before this can happen. If it ever does, failing
    # toward keeping the part is the recoverable direction: an extra part is
    # visible, a missing one is not.
    result = sheet_core.row_toggles(["Unit_S", "maybe"], [(1, "Drawer")])
    assert result == {"Drawer": True}


def test_row_toggles_rightmost_duplicate_column_wins():
    result = sheet_core.row_toggles(
        ["Unit_S", "TRUE", "FALSE"], [(1, "Drawer"), (2, "Drawer")])
    assert result == {"Drawer": False}


def test_row_toggles_with_no_toggle_columns_is_empty():
    assert sheet_core.row_toggles(["Unit_S", "500 mm"], []) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_sheet_core.py -k row_toggles -q`
Expected: FAIL — `AttributeError: module 'sheet_core' has no attribute 'row_toggles'`

- [ ] **Step 3: Write the implementation**

```python
def row_toggles(row, toggle_columns):
    """{component name: is it in} for one variant row.

    A cell the row does not reach is treated as blank (component stays in):
    a spreadsheet often omits trailing empty cells entirely, and the parameter
    path already treats a short row the same way.

    An unrecognised value also keeps the component. validate_mapping blocks
    the build before a build can ever see one, so this is a defensive default
    rather than a rule — and it fails toward the recoverable direction, since
    an unwanted part is visible in the output while a missing one is not.

    Keyed by component name, so if the same component is named by two columns
    the rightmost wins.
    """
    out = {}
    for index, name in toggle_columns or []:
        raw = row[index] if index < len(row) else ""
        value = parse_toggle(raw)
        out[name] = True if value is None else value
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_sheet_core.py -k row_toggles -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 159 passed

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "feat: resolve one row's component on/off values"
```

---

### Task 4: Check report — errors, warnings and summary

**Files:**
- Modify: `SheetVariants/sheet_core.py` — `ValidationReport` (~line 320) and `validate_mapping` (~line 350)
- Test: `tests/test_sheet_core.py`

**Interfaces:**
- Consumes: `classify_columns` (Task 2), `parse_toggle` (Task 1), existing `classify_value` and `_cell_ref`.
- Produces:

```python
validate_mapping(header, rows, known_param_names, driveable_param_names,
                 top_level_names=(), all_component_names=()) -> ValidationReport
```

`ValidationReport` gains `self.toggle_columns = 0`. When it is 0, `summary()` returns exactly today's string.

- [ ] **Step 1: Write the failing tests**

```python
def test_validate_toggle_column_is_accepted():
    header = ["Name", "diameter", "Drawer"]
    rows = [["V1", "18 mm", "FALSE"]]
    rep = sheet_core.validate_mapping(
        header, rows, {"diameter"}, ["diameter"],
        top_level_names=["Drawer"], all_component_names=["Drawer"])
    assert rep.ok
    assert rep.toggle_columns == 1
    assert "1 on/off" in rep.summary()


def test_validate_summary_unchanged_when_there_are_no_toggles():
    header = ["Name", "diameter", "hoogte"]
    rows = [["V1", "18 mm", "5 mm"], ["V2", "20 mm", "6 mm"]]
    rep = sheet_core.validate_mapping(header, rows, {"diameter", "hoogte"},
                                      ["diameter", "hoogte"])
    assert rep.summary() == "✓ 2 columns mapped, 2 rows OK"


def test_validate_bad_toggle_value_is_error_with_cell_ref():
    header = ["Name", "Drawer"]
    rows = [["V1", "TRUE"], ["V2", "maybe"]]
    rep = sheet_core.validate_mapping(
        header, rows, set(), [], top_level_names=["Drawer"])
    assert not rep.ok
    assert any("maybe" in e and "B3" in e for e in rep.errors)


def test_validate_blank_toggle_cells_are_their_own_warning():
    header = ["Name", "Drawer"]
    rows = [["V1", ""], ["V2", ""]]
    rep = sheet_core.validate_mapping(
        header, rows, set(), [], top_level_names=["Drawer"])
    assert rep.ok
    assert any("2 blank on/off cell(s)" in w and "stay in" in w
               for w in rep.warnings)
    # Must NOT be counted as a parameter "empty cell" — that message says
    # "left unchanged", which is the wrong thing to tell someone about a toggle.
    assert not any("left unchanged" in w for w in rep.warnings)


def test_validate_sub_component_column_is_error():
    header = ["Name", "Side_L"]
    rows = [["V1", "TRUE"]]
    rep = sheet_core.validate_mapping(
        header, rows, set(), [], top_level_names=["Carcass"],
        all_component_names=["Carcass", "Side_L"])
    assert not rep.ok
    assert any("Side_L" in e and "sub-component" in e for e in rep.errors)


def test_validate_unknown_column_mentions_components_now():
    header = ["Name", "Drawr"]
    rows = [["V1", "TRUE"]]
    rep = sheet_core.validate_mapping(
        header, rows, set(), [], top_level_names=["Drawer"])
    assert not rep.ok
    assert any("Drawr" in e and "component" in e for e in rep.errors)


def test_validate_collision_is_a_warning_not_an_error():
    header = ["Name", "Door"]
    rows = [["V1", "18 mm"]]
    rep = sheet_core.validate_mapping(
        header, rows, {"Door"}, ["Door"], top_level_names=["Door"])
    assert rep.ok
    assert any("Door" in w and "read as a parameter" in w for w in rep.warnings)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_sheet_core.py -k "validate_toggle or validate_summary_unchanged or validate_bad_toggle or validate_blank_toggle or validate_sub_component or validate_unknown_column or validate_collision" -q`
Expected: FAIL — `TypeError: validate_mapping() got an unexpected keyword argument 'top_level_names'`

- [ ] **Step 3: Extend `ValidationReport`**

In `SheetVariants/sheet_core.py`, change `ValidationReport.__init__` and `summary`:

```python
class ValidationReport:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.mapped_columns = 0
        self.toggle_columns = 0
        self.row_count = 0

    @property
    def ok(self):
        return not self.errors

    def summary(self):
        # The on/off clause is omitted entirely when there are none, so a
        # sheet with no toggle columns produces the exact string it always did.
        toggles = ", {} on/off".format(self.toggle_columns) if self.toggle_columns else ""
        if self.ok and not self.warnings:
            return "✓ {} columns mapped{}, {} rows OK".format(
                self.mapped_columns, toggles, self.row_count)
        if self.ok:
            return "✓ {} columns mapped{}, {} rows — {} warning(s)".format(
                self.mapped_columns, toggles, self.row_count, len(self.warnings))
        return "✗ {} error(s), {} warning(s) — fix before building".format(
            len(self.errors), len(self.warnings))
```

- [ ] **Step 4: Rewrite `validate_mapping`**

Replace the whole of `validate_mapping` with:

```python
def validate_mapping(header, rows, known_param_names, driveable_param_names,
                     top_level_names=(), all_component_names=()):
    rep = ValidationReport()
    rep.row_count = len(rows)
    header = [h.strip() for h in header]

    if not header or header[0] != "Name":
        rep.errors.append('The first column header must be "Name".')
        return rep

    cols = classify_columns(header, known_param_names, top_level_names,
                            all_component_names)
    rep.mapped_columns = len(cols["parameters"])
    rep.toggle_columns = len(cols["toggles"])

    for name in cols["unknown"]:
        rep.errors.append(
            'Column "{}" matches no parameter or top-level component in the model.'
            .format(name))
    for name in cols["sub_components"]:
        rep.errors.append(
            'Column "{}" is a sub-component — only top-level components can be '
            'switched on or off.'.format(name))
    for name in cols["collisions"]:
        rep.warnings.append(
            'Column "{}" is both a parameter and a component — read as a parameter.'
            .format(name))

    covered = set(name for _, name in cols["parameters"])
    for pname in driveable_param_names:
        if pname not in covered:
            rep.warnings.append(
                'Parameter "{}" has no column — keeps its current value.'.format(pname))

    empty_count = 0
    blank_toggles = 0
    for ri, row in enumerate(rows, start=2):  # row 2 = first data row in the sheet
        for ci, name in cols["parameters"]:
            val = row[ci] if ci < len(row) else ""
            kind = classify_value(val)
            if kind == "comma_decimal":
                rep.errors.append(
                    'Cell {} ("{}") looks like a comma decimal — use a dot and a unit, e.g. "18.2 mm".'
                    .format(_cell_ref(ci, ri), val.strip()))
            elif kind == "empty":
                empty_count += 1
        for ci, name in cols["toggles"]:
            val = row[ci] if ci < len(row) else ""
            if not (val or "").strip():
                blank_toggles += 1
            elif parse_toggle(val) is None:
                rep.errors.append(
                    'Cell {} ("{}") is not a yes/no value — use TRUE or FALSE.'
                    .format(_cell_ref(ci, ri), val.strip()))
    if empty_count:
        rep.warnings.append("{} empty cell(s) left unchanged.".format(empty_count))
    if blank_toggles:
        rep.warnings.append(
            "{} blank on/off cell(s) — those components stay in.".format(blank_toggles))
    return rep
```

- [ ] **Step 5: Run the new tests**

Run: `python3 -m pytest tests/test_sheet_core.py -k "validate" -q`
Expected: PASS — all validate tests, new and pre-existing

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 166 passed. If any pre-existing test fails, the behaviour-preservation constraint is broken — fix the implementation, not the old test.

- [ ] **Step 7: Commit**

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "feat: validate component on/off columns in the Check report"
```

---

### Task 5: Report skipped variants in the run summary

**Files:**
- Modify: `SheetVariants/sheet_core.py` — `summarize_results` (~line 152)
- Test: `tests/test_sheet_core.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `summarize_results` reads an optional `"skipped_variants"` key (list of variant names) on each result dict. Task 7 populates it.

- [ ] **Step 1: Write the failing tests**

```python
def test_summarize_reports_variants_that_had_nothing_to_build():
    results = [{"name": "Kitchen", "built": 2, "skipped_variants": ["Unit_X"]}]
    text = sheet_core.summarize_results(results)
    assert "Kitchen (2 variant(s))" in text
    assert "Unit_X" in text
    assert "nothing to build" in text


def test_summarize_combines_warnings_and_skipped_variants():
    results = [{"name": "Kitchen", "built": 1,
                "warnings": ["component(s) not found: Ghost"],
                "skipped_variants": ["Unit_X", "Unit_Y"]}]
    text = sheet_core.summarize_results(results)
    assert "Ghost" in text
    assert "2 variant(s)" in text
    assert "Unit_X, Unit_Y" in text


def test_summarize_unchanged_without_skipped_variants():
    results = [{"name": "Full model", "built": 3}]
    assert sheet_core.summarize_results(results) == (
        "Built:\n  • Full model (3 variant(s))")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_sheet_core.py -k summarize -q`
Expected: FAIL on the first two — the skipped-variant text is absent

- [ ] **Step 3: Write the implementation**

Replace the `built` loop inside `summarize_results`:

```python
def summarize_results(results):
    """Build the end-of-run message box text from per-profile result dicts."""
    lines = []
    built = [r for r in results if not r.get("skipped")]
    if built:
        lines.append("Built:")
        for r in built:
            # Variants dropped by their component toggles are reported, never
            # silent: a variant missing from an output design with no
            # explanation reads as a bug in the add-in.
            notes = list(r.get("warnings") or [])
            dropped = r.get("skipped_variants") or []
            if dropped:
                notes.append("{} variant(s) had nothing to build: {}".format(
                    len(dropped), ", ".join(dropped)))
            warn = (" — " + "; ".join(notes)) if notes else ""
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_sheet_core.py -k summarize -q`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 169 passed

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "feat: name the variants a profile had nothing to build"
```

---

### Task 6: Prune off components when collecting geometry

**Files:**
- Modify: `SheetVariants/SheetVariants.py:235-299` (`iter_solid_bodies`, `component_names`, `_component_solid_bodies`, both resolvers)

**Interfaces:**
- Consumes: nothing from the pure layer.
- Produces:
  - `top_level_component_names(design) -> [str]`
  - `iter_solid_bodies(design, off_names=())` — generator of solid bodies
  - `resolve_whole_model(design, profile, off_names=())` → `(bodies, warnings)`
  - `resolve_named_components(design, profile, off_names=())` → `(bodies, warnings)`

`component_names(design)` keeps its current signature and meaning (every component at any depth) — it still backs the profile picker.

**No unit tests.** This module imports `adsk` and cannot be imported outside Fusion; Task 12's manual checklist is its verification. Do not add a test file for it.

- [ ] **Step 1: Add `top_level_component_names`**

Insert after `component_names` (~line 259):

```python
def top_level_component_names(design):
    """Distinct component names among the root's DIRECT children, in order of
    first appearance. These are the only components a sheet column can switch
    off — deliberately narrower than component_names(), which reaches every
    depth and backs the export-profile picker."""
    names, seen = [], set()
    for occ in design.rootComponent.occurrences:
        try:
            n = occ.component.name
        except Exception:
            continue
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    return names
```

- [ ] **Step 2: Replace `iter_solid_bodies` with the pruning walk**

Replace lines 235-245 (the whole of `iter_solid_bodies`) with:

```python
def _occurrence_solid_bodies(occ, off):
    """Solid bodies of an occurrence and its descendants, pruning any component
    in ``off`` along with everything beneath it.

    Component names are unique within a Fusion design, so a name in ``off``
    identifies one component wherever it sits in the tree; the check is applied
    at every depth rather than only at the top, which keeps the answer the same
    whether a component is placed at the root or nested.
    """
    try:
        name = occ.component.name
    except Exception:
        name = ''
    if name in off:
        return
    for b in occ.bRepBodies:
        if b.isSolid:
            yield b
    for child in occ.childOccurrences:
        for b in _occurrence_solid_bodies(child, off):
            yield b


def iter_solid_bodies(design, off_names=()):
    """Yield every solid BRepBody in the design, as proxies positioned in their
    assembly-context (world) location, skipping components switched off for
    this variant.

    Walks down from root.occurrences rather than flattening with
    allOccurrences, so an off component can take its whole subtree with it.
    Filtering a flat list afterwards would mean comparing body proxies for
    identity, which this avoids entirely.

    Bodies owned by the root component itself belong to no occurrence, so no
    column can address them; they are always included.
    """
    off = set(off_names or ())
    root = design.rootComponent
    for b in root.bRepBodies:
        if b.isSolid:
            yield b
    for occ in root.occurrences:
        for b in _occurrence_solid_bodies(occ, off):
            yield b
```

- [ ] **Step 3: Replace `_component_solid_bodies` with a pruning walk**

Replace lines 267-284 with:

```python
def _component_solid_bodies(design, included_names, off_names=()):
    """Solid bodies of the selected components — one representative occurrence
    per component name, so a part exports once rather than once per instance.

    Uses the same pruning walk as iter_solid_bodies, which is what makes a
    variant's toggles win over a profile's include list: a profile naming a
    sub-component of a switched-off component finds nothing, because the walk
    never descends into it.
    """
    off = set(off_names or ())
    wanted = set(included_names)
    got = {}

    def visit(occ):
        try:
            cname = occ.component.name
        except Exception:
            return
        if cname in off:
            return                       # prune this component and its subtree
        if cname in wanted and cname not in got:
            bodies = [b for b in occ.bRepBodies if b.isSolid]
            if bodies:
                got[cname] = bodies
        for child in occ.childOccurrences:
            visit(child)

    for occ in design.rootComponent.occurrences:
        visit(occ)

    out = []
    for name in included_names:
        out.extend(got.get(name, []))
    return out
```

- [ ] **Step 4: Thread `off_names` through both resolvers**

Replace `resolve_whole_model` and `resolve_named_components`:

```python
def resolve_whole_model(design, profile, off_names=()):
    """Every solid body in the design, minus components switched off for this
    variant."""
    return list(iter_solid_bodies(design, off_names)), []


def resolve_named_components(design, profile, off_names=()):
    present = component_names(design)
    included, missing = sheet_core.select_component_names(present, profile.get('components', []))
    warnings = []
    if missing:
        warnings.append("component(s) not found: " + ", ".join(missing))
    return _component_solid_bodies(design, included, off_names), warnings
```

- [ ] **Step 5: Verify the module still parses**

Run: `python3 -c "import ast,sys; ast.parse(open('SheetVariants/SheetVariants.py').read()); print('parses OK')"`
Expected: `parses OK`

This is a syntax check only. The module cannot be imported outside Fusion (it imports `adsk`), and nothing here is proven to work until Task 12.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 169 passed (unchanged — no pure code was touched)

- [ ] **Step 7: Commit**

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat: prune switched-off components when collecting geometry"
```

---

### Task 7: Wire toggles into the build

**Files:**
- Modify: `SheetVariants/SheetVariants.py` — `build_exports` (~lines 302-348 and the per-row loop at 365-392)

**Interfaces:**
- Consumes: `classify_columns`, `row_toggles` (Tasks 2-3); `top_level_component_names`, the `off_names` resolver argument (Task 6); the `"skipped_variants"` key (Task 5).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Replace the header/parameter validation block**

In `build_exports`, replace from `param_names = header[1:]` down to and including the `missing = [...]` guard (currently lines 311-320) with:

```python
    src_design = adsk.fusion.Design.cast(app.activeProduct)
    if not src_design:
        raise RuntimeError('Open the parametric source model as the active design before running this command.')

    # Classify the header against the model once: parameter columns get
    # applied, component columns switch parts off per row. Only headers that
    # match neither are fatal — a toggle column is not a missing parameter.
    cols = sheet_core.classify_columns(
        header, known_param_names(src_design),
        top_level_component_names(src_design), component_names(src_design))
    param_columns = cols['parameters']
    toggle_columns = cols['toggles']
    param_names = [name for _, name in param_columns]

    if cols['unknown']:
        raise RuntimeError('These columns do not match any parameter or top-level '
                           'component in the model: ' + ', '.join(cols['unknown']))
    if cols['sub_components']:
        raise RuntimeError('These columns name sub-components, which cannot be '
                           'switched on or off: ' + ', '.join(cols['sub_components']))
```

Delete the now-redundant `src_design = ...` block that followed the old `param_names` line, and the `all_params = src_design.allParameters` line together with the `missing` guard that used it. Keep everything from `enabled = [p for p in profiles if p.get('enabled')]` onward.

- [ ] **Step 2: Replace the per-row apply block**

Replace the body of the row loop from `values = {}` through the `for ctx in active:` block (currently lines 376-391) with:

```python
                # Re-derive design + parameter FRESH for every apply: setting a
                # driving dimension recomputes the model, which can invalidate the
                # parameter collection (see build_engine._design()'s docstring).
                values = {}
                for col, pname in param_columns:
                    if col < len(row):
                        val = row[col].strip()
                        if val:
                            values[pname] = val
                build_engine.apply_values(values)
                adsk.doEvents()  # recompute the source with this variant's values

                # Components this row switches off. Purely a read of the sheet —
                # the source model is never modified, the bodies are simply not
                # collected below.
                toggles = sheet_core.row_toggles(row, toggle_columns)
                off_names = [name for name, keep in toggles.items() if not keep]

                design = adsk.fusion.Design.cast(app.activeProduct)  # fresh after recompute
                for ctx in active:
                    resolver = RESOLVERS[ctx['profile']['rule']]
                    src_bodies, _warn = resolver(design, ctx['profile'], off_names)
                    snaps = build_engine.snapshot_bodies(src_bodies)
                    if snaps:
                        ctx.setdefault('variants', []).append((safe_name, snaps))
                    else:
                        ctx.setdefault('skipped_variants', []).append(safe_name)
                progress.progressValue = i + 1
```

- [ ] **Step 3: Verify the module still parses**

Run: `python3 -c "import ast; ast.parse(open('SheetVariants/SheetVariants.py').read()); print('parses OK')"`
Expected: `parses OK`

- [ ] **Step 4: Confirm no stale references remain**

Run: `grep -n "all_params\|param_names = header" SheetVariants/SheetVariants.py`
Expected: no matches inside `build_exports`. (`known_param_names` and `driveable_param_names` at lines 179-185 are separate helpers and must stay.)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 169 passed

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat: apply each row's component toggles when building"
```

---

### Task 8: Show the classification in the Check report

**Files:**
- Modify: `SheetVariants/SheetVariants.py` — `_run_build_validation` (~line 647)

**Interfaces:**
- Consumes: `validate_mapping`'s new arguments (Task 4), `top_level_component_names` (Task 6).
- Produces: nothing.

- [ ] **Step 1: Pass the model's component names to the validator**

Replace the `rep = sheet_core.validate_mapping(...)` call:

```python
    rep = sheet_core.validate_mapping(
        rows[0], rows[1:], known_param_names(design), driveable_param_names(design),
        top_level_component_names(design), component_names(design))
```

- [ ] **Step 2: Verify the module still parses**

Run: `python3 -c "import ast; ast.parse(open('SheetVariants/SheetVariants.py').read()); print('parses OK')"`
Expected: `parses OK`

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 169 passed

- [ ] **Step 4: Commit**

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat: validate component columns against the open model"
```

---

### Task 9: Emit toggle columns in the generated template

**Files:**
- Modify: `SheetVariants/SheetVariants.py` — `create_template` (~line 525) and `TemplateExecuteHandler.notify` (~line 950)

**Interfaces:**
- Consumes: `top_level_component_names` (Task 6).
- Produces: `create_template(use_favorites) -> (path, param_count, component_count)`. **The return arity changes from 2 to 3** — its only caller is updated in the same task.

- [ ] **Step 1: Add the component columns**

In `create_template`, replace the `header = [...]` / `example = [...]` pair and the `return`:

```python
    # One TRUE column per top-level component, so the on/off feature is
    # visible without reading the docs. TRUE everywhere is exactly today's
    # behaviour, so a generated template still builds an identical result.
    # A component sharing a parameter's name is skipped: the parameter wins
    # when the header is classified, so the column would never be read as a
    # toggle.
    design = adsk.fusion.Design.cast(app.activeProduct)
    param_names = set(p.name for p in params)
    comp_names = [n for n in top_level_component_names(design)
                  if n not in param_names]

    header = ['Name'] + [p.name for p in params] + comp_names
    # One example row seeded with the model's current expressions, so the
    # expected "value + unit" format is obvious. Text parameters are written
    # without their surrounding quotes (so 'A-6' becomes A-6) to keep the sheet
    # tidy; the quotes are re-added automatically on import based on the model's
    # parameter type, so a value can even be a number used as engraving text.
    example = (['Variant_1']
               + [sheet_core.unquote_text(p.expression) for p in params]
               + ['TRUE'] * len(comp_names))

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerow(example)

    return path, len(params), len(comp_names)
```

Note the early return for a cancelled save dialog (`return None, 0`) must also become `return None, 0, 0`.

- [ ] **Step 2: Update the caller**

In `TemplateExecuteHandler.notify`:

```python
            path, n, c = create_template(use_favorites)
            if path is None:
                return  # user cancelled the save dialog
            comp_note = (' and {} component on/off column(s)'.format(c)) if c else ''
            ui.messageBox(
                'Template with {} parameter column(s){} saved to:\n{}\n\n'
                'In Google Sheets: File > Import > Upload, then fill in one row per variant. '
                'Use the same link with "Build Variants Assembly".'.format(n, comp_note, path))
```

- [ ] **Step 3: Verify the module still parses**

Run: `python3 -c "import ast; ast.parse(open('SheetVariants/SheetVariants.py').read()); print('parses OK')"`
Expected: `parses OK`

- [ ] **Step 4: Confirm both return sites were updated**

Run: `grep -n "return None, 0\|return path, len(params)\|create_template(" SheetVariants/SheetVariants.py`
Expected: the cancel return reads `return None, 0, 0`, the success return reads `return path, len(params), len(comp_names)`, and the call site unpacks three values.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 169 passed

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat: seed the sheet template with component on/off columns"
```

---

### Task 10: Spike — does Fusion's preview revert restore visibility?

**Files:** none (investigation).

**Interfaces:**
- Consumes: nothing.
- Produces: a documented yes/no that decides Task 11's size. **Task 11 must not start until this is answered.**

The Test tab preview relies entirely on Fusion reverting changes made while `isValidResult` stays `False` — `_preview_test_row` restores nothing itself and there is no destroy-time restore behind it. Whether that revert covers a visibility change is the open question.

- [ ] **Step 1: Run the spike in Fusion**

1. Open any design with at least one top-level component.
2. Run **Build Variants Assembly from Sheet**.
3. In the **Test tab**, add this line temporarily at the end of `_preview_test_row`, before running:

```python
    # SPIKE ONLY — remove after answering
    design.rootComponent.occurrences.item(0).isLightBulbOn = False
```

4. Pick a variant row so the preview fires. Confirm the first component's light bulb goes off.
5. Press **Cancel**.
6. Look at the browser tree.

- [ ] **Step 2: Record the answer**

Append a short section to the design spec at `docs/superpowers/specs/2026-08-12-component-toggles-design.md`, under "Test tab preview", stating what happened:

- **Bulb came back on** → Fusion's revert covers visibility. Task 11 is the simple path.
- **Bulb stayed off** → the revert does not cover visibility. Task 11 must add explicit capture-and-restore.

- [ ] **Step 3: Remove the spike line**

Run: `git diff SheetVariants/SheetVariants.py`
Expected: no changes — the spike line has been deleted.

- [ ] **Step 4: Commit the finding**

```bash
git add docs/superpowers/specs/2026-08-12-component-toggles-design.md
git commit -m "docs: record whether Fusion's preview revert restores visibility"
```

---

### Task 11: Test tab preview honours toggles

**Files:**
- Modify: `SheetVariants/SheetVariants.py` — `_preview_test_row` (~line 673)

**Interfaces:**
- Consumes: `classify_columns`, `row_toggles` (Tasks 2-3), `top_level_component_names` (Task 6), Task 10's answer.
- Produces: nothing.

**Do not start before Task 10 is answered.** Step 2 branches on it.

- [ ] **Step 1: Replace the parameter-application block**

In `_preview_test_row`, replace everything from `param_names = [h.strip() for h in rows[0]][1:]` to the end of the function:

```python
    data = rows[1:]
    idx = row_item.index
    if idx >= len(data):
        return
    row = data[idx]

    design = adsk.fusion.Design.cast(app.activeProduct)
    cols = sheet_core.classify_columns(
        rows[0], known_param_names(design),
        top_level_component_names(design), component_names(design))

    for col, pname in cols['parameters']:
        if col >= len(row):
            continue
        val = row[col].strip()
        if not val:
            continue
        # Re-derive fresh per parameter: a recompute can invalidate the collection.
        p = adsk.fusion.Design.cast(app.activeProduct).allParameters.itemByName(pname)
        if p:
            try:
                build_engine.apply_expression(p, val)
            except Exception:
                pass  # a bad cell just doesn't preview; never crash the preview

    # Show what the build would produce: hide the components this row switches
    # off. Visibility is the right instrument here — it is purely visual and
    # cannot break a feature, unlike suppression. Components are only ever
    # switched OFF, never on, so a part the designer hid by hand stays hidden.
    toggles = sheet_core.row_toggles(row, cols['toggles'])
    off_names = set(name for name, keep in toggles.items() if not keep)
    if off_names:
        for occ in adsk.fusion.Design.cast(app.activeProduct).rootComponent.occurrences:
            try:
                if occ.component.name in off_names:
                    occ.isLightBulbOn = False
            except Exception:
                pass  # a preview must never crash the dialog
```

- [ ] **Step 2: Add explicit restore — only if Task 10 said the revert does not cover visibility**

If Task 10 found the bulb came back on by itself, **skip this step entirely** — Fusion already handles it.

Otherwise, add a module-level cache next to the existing `_build_report` dict near the top of the command-handler section:

```python
# Light bulbs the Test tab preview switched off, so they can be put back when
# the dialog closes. Fusion's preview revert does not cover visibility (spike,
# task 10), so this feature restores them itself.
_preview_hidden_bulbs = []
```

Record each bulb before switching it off — replace the `occ.isLightBulbOn = False` line above with:

```python
                if occ.component.name in off_names and occ.isLightBulbOn:
                    _preview_hidden_bulbs.append(occ)
                    occ.isLightBulbOn = False
```

The Build command has **no** destroy handler today (confirmed: the only handlers registered are execute, inputChanged, executePreview and validateInputs, at lines 839-853). Add one. Define the class next to `BuildExecutePreviewHandler`:

```python
class BuildDestroyHandler(adsk.core.CommandEventHandler):
    """Put back any light bulbs the Test tab preview switched off.

    Fusion's preview revert restores parameters but not visibility (spike,
    task 10), so the preview's own hiding has to be undone here — otherwise
    cancelling the dialog would leave the model looking like the variant that
    was last previewed.
    """
    def notify(self, args):
        for occ in _preview_hidden_bulbs:
            try:
                occ.isLightBulbOn = True
            except Exception:
                pass
        del _preview_hidden_bulbs[:]
```

Register it in the Build command's `CommandCreatedHandler`, after the `on_validate` block at lines 851-853, following the same pattern (`_handlers.append` keeps the handler alive):

```python
            on_destroy = BuildDestroyHandler()
            cmd.destroy.add(on_destroy)
            _handlers.append(on_destroy)
```

- [ ] **Step 3: Verify the module still parses**

Run: `python3 -c "import ast; ast.parse(open('SheetVariants/SheetVariants.py').read()); print('parses OK')"`
Expected: `parses OK`

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 169 passed

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/SheetVariants.py
git commit -m "feat: hide switched-off components in the Test tab preview"
```

---

### Task 12: Documentation and manual verification

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/plans/2026-08-13-component-toggles-verification.md`

**Interfaces:**
- Consumes: everything.
- Produces: the verification record.

- [ ] **Step 1: Document the feature in the README**

In the **Sheet layout** section, after the bullet list ending `Blank cells leave that parameter unchanged.`, add:

```markdown
### Switching components off per variant

A column whose header is the name of a **top-level component** switches that
component on or off for each variant, instead of setting a parameter:

| Name    | length | Drawer | Back  |
|---------|--------|--------|-------|
| Unit_S  | 500 mm | FALSE  | TRUE  |
| Unit_L  | 900 mm | TRUE   | TRUE  |

- `TRUE`, `1`, `yes`, `y`, `on` keep the component; `FALSE`, `0`, `no`, `n`,
  `off` drop it. Case does not matter, so a Google Sheets checkbox column
  works as-is.
- A **blank** cell keeps the component. Anything else is a Check error, so a
  typo never quietly removes a part.
- Switching a component off takes its **sub-components with it**.
- Only **top-level** components can be switched — a column naming a
  sub-component is reported as an error rather than ignored.
- If a name is both a parameter and a component, it is read as a **parameter**
  and Check warns about the collision.
- Toggles apply to **every export profile**. A Named-components profile builds
  the components it lists *and* that the row keeps, so off wins. A variant left
  with nothing to build is named in the run summary; the rest still build.

The source model is never modified — the geometry is simply not collected for
that variant.
```

In the **Features** list, after the **Export profiles** bullet, add:

```markdown
- **Component on/off columns** — a sheet column named after a top-level
  component switches it off for individual variants, so one sheet can describe
  a 500 mm unit with no drawer and a 900 mm unit with one.
```

- [ ] **Step 2: Write the verification checklist**

Create `docs/superpowers/plans/2026-08-13-component-toggles-verification.md`:

```markdown
# Component on/off columns — manual verification

The geometry walk, the Test tab preview and the template generator all run
inside Fusion and cannot be unit-tested. Run this against a **nested** test
assembly and record the result under each item.

**Test assembly:** a design with `Carcass` (containing sub-components `Side_L`
and `Back`), `Drawer` placed **twice** at the top level, and at least one loose
body directly in the root component.

**Test sheet:** columns `Name`, one driveable parameter, `Carcass`, `Drawer`.

## Items

1. **Off removes the component and its subtree.** Build with `Carcass=FALSE`
   on one row. That variant contains no `Carcass`, no `Side_L`, no `Back`. The
   other row is unaffected.
   - Result:

2. **Both instances switch together.** Build with `Drawer=FALSE`. Neither
   top-level instance appears.
   - Result:

3. **Off wins over a Named-components profile.** Add a profile with rule
   **Named components** selecting `Side_L`. Build a row with `Carcass=FALSE`.
   That variant is absent from the profile's output and named in the run
   summary; the profile's other variants still build.
   - Result:

4. **Loose root bodies are unaffected.** The body modelled directly in the root
   appears in every variant regardless of any toggle.
   - Result:

5. **The source model is unchanged after a run.** This is the item that matters
   most — dropping bodies instead of suppressing occurrences is justified
   entirely by the source model being untouchable. After a build, confirm: same
   components present, every light bulb in its original state, parameters back
   to their original expressions, and the document not marked modified beyond
   the usual parameter round-trip.
   - Result:

6. **Check catches a bad sheet.** In turn: a column naming `Side_L` (error,
   "sub-component"); a column naming `Drawr` (error, no match); a cell reading
   `maybe` (error naming the cell); a blank toggle cell (warning, component
   stays in). The OK/Build button is disabled while any error stands.
   - Result:

7. **Test tab preview matches the build.** Preview a row with `Drawer=FALSE`:
   the drawers disappear from the model. Cancel the dialog: they come back, and
   the parameters are restored too.
   - Result:

8. **Generated template round-trips.** Run **Create Variant Sheet Template**.
   It has one `TRUE` column per top-level component. Build from it unchanged
   and confirm the result is identical to a build from the same sheet with the
   component columns deleted.
   - Result:

## Sign-off

- Verified by:
- Date:
- Fusion version:
```

- [ ] **Step 3: Run the checklist in Fusion**

Work through all 8 items, filling in each **Result** line with what actually happened. An item that fails is a bug to fix before sign-off, not a note to leave behind.

- [ ] **Step 4: Run the full suite one last time**

Run: `python3 -m pytest -q`
Expected: 169 passed

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/plans/2026-08-13-component-toggles-verification.md
git commit -m "docs: document component on/off columns and record verification"
```

---

## Self-review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Top-level components only | 2 (classification), 6 (`top_level_component_names`) |
| Bodies dropped at capture; model never modified | 6, verified by item 5 in 12 |
| Plain component name as the column header | 2 |
| Parameter wins a collision | 2, 4 |
| Accepted values, blank = on | 1 |
| Unrecognised value is an error | 4 |
| Sub-component column is an error | 2, 4 |
| Applies to every profile; off wins | 6 (`_component_solid_bodies`), verified by item 3 in 12 |
| Empty variant skipped and named | 5, 7 |
| Test tab preview | 10 (spike), 11 |
| Template emits toggle columns | 9 |
| Blank toggles get their own warning line | 4 |
| Summary unchanged when there are no toggles | 4 |
| Rightmost duplicate column wins | 3 |
| README documentation | 12 |
| Manual verification checklist | 12 |

**Placeholder scan:** none — every code step carries the code, and every test step carries the assertions.

**Type consistency:** `classify_columns` returns the same five-key dict in Tasks 2, 4, 7, 8 and 11; `"parameters"` and `"toggles"` are `[(col_index, name)]` at every use. `row_toggles` takes that same list shape in Tasks 3, 7 and 11. `off_names` is passed positionally as the third resolver argument in Tasks 6 and 7. `create_template`'s arity change to 3 is made and consumed in Task 9.

**Known gap:** the spec's sub-component message names the parent component; this plan does not. Documented above under "Deviation from the spec".
