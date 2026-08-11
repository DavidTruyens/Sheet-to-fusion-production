# Export Profiles — design

**Date:** 2026-07-17
**Status:** Approved (design), pending implementation plan
**Component:** `SheetVariants/SheetVariants.py`

## Problem

The current add-in has one export behaviour: it snapshots *every* solid body in
the active design and copies them into one component per variant in a single new
design. This is "naive" — it treats the whole model as one blob and offers no way
to export a subset.

Now that a source model can be an assembly (e.g. `Nis`, `Gordijnplaat`), we want
to export different *slices* of it. Concretely:

- **Whole model, per variant** — the current behaviour.
- **A single named component, per variant** — a per-part production export.
- **(Future)** all unfolded sheet-metal components; parts filtered by thickness.

## Goal

Turn the single, whole-model export into a small set of **named export profiles**.
One build run applies each variant's parameters once, then feeds every enabled
profile — each profile opens its own new Fusion design containing one component
per variant. Everything is copied in-memory (no SAT/STEP/DXF export), so the
Fusion **Personal** licence stays supported.

## Decisions (locked)

| Question | Decision |
|----------|----------|
| Where profiles are defined | In the Fusion UI, saved to `settings.json` |
| v1 selection rules | `whole_model`, `named_components` |
| How named components are picked | Checklist of the active design's components; stored by name; missing names warned at run time |
| Output | One new Fusion design **per enabled profile** (in-memory, one component per variant, laid left-to-right) |
| Run model | One run builds every enabled profile |
| UI shape | One combined Build dialog with a `TableCommandInput` of profiles (Approach A) |

## Data model (`settings.json`)

```json
{
  "sheet_url": "...",
  "spacing_mm": 100.0,
  "profiles": [
    { "id": "p1", "name": "Full model",          "enabled": true, "rule": "whole_model" },
    { "id": "p2", "name": "Gordijnplaat (prod)", "enabled": true, "rule": "named_components",
      "components": ["Gordijnplaat"] }
  ]
}
```

- `rule` is a string tag so new rules (`sheet_metal`, `thickness`) slot in later
  without schema churn. Extra per-rule fields (e.g. `thickness_mm`) can hang off
  the profile object.
- `id` is a stable key for the profile (used to track table rows); `name` is the
  user-facing label and the name given to the output design's root component.
- **Migration:** if `profiles` is missing (existing users), synthesize a single
  default profile `{ name: "Full model", enabled: true, rule: "whole_model" }`.
  This reproduces today's behaviour exactly — nothing is lost on upgrade.

## UI — combined Build dialog

The existing **Build Variants Assembly** button opens this dialog. **Create
Variant Sheet Template** is untouched.

Inputs, top to bottom:

1. **Google Sheet URL** — string (as today).
2. **Gap between variants (mm)** — value input (as today; single global gap for
   all profiles in v1).
3. **Profiles table** — a `TableCommandInput` with columns:
   `✓ enabled | name | rule ▾ | components ▾`
   - `enabled` — bool checkbox per row.
   - `name` — string value input per row.
   - `rule ▾` — dropdown: `Whole model` / `Named components`.
   - `components ▾` — checkbox-dropdown populated from the **active design's**
     distinct component names; active only when `rule = Named components`.
   - Table toolbar **+ / –** buttons add/remove profile rows.

Interaction details (handled in `inputChanged`):

- **+** adds a row with sensible defaults (enabled, `whole_model`, empty name → a
  generated name).
- **–** removes the selected row.
- Changing a row's `rule` to `Named components` reveals/enables that row's
  `components ▾`; changing it back to `Whole model` disables/clears it.
