# Placeholder Instantiation — Spike

**Prerequisite to** [Plan 1](2026-08-08-placeholder-fill.md) and [Plan 2](2026-08-08-placeholder-update.md).
**Spec:** [2026-08-08-placeholder-instantiation-design.md](../specs/2026-08-08-placeholder-instantiation-design.md)

This is **not** a TDD plan. It is a manual session inside real Fusion, because
none of these three behaviours can be exercised by CI — `adsk` only exists inside
Fusion, and the whole design rests on them.

**Do not start Plan 1 until all three rows below are filled in.** If any answer is
NO, stop and revise the spec rather than working around it.

Fastest way to run these: **Utilities → Scripts and Add-Ins → Scripts → green +**,
create a scratch script, paste each snippet, Run, read the message box.

## Results

| # | Question | Answer | Notes |
|---|----------|--------|-------|
| 1 | Do `TemporaryBRepManager` bodies survive activating and closing a *different* document? | | |
| 2 | Do `BRepBody` attributes survive recompute, rollback, and save/reopen? | | |
| 3 | Does `BaseFeature.updateBody()` preserve downstream features? | | |
| 4 | Is the joint-origin collection spelled `jointOrgins`? | | |

---

## Spike 1 — Temp BRep survival across documents

**Why it matters:** the entire cross-document engine (spec, "Generation engine")
snapshots geometry in the mother document, then activates the layout document and
inserts it. If temp bodies die when another document is activated, Phase 1 and
Phase 2 cannot be separated and the approach must change shape.

**What we know:** `build_exports()` already relies on temp bodies surviving
`documents.add()` — see the comment at `SheetVariants.py:399`. That is suggestive,
not proof: creating a document is not the same as activating and closing one.

**Setup:** Doc A with any solid body. A second saved document, Doc B (can be empty).

```python
# Scratch script. Run with Doc A active and Doc B saved but closed.
import adsk.core, adsk.fusion, traceback

def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        tbm = adsk.fusion.TemporaryBRepManager.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        body = design.rootComponent.bRepBodies.item(0)
        temp = tbm.copy(body)
        before = temp.volume

        # Open, activate and close a DIFFERENT document.
        docs = app.data.activeProject.rootFolder.dataFiles
        other = None
        for i in range(docs.count):
            if docs.item(i).name != app.activeDocument.name:
                other = docs.item(i)
                break
        if not other:
            ui.messageBox('Need a second saved document in this project.')
            return
        opened = app.documents.open(other)
        adsk.doEvents()
        opened.close(False)
        adsk.doEvents()

        # Is the snapshot still usable?
        after = temp.volume
        again = tbm.copy(temp)
        ui.messageBox('volume before: {}\nvolume after:  {}\nre-copy ok: {}'
                      .format(before, after, again is not None))
    except Exception:
        ui.messageBox(traceback.format_exc())
```

**PASS:** both volumes are equal and non-zero, and `re-copy ok: True`.
**FAIL:** an exception, a zero/garbage volume, or a "deleted Object" error.

**If it fails:** the fallback is a staging document — snapshot into a hidden
temporary design while the mother is active, then copy from staging into the
layout. Record that here and revise the spec's "Generation engine" section before
starting Plan 1.

---

## Spike 2 — Body attribute persistence

**Why it matters:** slot identity (spec, "On each placeholder box body") is an
attribute stamped on the box. If it does not survive, identity has to fall back to
body names and renaming a box silently orphans its child.

**Setup:** any document with a parametric solid (e.g. a sketch + extrude), saved.

```python
# Scratch script — run TWICE: once as written, then again with STAMP = False
# after closing and reopening the document.
import adsk.core, adsk.fusion, traceback

STAMP = True

def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        body = design.rootComponent.bRepBodies.item(0)
        if STAMP:
            body.attributes.add('SheetVariants', 'slotId', 'slot-deadbeef')
            ui.messageBox('stamped. Now: change a parameter, roll the timeline '
                          'back and forward, save, close, reopen, then re-run '
                          'this script with STAMP = False.')
            return
        found = design.findAttributes('SheetVariants', 'slotId')
        lines = ['findAttributes count: {}'.format(found.count)]
        for i in range(found.count):
            a = found.item(i)
            lines.append('  value={} parent={}'.format(a.value, a.parent.name))
        direct = body.attributes.itemByName('SheetVariants', 'slotId')
        lines.append('direct read: {}'.format(direct.value if direct else 'LOST'))
        ui.messageBox('\n'.join(lines))
    except Exception:
        ui.messageBox(traceback.format_exc())
```

