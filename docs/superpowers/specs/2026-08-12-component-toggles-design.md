# Component on/off columns — design

**Date:** 2026-08-12
**Status:** Approved (design), pending implementation plan
**Components:** `SheetVariants/sheet_core.py`, `SheetVariants/SheetVariants.py`

## Problem

Every variant built from a sheet contains the same set of components. The sheet
drives parameter *values*, so a variant can be wider, taller or a different
colour — but it cannot be missing a part.

Real product families are not like that. A base cabinet range shares one
parametric mother, yet the 500 mm unit has no drawer and the corner unit has no
back panel. Today the only way to express that is to model a parameter that
collapses the part to zero thickness, or to maintain a second source model.

The one inclusion control that exists — the **Named components** picker on an
export profile — is the wrong shape for this. It is fixed per profile, so it
applies identically to every row, and it is an *include* list describing what an
output design contains, not what an individual variant *is*.

## Goal

Let a sheet row switch a top-level component off for that variant, with no new
UI and no change to how a model is authored: a column whose header is the
component's name, and `TRUE`/`FALSE` in the cells.

## Decisions (locked)

| Question | Decision |
|----------|----------|
| Where the decision lives | Per variant row, in the sheet |
| Granularity | **Top-level components only** (direct children of the root component) |
| What "off" does | Its bodies are **not collected** when that variant is snapshotted |
| Source model | **Never modified.** No suppression, no parameter writes, nothing to restore |
| Column syntax | Plain component name — no marker or prefix |
| Name collision (parameter *and* component) | Parameter wins; Check warns |
| Accepted values | `TRUE`/`FALSE`, `1`/`0`, `yes`/`no`, `y`/`n`, `on`/`off`, case-insensitive |
| Blank cell | Component stays **in**; reported as a warning |
| Unrecognised value | Check **error** — the build is blocked |
| Interaction with export profiles | Applies to **every** profile; off wins over a profile's include list |
| Variant left with no bodies | That variant is skipped with a note; the profile still builds the rest |
| Test tab preview | DEFERRED — not implemented; see verification item 8 |
| Template generator | Emits one `TRUE` column per top-level component |

### Rejected alternatives

- **Suppress the occurrence while the row is applied**, then restore it, the way
  parameters are captured and restored today. Genuinely recomputes the model, so
  a cut or joint that depends on the component reacts. Rejected: suppression can
  break features that reference the component, and it leaves the source design
  modified until a restore that may itself fail. Dropping bodies at capture time
  cannot corrupt anything. The accepted cost is that the rest of the model does
  **not** react — a cut that was made by the drawer is still there when the
  drawer is off.
- **Drive a parameter you already model with** (`hasDrawer = 0`) and let the
  model do the work. Zero new mechanism, but it only serves models already
  authored that way, which is the problem we are solving.
- **A marked header such as `[Drawer]`.** Unambiguous, and a typo fails loudly
  instead of being read as the wrong kind of column. Rejected as a syntax to
  remember for a collision that is rare and is reported when it happens.
- **Per-profile sub-component tree in the dialog.** Shapes an output, not a
  variant — the same drawer would be present in every row.

## Behaviour

### Reading the header

Each header cell after `Name` is classified once, against the model:

| Header matches | Read as |
|---|---|
| a parameter | parameter column (unchanged) |
| a top-level component | toggle column |
| both | parameter column, plus a collision warning |
| a sub-component only | **error** |
| neither | **error** |

Parameter-first precedence means every sheet that works today keeps working
identically: no existing column can change meaning, because a column that
matched a parameter yesterday still matches it.

A sub-component is rejected explicitly rather than ignored. Reading `Side_L` as
"matches nothing" would produce a misleading error; the designer needs to be
told the concept exists but stops at the top level.

### Reading a cell

`TRUE`, `1`, `yes`, `y`, `on` → in. `FALSE`, `0`, `no`, `n`, `off` → out. Case
and surrounding whitespace are ignored. A Google Sheets checkbox column writes
`TRUE`/`FALSE`, so it drops straight in.

A blank cell means the component stays in — consistent with the existing rule
that a blank parameter cell leaves that parameter unchanged, and it is what
makes adding a column to a 40-row sheet bearable.

