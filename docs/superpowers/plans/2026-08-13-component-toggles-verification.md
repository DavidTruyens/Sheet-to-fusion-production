# Component on/off columns — manual verification

The geometry walk, the Test tab preview and the template generator all run
inside Fusion and cannot be unit-tested. Run this against a **nested** test
assembly and record the result under each item.

**Test assembly:** a design with `Carcass` (containing sub-components `Side_L`
and `Back`), `Drawer` placed **twice** at the top level, and at least one loose
body directly in the root component.

**Test sheet:** columns `Name`, one driveable parameter, `Carcass`, `Drawer`.

## Items

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
   - Result:

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
