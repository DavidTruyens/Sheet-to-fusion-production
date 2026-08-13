# Changelog / release notes

Notable changes and planned work for the **Sheet to Fusion** add-in.

## Planned / ideas

- **Sheet metal flat patterns** — build or export the flat pattern of sheet-metal
  components (e.g. as a dedicated output set) alongside the solid variants.
- **Filter by thickness** — filter which variants or components are built/exported
  by their material thickness.

## 1.17.2 — Update Children fixes from first real use

- **A fillet on a placeholder box is no longer mistaken for a rotation.** The
  check asked for exactly two distinct vertex coordinates per axis; rounding a
  box's edges puts vertices at the fillet tangent points, giving four
  (`min`, `min+r`, `max-r`, `max`) on a box that is perfectly square to its
  frame. Every filleted placeholder read `rotated — re-run Fill Placeholders`
  permanently, and re-filling could not clear it because the geometry was never
  the problem. Orientation is now judged from the body's **flat faces**, which a
  fillet adds nothing to and a chamfer only adds to. A body too far from a box to
  vouch for — a tube, a sheet — is still reported rather than measured.
- **A mother saved to a new version is picked up.** A mother saved to v18 was
  still being read as v17, because the version came from a `DataFile` that lags
  the document it describes. An open mother's version is now whichever of its two
  version numbers is further ahead, so a save is noticed immediately instead of
  one run later.
- **A mother whose version can't be read is no longer reported as missing.**
  Fusion's `findFileById` can refuse a valid lineage id — including the id a
  document reports about *itself*, offline and online alike — and a failed
  lookup was being treated as "this mother does not exist", which **disabled
  every row** and made the dialog unusable rather than merely uninformative.
  An unresolvable version now shows `unknown version` on a row you can still
  tick and rebuild. Only a genuinely missing lookup at rebuild time reports a
  missing mother, and it now tells you to open the mother and try again.
- **A mother's version is read from the open document where possible**, with no
  data-panel lookup at all — the reliable path, and the normal case, since you
  have usually just been editing it. Children also record the mother's
  version-specific id as a second key for when it is not open.
- **The comparison uses the mother's latest version**, not the version a
  lookup happened to land on, so a mother resolved through an older id can no
  longer make every child look up to date.
- **One mother, one heading — and one heading, one mother.** Groups are keyed on
  the mother's file id now, not its name. A rotated child used to make its mother
  render a second, contradictory heading (`mother1 — v16` above it, `mother1 —
  v16 is out of date` above its siblings), because the heading was derived from a
  single child's staleness, which is suppressed for a child with its own problem.
  Two different mothers that happened to share a name and a version merged into
  one group as though they were the same model; one mother recorded under two
  names split into two groups.
- **Headings name both versions**: `Base Cabinet — built from v12, now v14`
  instead of `v12 is out of date`, which gave you nothing to compare against.
- **The mother's name no longer carries a version suffix.** It was recorded from
  the document name (`mother1 v16`) instead of the file name (`mother1`), so
  headings read as though the version had been printed twice. Names already
  stored that way are re-read from the file, so existing children display
  correctly without being rebuilt, and a rebuild records the corrected name.
- **Update Children refuses a mother that is open at an older version than its
  newest**, naming both versions. Driving it would have built children from the
  old version while the dialog advertised the new one, then stamped the old
  version onto them and offered the same rebuild forever. Only that mother's
  children fail; the rest of the run continues. Fill Placeholders is deliberately
  left alone for now — see below.
- A child whose mother sits in a sub-assembly no longer reports its mother's
  version as unknown just because none of that mother's children are at the top
  level.
- A failed mother lookup reports Fusion's own reason, so a permission, hub or
  network failure is no longer indistinguishable from a deleted file.
- The status column is wider; it was truncating its own instructions mid-word.

Measured with `spikes/SVSpike6VersionIds`: `latestVersionNumber` **is**
lineage-wide — an older version's record reports its own `versionNumber` as 2
alongside `latestVersionNumber` 3 — so a mother resolved through either id
answers the staleness question correctly. The same run found `findFileById`
resolving a lineage urn it had refused earlier, so that failure is intermittent
rather than permanent, which is what the fallback is for.

