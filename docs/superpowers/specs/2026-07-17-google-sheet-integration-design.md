# Better Google Sheet integration — design

**Date:** 2026-07-17
**Branch / worktree:** `worktree-google-sheet-integration`
**Status:** Approved design, ready for implementation plan

## Problem

The add-in reads variants from a Google Sheet, but tab selection is entirely
URL-driven: it reads only the tab whose `gid` is embedded in the pasted link
(and forces the first tab when `gid=0` or absent). There is no way to *see* the
tabs and pick one.

The user now works with a spreadsheet that has **multiple tabs — one real
variant table plus helper tabs** (dropdown lists, calculations). They need to:

1. **Select and pin** the correct data tab, instead of hunting for a `gid`.
2. **Validate that all parameters are mapped** before building.
3. **Test a specific configuration** by applying one row to the live model.

Inspection of the user's real sheet (`1x-p9znWXejdvPQzHZdMR3mgPX3Mh-p1B0eEMABX2YSs`,
tab `rubber_variants`, columns `Name, diameter, hoogte`) also surfaced real
data-quality problems that motivate validation: comma decimals with no unit
(`18,2`) and inconsistent spacing (`5mm` vs `5 mm`).

## Chosen approach

Enhance the existing **Build** command with a tab picker + inline validation,
and add a new **Test Variant Row** command. No Google API key or extra Python
package is introduced.

### Key technical enabler: XLSX export

To list tab **names** without the Google API, use the
`export?format=xlsx` endpoint. One HTTP request returns every tab, and Fusion's
bundled Python parses it with only `zipfile` + `xml.etree`. Verified against the
user's sheet: it yields both tab names (`xl/workbook.xml`) and cell values
as-typed (`xl/sharedStrings.xml` / inline values).

That single download serves **both** the tab picker and the data read — the
chosen worksheet's rows are read directly from the same in-memory blob, so there
is no per-tab `gid` lookup at all. This removes the fragile-`gid` behaviour that
motivated the request.

## Architecture & file layout

Split the pure logic out of the Fusion-coupled code so it can be unit-tested on
CI (which has no `adsk` module).

- **`SheetVariants/sheet_source.py`** — *stdlib only, no `adsk` import.* Owns:
  - URL → spreadsheet-id parsing (share / edit / published / direct-CSV forms).
  - XLSX fetch + parse: ordered tab names, and rows for a chosen tab.
  - CSV fallback (existing behaviour) for links without a spreadsheet id.
  - Static/format validation: columns↔params, comma-decimal & empty-cell &
    unitless-number heuristics.
  - Numeric-formatting normalisation (`18.0` → `18`).
- **`SheetVariants/SheetVariants.py`** — the `adsk` UI and model work: command
  handlers, the tab dropdown, applying expressions to real parameters, the deep
  value check, building the assembly, and the new test-row apply/restore.
  Imports `sheet_source`.

**Import robustness:** the main file inserts its own directory on `sys.path`
before `import sheet_source` — the reliable pattern for multi-file Fusion
add-ins.

### Settings model

`settings.json` gains a per-sheet pin and a test-row snapshot:

```json
{
  "sheet_url": "...",
  "spacing_mm": 10.0,
  "pinned_tabs": { "<spreadsheetId>": "rubber_variants" },
  "test_snapshot": { "<paramName>": "<originalExpression>", "...": "..." }
}
```

The chosen tab is remembered per spreadsheet and reused automatically. The
test-row snapshot is persisted so Restore survives an add-in reload.

## Feature 1 — Tab discovery, selection & pinning

Build dialog data flow:

1. Dialog opens with the saved URL pre-filled. Below it: a **Tab** dropdown
   (initially the pinned tab, or a "load sheet to list tabs" placeholder) and a
   **Load tabs** button (a `BoolValueInput` styled as a button — dialogs should
   not re-fetch on every keystroke).
2. Clicking **Load tabs** (or changing the URL) triggers an
   `InputChangedHandler` that: extracts the spreadsheet id, fetches the XLSX
   once, parses tab names, and repopulates the Tab dropdown — pre-selecting the
   pinned tab for that sheet if present, else the first tab.
