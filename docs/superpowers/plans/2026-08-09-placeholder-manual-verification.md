# Placeholder instantiation — manual verification checklist

**Branch:** `placeholder-fusion` (Plan 1, Tasks 6–11) · **Version:** 1.14.0
**Why this exists:** `adsk` only runs inside Fusion, so CI can never execute any of
this feature's Fusion-side code. Every task's review verified by *reading*. This
list is the only actual verification the feature gets.

Ordered by value. **Items 1–6 are worth the session**; 7–14 are cheap
confirmations you can batch at the end.

## Results so far (session of 2026-08-10/11, Fusion Personal, macOS)

| # | Result |
|---|---|
| 1 | **PASS** — reported fine. Materials and appearances confirmed carrying over, including on the path where the tool opens and closes the mother itself, which is what the deferred-close fix was for |
| 2 | **PASS** — after the anchor fix. Originally failed: every child sat half a depth too far back |
| 3 | **PASS** |
| 4 | **PASS** — a reported appearance problem turned out to be a panel with no appearance in the mother itself, faithfully copied. Not a defect |
| 5–15 | not yet run |

Found by using it, not by review — all now fixed and released in 1.15.0:

- The anchor always landed on the box's **centre**, which only works if the joint
  origin is at the model's centre. Fusion snaps to face centres instead, so a
  front-face anchor put every child half a depth back. Now the author says what
  the anchor lands on.
- The two new buttons were registered but never **promoted**, so they sat in the
  panel's overflow menu and looked entirely absent.
- Switching to another design **executed** the open dialog as if OK had been
  clicked (Fusion's documented default for a pre-empted command), silently
  starting a whole build. Affected the shipped Build Variants dialog too.
- A sheet config was mandatory; it is now optional, which is what made testing
  without a linked sheet possible at all.

**Do item 1 before touching any placeholder work** — it is the only thing here
that can have broken something already shipped and released.

---

## 1. Regression: the shipped Build Variants Assembly from Sheet

Task 6 refactored `build_exports()` — working, released code — to share a geometry
core with the new feature. Three independent checks confirmed no behaviour change
by reading, but the `TemporaryBRepManager` handle is now fetched per call instead
of held for the build, and reading cannot settle whether that matters.

Run a real multi-row sheet through **both** a *Whole model* and a *Named
components* profile, on a source model whose bodies have **distinct materials and
appearances**. Then use the **Test tab** preview on a row.

- **PASS** — output identical to 1.13.0: same components, same names, same
  left-to-right spacing, **materials and appearances present on every body**, view
  framed on open, source model back at its original parameter values afterwards.
- **FAIL** — any grey body (the temp-BRep handle change), any missing body, wrong
  spacing, a source model left holding variant values, or a Test-tab preview that
  no longer applies values (`apply_expression` moved modules).

## 2. Front-face orientation across differently-modelled boxes

`face.geometry.normal` returns the underlying plane's normal, which the Fusion API
does not guarantee is the face's *outward* normal — `BRepFace.isParamReversed`
exists precisely for this. Nothing in the add-in consults it. **Deliberately not
"fixed" blind** — it has to be measured first.

Model four boxes in one layout: one extruded along +Y, one along −Y, one from a
symmetric/midplane extrude, one rotated 45°. Select each one's *intended* front
face and fill them all in one gesture.

- **PASS** — every child faces out of the face you picked, and each child's
  width/depth/height match its own box.
- **FAIL** — any child rotated 180°, or width and depth swapped. **Note which
  boxes failed and how they were modelled** — that tells us whether
  `isParamReversed` is the fix.

## 3. Prepare → Fill, then Fill again

`_open_mother` refuses a mother with unsaved changes. It cannot tell your unsaved
work from the add-in's own. A session-level bypass was added for mothers this run
drove *and* restored cleanly, but the two triggering sequences need proving.

Prepare a mother. Without closing it, run Fill on 2 boxes. Then, still without
closing it, run Fill on 2 more.

- **PASS** — both runs complete.
- **FAIL** — either run refuses with *"The mother has unsaved changes"* when you
  changed nothing. Note **which leg** failed: that decides whether the fix needs to
  cover Prepare's attribute write, the parameter drive, or both.

## 4. Rebuild with a changing body count — three times

Two separate bugs live here, and **neither can show up on the first rebuild**.

Use a mother with **3+ bodies carrying visibly different materials**. Fill a box
with config A. Re-fill with config B, where B adds a body whose name sorts into the
**middle** (not the tail). Re-fill with config A again. Inspect **body by body**
after each step.

- **PASS** — correct geometry every time, **and every body wearing its own
  material**, on all three passes.
- **FAIL, geometry wrong or a body missing on the *third* pass** — the recipe
  records body order wrongly again.
- **FAIL, geometry right but materials swapped between bodies** — the look-ordering
  fix did not hold.

## 5. Deliberate fragile-feature failure mid-run

This is the README's headline promise, and the one thing the spike measured but did
not test *in a multi-child run*.

Fill three boxes. Add a **fillet on a generated edge** of child #1 (deliberately the
fragile case). Re-fill all three with a config that changes the shape.