Anything else is an error naming the cell, in the style of the existing
comma-decimal error. A typo must never quietly mean "off": that failure is
invisible in the output, because a missing part looks exactly like a part you
meant to remove.

### Collecting geometry

`iter_solid_bodies` currently flattens the assembly with `root.allOccurrences`,
which yields every occurrence at every depth with no notion of ancestry. It is
replaced by a walk that starts at `root.occurrences` — direct children only —
and prunes an off branch at depth 1:

```text
root.bRepBodies              always in — loose root bodies belong to no
                             component, so no column can address them
root.occurrences
  Carcass   ON   yield its solid bodies, recurse into childOccurrences
  Drawer    OFF  prune — skip it and its entire subtree
  Door      ON   yield, recurse
```

Pruning at collection time rather than filtering a flat list afterwards avoids
having to compare body proxies for identity, and "off takes its subtree with it"
falls out of the structure instead of being a second rule to enforce.

`_component_solid_bodies` (the `named_components` resolver) uses the same walk,
which is what makes off win over a profile's include list: a profile listing
`Side_L` gets nothing for a row where `Carcass` is off, because the walk never
descends into `Carcass`. The intersection is structural, not a rule applied
afterwards.

Both resolvers take the row's off-set as an argument; an empty off-set reproduces
today's behaviour exactly.

**Note on component-name uniqueness.** The off-set is checked at every depth of
the walk because Fusion enforces unique component names *within a document* —
it does not extend that guarantee to an externally linked sub-assembly. A
linked sub-assembly can contain its own component sharing a top-level
component's name, and switching that top-level component off would prune the
linked one too. It is visible in the output (a part goes missing where it
should not have) rather than silently wrong, but it is outside this feature's
intended scope.

### Keyed by name

Two top-level occurrences of the same component (`Drawer:1`, `Drawer:2`) share
one column and switch together. This matches the existing Components picker,
which is also name-keyed and deduplicates by name.

## Module layout

Following the repo's rule that anything expressible without Fusion lives in
`sheet_core.py` and is unit-tested:

### `sheet_core.py` (pure)

| Function | Contract |
|---|---|
| `parse_toggle(text)` | `True` for an on-word, `False` for an off-word, `True` for blank/whitespace, `None` for anything unrecognised |
| `classify_columns(header, param_names, top_level_names, all_component_names)` | Splits the header into parameter columns, toggle columns and per-column problems. `all_component_names` exists only to tell a sub-component apart from a typo |
| `row_toggles(row, toggle_columns)` | `{component_name: bool}` for one row; short rows are treated as blank cells, matching how parameter columns already handle them. A component named by two columns resolves to the rightmost one, since the result is keyed by name |
| `validate_mapping(...)` | Extended with the new errors and warnings below |
| `summarize_results(results)` | Extended with the skipped-variant line |

`validate_mapping` gains the model's component names as arguments. Its existing
signature `(header, rows, known_param_names, driveable_param_names)` becomes
`(header, rows, known_param_names, driveable_param_names, top_level_names,
all_component_names)`, with the two new arguments defaulting to empty so the
existing tests keep describing existing behaviour.

### `SheetVariants.py` (Fusion, not unit-testable)

| Function | Change |
|---|---|
| `top_level_component_names(design)` | New. Distinct component names from `root.occurrences`, order of first appearance |
| `iter_solid_bodies(design, off_names)` | Rewritten as the pruning walk |
| `resolve_whole_model` / `resolve_named_components` | Take and forward the off-set |
| `build_exports` | Splits each row into values and toggles; the "columns match no parameter" guard at line 318 must exempt toggle columns |
| `create_template` | Appends one `TRUE` column per top-level component |
| `_preview_test_row` | DEFERRED — not implemented; see verification item 8 |

## Check report

New errors — all block the build, consistent with today's rule:

- `Column "Side_L" is a sub-component — only top-level components can be
  switched on or off.`
- `Column "Drawr" matches no parameter or top-level component in the model.`
  (widening of the existing message)
- `Cell D3 ("maybe") is not a yes/no value — use TRUE or FALSE.`

New warnings:

- `Column "Door" is both a parameter and a component — read as a parameter.`
- `3 blank on/off cell(s) — those components stay in.`

Blank toggle cells get their own warning line rather than joining the existing
`N empty cell(s) left unchanged` count. "Left unchanged" is accurate for a
parameter and misleading for a toggle, where the reader wants to know which way
a blank fell.

A top-level component with no column is not reported. Most models will have more
components than columns, and warning about each would drown the report.

## Failure modes

| Situation | Behaviour |
|---|---|
| A variant's toggles leave a profile with no bodies | That variant is skipped, named in the run summary; every other variant in the profile still builds |
| Every variant leaves a profile empty | The profile is skipped through the existing `no solid bodies matched` path |
| A toggle column names a component that exists but is nested | Blocked at Check, before any build |
| Unrecognised cell value | Blocked at Check |
| Layout after a component is dropped | Nothing to do — a smaller variant has a smaller bounding box, and the left-to-right spacing already works from bounding boxes |

The skipped-variant case needs a `skipped_variants` list on the per-profile
result dict and a line in `summarize_results`. Silence there would be the bad
outcome: a variant vanishing from an output design with no explanation reads as
a bug in the add-in.

## Test tab preview

**Deferred — not implemented on this branch.** See item 8 of the verification
checklist.

The Test tab applies a row's parameters to the live model so it can be
inspected. Without this change, previewing a row whose `Drawer` is `FALSE` still
shows the drawer, so the preview disagrees with what the build would produce.

The preview switches `isLightBulbOn` off on the off components' top-level
occurrences. Visibility is the right instrument: it is purely visual, it costs
nothing, and it cannot break a feature.

The preview relies entirely on Fusion reverting changes made while
`isValidResult` stays `False` — `_preview_test_row` writes parameters and
restores nothing itself, and there is no destroy-time restore behind it.
**Whether that revert covers visibility changes must be verified in Fusion, not
assumed.** If it does not, this feature has to add an explicit restore — capture
each touched occurrence's `isLightBulbOn` before changing it and put it back when
the dialog closes — which is new machinery, not an extension of something the
command already does. That verification therefore comes before the preview work,
not after it: the answer decides how much there is to build.

## Template generator

`create_template` appends one column per top-level component after the parameter
columns, with `TRUE` in the example row. `TRUE` everywhere is exactly today's
behaviour, so a generated template still builds an identical result. The point is
discoverability: the columns show up without the README having to be read first.

## Testing

**Unit tests** (`tests/test_sheet_core.py`) — every accepted on-word and off-word
including casing and surrounding whitespace; blank; unrecognised; the
parameter-wins collision; the sub-component rejection; a typo; rows shorter than
the header; and the new summary line for skipped variants.

**Manual verification** — the pruning walk, the preview and the template touch
Fusion and cannot be unit-tested. They get a checklist committed with the
feature, following the pattern the placeholder work used, run against a
**genuinely nested assembly** (a top-level component with children, and one
component instanced twice at the top level). The checklist must confirm:

1. `FALSE` on a top-level component removes it and everything under it.
2. A second occurrence of the same component switches off with the first.
3. A `Named components` profile listing a sub-component of an off component
   produces nothing for that row and still builds its other rows.
4. Loose bodies in the root component are unaffected.
5. The source model is unchanged after a run — same components, same visibility,
   same parameters.
6. The Test tab preview hides the off component and restores it on close.
7. A generated template builds a result identical to one from the same sheet
   without toggle columns.

Item 5 is the one that matters most. The whole justification for dropping bodies
rather than suppressing occurrences is that the source model cannot be harmed,
and that claim is worth checking rather than asserting.

## Scope

In:

- Toggle columns for top-level components, applied to every export profile.
- Check-report classification, errors and warnings.
- Skipped-variant reporting in the run summary.
- Test tab preview honouring toggles. **Deferred — not implemented on this
  branch;** see item 8 of the verification checklist.
- Template generator emitting toggle columns.
- README documentation of the sheet layout and the rules.

Out:

- Sub-component toggles. Deliberately deferred; the column syntax has room for a
  path such as `Carcass/Back` later if it is wanted.
- Suppressing occurrences so that dependent features react.
- Toggling from the Fill Placeholders / mother-model config flow.
- Honouring a component's existing visibility in the source model as an
  implicit off.