3. Selecting a tab and building **pins** it:
   `pinned_tabs[spreadsheetId] = tabName`.

**Reading rows:** `sheet_source` reads the chosen worksheet's rows directly from
the already-downloaded XLSX blob (no second request, no `gid`).

**Fallbacks & edge cases:**

- Published-to-web / direct-CSV links (no spreadsheet id): the Tab dropdown is
  disabled and the existing single-tab CSV read is used.
- XLSX numeric cells: text like `18 mm` is preserved exactly; a pure-number cell
  comes back as a float and is rendered without a spurious trailing `.0`.
- The fetched workbook is cached in memory for the dialog session so
  "Load tabs" then "Build" does not download twice.

## Feature 2 — Validation

Two tiers.

### Tier 1 — Static report (automatic, instant, non-mutating)

Runs in `sheet_source` when a tab is loaded/selected; rendered into a read-only
`textBoxCommandInput` in the Build dialog.

The validator is a **pure function** — it never imports `adsk`. The main file
gathers what it needs from the model and passes it in:
`validate(header, rows, known_param_names, driveable_param_names)`, where
`known_param_names` is every parameter in the model (used to match columns) and
`driveable_param_names` is the "meaningful" subset used for the coverage warning
(see below). This keeps the validator fully unit-testable on CI.

Covers:

- **Columns → params:** each column ✓ matched (in `known_param_names`) or ✗ *no
  parameter named "X"*.
- **Params → columns:** each *driveable* param not driven by a column listed as
  ⚠ *"height" has no column — keeps current value*. `driveable_param_names` is
  the model's **favourite** parameters if it has any, otherwise its **user**
  parameters — the same set the *Create Template* command offers. This avoids
  flagging every internal model parameter (`d1`, `d2`, …) as "uncovered".
- **Value format heuristics:** ✗ comma-decimal (`18,2` →
  *"use a dot and unit, e.g. 18.2 mm"*); ⚠ empty cell (*left unchanged*);
  ⚠ bare number with no unit (*ambiguous but accepted*).

### Tier 2 — Deep value check (pre-build, definitive)

Right before building, try-set each **distinct** `(param, value)` via
`param.expression` in a try/except and immediately restore. This is Fusion's own
ground truth for "will this expression be accepted" (bad units, unknown
functions, etc.). Only distinct pairs, so it is cheap.

### Error vs warning

- **Errors block the build:** column matches no parameter; any value Fusion
  actually rejects (comma-decimals surface here too).
- **Warnings never block:** uncovered params, empty cells, unitless numbers.

The report leads with a one-line verdict
(`✓ 3 columns mapped, 10 rows OK` or `✗ 2 errors, 1 warning — fix before
building`). The **OK/Build button is disabled while errors exist**. No
auto-fixing of comma decimals — flag with the corrected form instead.

## Feature 3 — Test Variant Row (new command)

A third button on the Sheet Variants panel: **Test Variant Row**.

**Dialog:** same URL + **Tab** dropdown + **Load tabs** mechanism as Build
(shared UI code, pre-selects the pinned tab), plus a **Row** dropdown listing the
tab's variants by their `Name` column.

**On OK (apply):**

1. Snapshot the current expressions of exactly the parameters this row will
   touch (mapped columns) — in module memory **and** `settings.json` so it
   survives a Fusion reload.
2. Apply the row's values to the live active model via the existing
   `apply_expression`, then `doEvents()` so it rebuilds in place. Any cell Fusion
   rejects is reported (`✗ diameter: "18,2"`) without aborting the others.
3. Close the dialog so the model can be freely orbited / measured / inspected.

**Restore:** because inspection needs the dialog closed, restore is an explicit
re-entry. When **Test Variant Row** is reopened and a snapshot is active, a
**Restore original values** checkbox appears at the top — tick it + OK to roll
those parameters back to the snapshot. Picking a different row instead tries
another config; the snapshot is taken once from the true original, so repeated
tests never compound. The apply confirmation message states this.

**Scope discipline:** only parameters the tested row touches are ever changed or
restored.

## Build integration

