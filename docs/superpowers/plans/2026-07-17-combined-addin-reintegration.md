# Combined Add-in Re-integration Plan

> **For agentic workers:** implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Merge this branch's Google-Sheet tab-selection + validation + test-a-row features onto `main`'s export-profiles ("output sets") architecture, in a single 3-tab Build dialog.

**Architecture:** Branch is re-baselined on `origin/main` (8fddd1b). Fold the pure tab/validation logic into main's network-free `sheet_core.py`; add tab-aware sheet reading to the add-in; rebuild the Build command as a 3-tab dialog (Sheet / Test / Output sets) that reuses main's multi-profile `build_exports` engine.

**Tech Stack:** Python 3.11 (Fusion), stdlib only (`urllib`, `zipfile`, `xml.etree`, `csv`, `re`, `json`); pytest (dev). Fusion API.

## Global Constraints

- **stdlib only** at runtime; `sheet_core.py` stays **network-free and adsk-free** (pure, unit-tested). Network (`urllib`) lives in `SheetVariants.py`, as on main.
- **Do NOT re-add** names already on main's `sheet_core.py` (`csv_url_candidates`, `SHARING_HELP`, `parse_sheet_csv`, `unquote_text`, profiles/settings/select/summarize). Extend, don't duplicate.
- **Preserve main's behavior**: export profiles, multi-profile build engine (`build_exports`, `RESOLVERS`), settings migration, template command — all keep working. CSV-only links (no spreadsheet id) still build with no tab picker.
- **Commits are gated** — no `git commit` until the user asks. Implementers leave changes in the working tree.
- **No unverified success claims** for Fusion behavior — only py_compile/pyflakes/pytest may be reported as passing when they pass; runtime is verified by the user in Fusion.
- Reference (this branch's prior tested code, for verbatim reuse):
  `scratchpad/pre-rebaseline/sheet_source.py`, `scratchpad/pre-rebaseline/test_sheet_source.py`,
  `scratchpad/pre-rebaseline/SheetVariants_with_tasks7-11.py`
  (full paths under `/private/tmp/claude-501/-Users-davidtruyens-Source-Sheet-to-fusion-production--claude-worktrees-google-sheet-integration/c16c305c-3914-4c1a-acf3-a103cd8a9264/`).

---

## Task A: Fold tab + validation logic into `sheet_core.py` (+ tests)

**Files:**
- Modify: `SheetVariants/sheet_core.py`
- Modify: `tests/test_sheet_core.py`

**Interfaces produced (new public names in `sheet_core`):**
- `extract_spreadsheet_id(url)->str|None`, `xlsx_export_url(id)->str`
- `parse_workbook_tabs(xlsx_bytes)->list[str]`, `read_tab_rows(xlsx_bytes, tab_name)->list[list[str]]`
- `normalize_number(text)->str`, `classify_value(text)->str` ("ok"/"empty"/"comma_decimal"/"unitless")
- `validate_mapping(header, rows, known_param_names, driveable_param_names)->ValidationReport`
- `ValidationReport` with `.errors`, `.warnings`, `.ok`, `.summary()`, `.to_html()`

- [ ] **Step 1:** Copy these functions/classes VERBATIM from `scratchpad/pre-rebaseline/sheet_source.py` into `sheet_core.py` (append after the existing code): `extract_spreadsheet_id`, `xlsx_export_url`, the XML namespace constants (`_MAIN_NS`, `_REL_NS`, `_PKGREL_NS`), `normalize_number`, `_col_index`, `_shared_strings`, `_worksheet_path_for`, `parse_workbook_tabs`, `read_tab_rows`, `classify_value`, `_cell_ref`, `_COMMA_DECIMAL`, `_UNITLESS`, `ValidationReport`, `validate_mapping`. Add `import zipfile` and `import xml.etree.ElementTree as ET` to the imports. Do **NOT** copy `SHARING_HELP`, `csv_url_candidates`, `parse_csv_bytes`, or `fetch_bytes` (network stays in the add-in; the other two already exist on main).

- [ ] **Step 2:** Copy the corresponding tests from `scratchpad/pre-rebaseline/test_sheet_source.py` into `tests/test_sheet_core.py`: the `_build_xlsx` helper (+ its `_col_letter` helper and `import zipfile, io`) and the tests for id extraction, `xlsx_export_url`, `parse_workbook_tabs`, `read_tab_rows` (3), `normalize_number`, `classify_value`, and `validate_mapping` (5). Change every `import sheet_source as ss` / `ss.` reference to use `sheet_core` (the test file uses `import sheet_core` via `conftest.py`; reference names as `sheet_core.NAME`). Drop the tests for the NOT-folded functions (`parse_csv_bytes`, `fetch_bytes`, `csv_url_candidates` — main already tests `csv_url_candidates`).

- [ ] **Step 3:** Run `python3 -m pytest tests/ -q`. Expected: all pass (main's 24 + the ~13 folded). Fix any import/reference drift.

- [ ] **Step 4:** `python3 -m py_compile SheetVariants/sheet_core.py` and `python3 -m pyflakes SheetVariants/sheet_core.py` → clean.

- [ ] **Step 5 (gated):** commit only if the user asks.

---

## Task B: Tab-aware sheet reading + build wiring in the add-in

**Files:**
- Modify: `SheetVariants/SheetVariants.py`

**Interfaces produced (add-in module level):**
- `_xlsx_bytes_for(url)->bytes` (urllib GET of `sheet_core.xlsx_export_url(id)`, cached in `_xlsx_cache`)
- `list_tabs(url)->list[str]` ( `[]` when no spreadsheet id)
- `get_rows(url, tab_name=None)->list[list[str]]` (xlsx tab read when id+tab; else existing `fetch_rows` CSV path; raises if `<2` rows)
- `known_param_names(design)->list[str]`, `driveable_param_names(design)->list[str]` (favorites if any, else user params)
- pin helpers reading/writing `settings['pinned_tabs']` (dict keyed by spreadsheet id); `deep_check_values(all_params, param_names, rows)->list[str]`

- [ ] **Step 1:** Add a network fetch + cache and the readers. Keep main's `fetch_rows` for the CSV fallback. Add near the top after imports: `import zipfile`? No — parsing is in `sheet_core`; the add-in only needs `urllib` (already imported on main) to fetch bytes. Add:

```python
_xlsx_cache = {"url": None, "bytes": None}


def _xlsx_bytes_for(url):
    if _xlsx_cache["url"] != url or _xlsx_cache["bytes"] is None:
        sid = sheet_core.extract_spreadsheet_id(url)
        req = urllib.request.Request(sheet_core.xlsx_export_url(sid),
                                     headers={"User-Agent": "Mozilla/5.0 (FusionAddin)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            _xlsx_cache["bytes"] = resp.read()
        _xlsx_cache["url"] = url
    return _xlsx_cache["bytes"]


def list_tabs(url):
    if not sheet_core.extract_spreadsheet_id(url):
        return []
    return sheet_core.parse_workbook_tabs(_xlsx_bytes_for(url))


def get_rows(url, tab_name=None):
    sid = sheet_core.extract_spreadsheet_id(url)
    if sid and tab_name:
        rows = sheet_core.read_tab_rows(_xlsx_bytes_for(url), tab_name)
    else:
        rows = fetch_rows(url)
        return rows  # fetch_rows already enforces >=2 rows
    if len(rows) < 2:
        raise RuntimeError("The sheet needs a header row plus at least one variant row.")
    return rows


def known_param_names(design):
    return [p.name for p in design.allParameters]


def driveable_param_names(design):
    favs = [p.name for p in design.allParameters if getattr(p, "isFavorite", False)]
    return favs if favs else [p.name for p in design.userParameters]
```

- [ ] **Step 2:** Add pin helpers (using main's `load_settings`/`save_settings` dict; `pinned_tabs` is preserved by `migrate_settings` because it copies the dict and only touches `profiles`):

```python
def load_pinned_tab(settings, spreadsheet_id):
    return (settings.get("pinned_tabs") or {}).get(spreadsheet_id, "")


def set_pinned_tab(settings, spreadsheet_id, tab):
    pinned = dict(settings.get("pinned_tabs") or {})
    pinned[spreadsheet_id] = tab
    settings["pinned_tabs"] = pinned
```

- [ ] **Step 3:** Add the pre-build deep value check and wire the tab into the engine. Change `build_exports(sheet_url, spacing_cm, profiles)` to `build_exports(sheet_url, spacing_cm, profiles, tab_name=None)`; replace `rows = fetch_rows(sheet_url)` with `rows = get_rows(sheet_url, tab_name)`. After the missing-columns check and before snapshotting `original`, add:

```python
    rejects = deep_check_values(all_params, param_names, rows[1:])
    if rejects:
        raise RuntimeError("These cell values were rejected by Fusion:\n  " + "\n  ".join(rejects))
```

and define `deep_check_values` (copy from `scratchpad/pre-rebaseline/SheetVariants_with_tasks7-11.py`; it try-sets each distinct `(param,value)` via `apply_expression` and restores in a `finally`).

- [ ] **Step 4:** `python3 -m py_compile SheetVariants/SheetVariants.py` + `pyflakes` → clean. `pytest tests/ -q` still green (this task adds no tests; it's adsk-coupled). Verify no unused imports introduced.

- [ ] **Step 5 (gated):** commit only if the user asks.

---

## Task C: Rebuild the Build command as a 3-tab dialog

**Files:**
- Modify: `SheetVariants/SheetVariants.py` (`CommandCreatedHandler`, `CommandExecuteHandler`, `BuildInputChangedHandler`; add `ValidateInputsHandler`, `_run_build_validation`, Test-tab apply/restore, snapshot helpers).

**This is adsk-coupled: verify with py_compile + pyflakes + the manual Fusion checklist. Reference the working handler code in `scratchpad/pre-rebaseline/SheetVariants_with_tasks7-11.py` and adapt names to `sheet_core`.**

Dialog layout — `cmd.setDialogInitialSize(560, 460)`, then three tabs via `inputs.addTabCommandInput(id, name).children`:

- **Sheet tab** (`tabSheet`): `sheetUrl` (string), **`loadTabs`** button (`addBoolValueInput('loadTabs','Load tabs',False,'',False)`) placed **above** the `tab` dropdown, `tab` dropdown (`TextListDropDownStyle`, pre-selected pinned tab if known), `report` textbox (`addTextBoxCommandInput('report','Check','',6,True)`, `isFullWidth=True`), `spacing` value input (moved here from main).
- **Test tab** (`tabTest`): `testRow` dropdown (variants by Name), `testApply` button (`addBoolValueInput('testApply','Apply to model',False,'',False)`), `testRestore` button (`addBoolValueInput('testRestore','Restore original values',False,'',False)`), a read-only note textbox. These act **immediately** via `BuildInputChangedHandler` (not via OK).
- **Output sets tab** (`tabOutput`): main's `profiles` `TableCommandInput` + `profileAdd`/`profileDelete` toolbar buttons + `compNote` — moved verbatim from main's dialog.

- [ ] **Step 1:** Add module state near the top: `_build_report = {"ok": True}`, `_component_name_cache = []` (main already has this), and the shared sentinel `CSV_ONLY_TAB_LABEL = "— single sheet (read as CSV) —"`.

- [ ] **Step 2:** Rewrite `CommandCreatedHandler.notify` to build the three tabs above. Reset `_build_report["ok"] = True` at the top. Load settings once (`sheet_core.load_settings`), pre-fill URL/spacing, seed profiles rows (reuse main's `_add_profile_row` loop) under the Output sets tab, and pre-select the pinned tab under the Sheet tab. Register `CommandExecuteHandler`, `BuildInputChangedHandler`, and a new `ValidateInputsHandler`; append all to `_handlers`.

- [ ] **Step 3:** Add `_run_build_validation(inputs)` (adapt from the reference file): reads url + selected tab, gets rows via `get_rows`, calls `sheet_core.validate_mapping(rows[0], rows[1:], known_param_names(design), driveable_param_names(design))`, writes `report.formattedText = rep.to_html()`, sets `_build_report["ok"] = rep.ok`. Guards: no active design → info message, ok=True; no tab chosen → prompt, ok=True.

- [ ] **Step 4:** Extend `BuildInputChangedHandler.notify` to handle ALL of:
  - main's existing `profileAdd` / `profileDelete` / `rl_*` rule-visibility logic (keep verbatim);
  - `loadTabs` pressed → reset button, `list_tabs(url)`; if empty add `CSV_ONLY_TAB_LABEL`, set report "read as single CSV", `_build_report["ok"]=True`; else populate tabs (pre-select pinned/first), then `_run_build_validation` and refresh the Test-tab `testRow` dropdown;
  - `tab` or `sheetUrl` changed → `_run_build_validation` + refresh `testRow`;
  - `testApply` pressed → snapshot touched params to `settings['test_snapshot']`, apply the selected row via `apply_expression`, `adsk.doEvents()`, report failures in a messageBox;
  - `testRestore` pressed → restore from `settings['test_snapshot']`, clear it.
  Add a `_refresh_test_rows(inputs)` helper mirroring `_reload_rows` from the reference file, using `CSV_ONLY_TAB_LABEL`→`tab_name=None` so CSV-only sheets still list rows.

- [ ] **Step 5:** Add `ValidateInputsHandler` (`adsk.core.ValidateInputsEventHandler`) → `args.areInputsValid = _build_report.get("ok", True)`.

- [ ] **Step 6:** Update `CommandExecuteHandler.notify`: read the selected `tab` (None if it starts with `—` other than the CSV sentinel — treat `CSV_ONLY_TAB_LABEL` as None), pin it (`set_pinned_tab`) when real, read spacing + profiles as main does, and call `build_exports(url, spacing_cm, profiles, tab)`; keep `ui.messageBox(sheet_core.summarize_results(results))`.

- [ ] **Step 7:** `python3 -m py_compile SheetVariants/SheetVariants.py` + `pyflakes` → clean. `pytest tests/ -q` → still green.

- [ ] **Step 8 (gated):** commit only if the user asks.

- [ ] **Step 9: Manual verification (user, in Fusion)** — see checklist below.

---

## Task D: README + final verification

**Files:** Modify `README.md`.

- [ ] **Step 1:** Update README: document the 3-tab Build dialog (Sheet / Test / Output sets), tab selection + pinning, validation, and that these compose with export profiles. Merge with main's export-profiles docs rather than replacing them.
- [ ] **Step 2:** Full verify: `py_compile` both modules, `pyflakes` both, `pytest tests/ -q` all green.
- [ ] **Step 3 (gated):** commit only if the user asks.

---

## Manual Fusion checklist (user)

1. Load the add-in; open a parametric model (params matching your sheet columns).
2. **Build → Sheet tab:** Load tabs (button above the picker) lists tabs; pick the data tab → validation report renders; a bad cell (comma decimal) shows ✗ and disables OK.
3. **Output sets tab:** add/enable profiles (whole model / named components), edit the table.
4. **OK** builds one output design per enabled profile, reading the selected tab; source model restored after.
5. Reopen Build → pinned tab pre-selected.
6. **Test tab:** pick a row → Apply to model (live rebuild) → Restore original values.
7. CSV-only/published link: Sheet tab shows "read as single CSV", Build still works, Test tab still lists rows.

---

## Self-Review

- Spec addendum coverage: fold logic → Task A; tab reading + build wiring → Task B; 3-tab dialog + test-a-row + Load-tabs-above + validation gating + pin → Task C; docs → Task D. ✓
- No duplication of main's `sheet_core` names (Task A Step 1 excludes them). ✓
- `sheet_core` stays network/adsk-free; network in add-in. ✓
- Names consistent: `get_rows`/`list_tabs`/`build_exports(...,tab_name)`/`validate_mapping`/`ValidationReport`/`CSV_ONLY_TAB_LABEL` used the same across tasks. ✓
- Backward compat (CSV-only) preserved via `get_rows` fallback + CSV sentinel handling. ✓