- **PASS** — child #1 reports `rebuild failed`; children #2 and #3 rebuild
  correctly; the run ends cleanly back in the layout document.
- **FAIL** — #2 and #3 also fail, or Fusion is stuck in base-feature edit mode.
  `finishEdit()` raising may leave the edit open, and nothing closes it.

Then look at child #1 itself: is its geometry really recoverable by re-filling? The
swap already succeeded before `finishEdit()` raised, so the recipe records the old
body names while the base feature holds the new ones — if the body count changed,
the re-run will refuse loudly rather than recover.

## 6. Move a filled box, re-fill, then save / close / reopen

- **PASS** — the child moves with the box **and is still there after reopening**.
- **FAIL** — the child snaps back on recompute or reopen. Then
  `occurrence.transform2` needs a `design.snapshots.add()` in a parametric design.

---

## Cheap confirmations — batch these

**7. First run with no prepared mother.** Open Fill Placeholders with no mother
anywhere, click one face.
PASS: the "No prepared mother models found" text. FAIL: a Python traceback.

**8. Forget to press Load configs.** Select faces, pick a mother, click OK.
PASS: "Pick a mother model and a config first." FAIL: a traceback naming
`— press Load configs —`.

**9. Expected failures read as sentences, not stack traces.** Trigger each: a
mother with real unsaved changes; a mother never prepared; a mother with one W/D/H
parameter renamed; a sheet column matching no parameter.
PASS: a plain readable message box each time. FAIL: a traceback.

**10. Multi-tab mother sheet.** Put the configs on the **second** tab of a workbook.
PASS: Load configs lists that tab's rows. FAIL: it lists the first tab's rows.
Known residual: the pinned tab is keyed by *spreadsheet id*, not by mother, so two
mothers sharing one workbook on different tabs will both resolve to whichever tab
was last pinned in the Build dialog.

**11. Placeholders inside a `Layout` component** — as the README recommends — with
that `Layout` occurrence **moved and rotated off the origin**.
PASS: slot ids stamp, boxes hide, children land at correct world positions.
FAIL: `no slot id was stamped` lines, or children offset by the Layout's transform.

**12. Copy-paste a *filled* placeholder box, then fill the copy.**
PASS: a new child at the copy; the original keeps its own child.
FAIL: the original's child *moves* to the copy — `slotId` was inherited on paste.

**13. Cancel a run mid-way.**
PASS: already-built children remain, the rest report `cancelled before it was
built`, you end back in the layout, no traceback, and the mother is closed (if we
opened it) or still open and **not saved** (if you had it open).

**14. UI lifecycle.** Stop the add-in from Scripts and Add-Ins, then Start it
again. Twice.
PASS: exactly one **Prepare Mother Model** and one **Fill Placeholders** button,
both functional. FAIL: duplicate buttons, or a button that does nothing.
While you're there: note whether the two new buttons land on the add-in's own
**Sheet Variants** panel or on Fusion's native Add-Ins panel.

**15. A child moved into a sub-assembly.** Drag a filled child under another
component, then re-fill its box.
PASS: a clear refusal saying the child was moved into a sub-assembly.
FAIL: a second child built on top of the first.

---

## Known residuals — not blocking, recorded deliberately

1. ~~`find_children`'s `allOccurrences` access is unguarded.~~ **Fixed before merge.**
   The collection access is now guarded, and when it fails the slot is *refused*
   rather than falling through: without that list we cannot tell "moved into a
   sub-assembly" from "deleted", and wrongly refusing a slot is loud and
   recoverable where wrongly duplicating one is neither.
2. **The README's recovery claim is conditionally true.** Re-filling recovers a
   same-body-count failure; a body-count-changing failure refuses loudly instead.
3. **Pinned tab is keyed by spreadsheet id, not mother** — see item 10.

Also deliberately unchanged: cancel leaves already-built children in place (their
recomputes were already paid for), and `restore_values` writes expressions raw
rather than through `apply_expression`'s quoted-text fallback, so a *text* parameter
can genuinely fail to restore — pre-existing, shared with the shipped build path,
and now at least *detected* by the loud "close WITHOUT SAVING" warning.
