# Update Children — manual verification checklist

**Branch:** merged to `main` (PRs #21, #22) · **Version:** 1.17.2
**Why this exists:** `adsk` only runs inside Fusion, so CI can never execute this
feature's Fusion-side code. Every task was verified by *reading*. This is the only
actual verification it gets.

Ordered by value. **Items 1–3 decide whether the feature is trustworthy** — if 1 or
2 fails, stop and report before doing the rest.

## Status at 1.17.2

| # | Item | Status |
|---|------|--------|
| 1 | Null test | ⚠️ **partial** — no false `moved`/`resized`, but boxes were at ROOT |
| 2 | Two-mother run | ⬜ not run — only one mother in the test layout |
| 3 | Core loop | ✅ **pass** |
| 4 | Hand-made cut | ⬜ not run |
| 5 | Move a box | ⬜ not run |
| 6 | Resize a box | ⬜ not run |
| 7 | Rotate a box | ✅ **pass** — and exposed a separate false positive, now fixed |
| 8 | Deleted box / sub-assembly | ⬜ not run |
| 9 | Isolation | ⬜ not run |
| 10 | Mothers come back clean | ⬜ not run |
| 11 | Session trust | ⬜ not run |
| 12 | Cancel midway | ⬜ not run |
| 13 | The dialog as an object | ⚠️ **partial** — three defects found and fixed |
| 14 | Scale | ⬜ not run |

**Four defects reached Fusion and were found by real use, not review** — all fixed
in 1.17.1/1.17.2 and recorded under *What real use found* at the foot of this file.
None were on this checklist, which is worth noticing: every item tests what the code
was *designed* to do, and all four were things it was designed to do wrongly.

**Set-up, once:** a layout filled from **two different mothers**, with the
placeholder boxes **inside a `Layout` component** (as the README recommends), at
least one child carrying a **hand-made cut**, and two children of the same mother
at the same size.

---

## 1. The null test, with boxes inside a component

> **Status: ⚠️ partial.** In the 1.17.0 run, untouched children read `out of date`
> alone — no spurious `moved` or `resized` — which provisionally exonerates
> `matrices_differ`'s 1e-6 tolerance. But the browser in that session shows the
> boxes in the **root component's** `Bodies` folder, not inside a `Layout`
> component. Native and world coordinates coincide at the root, so the
> coordinate-space cause **was never exercised**. This item is not done: it needs
> re-running with the boxes inside a component, which is what the README recommends.

**This is the diagnostic that matters most.** Change nothing at all. Run
**Update Children**.

- **PASS** — every child reads `up to date` (or `unknown version` if a mother's
  version cannot be resolved), and **nothing is pre-ticked**.
- **FAIL** — anything reads `moved`, `resized` or `rotated` when you have touched
  nothing.

**If it fails, this tells us which of two causes it is.** Move your `Layout`
component (or move the boxes into the root component) and re-run:

- Readings **change** → the survey is measuring the box in its component's local
  space instead of world space. `find_slot_bodies` returns a native `BRepBody`,
  whose vertex coordinates are parent-component-relative, while fill time reads a
  selection proxy, which is world. Fix is an assembly-context proxy or applying
  the occurrence transform.
- Readings are the **same** wherever the boxes live → `matrices_differ`'s
  tolerance is too tight. It applies a single `1e-6` to both rotation cosines and
  translation, i.e. **10 nanometres**, against a matrix Fusion stored and handed
  back. Fix is loosening the default to about `1e-4` (1 µm), still far below any
  deliberate nudge.

Report which. Both were left deliberately unfixed so this check can tell them
apart — pre-fixing either would have destroyed the signal.

A false positive here is not cosmetic: clicking OK would send every healthy child
through a real `updateBody()` swap, and that can destroy a downstream fillet.

## 2. A two-mother run in one OK

Tick children belonging to **both** mothers, click OK once.

- **PASS** — each child gets its own mother's geometry, every ticked child appears
  exactly once in the report, each mother opens once.
- **FAIL** — a child of mother B comes back looking like mother A, or the report
  claims success for a child whose geometry did not change.

That failure would be the multi-mother activation path, and it is the worst
outcome available on this branch. A check was added for it (the run now verifies
the active document really is the intended mother and fails that mother's group
loudly if not), but the failure path itself has never executed.

## 3. The core loop

> **Status: ✅ pass** (1.17.2). A parameter changed in the mother and saved; its
> children read `out of date` under a heading naming the mother and the version
> they were built from; OK rebuilt them with the new geometry.
>
> Two things this item was written to catch failed first, and are what 1.17.1 and
> 1.17.2 fix: the comparison read a **stale** version (a mother saved to v18 read
> as v17 — item 3's own FAIL note about the data panel and the open document
> disagreeing was closer to the truth than it knew), and the heading was
> **duplicated** for one mother.

Change a parameter in mother A, **save** it, close it. Run **Update Children**.

- **PASS** — only mother A's children read `out of date` and are ticked, under a
  heading naming mother A and the version they were built from. OK → each rebuilds
  with the new geometry. Re-run immediately → everything reads `up to date`,
  nothing ticked. That last part proves the stored version was rewritten.
- **FAIL** — mother B's children are flagged too; or the re-run still says
  `out of date` (if so, check whether you have mother A open at an *older* version
  than the cloud's latest — the survey reads the data panel while the rebuild
  records the open document's version, and those disagree in that case).

## 4. The hand-made cut

On the child carrying one, after item 3.

- **PASS** — the cut survives, **or** Fusion marks it errored. Both acceptable.
- **FAIL** — it vanishes silently.

Say explicitly which of the three happened.

## 5. Move a box

- **PASS** — that child reads `moved`, is ticked, and after OK it moves to the box
  **with its hand-made cut moving with it**, staying in the same place on the
  cabinet.
- **FAIL** — the child moves but the cut stays behind. That would mean placement
  was baked into the bodies instead of the occurrence transform.

## 6. Resize a box

- **PASS** — the label contains `resized`. **`resized, moved` is also a pass** —
  dragging one side moves the box's front-face centre, which genuinely is a move.
  Only a resize that leaves the front face exactly where it was reads `resized`
  alone.
- **FAIL** — no flag at all, or `rotated`.

## 7. Rotate a box 30° about Z

> **Status: ✅ pass.** A genuinely rotated box read
> `rotated — re-run Fill Placeholders`, checkbox disabled and unticked, while its
> siblings were ticked.
>
> It also exposed a **false positive this item did not anticipate**: the same box
> carried fillets, and a filleted box read `rotated` *whatever its orientation*.
> Item 7's own remedy — re-run Fill Placeholders — could never have cleared it,
> because the geometry was never the problem. Fixed in 1.17.2 by judging
> orientation from flat faces. See *What real use found*.

- **PASS** — reads `rotated — re-run Fill Placeholders`, checkbox **disabled**, not
  pre-selected.
- **FAIL** — it is tickable, or it reports `resized`/`moved` with plausible
  numbers. That would mean it is being mis-measured in the stale frame, which is
  the silent failure this design set out to avoid.

**Known and undetectable:** a 180° flip, or any 90° turn of a **square-plan** box,
leaves the vertex projections identical. Those read `up to date` and stay facing the
old way. Not worth reporting — but the README overstates this, and that is worth
fixing.

## 8. A deleted box, and a child dragged into a sub-assembly

- **PASS** — the deleted-box child reads `placeholder missing`, disabled. The
  sub-assembly child still **appears as a row**, unticked, saying to move it back
  to the top level.
- **FAIL** — either row is missing entirely, or either is tickable.

## 9. Isolation

After every run above.

- **PASS** — the other mother's children were never touched; one failing child
  never cost the run.
- **FAIL** — a child you did not tick changed.

## 10. The mothers come back clean

Reopen each mother after a run.

- **PASS** — every parameter exactly as you left it, and **no** "could not restore"
  message box appeared.
- **FAIL** — a driven `NNN.NNNNNN cm` value still sitting in a parameter. If so,
  do **not** save that mother.

If the warning box ever does appear, nobody has seen it rendered — read it
critically and report the wording.

## 11. The session-trust check *(deliberately adversarial)*

Run an Update successfully. Then open that mother, make a **real edit**, leave it
**unsaved**, and run Update Children again on its children.

- **Expected today** — the run proceeds, with no false "unsaved changes" refusal.
  That is the session bookkeeping working: a mother this session drove and cleanly
  restored is trusted thereafter.
- **What to think about** — the children are now built from your **unsaved**
  geometry but will read `up to date` against the last *saved* version. Confirm
  that is what you see, then decide whether you want the equivalent gate in
  `Fill Placeholders` tightened. It currently grants that trust even when a run
  drove nothing at all, which is the looser of the two rules.
- Separately, in a **fresh** Fusion session, a mother with genuine unsaved changes
  **must** be refused on the first attempt.

## 12. Cancel midway

- **PASS** — children already driven are rebuilt, none half-built, the rest listed
  as `cancelled before it was built`, no traceback, and you end up back in the
  layout.
- Cancel stops *driving*; Phase 2 still commits what was already driven. That is
  intended, not a failure.

## 13. The dialog as an object

> **Status: ⚠️ partial.** The button is on the panel and the heading row spans the
> table width — both pass. The two open questions this item raised were both
> answered **FAIL**, and both are fixed in 1.17.2:
>
> - the status column *was* clipping (`rotated — re-run Fill Placeho`) — widened
> - a mother with children at two versions did **not** give one heading per
>   version; it gave two contradictory headings for the *same* version, because
>   the heading was derived from one child's staleness
>
> Still to check: switching documents while the dialog is open.

- **PASS** — the **Update Children** button is on the panel itself, not in the
  overflow `…` menu, after a fresh add-in load.
- Switch documents while the dialog is open. **PASS:** nothing is rebuilt.
- Also look at: whether the mother heading row spans the full table width; whether
  the long "moved into a sub-assembly" sentence is clipped in the status column
  (it probably is — decide if you care); and whether a mother with children built
  at two different versions gives one heading per version rather than alternating
  rows.

## 14. Scale and the cheap paths

- On a kitchen-sized document the dialog opens without a stall, and the data panel
  is hit once per **mother**, not once per child.
- A **size-only** child (config left on *none*) updates with no sheet read.
- Two children of the same mother, config and size cause **one** recompute.
- **FAIL** — the dialog takes many seconds to open, or a size-only child reports a
  sheet error.

---

## What real use found — none of it on this checklist

Four defects reached Fusion. Each was found by using the feature, not by review and
not by any item above, and each is fixed in 1.17.1/1.17.2.

1. **Every row disabled: "mother not found".** `findFileById` refused a valid
   lineage urn — including the id a document reported about *itself* — and a failed
   lookup was reported as a *missing mother*, which greys out the row. The command
   was unusable rather than merely uninformative. An open mother's version now
   comes off its own `DataFile` with no service call, and an unresolvable version
   reads `unknown version` on a row you can still tick. Later measurement (spike 6)
   found the same lookup working, so the failure is **intermittent** — meaning the
   real fix was never trusting the lookup, not making it succeed.

2. **A fillet read as a rotation.** The check wanted exactly two distinct vertex
   coordinates per axis; rounding a box's edges puts vertices at the tangent
   points, giving four (`min`, `min+r`, `max-r`, `max`) on a box perfectly square
   to its frame. Every filleted placeholder read `rotated` permanently. Orientation
   is judged from **flat faces** now — a fillet adds none, a chamfer only adds
   extra ones.

3. **A saved mother read as the previous version.** A mother saved to v18 was read
   as v17, because the `DataFile` lags the document it describes. An open mother's
   version is now whichever of its two version numbers is further ahead.

4. **One mother, two contradictory headings.** The heading came from a single
   child's staleness, which `child_status` suppresses when it returns early for a
   per-child problem — so a rotated child got `mother1 — v16` and its siblings
   `mother1 — v16 is out of date`. Headings are keyed on the mother's **file id**
   now, which also stops two same-named mothers merging and one mother recorded
   under two names splitting. The name came from the *document* (`mother1 v16`)
   rather than the file, so headings read as though the version were printed twice.

**What this says about the checklist.** Every item above tests behaviour the code
was designed to have. All four of these were behaviours it was designed to have
*wrongly* — a false negative in a lookup, a geometric check with an unstated
assumption, a stale read, and a display keyed on the wrong thing. A checklist
written from the implementation cannot find those. They were caught by looking at a
screenshot and asking why it said what it said.

## Known residuals — recorded, not hidden

- **The native-vs-world coordinate space of the measured box is still untested.**
  Item 1 ran with the boxes in the **root** component, where native and world
  coincide, so the question it exists to answer went unasked. `matrices_differ`'s
  1e-6 tolerance is provisionally exonerated — untouched children showed no false
  `moved` — but only in that same configuration.
- **Q4 is unmeasured:** which of an open document's version numbers tracks its own
  saves. Not a correctness risk — the stale-version guard fires only when the open
  version is genuinely *behind*, and both directions of lag are handled — but it
  decides whether that guard can extend to `Fill Placeholders`.
  `spikes/SVSpike6VersionIds` asks it and now scans every open document.
- **The multi-mother activation failure path has never executed.** The guard is
  new; item 2 can only fail to reproduce the problem, never prove it cannot happen.
- **`Fill Placeholders` grants session trust on weaker evidence** than
  `Update Children` does — it can mark a mother "cleanly restored" after a run that
  drove nothing. Shipped code; see item 11.
- **A 180° or square-plan 90° rotation is undetectable** (item 7), and the docs
  currently claim rotations are flagged without that caveat.
- **The spec's dialog mockup is aspirational** — it shows `v12 → v14`, per-row
  dimensions and `resized 900 → 1000`, none of which the code renders. The README
  and CHANGELOG were written from the code instead.
- **`placeholder_cmds.py` is ~1,950 lines.** Still coherent, but this is the point
  at which splitting the Update command into its own module would help.