- Stored-but-absent component names (a saved profile references a component the
  currently open design doesn't have) appear pre-checked with a `(missing)`
  suffix, so nothing silently disappears; they are retained on save and reported
  at run time.
- If no design is open, whole-model rows still work; the components picker shows a
  short note: "open your source design to pick components".

*Known risk:* a `TableCommandInput` with a per-row checkbox-dropdown is the
fiddliest part of the Fusion command API. If the in-table checkbox-dropdown
proves unreliable in practice, fall back to Approach B (a simple "Edit profile…"
sub-dialog) — **the build engine below is identical either way**, so this fallback
costs nothing structural.

## Build engine (core refactor)

Replace `build_assembly(url, spacing)` with a multi-profile loop that recomputes
each variant **only once**, regardless of how many profiles are enabled:

```
fetch rows + validate params (union of all sheet param columns)
snapshot original parameter expressions
create one new design per enabled profile (each keeps its own root + x_cursor)
for each variant row:
    apply params → adsk.doEvents()          # single parametric recompute
    for each enabled profile:
        bodies = resolve_selection(src_design, profile)   # world-positioned proxies
        temp = [tbm.copy(b) for b in bodies]              # skip profile-for-variant if empty
        place temp as a new component named after the variant,
          laid out left-to-right by bounding box using the profile's x_cursor
finally:
    restore original parameter expressions (always)
report per-profile variant counts + any warnings
```

Rationale: the parametric recompute is the expensive step. Iterating variants on
the outer loop and profiles on the inner loop keeps it at once-per-variant instead
of once-per-(variant × profile).

## Selection rules

A small resolver registry maps `rule` → function:

```
RESOLVERS = {
    "whole_model":      resolve_whole_model,
    "named_components": resolve_named_components,
}
```

- `whole_model` → every solid body in the design (existing `iter_solid_bodies`).
- `named_components` → the solid bodies of the selected component(s). **Each
  selected component contributes its bodies once per variant** (a representative
  occurrence), matching "one part for production" rather than every placed
  instance.
- The **name-matching half** (given a list of component names present in the
  design and a profile's target names, decide which to include and which are
  missing) is a pure function, unit-testable without Fusion. The **body-fetching
  half** (turning matched components into world-positioned `BRepBody` proxies)
  touches the API.

This registry is the extension seam: `sheet_metal` and `thickness` rules are added
later by writing a resolver plus a UI affordance, with no change to the loop.

## Output & reporting

- One new untitled design per enabled profile. Its **root component is named after
  the profile** so the document tabs are distinguishable.
- Layout unchanged: one component per variant, spaced left-to-right by bounding
  box with the global gap.
- Final message box summarises the run, e.g.:
  `Built: Full model (5 variants); Gordijnplaat prod (5). Skipped: <profile> — component 'X' not found.`

## Error handling / edge cases

- Sheet fetch failure or a param column that matches no model parameter fails
  early, before any design is created (as today).
- Original parameter expressions are always restored in a `finally` block.
- A profile that resolves to zero bodies **for a given variant** is skipped for
  that variant and reported; it does not abort the run.
- A profile whose components match nothing in the design is skipped entirely and
  reported; it does not abort the run.
- No enabled profiles → friendly prompt, no build performed.

## Non-goals (v1 — YAGNI, but designed-for)

- File export (STEP/DXF) — would break the Personal-licence guarantee.
- Sheet-metal unfold / flat pattern.
- Thickness filter.
- Jointing/constraints between placed components.
- Per-profile gap (single global gap in v1).

## Testing

- **Pure-logic unit tests (no Fusion):** settings migration (missing `profiles`
  → default), profile load/save round-trip, `csv_url_candidates`, `unquote_text`,
  and the name-matching half of `named_components` selection.
- **Manual verification in Fusion (by the user):** the geometry-copy path, the
  profiles table UI, and multi-design output. These touch the Fusion API and
  hardware/app behaviour and will **not** be claimed working until run in Fusion.

## Backward compatibility

Existing users upgrade transparently: with no `profiles` key, the migration
creates one `whole_model` profile, so the first run produces exactly the single
whole-model design they get today. The template button is unchanged.
