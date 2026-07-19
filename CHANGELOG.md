# Changelog / release notes

Notable changes and planned work for the **Sheet to Fusion** add-in.

## Planned / ideas

- **Sheet metal flat patterns** — build or export the flat pattern of sheet-metal
  components (e.g. as a dedicated output set) alongside the solid variants.
- **Filter by thickness** — filter which variants or components are built/exported
  by their material thickness.

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