Open dialog → URL pre-filled → **Load tabs** → pick tab (pinned pre-selected) →
static report renders inline → fix any ✗ errors (Build disabled until clean) →
**Build** runs the deep value check, then the existing assembly build reading
rows from the selected tab. Everything downstream of "get rows for a tab" is the
current, working build code — unchanged. Published/CSV-only links skip the picker
and behave exactly as today.

## Testing strategy

- **Automated (CI, no Fusion needed):** a new `tests/` suite with `pytest`
  exercising `sheet_source` against a committed sample `.xlsx` fixture and
  crafted CSV/URL strings:
  - URL → id extraction (share / edit / published / direct-CSV forms),
  - XLSX tab enumeration,
  - per-tab row reading,
  - numeric-formatting (`18.0` → `18`),
  - the static validator (column mismatch, uncovered param, comma-decimal,
    empty cell).

  CI gains a `pytest` step alongside the existing byte-compile / manifest-JSON /
  pyflakes checks.
- **Manual (only reproducible inside Fusion):** the `adsk`-coupled paths —
  dropdown population, applying expressions to real parameters, the deep
  try-set/restore, the assembly build, and test-row apply/restore. A manual test
  checklist (below) uses the real `rubber_variants` sheet. No Fusion behaviour is
  claimed "working" until confirmed hands-on by the user.

### Manual test checklist (in Fusion)

1. Open a parametric model with parameters `diameter`, `hoogte` (or adapt the
   sheet to the model's real parameter names).
2. **Build → Load tabs:** the Tab dropdown lists `rubber_variants` (plus any
   helper tabs). Selecting it renders the validation report.
3. Confirm the report flags `18,2` as an error and disables Build.
4. Fix the sheet, reload, confirm the report goes green and Build enables.
5. **Build:** a new design opens with one component per row, laid out along X.
6. Confirm the source model's parameters are restored afterward.
7. Reopen Build: the pinned tab is pre-selected.
8. **Test Variant Row → pick a row → OK:** the live model rebuilds to that
   config; the confirmation explains how to restore.
9. Reopen **Test Variant Row**, tick **Restore original values**, OK: the model
   returns to its original parameter values.

## Out of scope (YAGNI)

- Writing back to the sheet (still read-only).
- Auto-fixing / locale-normalising comma decimals.
- Jointing / constraining the built components.
- Caching sheets to disk between sessions.

## Constraints honoured

- No Google API key, no extra Python packages (stdlib only).
- Works on the Fusion Personal licence (geometry copied in-memory, no export).
- No commits created until the user asks; Fusion behaviour verified by the user
  before any "it works" claim.

---

## Addendum (2026-07-17) — merge with main's "output sets" (export profiles)

`main` was reworked in parallel: it added `SheetVariants/sheet_core.py` (pure module:
CSV url logic, `unquote_text`, an export-**profiles** model, settings + migration,
component selection, result summary) and rewrote `SheetVariants.py` with an editable
**export-profiles table** and a **multi-profile build engine** (`build_exports` +
`RESOLVERS` for `whole_model` / `named_components`). It reads the sheet CSV-only.

Decision: **re-baseline this branch on `origin/main`** and re-apply this branch's
tab-selection + validation + test-a-row features onto main's architecture.

- The pure logic from the (now-removed) `sheet_source.py` — `extract_spreadsheet_id`,
  `xlsx_export_url`, `parse_workbook_tabs`, `read_tab_rows`, `normalize_number`,
  `classify_value`, `validate_mapping`, `ValidationReport` — is **folded into
  `sheet_core.py`** (which stays network-free and unit-tested). Duplicates already on
  main (`csv_url_candidates`, `SHARING_HELP`, CSV parsing) are NOT re-added.
- Network fetch stays in the add-in (matching main). New add-in helpers `list_tabs(url)`
  and `get_rows(url, tab_name=None)` add XLSX tab reading with CSV fallback.
- The Build command becomes a **3-tab dialog**: **Sheet** (URL, Load tabs *above* the
  Tab picker, Tab picker, validation report, gap), **Test** (pick a row → Apply to live
  model / Restore — immediate action buttons), **Output sets** (main's export-profiles
  table). OK = build; validation errors disable OK.
- `build_exports` gains `tab_name` and reads via `get_rows`; a pre-build deep value
  check runs first. Tab pin + test snapshot live in settings alongside `profiles`.
