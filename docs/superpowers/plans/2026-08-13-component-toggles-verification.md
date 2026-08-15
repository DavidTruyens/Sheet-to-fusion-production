# Component on/off columns — manual verification

The geometry walk, the Test tab preview and the template generator all run
inside Fusion and cannot be unit-tested. Run this against a **nested** test
assembly and record the result under each item.

**Test assembly:** a design with `Carcass` (containing sub-components `Side_L`
and `Back`), `Drawer` placed **twice** at the top level, and at least one loose
body directly in the root component.

**Test sheet:** columns `Name`, one driveable parameter, `Carcass`, `Drawer`.

## Items

> **First real use, 2026-08-15, on `Corpus v0` (add-in 1.18.0).** A four-variant
> build came out with the drawer switched off on `Variant_1` and present on
> `Variant_2`, `_3` and `_4`. That exercises the whole path end to end — sheet
> column read, off-set resolved, bodies pruned, variants laid out — on a real
> model rather than a purpose-built test one.
>
> The model is genuinely nested — `Corpus` holds `LeftCorpus`, `TopCorpus`,
> `RighhtCorpus`, `BottomCorpus` and `BackCorpus`; `Drawer` holds `Component8`
> through `Component11` — so switching `Drawer` off took its four children with
> it. That is the subtree pruning of item 2, on a real assembly.
>
> It is still not a pass of this checklist. Items 1, 4, 5, 6, 7 and 9 were not
> attempted, and item 3 needs a component instanced twice at the top level,
> which this model does not have. One thing to confirm while finishing item 2:
> a drawer-off variant showed 5 bodies and a drawer-on variant showed 6, so the
> whole `Drawer` subtree contributed a single body. If those four
> sub-components each own a solid body, the on-variant should have shown 9 —
> worth settling, because "fewer bodies than expected" is exactly the symptom
> item 1 is looking for.

1. **The rewritten walk still collects what the old one did.** This is the
   branch's core backward-compatibility claim and the only part of it a test
   cannot reach. Build the nested test assembly from a sheet with the component
   columns **deleted**, once on this branch and once on `6922331` (the commit
   the branch started from). Confirm each variant comes out with the same body
   count and the same placement. A difference here means the recursion does not
   reach something `allOccurrences` did — a derived component, a flat pattern,
   or a linked sub-assembly.
   - Result:

2. **Off removes the component and its subtree.** Build with `Carcass=FALSE`
   on one row. That variant contains no `Carcass`, no `Side_L`, no `Back`. The
   other row is unaffected.
   - Result:

3. **Both instances switch together.** Build with `Drawer=FALSE`. Neither
   top-level instance appears.
   - Result:

4. **Off wins over a Named-components profile.** Add a profile with rule
   **Named components** selecting `Side_L`. Build a row with `Carcass=FALSE`.
   That variant is absent from the profile's output and named in the run
   summary; the profile's other variants still build.
   - Result:

5. **Loose root bodies are unaffected.** The body modelled directly in the root
   appears in every variant regardless of any toggle.
   - Result:

6. **The source model is unchanged after a run.** This is the item that matters
   most — dropping bodies instead of suppressing occurrences is justified
   entirely by the source model being untouchable. After a build, confirm: same
   components present, every light bulb in its original state, parameters back
   to their original expressions, and the document not marked modified beyond
   the usual parameter round-trip.
   - Result:

7. **Check catches a bad sheet.** In turn: a column naming `Side_L` (error,
   "sub-component"); a column naming `Drawr` (error, no match); a cell reading
   `maybe` (error naming the cell); a blank toggle cell (warning, component
   stays in). The OK/Build button is disabled while any error stands.
   - Result: **sub-component case passes** (2026-08-15, `Corpus v0`, 1.18.0). A
     `BackCorpus` column — a sub-component of `Corpus` — reported
     `✗ 1 error(s), 0 warning(s) — fix before building` with
     `Column "BackCorpus" is a sub-component — only top-level components can be
     switched on or off.`, and the OK button was disabled, so the
     errors-block-the-build clause holds too. The `Drawr`, `maybe` and
     blank-cell cases are still to do.

8. **KNOWN GAP — the Test tab preview does not honour toggles.** Previewing a
   row whose component is `FALSE` still shows that component, so the preview
   disagrees with what a build would produce. The build itself is correct; only
   the preview is wrong. Implementing this was deferred pending a spike into
   whether Fusion's preview revert restores visibility. Nothing to verify here —
   this item records the gap so it is not mistaken for a bug found in testing.

9. **Generated template round-trips.** Run **Create Variant Sheet Template**.
   It has one `TRUE` column per top-level component. Build from it unchanged
   and confirm the result is identical to a build from the same sheet with the
   component columns deleted.
   - Result:

## Sign-off

- Verified by:
- Date:
- Fusion version:
