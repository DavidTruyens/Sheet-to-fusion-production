# Placeholder instantiation — design

**Date:** 2026-08-08
**Status:** Approved (design), pending implementation plan
**Components:** `SheetVariants/placeholder_core.py` (new), `SheetVariants/build_engine.py` (new, extracted), `SheetVariants/placeholder_cmds.py` (new), `SheetVariants/SheetVariants.py` (wiring)

## Problem

The add-in today drives one direction: a Google Sheet of variant rows produces one
new design per export profile, each holding one component per variant. That is a
catalogue generator — it answers "show me every configuration of this part".

Designing a kitchen needs the opposite direction. The kitchen is a *layout* of
slots, and each slot needs one specific configuration of one specific parametric
model, sized to that slot. There is no way today to say "this 600×580×720 gap is a
two-drawer base unit" and have the cabinet appear there.

The properties that make the existing tool good for production are exactly the ones
wanted here:

- **Copied geometry, no parametric history from the source.** A generated cabinet
  is a slab of static bodies, so the layout document stays light no matter how many
  cabinets it holds, and nothing in it silently changes when someone edits a source
  model.
- **Every configuration is testable** by exporting all of them from the same sheet
  that drives the layout.

What is missing is the back-link: a generated cabinet must remember where it came
from, so that when the source model improves, every cabinet built from it can be
rebuilt — without losing the cuts and edits a designer added downstream.

## Goal

Assign a parametric **mother** model, at a chosen **config**, to a **placeholder**
box in a layout document. The box's width, depth and height drive the mother's
corresponding parameters; the resulting geometry is copied into the layout as a
**child** component, positioned and oriented by the box's front face.

Children keep a recipe of how they were made, so a later command can rebuild them
in place when the mother moves on — preserving any features the designer added on
top.

## Vocabulary

| Term | Meaning |
|------|---------|
| **mother** | A saved, prepared parametric Fusion document (e.g. `base-cabinet.f3d`) with its own sheet of configs |
| **config** | One row of the mother's own Google Sheet, named by its `Name` column |
| **placeholder** | A box body in the layout document, conventionally grouped in a `Layout` component |
| **child** | A component in the layout document holding geometry generated from a mother |
| **slot** | A placeholder considered as an identity — a child's stable back-reference |

## Decisions (locked)

| Question | Decision |
|----------|----------|
| Where the mother lives | A **separate Fusion document**, saved (cloud), with its own version history |
| What a config is | **A row from the mother's Google Sheet** — reusing the existing sheet reading, validation and Test preview |
| How W/D/H map to parameters | Picked **once per mother**, stored as a document attribute on the mother |
| How the mother declares its facing | Explicit `front` axis (`+X`/`-X`/`+Y`/`-Y`) in the same mapping, **not** inferred from joint-origin orientation |
| How the mother declares its anchor | A **named joint origin** — survives parametric change where a face reference would not |
| Where the anchor lands | At the **box's centre**. One rule; offsets are achieved by moving the anchor |
| How orientation is chosen | User selects the **front face** of the box; height is always world `+Z` |
| Placeholder authoring | User models them freely as **bodies**, conventionally grouped in a `Layout` component and placed first in the timeline. Neither the grouping nor the ordering is enforced — placeholders are found by attribute, not by location |
| What happens to a filled placeholder | Hidden (`isLightBulbOn = False`), never deleted — roll back past the children to see the conceptual layout |
| Child ↔ box relationship | **Transform only, no joint.** Update reconciles move and resize together |
| Where the placement lives | The **occurrence transform**; bodies are stored in the child's local (anchor) space |
| How edits survive a rebuild | `BaseFeature.updateBody()` **in place**, so the designer's downstream features recompute. No freeze flag. **Verified constraint:** only features that do not reference the generated topology survive — see "What survives, measured" |
| Update trigger | One `Update Children` dialog, showing each mother's stored vs current version |

### Rejected alternatives

- **Mother as a component in the same document** — simpler (no cross-document
  activation) but a mother could not be shared between kitchens, and "the mother
  updated" would have no version to compare against.
- **Naming convention for W/D/H** (`width`/`depth`/`height`) — zero setup, but
  renaming a parameter breaks every placeholder using it with no visible cause.
- **Fusion's native Configurations** — a different API surface from everything in
  this add-in, not editable outside Fusion, and abandons the sheet workflow that is
  the tool's premise.
- **A per-child freeze flag** to protect hand edits — obsoleted by `updateBody()`,
  which lets edits survive the rebuild instead of blocking it. The Update dialog's
  per-child checkbox covers the remaining "not this one" case.
- **Auto-detecting hand edits by fingerprinting geometry** — unreliable in Fusion,
  and both failure directions are silent.
- **Checking mothers automatically on document open** — makes opening any kitchen
  do unrequested network work; add-ins acting on document-open are a known source
  of Fusion startup trouble.
- **A rigid as-built joint from child to placeholder** — chosen at first, then made
  impossible by placeholders being bodies in a shared component rather than
  occurrences. Update covers move and resize in one action instead.

## Commands

| Command | Runs in | Does |
|---------|---------|------|
| `Prepare Mother Model` | the mother doc | Records anchor, front axis and W/D/H mapping onto the document, once |
| `Fill Placeholders` | the layout doc | Select front faces → pick mother + config → generate children |
| `Update Children` | the layout doc | Staleness list → rebuild picked children in place |

All three sit in the existing **Sheet Variants** panel on the MANAGE tab.

### `Prepare Mother Model`

Refuses to run on an unsaved document: without a saved file there is no id to
reference and no version number to compare, so staleness would be undefined.

Dialog: a dropdown of the design's joint origins (anchor), a `+X/-X/+Y/-Y`
dropdown (front), and three parameter dropdowns (width, depth, height). Pre-filled
from the existing `motherSetup` attribute when re-run.

### `Fill Placeholders`

- **Front faces** — a multi-select `SelectionCommandInput` limited to planar faces.
  Each selected face implies its own body, so one gesture assigns a whole run of
  cabinets, each sized to its own box.
- **Mother** — a dropdown: the union of currently-open documents carrying
  `motherSetup`, plus previously-used mothers remembered in `settings.json`.
- **Config** — a dropdown of the `Name` column from that mother's sheet.

Selecting a face whose body already has a child is **not** an error: it re-runs the
child through the rebuild path with the new config. Changing a unit from two-drawer
to three-drawer therefore preserves the designer's downstream features, and needs
no separate command.

**Naming.** A child component takes its placeholder body's name, so the browser
tree reads as the layout does and each cabinet is traceable to its slot at a
glance. Name the box `B60_1` and you get a cabinet called `B60_1`. Collisions are
suffixed `_2`, `_3`; renaming a child afterwards is harmless, since identity lives
in `slotId`, not in the name. The config is not part of the name — it changes, and
a name that lies after a reconfigure is worse than one that says less.

### `Update Children`

On open, resolves each referenced mother once (`app.data.findFileById`) and each
slot's body, then lists every child grouped by mother:

```
Update children

  base-cabinet.f3d          v12 → v14   OUT OF DATE
    [x] B60_2drawer          600×580×720   Base_2drawer
    [x] B90_sink             900×580×720   Base_sink        resized 900 → 1000
    [x] B60_corner           600×580×720   Base_2drawer     moved

  tall-unit.f3d             v3  → v3    up to date
    [ ] TALL_60              600×580×2100  Tall_oven

  wall-unit.f3d             missing
    [!] W80                  mother not found

                    [ Cancel ]  [ Update 3 ]
```

- **out of date** — stored `mother.version` differs from the current version.
- **resized** — the box's measured extents differ from the stored `dims_cm`.
- **moved** — the child occurrence's current transform differs from one freshly
  computed from its box. Derived, not stored.

Out-of-date, resized and moved children are ticked by default.

## Data model

All attributes live under the existing `SheetVariants` attribute group, as JSON
strings with a `v` field, migrated the way `migrate_settings()` already migrates
profiles.

### On the mother document — `motherSetup`

```jsonc
{ "v": 1,
  "anchor": "SV_Anchor",              // joint origin name
  "front":  "-Y",                     // which model axis points out the front
  "params": { "width":  "cab_W",
              "depth":  "cab_D",
              "height": "cab_H" } }
```

The mother's `sheetUrl` attribute already exists and is reused unchanged, so a
mother's config catalogue needs no new storage.

### On each placeholder box body — `slotId`

```jsonc
"slot-3f7a91c2"
```

A generated token, written when the box is first filled. Survives renaming the
body, which a name-based key would not.

### On each child component — `childRecipe`

```jsonc
{ "v": 1,
  "slotId": "slot-3f7a91c2",
  "mother": { "fileId": "urn:adsk.wipprod:dm.lineage:…",
              "name":   "base-cabinet.f3d",
              "version": 12 },
  "config": "Base_2drawer",
  "sheetUrl": "https://…", "tab": "Cabinets",
  "dims_cm": { "w": 60.0, "d": 58.0, "h": 72.0 },
  "bodies": ["Carcass::Left side", "Carcass::Right side", "Carcass::Back"],
  "builtAt": "2026-08-08T14:22:00" }
```

Deliberately **not** stored:

- **No placement matrix.** Re-derived from the box on every update; storing it
  would create a second source of truth that can disagree. Move detection compares
  the live occurrence transform instead.
- **No copy of the W/D/H mapping.** Re-read from the mother each time, so that
  remapping a mother actually takes effect on its children.

`dims_cm` is display and resize-detection only — it is never used to size a
rebuild, which always measures the box afresh.

`bodies` holds qualified `component::body` names and is what drives pairing on
update.

### Discovery

`Design.findAttributes('SheetVariants', 'childRecipe')` returns every child in the
document, and the same call with `slotId` returns every placeholder — no occurrence
tree walking.

### `settings.json` addition

```jsonc
{ "mothers": [ { "fileId": "urn:…", "name": "base-cabinet.f3d",
                 "sheetUrl": "https://…", "tab": "Cabinets" } ] }
```

Explicitly a **cache**, so the `Fill Placeholders` dropdowns can be populated
without opening documents. The mother's own attributes remain the source of truth;
the cache is refreshed whenever a mother is actually opened.

## Placement

**One rule: the anchor is the point that lands at the box's centre.** If a cabinet
needs to sit 20 mm back, the author moves the anchor 20 mm. No offset fields.

```
   layout (world)                         mother (its own space)

        ╔═══════════╗ ← box body                ┌─────────┐
        ║           ║                           │         │
        ║     ●─────╫──► D  (depth)             │    ●    │  ● = SV_Anchor
        ║    ╱      ║     = −n                  │         │     front = "−Y"
        ╚═══╱═══════╝                           └─────────┘
           ╱   ▲ front face, normal n                 │
          W    │                                      │
                                             anchor ──┘ maps to box centre
```

Target frame, from the selected front face with outward normal `n`:

```
U (height) = world +Z
D (depth)  = −n                 ← must be horizontal; a picked top/bottom face is an error
W (width)  = D × U              ← right-handed, so W × D = U
```

Mother frame, built the same way from the stored `front` axis `f` — which points
*out of* the front, exactly as a face normal does:

```
U_m (height) = mother +Z
D_m (depth)  = −f               ← front "−Y" therefore gives depth along +Y
W_m (width)  = D_m × U_m
origin       = the named joint origin's position
```

Because a placeholder is only ever read (measured and located, never jointed to),
it does **not** need to be its own component. A loose body in the root works
identically to one inside `Layout`.

The full mapping is `T(centre)·R(target)·R(mother)⁻¹·T(−anchor)`, **split in two**:

- `R(mother)⁻¹·T(−anchor)` is applied to the snapshotted temporary bodies, putting
  them in the child's local space with the anchor at its origin.
- `T(centre)·R(target)` becomes the child **occurrence transform**.

This split is required for correctness, not tidiness. The designer's downstream
features are defined in the component's local space; if geometry moved inside the
component when a box is nudged, those features would stay behind and land in the
wrong place. It also makes a pure move cost one matrix write, with the base feature
untouched.

**Extents** are measured by projecting the body's **vertices** into the target
frame, not by reading `body.boundingBox` — a corner cabinet rotated 45° would
report a world-aligned box far too large. This is exact for any flat-faced solid; a
placeholder with curved faces would under-measure, which is acceptable for boxes
and is documented rather than guarded.

**Sizing order:** apply the config row's columns first, then overwrite the three
mapped parameters with the box's measurements. The box always wins — that ordering
is the feature.

