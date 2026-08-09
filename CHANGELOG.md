# Changelog / release notes

Notable changes and planned work for the **Sheet to Fusion** add-in.

## Planned / ideas

- **Sheet metal flat patterns** — build or export the flat pattern of sheet-metal
  components (e.g. as a dedicated output set) alongside the solid variants.
- **Filter by thickness** — filter which variants or components are built/exported
  by their material thickness.

## 1.14.0 — Placeholder instantiation

- **Prepare Mother Model** — record on a saved parametric document which
  parameters its width, depth and height map to, which joint origin is its
  anchor, and which way it faces. Stored on the document, so it travels with
  the file.
- **Fill Placeholders** — select the front face of each placeholder box in a
  layout, pick a prepared mother and one config row from its sheet, and each
  box gets a child component driven to that box's own size and orientation.
  The anchor lands at the box centre; the box is hidden, never deleted.
- **Rebuilds preserve your edits.** Re-running Fill on a filled box swaps the
  geometry inside its base feature via `updateBody()`: a cut anchored to an
  origin plane recomputes against the new shape instead of being deleted with
  the old one. A fillet or sketch anchored to the generated geometry itself
  does not survive a shape change — that child is reported as `rebuild failed`
  and skipped, and the rest of the run continues.
- Identical boxes share one recompute of the mother.
- The geometry core is now shared with the sheet-variants build
  (`build_engine.py`), and the new pure logic — schemas, frames, extents,
  matrices, body pairing — is unit-tested on CI in `placeholder_core.py`.

## 1.13.0 — Framed builds, clearer tab loading

- **Built designs open framed** — after a build, each output design is framed
  like the ViewCube **Home** view (plus a fit), instead of opening on the
  default empty-scene camera with the variants out of view.
- **Tab dropdown grayed until loaded** — on the *Sheet* tab, the **Tab**
  dropdown is disabled until **Load tabs** fetches the real tab list, so a
  pinned tab no longer looks like an already-loaded list. The pinned tab still
  validates and builds while grayed; single-CSV links keep it disabled.

## 1.12.0 — Google Sheet integration

The add-in reads a Google Sheet of parameter values and builds a production
assembly. Highlights of the 1.x line:

- **3-tab Build dialog** — *Sheet* (paste link, **Load tabs**, pick + pin the
  data tab, live **Check** validation with the OK/Build button gated on errors),
  *Test* (live-preview a single variant row on the model, auto-reverts on close),
  and *Output sets* (editable **export profiles** table).
- **Multi-profile builds** — each enabled profile (whole model, or a named subset
  of components) becomes its own new design, one component per variant, laid out
  left-to-right by bounding box.
- **Materials & appearances** are re-applied to the built variants.
- **Per-design sheet URL** memory, with an app-level last-used fallback.
- No Google Cloud project or API key: multi-tab sheets are fetched once as an
  XLSX workbook (stdlib `zipfile`); single-tab and published-to-web links are
  read as CSV. Works on the **Fusion Personal** licence (geometry copied
  in-memory, no file export).
- Pure, Fusion-free logic isolated in `sheet_core.py` and unit-tested on CI.
