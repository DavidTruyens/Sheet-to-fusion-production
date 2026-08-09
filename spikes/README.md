# Spikes

Throwaway Fusion scripts that answer questions CI cannot. The `adsk` API only
exists inside Fusion, so every assumption this add-in makes about it is unproven
until someone runs it on real hardware — these scripts are how that happens
before a design leans on the answer rather than after.

They are not part of the add-in and are never shipped in a release. They are kept
in the repo so a result can be re-checked when Fusion changes under us.

## Running one

**Utilities → Scripts and Add-Ins → Scripts tab → green +**, browse to the folder,
select it, click **Run**. Each script reports everything in one message box and
ends with its own PASS/FAIL verdict.

## Current spikes

| Folder | Question |
|--------|----------|
| `SVSpike1TempBrep` | Do `TemporaryBRepManager` bodies survive activating and closing another document, and still insert afterwards? |
| `SVSpike2BodyAttrs` | Do `BRepBody` attributes survive recompute, rollback and save/reopen? (run twice) |
| `SVSpike3UpdateBody` | Does `BaseFeature.updateBody()` preserve downstream features? |
| `SVSpike4JointOrigins` | Is the joint-origin collection `jointOrgins` or `jointOrigins`, and is an anchor readable after a recompute? |

Why each one matters, what counts as a pass, and what to do when one fails:
[`docs/superpowers/plans/2026-08-08-placeholder-spike.md`](../docs/superpowers/plans/2026-08-08-placeholder-spike.md).
Record results there, not here.