Internal units are centimetres (Fusion's internal unit); parameter expressions are
written with an explicit `cm` suffix.

## Generation engine

Phased exactly as `build_exports()` is, and for the reason its comment at
`SheetVariants.py:399` documents: creating or activating a document invalidates
live references to any other design, so no output work may happen while the source
still needs reading.

```
Phase 0   layout active     resolve every selected face → slot id, frame, w/d/h
                            → plain Python data, zero live object references

Phase 1   per mother        open/activate · read motherSetup + anchor + sheet rows
                            for each DISTINCT (config, w, d, h):
                                apply row → apply box overrides → doEvents
                                → snapshot solids as temp BReps + qualified names
                                  + appearance + material
                            restore original expressions · close if we opened it

Phase 2   layout active     create/update child · set occurrence transform
                            reapply material/appearance · write childRecipe
                            hide the box body
```

**Distinct** is load-bearing: a run of four identical 600 base units drives the
mother once and copies the snapshot four times.

Safety rules:

- If a mother is already open **with unsaved changes**, abort before touching
  anything. This is stricter than what `build_exports()` risks on the active
  document, because there the user can see it happening.
- A mother the tool opened itself is closed **without saving**, so a run never
  leaves parameter edits behind.
- A progress dialog with cancel, as `build_exports()` already provides. Cancel is
  safe: Phase 2 completes each child atomically, so a cancelled run leaves some
  children, never half a child.

## Rebuilding a child

Pairing is a pure function:

```
pair_bodies(old_names, new_names) -> [("update", old_i, new_i) | ("add", new_i) | ("remove", old_i)]
```

Matching is by qualified `component::body` name, with duplicate names paired by
ordinal. Unmatched old names are removed, unmatched new names added.

Applied in Fusion:

```
baseFeature.startEdit()
    update  →  baseFeature.updateBody(existing, newTemp)
    add     →  component.bRepBodies.add(newTemp, baseFeature)
    remove  →  existing.deleteMe()
baseFeature.finishEdit()          ← Fusion recomputes the designer's features here
```

### What survives, measured

Spike 3 tested this rather than assuming it. The results are not uniform, and the
difference is the single most important thing a user of this feature must know:

| Downstream feature | Result |
|--------------------|--------|
| **Topology-independent** — a cut from a sketch on an **origin plane** | **Survives cleanly.** Health `healthy`, and the cut is re-applied to the *new* geometry at full depth: a 10×10×10 box swapped for 16×12×10 came back at 1794.336 cm³, i.e. 1920 minus the ø4×10 hole's 125.664 exactly |
| **Topology-referencing** — a fillet on a specific **edge** | **Destroyed.** `updateBody()` returns `True`, then `finishEdit()` raises `InternalValidationError`, the feature count drops to 0, and the body is left unreadable (`Bad index parameter`) |

So the honest promise is **not** "your edits survive a rebuild". It is:

> Downstream features survive a rebuild when they do **not** reference the
> generated geometry's topology. Anchor cuts to origin planes and construction
> geometry, not to a generated face or edge.

An earlier draft of this spec claimed a broken reference would leave the feature
"errored — visible, recoverable". That was wrong: Fusion **throws** and the feature
is **gone**. `rebuild_base_feature()` must therefore treat `finishEdit()` as a
call that can raise, catch it, and report that child as failed rather than letting
one fragile fillet abort a whole run.

`updateBody()` does preserve body identity, which is what gives the
topology-independent case its clean survival.

Body references go stale after `finishEdit()`, so materials and appearances are
reapplied by index afterwards, exactly as the existing code documents at
`SheetVariants.py:498`.

A child whose base feature no longer exists (deleted by the designer) is reported
as unrebuildable and skipped.

## Failure modes

All are **reported per child** and skip only that child; none abort the run.

| Condition | Handling |
|-----------|----------|
| Mother file missing or inaccessible | Child listed as "mother not found" |
| Mother has no `motherSetup` | "mother not prepared" |
| Anchor joint origin renamed or deleted | Error naming the expected joint origin |
| A mapped parameter renamed or deleted | Error naming the parameter |
| Config row no longer in the sheet | Error naming the config |
| Placeholder body deleted | "placeholder missing"; the child is left untouched |
| Child's base feature deleted | "cannot rebuild"; skipped |
| `finishEdit()` raises because a downstream feature referenced the old topology | Caught; that child reported as "rebuild failed — a feature built on the old geometry could not be recomputed"; the run continues |
| A horizontal face picked as "front" | Rejected at selection time with an explanation |
| Sheet unreachable | Existing `fetch_rows` error handling and sharing help |

## Module layout

`SheetVariants.py` is already 1186 lines; this feature would add roughly half again
to it. Three new modules, one of them an extraction from existing code:

| Module | Imports `adsk`? | Holds |
|--------|-----------------|-------|
| `placeholder_core.py` | no — unit tested on CI | Both JSON schemas + migration, `pair_bodies`, placement math on plain tuples |
| `build_engine.py` | yes | The parametrize → recompute → snapshot-as-temp-BRep core, **extracted** from `build_exports()` so both features share one path |
| `placeholder_cmds.py` | yes | The three new command handlers and their dialogs |

The new pure logic goes in `placeholder_core.py` rather than `sheet_core.py`
because that module is about reading sheets and this is about geometry and schemas;
merging them would produce one file with no coherent name.

Extracting `build_engine.py` is the only change to existing code proposed here, and
it is forced: the alternative is a second copy of the phase-ordering rules that
`build_exports()` documents so carefully, which is exactly the knowledge that must
not exist twice.

## Testing

`placeholder_core.py` gets CI coverage mirroring `tests/test_sheet_core.py`:

- `motherSetup` and `childRecipe` schema validation, defaulting and migration
- `pair_bodies` — matches, additions, removals, duplicate names, empty sets
- Target-frame construction from a face normal, including rejection of horizontal
  normals
- Extents from vertices in a rotated frame
- Matrix composition and the local/occurrence split
- Staleness comparison, including a mother with no version available

The `adsk` layer stays uncovered by CI, exactly as it is today. That is precisely
why the spike below is a prerequisite, and why **no part of this may be claimed to
work until it has been run in Fusion against a real kitchen layout**.

## Spike — prerequisite to both plans

Three behaviours are load-bearing and none are proven. Each is a short manual
session in Fusion with a throwaway model.

1. **Do `TemporaryBRepManager` bodies survive activating and closing a *different*
   document?** The existing code proves they survive `documents.add()`, which
   strongly suggests they are application-level — but that is inference, not
   evidence. If this fails, the entire cross-document approach changes shape.
2. **Do attributes on a `BRepBody` survive recompute, timeline rollback, and
   save/reopen?** If not, slot identity must fall back to body names, and renaming
   a box silently orphans its child.
3. **Does `BaseFeature.updateBody()` genuinely preserve downstream features?** This
   carries the design's central promise — that a hand-added cut survives a
   rebuild. If it does not hold, that must be known on day one.

Also to confirm during the spike: the joint-origin collection on a component
appears to be spelled `jointOrgins` in the Fusion API (a long-standing upstream
typo).

## Scope

**One spec, two plans.** The attribute schema is shared by all three commands, so
it has to be designed as a whole; splitting the spec would mean designing it twice
and getting it wrong once.

- **Plan 1** — `Prepare Mother Model` + `Fill Placeholders`, **including the
  `pair_bodies` / `updateBody` rebuild path**. That path is not deferrable:
  re-filling an already-filled slot with a different config is a rebuild, so Plan 1
  cannot ship without it. Usable on its own — a kitchen can be laid out, filled,
  and reconfigured.
- **Plan 2** — `Update Children`: the dialog, resolving mothers to current
  versions, and move/resize detection. Plan 2 adds no geometry code; it decides
  *which* children to send through Plan 1's rebuild path.

Both are gated on the spike.

### Out of scope

- **Height on an axis other than Z.** Fixed to world `+Z`. Considered and deferred
  after Plan 1 shipped — recorded here so the reasoning is not re-derived.

  What the constraint buys: **one selection determines the whole frame.** Pick the
  front face, and depth is `-normal`, up is `+Z`, width is `depth × up`. Drop Z and
  a front-face normal leaves the rotation *about* that normal undetermined, so a
  second input becomes necessary.

  It is not structurally entangled. The assumption lives in
  `placeholder_core._frame_from_outward` (which forces `up` and rejects a
  non-vertical face) and in `FRONT_AXES` excluding `±Z`. Everything downstream —
  `extents_in_frame`, `occurrence_matrix`, `local_matrix`, `anchor_target` — already
  takes a frame as an argument and is indifferent to how it was built.

  Three ways to generalise, if a real case appears (a sloped ceiling, a non-level
  floor, non-casework uses):

  1. **Derive up from the box.** A true box has three axis directions; given the
     front normal, take the remaining axis closest to world `+Z`. No new UI, and it
     handles any tilt under 90°. Cost: it needs the placeholder to be a real box
     with parallel faces, which today it need not be. `is_axis_aligned()` (Plan 2)
     already answers exactly that question, so the check exists.
  2. **Optional second pick.** Front face required, an "up" reference optional,
     defaulting to `+Z`. Fully general, backwards compatible, one extra click only
     when needed. The mother gains an `up` axis beside `front`, validated
     perpendicular.
  3. **Always two picks.** Simplest code, worst ergonomics for the common case.

  Preference is (1) with a fallback to `+Z`. **Decide it together with Plan 2**, not
  before: `is_axis_aligned()` currently treats a rotated box as an error meaning
  "re-pick the front face", and under a general up axis some of those rotations
  become legitimate. Generalising Plan 1 alone would leave the two halves
  disagreeing.
- **Export profiles applied to a mother.** A child takes the mother's whole model.
  The existing profile machinery can produce cut lists from the finished layout
  later.
- **Nested placeholders** — a child containing its own placeholders.
- **Automatic staleness checking on document open** — explicitly rejected above.
- **Per-child update locking.** The Update dialog's checkbox covers it; a stored
  flag can be added to `childRecipe` later without a migration if real use proves
  it necessary.