Still open: which of an open document's version numbers keeps up with its own
saves. Real use has shown they can disagree — a document at v18 alongside a
record still reading v17 — so the refusal above triggers only when the open
version is genuinely BEHIND, never merely different, and applies to Update
Children only: a wrong guess there costs one mother's rows and a clear message,
where in Fill Placeholders it would abort the whole run on the commonest
workflow there is. Once measured it can cover both.

## 1.17.0 — Update children

- **Update Children** — one dialog listing every child in the layout, grouped
  by its mother. Each mother's heading shows the version its children were
  built from, and calls it out once that differs from the mother's current
  version — **any** difference counts, including a mother reverted to an
  older version, not just one that has moved forward. A box that has been
  moved or resized since it was filled is flagged the same way. Out-of-date,
  resized and moved children are pre-ticked; tick what you want rebuilt and
  click OK.
- A rebuild swaps geometry through the same in-place `updateBody()` path a
  re-fill uses, so a feature added downstream of the generated geometry
  survives for as long as what it references still exists after the change —
  the same durability rule as re-running Fill Placeholders, not a stronger one.
- Each mother is opened once for the whole run, and children sharing a mother,
  config and size share one recompute rather than driving it separately.
- Four kinds of child can't be helped by rebuilding, so they're shown but left
  unticked: a mother that can't be found, a placeholder box that was deleted,
  a box that has been **rotated**, and a child moved into a sub-assembly. A
  rotated box needs its front face picked again, so it's sent back to **Fill
  Placeholders**; a child in a sub-assembly has to be moved back to the top
  level before either command can find it.
- A problem opening or reading a mother fails every child under it; a problem
  with one child's own drive step fails only that child. Either way, every
  other mother's children still get their turn.
- If a run can't restore every parameter it drove on a mother you already had
  open, it warns you, names them, and tells you to close that mother
  **without saving**.
- Cancelling keeps whatever children were already rebuilt and reports the rest
  as cancelled.

## 1.16.0 — One anchor rule

- **The anchor always lands on the centre of the box's front face.** 1.15.0 asked
  the author to choose between four reference points; that choice turned out to add
  no capability. Placing a child is a rigid transform, the frame fixes its
  rotation, and the author already controls the remaining three degrees of freedom
  by where the joint origin goes — so one fixed rule expresses everything a menu
  could, with one fewer setting whose failure mode is silent.
- **Breaking:** a mother whose anchor rule was anything other than *front face
  centre* now places its children differently. Put the joint origin on the model's
  front face and re-run Prepare Mother Model.

## 1.15.0 — Placeholder fixes from first real use

Everything below was found by using 1.14.0 in Fusion, not by review.

- **The anchor's meaning is yours to choose.** Prepare Mother Model asks what the
  anchor joint origin lands on: the box's centre, its front-face centre, its
  bottom-face centre, or the middle of its bottom front edge. Fusion snaps a joint
  origin to a face centre readily but offers no easy way to snap to a model's
  centre, so assuming "anchor = box centre" placed a front-face anchor exactly
  half a depth too far back. If children come out offset by half of something,
  this is the setting to check.
- **A sheet config is optional** — see the 1.14.0 notes below.
- **The new buttons are visible.** They were registered but never promoted, so they
  sat in the panel's overflow menu and looked absent entirely.
- **Dialogs no longer run themselves when pre-empted.** Switching to another design
  while a dialog was open executed the command as if OK had been clicked — Fusion's
  documented default — which silently started a whole build. Affected the shipped
  Build Variants dialog too.
- Prepare Mother Model warns when two dimensions map to the same parameter, which
  is what every dropdown defaulting to the first parameter would otherwise save
  unnoticed.

## 1.14.0 — Placeholder instantiation

- **Prepare Mother Model** — record on a saved parametric document which
  parameters its width, depth and height map to, which joint origin is its
  anchor, and which way it faces. Stored on the document, so it travels with
  the file.
- **Fill Placeholders** — select the front face of each placeholder box in a
  layout, pick a prepared mother, and each box gets a child component driven to
  that box's own size and orientation. The anchor lands at the box centre; the
  box is hidden, never deleted.
- **A sheet config is optional.** By default each box drives only the mother's
  width, depth and height and no sheet is read at all, so a mother that was
  never linked to one still works. Pick a config row when you want the sheet to
  set everything else as well.
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
