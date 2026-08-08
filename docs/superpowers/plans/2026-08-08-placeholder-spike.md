# Placeholder Instantiation — Spike

**Prerequisite to** [Plan 1](2026-08-08-placeholder-fill.md) and [Plan 2](2026-08-08-placeholder-update.md).
**Spec:** [2026-08-08-placeholder-instantiation-design.md](../specs/2026-08-08-placeholder-instantiation-design.md)
**Scripts:** [`spikes/`](../../../spikes/) — ready to run, no copy-paste.

This is **not** a TDD plan. It is a manual session inside real Fusion, because
none of these behaviours can be exercised by CI — `adsk` only exists inside
Fusion, and the whole design rests on them.

**Do not start Plan 1 Task 6 until Spikes 1 and 3 have passed.** Plan 1 Tasks 1–5
are pure Python and can run in parallel with this. If any spike fails, stop and
revise the spec rather than coding around it.

## Running them

In Fusion: **Utilities → Scripts and Add-Ins → Scripts tab → green +**, browse to
each folder under `spikes/`, then select it and click **Run**. Each script reports
everything in one message box, ending with its own PASS/FAIL verdict.

| Script | Needs |
|--------|-------|
| `SVSpike1TempBrep` | A document with a solid body, plus one other saved document in the same project |
| `SVSpike2BodyAttrs` | A **saved** document with a parametric solid and a user parameter. **Run twice** |
| `SVSpike3UpdateBody` | An **empty parametric** document — it builds the scenario itself |
| `SVSpike4JointOrigins` | A document with at least one joint origin |

## Results

Fill this in as you go, then commit it.

| # | Question | Answer | Notes |
|---|----------|--------|-------|
| 1 | Do `TemporaryBRepManager` bodies survive activating and closing a *different* document, and still insert? | **PASS** | Volume 600.0 unchanged; inserted into a fresh document as 1 body. Fusion Personal, macOS. First run only exercised the scratch-document leg — the "activate a real second design" leg was skipped by a bug (identity comparison on API wrappers); **re-run pending** to confirm the stronger leg |
| 1b | Does `app.data.findFileById()` resolve? | **PASS** | Resolved `"spike1" v1`. Plan 1 Task 9 `_open_mother()` is viable. (`app.data.activeProject` throws `InternalValidationError` on this setup — avoid it) |
| 2 | Do `BRepBody` attributes survive recompute, rollback, and save/reopen? | | |
| 3 | Does `BaseFeature.updateBody()` preserve downstream features? | | |
| 3b | Is `base.bodies` populated once downstream features exist? | | |
| 4 | Is the joint-origin collection spelled `jointOrgins` or `jointOrigins`? | | |

**Fusion API gotcha found while spiking:** `documents.item(i)` returns a **new
Python wrapper each call**, so `doc_a is doc_b` is never true even for the same
document. Compare by name or `dataFile.id`. Plan 1 Task 9's `_open_mother()`
already compares `doc.dataFile.id`, which is correct — but nothing else in either
plan may use `is` on a Fusion object.

---

## Spike 1 — Temp BRep survival across documents

**Why it matters:** the entire cross-document engine snapshots geometry with the
mother active, then activates the layout and inserts it. If snapshots die when
another document is activated, Phase 1 and Phase 2 cannot be separated and the
approach must change shape.

**What we already know:** `build_exports()` relies on snapshots surviving
`documents.add()` — the comment at `SheetVariants.py:399` is explicit that
everything *else* gets invalidated. That is suggestive, not proof: creating a
document is not the same as activating and closing one.

The script goes further than reading a volume back. It opens, activates and closes
another document, then **actually inserts** the snapshot into a fresh design via a
base feature — the exact thing Phase 2 does. A snapshot that reports a plausible
volume but refuses to insert would still sink the design.

**PASS:** volume unchanged and non-zero, and the insert produces a body.
**FAIL:** an exception, a garbage volume, or a failed insert.

**If it fails:** the fallback is a staging document — snapshot into a hidden
temporary design while the mother is active, then copy from staging into the
layout. Record that here and revise the spec's "Generation engine" section before
starting Plan 1.

---

## Spike 2 — Body attribute persistence

**Why it matters:** slot identity is an attribute stamped on the box body. If it
does not survive, identity has to fall back to body names and renaming a box
silently orphans its child. Discovery also depends on `Design.findAttributes`
returning the whole set in one call, which the script checks too.

**Run it twice.** The first run stamps the attribute and tells you what to do; the
second verifies. It detects which phase it is in, so nothing needs editing. Between
runs you must: change a parameter, roll the timeline back and forward, save, close
and reopen.

**PASS:** the direct read returns the value, `findAttributes` count is at least 1,
and the attribute's parent is the body.
**FAIL:** a lost value, a count of 0, or an unreadable parent.

**If it fails:** slot identity becomes `(component name, body name)` stored in
`childRecipe`, and the spec must state that renaming a placeholder orphans its
child. Also re-check `findAttributes` on its own — the whole discovery mechanism
in both plans depends on it.

---

## Spike 3 — `updateBody` preserving downstream features

**This is the one that matters.** It carries the design's central promise — that a
cut a designer adds by hand survives a rebuild — and that promise is the entire
reason the freeze flag was rejected during brainstorming.

The script builds the scenario itself: a base feature holding a box, a fillet on
top of it as the "designer's" downstream feature, then swaps the base feature's
geometry for a bigger box via `updateBody()`.

**PASS:** the fillet still exists afterwards and the volume reflects the new box.
A **warning or error** health state is an acceptable partial pass — the spec
already says Fusion marking a broken reference is the expected outcome. What must
not happen is the feature silently vanishing, or `updateBody` throwing.

**FAIL:** `updateBody` raises, or the fillet count drops to 0.

**If it fails:** the "your extra cut survives a rebuild" promise is false. Do not
work around it — return to the spec. The likely replacement is the freeze flag
rejected during brainstorming, which is a materially worse feature and the user's
decision to make, not a detail to patch.

**Also record 3b.** The script prints `base.bodies.count` before and after the
downstream feature exists. `build_engine.base_feature_bodies()` (Plan 1 Task 10)
uses `base.bodies` when it is populated and falls back to positional matching when
it is not — this tells us which branch is real, rather than shipping a fallback
nobody has ever exercised.

---

## Spike 4 — Joint origin spelling and readability

Two things in one short script. First, which spelling resolves: the Fusion API has
a long-standing typo and Plan 1 Task 7 needs the right one. Second, that a joint
origin's position is still readable **after** a parameter change — `_snapshot_for()`
reads the anchor after driving the mother, so a stale or unreadable origin there
would misplace every child.

**PASS:** one spelling resolves, and the origin's position reads back after the
nudge. The position being *identical* is fine — it only means that anchor does not
depend on that particular parameter. What is being tested is that it is readable.

**FAIL:** neither spelling resolves, or the position read throws after a recompute.

---

## When the spike is done

- [ ] All five rows in the Results table are filled in
- [ ] Any FAIL has been discussed and the spec revised before Plan 1 Task 6 starts
- [ ] Plan 1 Task 7's joint-origin spelling matches result 4
- [ ] Plan 1 Task 10's `base_feature_bodies()` matches result 3b
- [ ] Commit the results: `git commit -am "docs: record placeholder spike results"`