**PASS:** after parameter change + rollback + save + reopen, `findAttributes count: 1`,
the value reads back, and `a.parent` is the body.
**FAIL:** count 0, `direct read: LOST`, or `a.parent` raises.

**If it fails:** slot identity falls back to `(component name, body name)` stored
in `childRecipe`, and the spec must state that renaming a placeholder orphans its
child. Also re-check `Design.findAttributes` — the whole discovery mechanism
depends on it.

---

## Spike 3 — `updateBody` preserving downstream features

**Why it matters:** this is the design's central promise — that a cut a designer
adds by hand survives a rebuild. Everything in the spec's "Rebuilding a child"
section, and the decision to drop a freeze flag entirely, rests on it. If it does
not hold, find out now.

**Setup:** an empty document. The script builds the whole scenario.

```python
import adsk.core, adsk.fusion, traceback

def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent
        tbm = adsk.fusion.TemporaryBRepManager.get()

        # 1. A base feature holding a 10x10x10 box.
        box = tbm.createBox(adsk.core.OrientedBoundingBox3D.create(
            adsk.core.Point3D.create(0, 0, 0),
            adsk.core.Vector3D.create(1, 0, 0),
            adsk.core.Vector3D.create(0, 1, 0),
            10, 10, 10))
        base = root.features.baseFeatures.add()
        base.startEdit()
        root.bRepBodies.add(box, base)
        base.finishEdit()
        adsk.doEvents()

        # 2. A downstream feature the "designer" added: a fillet on one edge.
        target = root.bRepBodies.item(0)
        edges = adsk.core.ObjectCollection.create()
        edges.add(target.edges.item(0))
        fin = root.features.filletFeatures.createInput()
        fin.addConstantRadiusEdgeSet(edges, adsk.core.ValueInput.createByReal(1.0), True)
        root.features.filletFeatures.add(fin)
        adsk.doEvents()
        before = root.features.filletFeatures.count

        # 3. Swap the base feature's geometry for a BIGGER box.
        bigger = tbm.createBox(adsk.core.OrientedBoundingBox3D.create(
            adsk.core.Point3D.create(0, 0, 0),
            adsk.core.Vector3D.create(1, 0, 0),
            adsk.core.Vector3D.create(0, 1, 0),
            16, 12, 10))
        base.startEdit()
        base.updateBody(root.bRepBodies.item(0), bigger)
        base.finishEdit()
        adsk.doEvents()

        fillet = root.features.filletFeatures.item(0)
        ui.messageBox(
            'fillets before: {}\nfillets after:  {}\n'
            'fillet health:  {}\nbody volume:    {}'
            .format(before, root.features.filletFeatures.count,
                    fillet.healthState, root.bRepBodies.item(0).volume))
    except Exception:
        ui.messageBox(traceback.format_exc())
```

**PASS:** the fillet still exists after the swap, `healthState` is
`HealthStateStates.HealthyFeatureHealthState`, and the volume reflects the bigger
box. A *warning* or *error* health state is an acceptable partial pass — the spec
already says Fusion marking a broken reference is the expected outcome. What must
not happen is the feature silently vanishing or `updateBody` throwing.

**FAIL:** `updateBody` raises, or the fillet count drops to 0.

**If it fails:** the "your extra cut survives a rebuild" promise is false. Do not
work around it — return to the spec. The likely replacement is the freeze flag
that was rejected during brainstorming, which is a materially worse feature and a
decision the user must make, not a detail to patch.

---

## Spike 4 — the `jointOrgins` spelling

Thirty seconds, folded in because Plan 1 Task 7 reads this collection:

```python
import adsk.core, adsk.fusion, traceback

def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
        ui.messageBox('jointOrgins: {}\njointOrigins: {}'.format(
            hasattr(root, 'jointOrgins'), hasattr(root, 'jointOrigins')))
    except Exception:
        ui.messageBox(traceback.format_exc())
```

Record whichever is `True` in the results table; Plan 1 Task 7 uses that spelling.

---

## When the spike is done

- [ ] All four rows in the Results table are filled in
- [ ] Any FAIL has been discussed and the spec revised before Plan 1 starts
- [ ] Commit this file with the results:
      `git commit -am "docs: record placeholder spike results"`
