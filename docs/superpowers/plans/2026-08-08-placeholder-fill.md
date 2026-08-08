# Placeholder Fill Implementation Plan (Plan 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assign a prepared parametric mother document, at a chosen sheet config, to placeholder boxes in a layout design — the box drives width/depth/height, its front face fixes orientation, and the result lands as a static child component that remembers how it was made and can be rebuilt in place.

**Architecture:** All geometry and schema logic that does not need Fusion goes in a new pure module `placeholder_core.py`, unit-tested on CI exactly like `sheet_core.py`. The Fusion-side geometry core (`apply values → recompute → snapshot as temporary BReps → insert into a base feature`) is **extracted** from the existing `build_exports()` into `build_engine.py` so the sheet-variants build and this feature share one tested path. The two new commands live in `placeholder_cmds.py`; `SheetVariants.py` only gains registration wiring.

**Tech Stack:** Python 3 (Fusion's bundled interpreter), Autodesk Fusion API (`adsk.core`, `adsk.fusion`), stdlib only at runtime (`json`, `math`, `uuid`, `urllib`, `csv`), pytest for tests.

**Spec:** [2026-08-08-placeholder-instantiation-design.md](../specs/2026-08-08-placeholder-instantiation-design.md)
**Prerequisite:** [the spike](2026-08-08-placeholder-spike.md) — all four results recorded. **Do not start Task 6 until Spike 1 and Spike 3 have passed.** Tasks 1–5 are pure Python and may proceed in parallel with the spike.

## Global Constraints

- **Runtime code is stdlib-only.** No third-party imports in any `SheetVariants/*.py`. pytest is a dev dependency only, never imported by runtime code.
- **`placeholder_core.py` and `sheet_core.py` must never import `adsk`.** They must import in a plain Python process so CI can test them without Fusion.
- **`SheetVariants.py`, `build_engine.py` and `placeholder_cmds.py` import `adsk` at module top**, so they cannot be imported outside Fusion — never write a test that imports them.
- **Personal-licence-safe.** Geometry is copied in-memory via `TemporaryBRepManager`; no SAT/STEP/DXF file export anywhere.
- **Internal units are centimetres** (Fusion's internal unit). Parameter expressions are written with an explicit `cm` suffix.
- **Attribute group is `SheetVariants`** for every attribute this feature writes, matching the existing `sheetUrl` attribute.
- **All matrices are row-major flat 16-float lists**, matching `Matrix3D.asArray()`.
- **Never claim a Fusion-side task works on the basis of `py_compile`/`pyflakes`.** Steps labelled *(manual, user-run)* are verified by the user inside Fusion and must not be ticked otherwise.
- **Commit each completed task.** Per the user's workflow, plan execution commits per step without asking.

## File structure

| File | Responsibility |
|------|----------------|
| `SheetVariants/placeholder_core.py` | **new, pure.** Attribute schemas + migration, frame construction, extents, matrices, body pairing |
| `tests/test_placeholder_core.py` | **new.** CI coverage for the above |
| `SheetVariants/build_engine.py` | **new, `adsk`.** Parameter apply/restore, snapshot to temp BReps, insert into base features, rebuild via `updateBody`. Extracted from `build_exports()` |
| `SheetVariants/placeholder_cmds.py` | **new, `adsk`.** `Prepare Mother Model` and `Fill Placeholders` handlers and dialogs |
| `SheetVariants/SheetVariants.py` | **modify.** Use `build_engine` in `build_exports()`; register the two new commands |
| `.github/workflows/ci.yml` | **modify.** Compile and lint the new modules |
| `SheetVariants/SheetVariants.manifest` | **modify.** Version 1.13.0 → 1.14.0 |
| `README.md`, `CHANGELOG.md` | **modify.** Document the feature |

---

### Task 1: `placeholder_core` scaffold + `motherSetup` schema

**Files:**
- Create: `SheetVariants/placeholder_core.py`
- Create: `tests/test_placeholder_core.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `placeholder_core.ATTR_GROUP`, `MOTHER_SETUP_ATTR`, `CHILD_RECIPE_ATTR`, `SLOT_ID_ATTR`, `FRONT_AXES` — constants used by every later task.
- Produces: `default_mother_setup() -> dict`, `migrate_mother_setup(data: dict|None) -> dict`, `validate_mother_setup(data) -> list[str]`, `dumps_attr(data) -> str`, `loads_attr(text: str|None, migrate: callable) -> dict`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_placeholder_core.py`:

```python
import pytest
import placeholder_core as pc


def test_default_mother_setup_shape():
    s = pc.default_mother_setup()
    assert s["v"] == 1
    assert s["front"] == "-Y"
    assert s["params"] == {"width": "", "depth": "", "height": ""}


def test_migrate_fills_missing_fields():
    s = pc.migrate_mother_setup({"anchor": "SV_Anchor"})
    assert s["anchor"] == "SV_Anchor"
    assert s["front"] == "-Y"
    assert s["params"]["width"] == ""


def test_migrate_rejects_unknown_front_axis():
    assert pc.migrate_mother_setup({"front": "+Z"})["front"] == "-Y"
    assert pc.migrate_mother_setup({"front": "+X"})["front"] == "+X"


def test_migrate_handles_none_and_garbage():
    assert pc.migrate_mother_setup(None)["v"] == 1
    assert pc.migrate_mother_setup("nonsense")["v"] == 1
    assert pc.migrate_mother_setup({"params": "nonsense"})["params"]["depth"] == ""


def test_validate_reports_every_missing_piece():
    errs = pc.validate_mother_setup({})
    assert len(errs) == 4
    assert any("anchor" in e for e in errs)
    assert any("width" in e for e in errs)


def test_validate_passes_a_complete_setup():
    assert pc.validate_mother_setup({
        "anchor": "SV_Anchor", "front": "-Y",
        "params": {"width": "cab_W", "depth": "cab_D", "height": "cab_H"},
    }) == []


def test_attr_round_trip():
    s = pc.migrate_mother_setup({"anchor": "A", "front": "+X",
                                 "params": {"width": "w", "depth": "d", "height": "h"}})
    assert pc.loads_attr(pc.dumps_attr(s), pc.migrate_mother_setup) == s


def test_loads_attr_survives_corrupt_json():
    assert pc.loads_attr("{not json", pc.migrate_mother_setup)["v"] == 1
    assert pc.loads_attr(None, pc.migrate_mother_setup)["v"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_placeholder_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placeholder_core'`

- [ ] **Step 3: Write the implementation**

Create `SheetVariants/placeholder_core.py`:

```python
# placeholder_core.py
# Pure, Fusion-free logic for the placeholder-instantiation feature: attribute
# schemas, frame construction, extents, matrices and body pairing. This module
# MUST NOT import adsk so it can be imported and unit-tested outside Fusion.
#
# Kept separate from sheet_core.py deliberately: that module is about reading
# Google Sheets, this one is about geometry and stored schemas.

import json

ATTR_GROUP = "SheetVariants"
MOTHER_SETUP_ATTR = "motherSetup"
CHILD_RECIPE_ATTR = "childRecipe"
SLOT_ID_ATTR = "slotId"

# Which model axis points OUT of the mother's front, as a face normal would.
FRONT_AXES = ("+X", "-X", "+Y", "-Y")


def dumps_attr(data):
    """Serialize an attribute payload. Sorted and compact so an unchanged value
    round-trips to an identical string and does not dirty the document."""
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def loads_attr(text, migrate):
    """Parse an attribute payload through its migration function. A missing or
    corrupt value yields the migrated default rather than raising, so a hand-edited
    or truncated attribute degrades to 'not set up' instead of breaking a build."""
    try:
        data = json.loads(text) if text else {}
    except (TypeError, ValueError):
        data = {}
    return migrate(data)


def default_mother_setup():
    return {"v": 1, "anchor": "", "front": "-Y",
            "params": {"width": "", "depth": "", "height": ""}}


def migrate_mother_setup(data):
    """Return a well-formed motherSetup from whatever was stored."""
    data = data if isinstance(data, dict) else {}
    params = data.get("params")
    params = params if isinstance(params, dict) else {}
    front = data.get("front")
    return {
        "v": 1,
        "anchor": str(data.get("anchor") or ""),
        "front": front if front in FRONT_AXES else "-Y",
        "params": {k: str(params.get(k) or "")
                   for k in ("width", "depth", "height")},
    }


def validate_mother_setup(data):
    """Human-readable reasons this mother cannot be used. Empty list means usable."""
    setup = migrate_mother_setup(data)
    errors = []
    if not setup["anchor"]:
        errors.append("No anchor joint origin is set.")
    for key in ("width", "depth", "height"):
        if not setup["params"][key]:
            errors.append('No parameter is mapped to {}.'.format(key))
    return errors
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_placeholder_core.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Add the new module to CI**

In `.github/workflows/ci.yml`, change the pyflakes line to include the new module:

```yaml
      - name: Lint for real errors (pyflakes)
        run: |
          python -m pip install --upgrade pyflakes
          pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py SheetVariants/placeholder_core.py
```

- [ ] **Step 6: Verify the lint passes**

Run: `python -m pip install --upgrade pyflakes && python -m pyflakes SheetVariants/placeholder_core.py`
Expected: no output

- [ ] **Step 7: Commit**

```bash
git add SheetVariants/placeholder_core.py tests/test_placeholder_core.py .github/workflows/ci.yml
git commit -m "feat(core): motherSetup schema and attribute serialization"
```

---

### Task 2: `childRecipe` schema and slot ids

**Files:**
- Modify: `SheetVariants/placeholder_core.py`
- Modify: `tests/test_placeholder_core.py`

**Interfaces:**
- Consumes: `dumps_attr`, `loads_attr` from Task 1.
- Produces: `new_slot_id() -> str`, `new_child_recipe(slot_id, mother, config, sheet_url, tab, dims_cm, bodies, built_at) -> dict`, `migrate_child_recipe(data) -> dict`.
  - `mother` is `{"fileId": str, "name": str, "version": int|None}`.
  - `dims_cm` is a `(w, d, h)` tuple of floats.
  - `bodies` is a list of qualified `"component::body"` strings.
  - `built_at` is an ISO-8601 string, **passed in** rather than generated, so tests are deterministic.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_placeholder_core.py`:

```python
def test_new_slot_id_is_prefixed_and_unique():
    a, b = pc.new_slot_id(), pc.new_slot_id()
    assert a.startswith("slot-") and b.startswith("slot-")
    assert a != b


def _recipe():
    return pc.new_child_recipe(
        slot_id="slot-abc",
        mother={"fileId": "urn:x", "name": "base-cabinet.f3d", "version": 12},
        config="Base_2drawer",
        sheet_url="https://sheet", tab="Cabinets",
        dims_cm=(60.0, 58.0, 72.0),
        bodies=["Carcass::Left", "Carcass::Right"],
        built_at="2026-08-08T14:22:00")


def test_new_child_recipe_shape():
    r = _recipe()
    assert r["v"] == 1
    assert r["slotId"] == "slot-abc"
    assert r["mother"]["version"] == 12
    assert r["dims_cm"] == {"w": 60.0, "d": 58.0, "h": 72.0}
    assert r["bodies"] == ["Carcass::Left", "Carcass::Right"]


def test_child_recipe_round_trips_through_attribute():
    r = _recipe()
    assert pc.loads_attr(pc.dumps_attr(r), pc.migrate_child_recipe) == r


def test_migrate_child_recipe_fills_missing_fields():
    r = pc.migrate_child_recipe({"slotId": "slot-x"})
    assert r["slotId"] == "slot-x"
    assert r["mother"]["version"] is None
    assert r["bodies"] == []
    assert r["dims_cm"] == {"w": 0.0, "d": 0.0, "h": 0.0}


def test_migrate_child_recipe_handles_garbage():
    r = pc.migrate_child_recipe({"mother": "nope", "bodies": "nope", "dims_cm": 7})
    assert r["mother"]["fileId"] == ""
    assert r["bodies"] == []
    assert r["dims_cm"]["h"] == 0.0


def test_migrate_child_recipe_coerces_dims_to_float():
    r = pc.migrate_child_recipe({"dims_cm": {"w": "60", "d": 58, "h": 72.5}})
    assert r["dims_cm"] == {"w": 60.0, "d": 58.0, "h": 72.5}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_placeholder_core.py -v -k "slot or recipe"`
Expected: FAIL — `AttributeError: module 'placeholder_core' has no attribute 'new_slot_id'`

- [ ] **Step 3: Write the implementation**

Add `import uuid` at the top of `SheetVariants/placeholder_core.py` (after `import json`), then append:

```python
def new_slot_id():
    """A stable identity for a placeholder box, stamped on the body itself so it
    survives renaming the body — which a name-based key would not."""
    return "slot-" + uuid.uuid4().hex[:8]


def _float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def new_child_recipe(slot_id, mother, config, sheet_url, tab, dims_cm,
                     bodies, built_at):
    """The record a child carries so it can be rebuilt later.

    ``built_at`` is supplied by the caller rather than generated here, so this
    module stays free of wall-clock dependencies and its tests stay deterministic.
    """
    mother = mother if isinstance(mother, dict) else {}
    w, d, h = dims_cm
    return {
        "v": 1,
        "slotId": str(slot_id or ""),
        "mother": {"fileId": str(mother.get("fileId") or ""),
                   "name": str(mother.get("name") or ""),
                   "version": mother.get("version")},
        "config": str(config or ""),
        "sheetUrl": str(sheet_url or ""),
        "tab": str(tab or ""),
        "dims_cm": {"w": _float(w), "d": _float(d), "h": _float(h)},
        "bodies": [str(b) for b in (bodies or [])],
        "builtAt": str(built_at or ""),
    }


def migrate_child_recipe(data):
    """Return a well-formed childRecipe from whatever was stored."""
    data = data if isinstance(data, dict) else {}
    mother = data.get("mother")
    mother = mother if isinstance(mother, dict) else {}
    dims = data.get("dims_cm")
    dims = dims if isinstance(dims, dict) else {}
    bodies = data.get("bodies")
    bodies = bodies if isinstance(bodies, list) else []
    version = mother.get("version")
    if not isinstance(version, int):
        version = None
    return new_child_recipe(
        slot_id=data.get("slotId"),
        mother={"fileId": mother.get("fileId"), "name": mother.get("name"),
                "version": version},
        config=data.get("config"),
        sheet_url=data.get("sheetUrl"),
        tab=data.get("tab"),
        dims_cm=(_float(dims.get("w")), _float(dims.get("d")), _float(dims.get("h"))),
        bodies=bodies,
        built_at=data.get("builtAt"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_placeholder_core.py -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_core.py tests/test_placeholder_core.py
git commit -m "feat(core): childRecipe schema and slot ids"
```

---

### Task 3: Frame construction from a face normal

**Files:**
- Modify: `SheetVariants/placeholder_core.py`
- Modify: `tests/test_placeholder_core.py`

**Interfaces:**
- Produces: `target_frame(face_normal) -> ((wx,wy,wz), (dx,dy,dz), (0,0,1))`, `mother_frame(front_axis: str) -> same`, and helpers `cross(a, b)`, `dot(a, b)`, `normalize(v)`.
- Both raise `ValueError` with a user-facing message on bad input.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_placeholder_core.py`:

```python
import math


def _close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_target_frame_for_a_face_pointing_minus_y():
    w, d, u = pc.target_frame((0.0, -1.0, 0.0))
    assert _close(d, (0.0, 1.0, 0.0))     # depth runs INTO the box
    assert _close(u, (0.0, 0.0, 1.0))
    assert _close(w, (1.0, 0.0, 0.0))


def test_target_frame_is_right_handed():
    w, d, u = pc.target_frame((0.0, -1.0, 0.0))
    assert _close(pc.cross(w, d), u)


def test_target_frame_for_a_rotated_face():
    n = (math.sqrt(0.5), -math.sqrt(0.5), 0.0)
    w, d, u = pc.target_frame(n)
    assert _close(d, (-n[0], -n[1], 0.0))
    assert _close(pc.cross(w, d), u)
    assert abs(pc.dot(w, d)) < 1e-9


def test_target_frame_normalizes_a_long_normal():
    w, d, u = pc.target_frame((0.0, -7.0, 0.0))
    assert _close(d, (0.0, 1.0, 0.0))


def test_target_frame_rejects_a_horizontal_face():
    with pytest.raises(ValueError) as e:
        pc.target_frame((0.0, 0.0, 1.0))
    assert "vertical" in str(e.value)


def test_target_frame_rejects_a_zero_normal():
    with pytest.raises(ValueError):
        pc.target_frame((0.0, 0.0, 0.0))


def test_mother_frame_minus_y_matches_a_minus_y_face():
    assert pc.mother_frame("-Y") == pc.target_frame((0.0, -1.0, 0.0))


def test_mother_frame_plus_x():
    w, d, u = pc.mother_frame("+X")
    assert _close(d, (-1.0, 0.0, 0.0))
    assert _close(pc.cross(w, d), u)


def test_mother_frame_rejects_a_vertical_axis():
    with pytest.raises(ValueError) as e:
        pc.mother_frame("+Z")
    assert "+X" in str(e.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_placeholder_core.py -v -k frame`
Expected: FAIL — `AttributeError: module 'placeholder_core' has no attribute 'target_frame'`

- [ ] **Step 3: Write the implementation**

Add `import math` at the top of `SheetVariants/placeholder_core.py`, then append:

```python
UP = (0.0, 0.0, 1.0)

_AXIS_VECTORS = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
                 "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}

# A face normal from real geometry is never exactly horizontal, so the "is this
# face vertical?" test needs slack. 1e-4 accepts ordinary floating-point noise
# while still rejecting a face tilted by even a hundredth of a degree.
_HORIZONTAL_TOLERANCE = 1e-4


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def normalize(v):
    length = math.sqrt(dot(v, v))
    if length < 1e-12:
        raise ValueError("Could not read a direction from that face.")
    return (v[0] / length, v[1] / length, v[2] / length)


def _frame_from_outward(outward):
    """(width, depth, up) unit axes for a frame whose front points along
    ``outward``. Depth runs INTO the volume, opposite the outward direction; up is
    world +Z; width is depth x up, making the frame right-handed (w x d == u)."""
    n = normalize(outward)
    if abs(n[2]) > _HORIZONTAL_TOLERANCE:
        raise ValueError(
            "The front face must be vertical — pick a side of the box, not its "
            "top or bottom.")
    depth = (-n[0], -n[1], -n[2])
    return (cross(depth, UP), depth, UP)


def target_frame(face_normal):
    """The layout-side frame implied by the selected front face's outward normal."""
    return _frame_from_outward(face_normal)


def mother_frame(front_axis):
    """The mother-side frame implied by its stored front axis, which points out of
    the front exactly as a face normal does."""
    if front_axis not in _AXIS_VECTORS:
        raise ValueError(
            "The mother's front axis must be one of {}.".format(", ".join(FRONT_AXES)))
    return _frame_from_outward(_AXIS_VECTORS[front_axis])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_placeholder_core.py -v`
Expected: PASS, 23 tests

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_core.py tests/test_placeholder_core.py
git commit -m "feat(core): build target and mother frames from a facing direction"
```

---

### Task 4: Extents and placement matrices

**Files:**
- Modify: `SheetVariants/placeholder_core.py`
- Modify: `tests/test_placeholder_core.py`

**Interfaces:**
- Consumes: `dot`, `cross`, `target_frame`, `mother_frame` from Task 3.
- Produces: `extents_in_frame(vertices, frame) -> (w, d, h, centre_world)`, `occurrence_matrix(centre, frame) -> list[16 float]`, `local_matrix(anchor, frame) -> list[16 float]`.
- Both matrices are **row-major**, matching `Matrix3D.asArray()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_placeholder_core.py`:

```python
def _box_vertices(x0, y0, z0, x1, y1, z1):
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def test_extents_of_an_axis_aligned_box():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    w, d, h, centre = pc.extents_in_frame(_box_vertices(0, 0, 0, 60, 58, 72), frame)
    assert (round(w, 9), round(d, 9), round(h, 9)) == (60.0, 58.0, 72.0)
    assert _close(centre, (30.0, 29.0, 36.0), 1e-9)


def test_extents_swap_when_the_front_face_faces_x():
    frame = pc.target_frame((-1.0, 0.0, 0.0))
    w, d, h, _ = pc.extents_in_frame(_box_vertices(0, 0, 0, 60, 58, 72), frame)
    assert (round(w, 9), round(d, 9), round(h, 9)) == (58.0, 60.0, 72.0)


def test_extents_of_a_rotated_box_are_not_inflated():
    # A 60x58x72 box rotated 45 degrees about Z. A world-aligned bounding box
    # would report ~83 wide; measuring in the frame must still report 60x58.
    import math as m
    c = m.cos(m.pi / 4)
    frame = pc.target_frame((c, -c, 0.0))
    verts = []
    for lx, ly, lz in _box_vertices(-30, -29, 0, 30, 29, 72):
        verts.append((lx * c - ly * c, lx * c + ly * c, lz))
    w, d, h, centre = pc.extents_in_frame(verts, frame)
    assert abs(w - 60.0) < 1e-9
    assert abs(d - 58.0) < 1e-9
    assert abs(h - 72.0) < 1e-9
    assert _close(centre, (0.0, 0.0, 36.0), 1e-9)


def test_extents_rejects_an_empty_vertex_list():
    with pytest.raises(ValueError):
        pc.extents_in_frame([], pc.target_frame((0.0, -1.0, 0.0)))


def test_occurrence_matrix_places_the_origin_at_the_centre():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    m = pc.occurrence_matrix((10.0, 20.0, 30.0), frame)
    assert len(m) == 16
    assert [m[3], m[7], m[11]] == [10.0, 20.0, 30.0]
    assert m[12:] == [0.0, 0.0, 0.0, 1.0]
    # Identity rotation for a -Y-facing frame: columns are w, d, u.
    assert [m[0], m[1], m[2]] == [1.0, 0.0, 0.0]
    assert [m[4], m[5], m[6]] == [0.0, 1.0, 0.0]


def test_occurrence_matrix_rotation_for_an_x_facing_frame():
    frame = pc.target_frame((-1.0, 0.0, 0.0))
    m = pc.occurrence_matrix((0.0, 0.0, 0.0), frame)
    # depth is +X, so the matrix's second column must be (1, 0, 0).
    assert [m[1], m[5], m[9]] == [1.0, 0.0, 0.0]


def test_local_matrix_sends_the_anchor_to_the_origin():
    frame = pc.mother_frame("-Y")
    m = pc.local_matrix((5.0, 6.0, 7.0), frame)
    assert [m[3], m[7], m[11]] == [-5.0, -6.0, -7.0]


def test_local_matrix_is_the_inverse_of_the_mother_frame():
    frame = pc.mother_frame("+X")
    anchor = (5.0, 6.0, 7.0)
    m = pc.local_matrix(anchor, frame)
    # Applying it to the anchor point must land exactly on the origin.
    def apply(mat, p):
        return tuple(mat[r * 4 + 0] * p[0] + mat[r * 4 + 1] * p[1]
                     + mat[r * 4 + 2] * p[2] + mat[r * 4 + 3] for r in range(3))
    assert _close(apply(m, anchor), (0.0, 0.0, 0.0), 1e-9)
    # And a point one unit along the mother's depth axis must land at (0, 1, 0).
    w, d, u = frame
    ahead = tuple(anchor[i] + d[i] for i in range(3))
    assert _close(apply(m, ahead), (0.0, 1.0, 0.0), 1e-9)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_placeholder_core.py -v -k "extents or matrix"`
Expected: FAIL — `AttributeError: module 'placeholder_core' has no attribute 'extents_in_frame'`

- [ ] **Step 3: Write the implementation**

Append to `SheetVariants/placeholder_core.py`:

```python
def extents_in_frame(vertices, frame):
    """Measure ``vertices`` along ``frame``'s axes: (width, depth, height, centre).

    Vertices are world (x, y, z) tuples — a placeholder box has eight. Measuring by
    projection rather than by reading an axis-aligned bounding box is what lets a
    corner cabinet rotated 45 degrees report its true size instead of the much
    larger world-aligned box around it.

    Exact for any flat-faced solid. A placeholder with curved faces would
    under-measure, since only vertices are considered; that is accepted, because a
    placeholder is a box.
    """
    if not vertices:
        raise ValueError("The placeholder has no vertices to measure.")
    axes = frame
    projected = [tuple(dot(v, axis) for axis in axes) for v in vertices]
    lo = [min(p[i] for p in projected) for i in range(3)]
    hi = [max(p[i] for p in projected) for i in range(3)]
    mid = [(lo[i] + hi[i]) / 2.0 for i in range(3)]
    centre = tuple(sum(mid[i] * axes[i][k] for i in range(3)) for k in range(3))
    return (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], centre)


def occurrence_matrix(centre, frame):
    """Row-major local-to-world matrix for a child occurrence: the frame's axes as
    rotation columns, translated to the box centre.

    The placement lives here, on the occurrence — never baked into the bodies.
    The designer's downstream features are defined in the component's local space,
    so moving geometry inside the component would leave their cuts behind."""
    w, d, u = frame
    return [w[0], d[0], u[0], centre[0],
            w[1], d[1], u[1], centre[1],
            w[2], d[2], u[2], centre[2],
            0.0, 0.0, 0.0, 1.0]


def local_matrix(anchor, frame):
    """Row-major world-to-anchor-local matrix, applied to snapshotted bodies so
    they arrive with the mother's anchor at the child's origin.

    This is the inverse of the mother's anchor frame. Because the frame is
    orthonormal, the inverse rotation is its transpose and the inverse translation
    is -(transpose . anchor) — no general matrix inversion needed."""
    w, d, u = frame
    return [w[0], w[1], w[2], -dot(w, anchor),
            d[0], d[1], d[2], -dot(d, anchor),
            u[0], u[1], u[2], -dot(u, anchor),
            0.0, 0.0, 0.0, 1.0]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_placeholder_core.py -v`
Expected: PASS, 31 tests

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_core.py tests/test_placeholder_core.py
git commit -m "feat(core): measure placeholder extents and compose placement matrices"
```

---

### Task 5: Body pairing for rebuilds

**Files:**
- Modify: `SheetVariants/placeholder_core.py`
- Modify: `tests/test_placeholder_core.py`

**Interfaces:**
- Produces: `qualified_body_name(component_name, body_name) -> str`, `pair_bodies(old_names, new_names) -> list[(kind, old_index, new_index)]`.
- `kind` is `"update"`, `"add"` or `"remove"`. Unused index is `None`. Ops come back ordered **update, then add, then remove**, so a caller applying them in order never deletes a body another op still refers to.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_placeholder_core.py`:

```python
def test_qualified_body_name():
    assert pc.qualified_body_name("Carcass", "Left side") == "Carcass::Left side"


def test_pair_bodies_identical_lists_are_all_updates():
    ops = pc.pair_bodies(["A", "B"], ["A", "B"])
    assert ops == [("update", 0, 0), ("update", 1, 1)]


def test_pair_bodies_reordered_lists_track_by_name():
    ops = pc.pair_bodies(["A", "B"], ["B", "A"])
    assert ops == [("update", 0, 1), ("update", 1, 0)]


def test_pair_bodies_added_body():
    ops = pc.pair_bodies(["A"], ["A", "B"])
    assert ops == [("update", 0, 0), ("add", None, 1)]


def test_pair_bodies_removed_body():
    ops = pc.pair_bodies(["A", "B"], ["A"])
    assert ops == [("update", 0, 0), ("remove", 1, None)]


def test_pair_bodies_orders_updates_then_adds_then_removes():
    ops = pc.pair_bodies(["A", "X"], ["A", "B"])
    assert [o[0] for o in ops] == ["update", "add", "remove"]


def test_pair_bodies_duplicate_names_pair_by_ordinal():
    ops = pc.pair_bodies(["A", "A", "A"], ["A", "A"])
    assert ops == [("update", 0, 0), ("update", 1, 1), ("remove", 2, None)]


def test_pair_bodies_from_empty_is_all_adds():
    assert pc.pair_bodies([], ["A", "B"]) == [("add", None, 0), ("add", None, 1)]


def test_pair_bodies_to_empty_is_all_removes():
    assert pc.pair_bodies(["A", "B"], []) == [("remove", 0, None), ("remove", 1, None)]


def test_pair_bodies_handles_none():
    assert pc.pair_bodies(None, None) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_placeholder_core.py -v -k pair`
Expected: FAIL — `AttributeError: module 'placeholder_core' has no attribute 'pair_bodies'`

- [ ] **Step 3: Write the implementation**

Append to `SheetVariants/placeholder_core.py`:

```python
def qualified_body_name(component_name, body_name):
    """A body's name qualified by its owning component, so two components can both
    hold a body called 'Side' without the two being confused during a rebuild."""
    return "{}::{}".format(component_name or "", body_name or "")


def _ordinal_keys(names):
    """Pair each name with how many times it has already been seen, so repeated
    names still match one-to-one rather than all collapsing onto the first."""
    seen, keys = {}, []
    for name in names:
        index = seen.get(name, 0)
        seen[name] = index + 1
        keys.append((name, index))
    return keys


def pair_bodies(old_names, new_names):
    """Ops that turn a base feature holding ``old_names`` into one holding
    ``new_names``, matched by qualified name.

    Matching by name rather than by position is what lets a config change alter
    the body count — a two-drawer front becoming three — without scrambling which
    body is replaced by which.

    Ops are returned update-first, then adds, then removes, so a caller can apply
    them in order: every deletion happens after every op that still needs to read
    the old bodies.
    """
    old_keys = _ordinal_keys(old_names or [])
    new_keys = _ordinal_keys(new_names or [])
    new_positions = {key: i for i, key in enumerate(new_keys)}

    updates, removes, matched = [], [], set()
    for old_index, key in enumerate(old_keys):
        new_index = new_positions.get(key)
        if new_index is None:
            removes.append(("remove", old_index, None))
        else:
            updates.append(("update", old_index, new_index))
            matched.add(new_index)
    adds = [("add", None, i) for i in range(len(new_keys)) if i not in matched]
    return updates + adds + removes
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS — all `test_sheet_core.py` tests plus 41 in `test_placeholder_core.py`

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_core.py tests/test_placeholder_core.py
git commit -m "feat(core): pair old and new bodies by qualified name for rebuilds"
```

---

### Task 6: Extract `build_engine.py` from `build_exports()`

**Files:**
- Create: `SheetVariants/build_engine.py`
- Modify: `SheetVariants/SheetVariants.py:229-254` (`apply_expression`), `:324-342` (`_appearance_in`, `_material_in`), `:345-536` (`build_exports`)
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `placeholder_core.qualified_body_name` from Task 5.
- Produces:
  - `build_engine.apply_expression(param, raw) -> None`
  - `build_engine.apply_values(values: dict[str, str]) -> None`
  - `build_engine.capture_values(names: list[str]) -> dict[str, str]`
  - `build_engine.restore_values(values: dict[str, str]) -> None`
  - `build_engine.snapshot_bodies(bodies) -> list[dict]` where each dict is `{"temp": BRepBody, "appearance": Appearance|None, "material": Material|None, "name": str}`
  - `build_engine.transform_snapshot(snaps, matrix16) -> None`
  - `build_engine.add_snapshot(component, snaps, base=None) -> BaseFeature`
  - `build_engine.reapply_looks(design, component, snaps) -> None`
  - `build_engine.appearance_in(design, src)`, `build_engine.material_in(design, src)`

**Prerequisite:** Spike 1 has PASSED. This task has **no behaviour change** — it is a pure refactor whose only verification is that the existing Build command still produces identical output.

- [ ] **Step 1: Create the new module**

Create `SheetVariants/build_engine.py`:

```python
# build_engine.py
# The Fusion-side geometry core shared by the sheet-variants build and the
# placeholder-instantiation feature: apply parameter values, snapshot solids as
# temporary BReps, and put those snapshots into a component's base feature.
#
# This module imports adsk and therefore cannot be unit-tested; every rule that
# can be expressed without Fusion belongs in sheet_core.py or placeholder_core.py.
#
# The phase ordering these functions assume is documented in build_exports():
# creating or activating a document invalidates live references to any other
# design, so all reading must finish before any output work begins.

import os
import sys

import adsk.core
import adsk.fusion

_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
sys.modules.pop('placeholder_core', None)
import placeholder_core

app = adsk.core.Application.get()


def _design():
    """The active design, re-derived fresh. Never cache this across a parameter
    write: setting a driving dimension recomputes the model, which can invalidate
    a held collection so the object from the previous call is already dead."""
    return adsk.fusion.Design.cast(app.activeProduct)


def apply_expression(param, raw):
    """Write a sheet cell into a parameter's expression.

    Text parameters need a single-quoted string expression (e.g. 'A-6'), but a
    sheet usually supplies the bare text — sometimes with a stray quote left
    over from a spreadsheet's text-prefix (so "1-1" can arrive as "1-1'"). We
    detect text parameters from their current expression and re-quote the value;
    numeric parameters get the value as-is.
    """
    raw = raw.strip()
    if not raw:
        return
    current = (param.expression or '').strip()
    if current[:1] in ("'", '"'):                     # existing text parameter
        param.expression = "'" + raw.strip('\'"') + "'"
        return
    try:
        param.expression = raw
    except Exception:
        try:                                          # maybe an unquoted text param
            param.expression = "'" + raw.strip('\'"') + "'"
        except Exception:
            raise RuntimeError(
                'Could not set parameter "{}" to "{}". Numeric values may need a '
                'unit (e.g. "50 mm"); text values are quoted automatically.'
                .format(param.name, raw))


def apply_values(values):
    """Write {parameter name: expression} into the active design. Blank values are
    skipped, leaving that parameter unchanged."""
    for name, raw in values.items():
        if not (raw or '').strip():
            continue
        param = _design().allParameters.itemByName(name)
        if param:
            apply_expression(param, raw)


def capture_values(names):
    """{name: current expression} for the named parameters, for later restoration."""
    params = _design().allParameters
    captured = {}
    for name in names:
        param = params.itemByName(name)
        if param:
            captured[name] = param.expression
    return captured


def restore_values(values):
    """Put captured expressions back. Best-effort per parameter: a failure on one
    must not leave the rest of the model in a variant state."""
    for name, expression in values.items():
        try:
            param = _design().allParameters.itemByName(name)
            if param:
                param.expression = expression
        except Exception:
            pass


def snapshot_bodies(bodies):
    """Copy each body to a temporary BRep, keeping its qualified name and its
    body-level appearance override and material. Bodies that cannot be copied are
    skipped rather than failing the run."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    snaps = []
    for body in bodies:
        try:
            temp = tbm.copy(body)
        except Exception:
            continue
        appearance = material = None
        component_name = ''
        try:
            appearance = body.appearance
        except Exception:
            pass
        try:
            material = body.material
        except Exception:
            pass
        try:
            component_name = body.parentComponent.name
        except Exception:
            pass
        snaps.append({
            'temp': temp,
            'appearance': appearance,
            'material': material,
            'name': placeholder_core.qualified_body_name(component_name, body.name),
        })
    return snaps


def transform_snapshot(snaps, matrix16):
    """Move every snapshotted body by a row-major 16-float matrix, in place."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    matrix = adsk.core.Matrix3D.create()
    matrix.setWithArray(matrix16)
    for snap in snaps:
        tbm.transform(snap['temp'], matrix)


def add_snapshot(component, snaps, base=None):
    """Add snapshotted bodies to ``component`` inside a base feature, creating one
    if not supplied. Returns the base feature."""
    if base is None:
        base = component.features.baseFeatures.add()
    base.startEdit()
    try:
        for snap in snaps:
            component.bRepBodies.add(snap['temp'], base)
    finally:
        base.finishEdit()
    return base


def appearance_in(design, src_appr):
    """The appearance named like ``src_appr`` inside ``design``, copied in once if
    needed. Lets a copied body show the source body's appearance (temporary BReps
    lose it). Returns None if it can't be copied."""
    try:
        existing = design.appearances.itemByName(src_appr.name)
        return existing or design.appearances.addByCopy(src_appr, src_appr.name)
    except Exception:
        return None


def material_in(design, src_mat):
    """The material named like ``src_mat`` inside ``design``, copied in once if
    needed. Returns None if it can't be copied."""
    try:
        existing = design.materials.itemByName(src_mat.name)
        return existing or design.materials.addByCopy(src_mat, src_mat.name)
    except Exception:
        return None


def reapply_looks(design, component, snaps):
    """Re-apply the source material and appearance to a component's bodies.

    Temporary BReps lose both, and the body objects returned during a base-feature
    edit go stale after finishEdit(), so fetch the component's bodies fresh and
    match them by index. Best-effort: the geometry is already built, so a failure
    just leaves the default look rather than breaking the build.
    """
    bodies = component.bRepBodies
    for index, snap in enumerate(snaps):
        if index >= bodies.count:
            break
        body = bodies.item(index)
        try:
            if snap['material']:
                material = material_in(design, snap['material'])
                if material:
                    body.material = material
            if snap['appearance']:
                appearance = appearance_in(design, snap['appearance'])
                if appearance:
                    body.appearance = appearance
        except Exception:
            pass  # geometry is built; a failed look just stays default
```

- [ ] **Step 2: Rewrite `build_exports()` to use the engine**

In `SheetVariants/SheetVariants.py`:

1. Add the import next to the existing `sheet_core` import (after line 40):

```python
sys.modules.pop('placeholder_core', None)
import placeholder_core
sys.modules.pop('build_engine', None)
import build_engine
```

2. **Delete** `apply_expression` (lines 229-254), `_appearance_in` (324-333) and `_material_in` (335-342) — they now live in `build_engine`.

3. In `build_exports()`, replace the parameter capture at line 369:

```python
    original = build_engine.capture_values(param_names)
```

4. Replace the per-row parameter application (lines 417-427) with:

```python
                values = {}
                for col, pname in enumerate(param_names, start=1):
                    if col < len(row):
                        values[pname] = row[col].strip()
                build_engine.apply_values(values)
```

5. Replace the snapshot block (lines 434-451) with:

```python
                    snaps = build_engine.snapshot_bodies(src_bodies)
                    if snaps:
                        ctx.setdefault('variants', []).append((safe_name, snaps))
```

6. Replace the restore block (lines 456-462) with:

```python
            build_engine.restore_values(original)
```

7. Replace the body insertion and look re-application (lines 483-518) with:

```python
            for safe_name, snaps in variants:
                tmps = [s['temp'] for s in snaps]
                min_x = min(tb.boundingBox.minPoint.x for tb in tmps)
                max_x = max(tb.boundingBox.maxPoint.x for tb in tmps)
                transform = adsk.core.Matrix3D.create()
                transform.translation = adsk.core.Vector3D.create(x_cursor - min_x, 0.0, 0.0)
                occ = root.occurrences.addNewComponent(transform)
                occ.component.name = safe_name
                build_engine.add_snapshot(occ.component, snaps)
                build_engine.reapply_looks(nd, occ.component, snaps)
                x_cursor += (max_x - min_x) + spacing_cm
                ctx['built'] += 1
```

8. Delete the now-unused `tbm = adsk.fusion.TemporaryBRepManager.get()` at line 370.

- [ ] **Step 3: Verify the module compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/build_engine.py SheetVariants/SheetVariants.py
python -m pyflakes SheetVariants/build_engine.py SheetVariants/SheetVariants.py SheetVariants/placeholder_core.py
```

Expected: no output from either. `py_compile` succeeds even though `adsk` is absent, because it only parses.

- [ ] **Step 4: Add `build_engine` to CI**

In `.github/workflows/ci.yml`, extend both the compile and lint steps:

```yaml
      - name: Byte-compile the add-in
        run: python -m py_compile SheetVariants/SheetVariants.py SheetVariants/build_engine.py

      - name: Lint for real errors (pyflakes)
        run: |
          python -m pip install --upgrade pyflakes
          pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py SheetVariants/placeholder_core.py SheetVariants/build_engine.py
```

- [ ] **Step 5: Regression-test the existing feature** *(manual, user-run)*

This refactor touches shipped, working code. Reload the add-in in Fusion (**Utilities → Scripts and Add-Ins**, Stop then Run) and run **Build Variants Assembly from Sheet** on a sheet and model you have used before.

Confirm, and report back:

- every enabled profile still produces its own design;
- one component per variant, named from the sheet's `Name` column;
- variants laid out left-to-right with the chosen gap, not overlapping;
- **materials and appearances still carry over** — this is the part most likely to regress, because `reapply_looks` now matches by index against a list of dicts rather than tuples;
- the source model's parameters are restored afterwards.

Do not tick this step or proceed to Task 7 until the user confirms all five.

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/build_engine.py SheetVariants/SheetVariants.py .github/workflows/ci.yml
git commit -m "refactor: extract the geometry core into build_engine"
```

---

### Task 7: `Prepare Mother Model` command

**Files:**
- Create: `SheetVariants/placeholder_cmds.py`
- Modify: `SheetVariants/SheetVariants.py` (imports, `run()`, `cleanup_ui()`)

**Interfaces:**
- Consumes: `placeholder_core.{migrate_mother_setup, validate_mother_setup, dumps_attr, loads_attr, ATTR_GROUP, MOTHER_SETUP_ATTR, FRONT_AXES}` from Tasks 1 and 3.
- Produces: `placeholder_cmds.PREPARE_CMD_ID = 'sheetVariantsPrepareMotherCmd'`, `placeholder_cmds.register(ui, panel, handlers) -> None`, and `placeholder_cmds.read_mother_setup(design) -> dict` used by Task 8.

**Note:** use whichever of `jointOrgins` / `jointOrigins` Spike 4 recorded as `True`. The code below uses `jointOrgins`; change both occurrences if the spike says otherwise.

**Carried forward from the Tasks 1–5 review — do this in Step 2:** `SheetVariants.py:68` defines `DESIGN_ATTR_GROUP = 'SheetVariants'` as its own literal, and `placeholder_core.ATTR_GROUP` is a second literal with the same value. Two independent definitions of the attribute group is a silent-divergence hazard: if one is ever changed, attributes get written to one group and read from another with **no error at all** — the feature just stops finding its own data. When you edit `SheetVariants.py` in Step 2, replace the literal with `DESIGN_ATTR_GROUP = placeholder_core.ATTR_GROUP` so there is exactly one definition.

- [ ] **Step 1: Create the command module**

Create `SheetVariants/placeholder_cmds.py`:

```python
# placeholder_cmds.py
# The placeholder-instantiation commands: Prepare Mother Model (records how a
# mother is driven and oriented) and Fill Placeholders (generates children).
#
# Imports adsk, so nothing here is unit-tested; the schemas, frames, extents,
# matrices and body pairing all live in placeholder_core.py, which is.

import os
import sys

import adsk.core
import adsk.fusion

_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)
sys.modules.pop('placeholder_core', None)
import placeholder_core

app = adsk.core.Application.get()
ui = app.userInterface

PREPARE_CMD_ID = 'sheetVariantsPrepareMotherCmd'
PREPARE_CMD_NAME = 'Prepare Mother Model'
PREPARE_CMD_DESC = ('Record which parameters this model\'s width, depth and height '
                    'map to, where its anchor is, and which way it faces — so it '
                    'can be assigned to placeholder boxes in a layout.')


def read_mother_setup(design):
    """The motherSetup stored on ``design``, migrated. A design that was never
    prepared yields the default, which validate_mother_setup() will reject with a
    readable reason."""
    text = ''
    try:
        attr = design.attributes.itemByName(placeholder_core.ATTR_GROUP,
                                            placeholder_core.MOTHER_SETUP_ATTR)
        if attr:
            text = attr.value
    except Exception:
        pass
    return placeholder_core.loads_attr(text, placeholder_core.migrate_mother_setup)


def write_mother_setup(design, setup):
    design.attributes.add(placeholder_core.ATTR_GROUP,
                          placeholder_core.MOTHER_SETUP_ATTR,
                          placeholder_core.dumps_attr(setup))


def joint_origin_names(design):
    """Joint origin names in the root component. A joint origin is used as the
    anchor rather than a face because it is a named entity that survives the
    parameter changes this feature makes; a face reference would not."""
    names = []
    try:
        origins = design.rootComponent.jointOrgins
        for i in range(origins.count):
            name = origins.item(i).name
            if name:
                names.append(name)
    except Exception:
        pass
    return names


def _add_dropdown(inputs, input_id, label, options, selected):
    """A single-select dropdown pre-set to ``selected`` when it is present."""
    drop = inputs.addDropDownCommandInput(
        input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    for option in options:
        drop.listItems.add(option, option == selected)
    if drop.listItems.count and not drop.selectedItem:
        drop.listItems.item(0).isSelected = True
    return drop


class PrepareCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = args.command
        inputs = cmd.commandInputs
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            inputs.addTextBoxCommandInput(
                'err', '', 'Open a parametric design first.', 2, True)
            return

        # Without a saved file there is no id to reference and no version number
        # to compare, so a child could never say whether its mother had moved on.
        if not design.parentDocument.dataFile:
            inputs.addTextBoxCommandInput(
                'err', '',
                'Save this document to your Fusion project first — a mother model '
                'must be a saved file so children can reference it and compare '
                'versions.', 4, True)
            return

        setup = read_mother_setup(design)
        origins = joint_origin_names(design)
        if not origins:
            inputs.addTextBoxCommandInput(
                'err', '',
                'This model has no joint origins. Create one at the point that '
                'should land at the centre of a placeholder box (Assemble > Joint '
                'Origin), then run this command again.', 4, True)
            return

        params = [p.name for p in design.allParameters]
        _add_dropdown(inputs, 'anchor', 'Anchor joint origin', origins, setup['anchor'])
        _add_dropdown(inputs, 'front', 'Front faces along',
                      list(placeholder_core.FRONT_AXES), setup['front'])
        _add_dropdown(inputs, 'pWidth', 'Width parameter', params,
                      setup['params']['width'])
        _add_dropdown(inputs, 'pDepth', 'Depth parameter', params,
                      setup['params']['depth'])
        _add_dropdown(inputs, 'pHeight', 'Height parameter', params,
                      setup['params']['height'])
        inputs.addTextBoxCommandInput(
            'hint', '',
            'The anchor is the point that lands at the centre of the placeholder '
            'box. To shift the model within its box, move the joint origin.',
            3, True)

        handler = PrepareExecuteHandler()
        cmd.execute.add(handler)
        _handlers.append(handler)


class PrepareExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            if not inputs.itemById('anchor'):
                return  # an error text box was shown instead of the form
            design = adsk.fusion.Design.cast(app.activeProduct)

            def picked(input_id):
                item = inputs.itemById(input_id).selectedItem
                return item.name if item else ''

            setup = placeholder_core.migrate_mother_setup({
                'anchor': picked('anchor'),
                'front': picked('front'),
                'params': {'width': picked('pWidth'),
                           'depth': picked('pDepth'),
                           'height': picked('pHeight')},
            })
            errors = placeholder_core.validate_mother_setup(setup)
            if errors:
                ui.messageBox('This mother cannot be used yet:\n\n• '
                              + '\n• '.join(errors))
                return
            write_mother_setup(design, setup)
            ui.messageBox(
                'Prepared "{}".\n\nanchor: {}\nfront: {}\nwidth: {}\ndepth: {}\n'
                'height: {}\n\nSave the document to keep this.'
                .format(design.parentDocument.name, setup['anchor'], setup['front'],
                        setup['params']['width'], setup['params']['depth'],
                        setup['params']['height']))
        except Exception:
            import traceback
            ui.messageBox('Prepare Mother Model failed:\n' + traceback.format_exc())


_handlers = []


def register(panel):
    """Create the command definitions and add them to ``panel``. Handlers are kept
    in this module's _handlers list so Python does not garbage-collect them."""
    existing = ui.commandDefinitions.itemById(PREPARE_CMD_ID)
    if existing:
        existing.deleteMe()
    definition = ui.commandDefinitions.addButtonDefinition(
        PREPARE_CMD_ID, PREPARE_CMD_NAME, PREPARE_CMD_DESC)
    handler = PrepareCreatedHandler()
    definition.commandCreated.add(handler)
    _handlers.append(handler)
    panel.controls.addCommand(definition)


def unregister():
    """Remove this module's command definitions and controls."""
    for cmd_id in (PREPARE_CMD_ID,):
        definition = ui.commandDefinitions.itemById(cmd_id)
        if definition:
            definition.deleteMe()
    _handlers[:] = []
```

- [ ] **Step 2: Wire it into the add-in**

In `SheetVariants/SheetVariants.py`, add to the import block after `import build_engine`:

```python
sys.modules.pop('placeholder_cmds', None)
import placeholder_cmds
```

In `run(context)`, after the existing commands are added to the panel, add:

```python
        placeholder_cmds.register(panel)
```

In `cleanup_ui()`, before the existing cleanup, add:

```python
    try:
        placeholder_cmds.unregister()
    except Exception:
        pass
```

- [ ] **Step 3: Verify it compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/placeholder_cmds.py SheetVariants/SheetVariants.py
python -m pyflakes SheetVariants/placeholder_cmds.py SheetVariants/SheetVariants.py
```

Expected: no output from either.

- [ ] **Step 4: Verify in Fusion** *(manual, user-run)*

Reload the add-in. Then, on a parametric model:

1. Run **Prepare Mother Model** on an **unsaved** document → the dialog explains it must be saved first, and OK does nothing.
2. Save it, remove all joint origins → the dialog explains a joint origin is needed.
3. Add a joint origin named `SV_Anchor` at the centre of the model, re-run → all five dropdowns appear.
4. Pick the anchor, `-Y`, and the three parameters, click OK → the confirmation lists exactly what you picked.
5. Save, close, reopen, re-run the command → every dropdown is **pre-selected with what you chose**. This is the real test; it proves the attribute round-tripped through a save.

Report back on all five. Do not tick this step otherwise.

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_cmds.py SheetVariants/SheetVariants.py
git commit -m "feat: Prepare Mother Model command records anchor, facing and W/D/H mapping"
```

---

### Task 8: `Fill Placeholders` — dialog and Phase 0 resolution

**Files:**
- Modify: `SheetVariants/placeholder_cmds.py`
- Modify: `SheetVariants/SheetVariants.py` (settings cache helpers)
- Modify: `SheetVariants/sheet_core.py` (mother cache in settings)
- Modify: `tests/test_sheet_core.py`

**Interfaces:**
- Consumes: `placeholder_core.{target_frame, extents_in_frame, new_slot_id, SLOT_ID_ATTR, ATTR_GROUP}`, `placeholder_cmds.read_mother_setup`, `SheetVariants.get_rows`.
- Produces:
  - `sheet_core.remember_mother(settings, mother) -> None` and `sheet_core.known_mothers(settings) -> list[dict]`
  - `placeholder_cmds.FILL_CMD_ID = 'sheetVariantsFillPlaceholdersCmd'`
  - `placeholder_cmds.resolve_slots(faces) -> (list[dict], list[str])` — the Phase 0 result. Each slot dict is `{"body": BRepBody, "slotId": str, "dims_cm": (w, d, h), "matrix": list[16 float], "name": str}`; the second value is a list of human-readable problems.

This task stops at a **dry run**: the command resolves everything and reports it in a message box without creating geometry. That makes the hardest-to-debug half (selection, frames, extents) verifiable on its own.

- [ ] **Step 1: Write the failing tests for the settings cache**

Append to `tests/test_sheet_core.py`:

```python
def test_known_mothers_defaults_to_empty():
    assert sheet_core.known_mothers({}) == []
    assert sheet_core.known_mothers({"mothers": "nonsense"}) == []


def test_remember_mother_adds_an_entry():
    s = {}
    sheet_core.remember_mother(s, {"fileId": "urn:a", "name": "base.f3d",
                                   "sheetUrl": "https://s", "tab": "Cab"})
    assert sheet_core.known_mothers(s) == [
        {"fileId": "urn:a", "name": "base.f3d", "sheetUrl": "https://s", "tab": "Cab"}]


def test_remember_mother_replaces_by_file_id():
    s = {}
    sheet_core.remember_mother(s, {"fileId": "urn:a", "name": "old.f3d",
                                   "sheetUrl": "", "tab": ""})
    sheet_core.remember_mother(s, {"fileId": "urn:a", "name": "new.f3d",
                                   "sheetUrl": "https://s", "tab": "Cab"})
    mothers = sheet_core.known_mothers(s)
    assert len(mothers) == 1
    assert mothers[0]["name"] == "new.f3d"


def test_remember_mother_ignores_an_entry_with_no_file_id():
    s = {}
    sheet_core.remember_mother(s, {"name": "x.f3d"})
    assert sheet_core.known_mothers(s) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sheet_core.py -v -k mother`
Expected: FAIL — `AttributeError: module 'sheet_core' has no attribute 'known_mothers'`

- [ ] **Step 3: Implement the settings cache**

Append to `SheetVariants/sheet_core.py`:

```python
_MOTHER_FIELDS = ("fileId", "name", "sheetUrl", "tab")


def known_mothers(settings):
    """Previously-used mother models, as a cache for populating dropdowns without
    opening documents. The mother's own attributes remain the source of truth;
    this is refreshed whenever a mother is actually opened."""
    mothers = (settings or {}).get("mothers")
    if not isinstance(mothers, list):
        return []
    out = []
    for entry in mothers:
        if isinstance(entry, dict) and entry.get("fileId"):
            out.append({k: str(entry.get(k) or "") for k in _MOTHER_FIELDS})
    return out


def remember_mother(settings, mother):
    """Add or replace a cached mother, keyed by fileId. Entries with no fileId are
    ignored — without one the mother could never be reopened."""
    if not isinstance(mother, dict) or not mother.get("fileId"):
        return
    entry = {k: str(mother.get(k) or "") for k in _MOTHER_FIELDS}
    kept = [m for m in known_mothers(settings) if m["fileId"] != entry["fileId"]]
    settings["mothers"] = kept + [entry]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS — all previous tests plus 4 new ones

- [ ] **Step 5: Add Phase 0 resolution and the dialog**

Append to `SheetVariants/placeholder_cmds.py`:

```python
FILL_CMD_ID = 'sheetVariantsFillPlaceholdersCmd'
FILL_CMD_NAME = 'Fill Placeholders'
FILL_CMD_DESC = ('Assign a prepared mother model, at a chosen config, to the '
                 'selected placeholder boxes. Each box drives its own width, '
                 'depth and height.')


def _body_vertices(body):
    """World (x, y, z) of every vertex of ``body``, in centimetres."""
    verts = body.vertices
    out = []
    for i in range(verts.count):
        point = verts.item(i).geometry
        out.append((point.x, point.y, point.z))
    return out


def read_slot_id(body):
    try:
        attr = body.attributes.itemByName(placeholder_core.ATTR_GROUP,
                                          placeholder_core.SLOT_ID_ATTR)
        return attr.value if attr else ''
    except Exception:
        return ''


def ensure_slot_id(body):
    """This body's slot id, stamping a new one the first time it is filled."""
    existing = read_slot_id(body)
    if existing:
        return existing
    slot_id = placeholder_core.new_slot_id()
    body.attributes.add(placeholder_core.ATTR_GROUP,
                        placeholder_core.SLOT_ID_ATTR, slot_id)
    return slot_id


def resolve_slots(faces):
    """Phase 0: turn selected front faces into plain-data build recipes.

    Everything a later phase needs is copied out into plain Python here, because
    activating another document invalidates every live Fusion reference. Returns
    (slots, problems); a face that cannot be resolved contributes a problem and no
    slot, so one bad pick does not lose the whole selection.
    """
    slots, problems, seen = [], [], set()
    for face in faces:
        body = face.body
        name = body.name
        if name in seen:
            problems.append('"{}" was selected more than once — using the first '
                            'face only.'.format(name))
            continue
        try:
            normal = face.geometry.normal
            frame = placeholder_core.target_frame((normal.x, normal.y, normal.z))
            width, depth, height, centre = placeholder_core.extents_in_frame(
                _body_vertices(body), frame)
        except ValueError as err:
            problems.append('"{}": {}'.format(name, err))
            continue
        seen.add(name)
        slots.append({
            'body': body,
            'slotId': read_slot_id(body),
            'dims_cm': (width, depth, height),
            'matrix': placeholder_core.occurrence_matrix(centre, frame),
            'name': name,
        })
    return slots, problems


def _mother_options(design):
    """Cached mothers plus any prepared document currently open, keyed by fileId
    so an open document supersedes its cache entry."""
    import sheet_core
    import SheetVariants
    settings = sheet_core.load_settings(SheetVariants.SETTINGS_FILE)
    options = {m['fileId']: m for m in sheet_core.known_mothers(settings)}
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        try:
            other = adsk.fusion.Design.cast(
                doc.products.itemByProductType('DesignProductType'))
            if not other or not doc.dataFile:
                continue
            setup = read_mother_setup(other)
            if placeholder_core.validate_mother_setup(setup):
                continue
            options[doc.dataFile.id] = {
                'fileId': doc.dataFile.id, 'name': doc.name,
                'sheetUrl': SheetVariants.load_design_url(other), 'tab': ''}
        except Exception:
            continue
    return sorted(options.values(), key=lambda m: m['name'])
```

- [ ] **Step 6: Add the dialog handlers**

Append to `SheetVariants/placeholder_cmds.py`:

```python
class FillCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = args.command
        inputs = cmd.commandInputs
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            inputs.addTextBoxCommandInput('err', '', 'Open a design first.', 2, True)
            return

        selection = inputs.addSelectionInput(
            'faces', 'Front faces', 'Select the front face of each placeholder box')
        selection.addSelectionFilter('PlanarFaces')
        selection.setSelectionLimits(1, 0)

        mothers = _mother_options(design)
        if not mothers:
            inputs.addTextBoxCommandInput(
                'nomother', '',
                'No prepared mother models found. Open one and run Prepare Mother '
                'Model first.', 3, True)
            return
        drop = inputs.addDropDownCommandInput(
            'mother', 'Mother model', adsk.core.DropDownStyles.TextListDropDownStyle)
        for index, mother in enumerate(mothers):
            drop.listItems.add(mother['name'], index == 0)

        config = inputs.addDropDownCommandInput(
            'config', 'Config', adsk.core.DropDownStyles.TextListDropDownStyle)
        config.listItems.add('— press Load configs —', True)
        inputs.addBoolValueInput('loadConfigs', 'Load configs', False, '', False)
        inputs.addTextBoxCommandInput('report', 'Resolved', '', 6, True)

        for handler_class, event in ((FillInputChangedHandler, cmd.inputChanged),
                                     (FillExecuteHandler, cmd.execute)):
            handler = handler_class()
            event.add(handler)
            _handlers.append(handler)

        cmd.setDialogInitialSize(460, 460)


def _selected_mother(inputs):
    item = inputs.itemById('mother').selectedItem if inputs.itemById('mother') else None
    if not item:
        return None
    for mother in _mother_options(adsk.fusion.Design.cast(app.activeProduct)):
        if mother['name'] == item.name:
            return mother
    return None


def _describe(slots, problems):
    lines = []
    for slot in slots:
        width, depth, height = slot['dims_cm']
        lines.append('{} — {:.0f} x {:.0f} x {:.0f} mm'.format(
            slot['name'], width * 10, depth * 10, height * 10))
    for problem in problems:
        lines.append('! ' + problem)
    return '<br/>'.join(lines) if lines else 'Nothing selected yet.'


class FillInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            changed = args.input
            if changed.id == 'faces':
                selection = inputs.itemById('faces')
                faces = [selection.selection(i).entity
                         for i in range(selection.selectionCount)]
                slots, problems = resolve_slots(faces)
                inputs.itemById('report').formattedText = _describe(slots, problems)
            elif changed.id == 'loadConfigs' and changed.value:
                changed.value = False
                mother = _selected_mother(inputs)
                if not mother or not mother['sheetUrl']:
                    ui.messageBox('That mother has no sheet link yet. Open it and '
                                  'run Build Variants Assembly from Sheet once to '
                                  'link its sheet.')
                    return
                import SheetVariants
                rows = SheetVariants.get_rows(mother['sheetUrl'], mother['tab'] or None)
                config = inputs.itemById('config')
                config.listItems.clear()
                for index, row in enumerate(rows[1:]):
                    name = (row[0] or '').strip()
                    if name:
                        config.listItems.add(name, config.listItems.count == 0)
                if not config.listItems.count:
                    config.listItems.add('— no named rows —', True)
        except Exception:
            import traceback
            ui.messageBox('Fill Placeholders failed:\n' + traceback.format_exc())


class FillExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            selection = inputs.itemById('faces')
            if not selection:
                return
            faces = [selection.selection(i).entity
                     for i in range(selection.selectionCount)]
            slots, problems = resolve_slots(faces)
            mother = _selected_mother(inputs)
            item = inputs.itemById('config').selectedItem
            config = item.name if item else ''
            lines = ['DRY RUN — no geometry built yet.', '',
                     'mother: {}'.format(mother['name'] if mother else '(none)'),
                     'config: {}'.format(config), '']
            for slot in slots:
                width, depth, height = slot['dims_cm']
                lines.append('{}  {:.1f} x {:.1f} x {:.1f} mm  slot={}'.format(
                    slot['name'], width * 10, depth * 10, height * 10,
                    slot['slotId'] or '(new)'))
            lines.extend('! ' + p for p in problems)
            ui.messageBox('\n'.join(lines))
        except Exception:
            import traceback
            ui.messageBox('Fill Placeholders failed:\n' + traceback.format_exc())
```

- [ ] **Step 7: Register the command**

In `placeholder_cmds.register(panel)`, after the prepare command is added:

```python
    fill_existing = ui.commandDefinitions.itemById(FILL_CMD_ID)
    if fill_existing:
        fill_existing.deleteMe()
    fill_definition = ui.commandDefinitions.addButtonDefinition(
        FILL_CMD_ID, FILL_CMD_NAME, FILL_CMD_DESC)
    fill_handler = FillCreatedHandler()
    fill_definition.commandCreated.add(fill_handler)
    _handlers.append(fill_handler)
    panel.controls.addCommand(fill_definition)
```

And in `unregister()`, change the tuple to `for cmd_id in (PREPARE_CMD_ID, FILL_CMD_ID):`.

- [ ] **Step 8: Verify it compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/placeholder_cmds.py
python -m pyflakes SheetVariants/placeholder_cmds.py SheetVariants/sheet_core.py
```

Expected: no output.

- [ ] **Step 9: Verify the dry run in Fusion** *(manual, user-run)*

Build a layout document: a `Layout` component holding three box bodies of known sizes, one of them **rotated 45° about Z**. Then:

1. Run **Fill Placeholders**, select the three front faces → the Resolved box lists three lines with the **correct mm sizes**, including the rotated one, which must report its true size and not an inflated world-aligned one.
2. Select a box's **top** face → that box is reported as a problem saying to pick a side, and the others still resolve.
3. Pick a mother and press **Load configs** → the dropdown fills with the `Name` column from that mother's sheet.
4. Click OK → the dry-run message lists mother, config, each box with its size, and `slot=(new)` for each.

Report the reported sizes so they can be checked against what you modelled. Do not tick this step otherwise.

- [ ] **Step 10: Commit**

```bash
git add SheetVariants/placeholder_cmds.py SheetVariants/sheet_core.py tests/test_sheet_core.py
git commit -m "feat: Fill Placeholders dialog resolves boxes to build recipes"
```

---

### Task 9: `Fill Placeholders` — build the children

**Files:**
- Modify: `SheetVariants/placeholder_cmds.py`

**Interfaces:**
- Consumes: everything from Tasks 6 and 8, plus `placeholder_core.{mother_frame, local_matrix, new_child_recipe, dumps_attr, CHILD_RECIPE_ATTR}`.
- Produces: `placeholder_cmds.build_children(slots, mother, config) -> list[str]` — a report line per slot. Replaces the dry run.

**Prerequisite:** Spike 1 PASSED. If it did not, stop — the phase split below is exactly what that spike tests.

- [ ] **Step 1: Add the generation engine**

First add these two imports to the **import block at the top** of
`SheetVariants/placeholder_cmds.py`, next to the existing ones:

```python
import datetime

import build_engine
```

Then append to `SheetVariants/placeholder_cmds.py`:

```python
def _unique_component_name(root, wanted):
    """``wanted``, suffixed _2, _3, ... if a component already has that name.

    A child is named after its placeholder body so the browser reads like the
    layout, but two boxes in different components may share a name and Fusion will
    not silently disambiguate them for us."""
    taken = set()
    for occurrence in root.occurrences:
        try:
            taken.add(occurrence.component.name)
        except Exception:
            continue
    if wanted not in taken:
        return wanted
    index = 2
    while '{}_{}'.format(wanted, index) in taken:
        index += 1
    return '{}_{}'.format(wanted, index)


def _row_values(rows, config):
    """{parameter name: cell} for the row whose Name column is ``config``."""
    header = [h.strip() for h in rows[0]]
    for row in rows[1:]:
        if (row[0] or '').strip() == config:
            return {name: (row[i].strip() if i < len(row) else '')
                    for i, name in enumerate(header) if i > 0 and name}
    raise RuntimeError('Config "{}" is no longer in the sheet.'.format(config))


def _cm(value):
    """A parameter expression for a length in Fusion's internal centimetres."""
    return '{:.6f} cm'.format(value)


def _open_mother(file_id):
    """(document, opened_by_us). Reuses an already-open document; refuses one with
    unsaved changes, because a run edits and restores its parameters and a crash
    partway would leave someone else's work in a variant state."""
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        try:
            if doc.dataFile and doc.dataFile.id == file_id:
                if doc.isModified:
                    raise RuntimeError(
                        'The mother "{}" has unsaved changes. Save or discard them '
                        'before filling placeholders.'.format(doc.name))
                return doc, False
        except AttributeError:
            continue
    data_file = app.data.findFileById(file_id)
    if not data_file:
        raise RuntimeError('The mother model could not be found in your projects.')
    return app.documents.open(data_file), True


def _snapshot_for(design, setup, values, dims_cm):
    """Drive the mother to one config-and-size and snapshot its solids, already
    transformed into the child's local space with the anchor at the origin."""
    frame = placeholder_core.mother_frame(setup['front'])
    origins = design.rootComponent.jointOrgins
    origin = origins.itemByName(setup['anchor'])
    if not origin:
        raise RuntimeError(
            'The anchor joint origin "{}" is missing from this mother.'
            .format(setup['anchor']))

    driven = dict(values)
    driven[setup['params']['width']] = _cm(dims_cm[0])
    driven[setup['params']['depth']] = _cm(dims_cm[1])
    driven[setup['params']['height']] = _cm(dims_cm[2])
    for key in ('width', 'depth', 'height'):
        if not design.allParameters.itemByName(setup['params'][key]):
            raise RuntimeError('The mapped {} parameter "{}" is missing from this '
                               'mother.'.format(key, setup['params'][key]))

    original = build_engine.capture_values(list(driven.keys()))
    try:
        build_engine.apply_values(driven)
        adsk.doEvents()
        fresh = adsk.fusion.Design.cast(app.activeProduct)
        # The anchor moves with the model, so read it AFTER the recompute.
        point = fresh.rootComponent.jointOrgins.itemByName(
            setup['anchor']).geometry.origin
        bodies = []
        for occurrence in fresh.rootComponent.allOccurrences:
            bodies.extend(b for b in occurrence.bRepBodies if b.isSolid)
        bodies.extend(b for b in fresh.rootComponent.bRepBodies if b.isSolid)
        snaps = build_engine.snapshot_bodies(bodies)
    finally:
        build_engine.restore_values(original)
        adsk.doEvents()
    build_engine.transform_snapshot(
        snaps, placeholder_core.local_matrix((point.x, point.y, point.z), frame))
    return snaps


def build_children(slots, mother, config):
    """Phases 1 and 2: drive the mother once per distinct size, then create a child
    component per slot in the layout document.

    Returns one report line per slot. A slot that cannot be built contributes a
    failure line and is skipped; it never aborts the run, so one bad box does not
    cost you the whole kitchen.
    """
    layout_doc = app.activeDocument
    rows_url, rows_tab = mother['sheetUrl'], mother['tab'] or None
    import SheetVariants
    values = _row_values(SheetVariants.get_rows(rows_url, rows_tab), config)

    # The progress dialog covers Phase 1 only: driving and recomputing the mother
    # is the slow part, while Phase 2 just copies snapshots that are already made.
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show('Filling placeholders', 'Placeholder %v of %m', 0, len(slots), 0)
    failures = []

    # Phase 1 — everything that needs the mother, with the layout in the background.
    doc, opened_by_us = _open_mother(mother['fileId'])
    version = doc.dataFile.versionNumber if doc.dataFile else None
    by_size = {}
    try:
        doc.activate()
        adsk.doEvents()
        mother_design = adsk.fusion.Design.cast(app.activeProduct)
        setup = placeholder_core.migrate_mother_setup(read_mother_setup(mother_design))
        errors = placeholder_core.validate_mother_setup(setup)
        if errors:
            raise RuntimeError('"{}" is not fully prepared:\n• {}'
                               .format(mother['name'], '\n• '.join(errors)))
        # One drive per DISTINCT size: a run of identical units costs one recompute.
        for index, slot in enumerate(slots):
            if progress.wasCancelled:
                raise RuntimeError('Cancelled by user.')
            key = tuple(round(v, 6) for v in slot['dims_cm'])
            if key not in by_size:
                try:
                    by_size[key] = _snapshot_for(mother_design, setup, values,
                                                 slot['dims_cm'])
                except Exception as err:
                    # One unusable slot must not cost the whole run.
                    failures.append('{} — {}'.format(slot['name'], err))
            progress.progressValue = index + 1
    finally:
        if opened_by_us:
            doc.close(False)
        adsk.doEvents()
        progress.hide()

    # Phase 2 — back in the layout, with every snapshot already in hand.
    layout_doc.activate()
    adsk.doEvents()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    tbm = adsk.fusion.TemporaryBRepManager.get()
    built_at = datetime.datetime.now().isoformat(timespec='seconds')
    report = []
    for slot in slots:
        key = tuple(round(v, 6) for v in slot['dims_cm'])
        template = by_size.get(key)
        if template is None:
            continue  # its failure is already recorded
        # Copy again per slot: identical units share one recompute, not one body.
        snaps = [{'temp': tbm.copy(s['temp']), 'appearance': s['appearance'],
                  'material': s['material'], 'name': s['name']} for s in template]

        matrix = adsk.core.Matrix3D.create()
        matrix.setWithArray(slot['matrix'])
        occurrence = root.occurrences.addNewComponent(matrix)
        occurrence.component.name = _unique_component_name(root, slot['name'])
        build_engine.add_snapshot(occurrence.component, snaps)
        build_engine.reapply_looks(design, occurrence.component, snaps)

        slot_id = ensure_slot_id(slot['body'])
        recipe = placeholder_core.new_child_recipe(
            slot_id=slot_id,
            mother={'fileId': mother['fileId'], 'name': mother['name'],
                    'version': version},
            config=config, sheet_url=rows_url, tab=mother['tab'],
            dims_cm=slot['dims_cm'],
            bodies=[s['name'] for s in snaps],
            built_at=built_at)
        occurrence.component.attributes.add(
            placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR,
            placeholder_core.dumps_attr(recipe))
        try:
            slot['body'].isLightBulbOn = False
        except Exception:
            pass
        report.append('{} — built {} bodies'.format(slot['name'], len(snaps)))
    return report + failures
```

- [ ] **Step 2: Replace the dry run with the real build**

In `FillExecuteHandler.notify`, replace the body after `config = item.name if item else ''` with:

```python
            if not mother or not config:
                ui.messageBox('Pick a mother model and a config first.')
                return
            report = build_children(slots, mother, config)
            import sheet_core
            import SheetVariants
            settings = sheet_core.load_settings(SheetVariants.SETTINGS_FILE)
            sheet_core.remember_mother(settings, mother)
            sheet_core.save_settings(SheetVariants.SETTINGS_FILE, settings)
            lines = report + ['! ' + p for p in problems]
            ui.messageBox('\n'.join(lines) if lines else 'Nothing was built.')
```

- [ ] **Step 3: Verify it compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/placeholder_cmds.py
python -m pyflakes SheetVariants/placeholder_cmds.py
```

Expected: no output.

- [ ] **Step 4: Verify in Fusion** *(manual, user-run)*

Using the prepared mother from Task 7 and the layout from Task 8:

1. Select three front faces, pick the mother and a config, OK. Confirm: three child components appear, **each sized to its own box**, each named after its box body.
2. Confirm the rotated box's child is **rotated to match** and its front faces the same way as the box's front face.
3. Confirm each box body is now **hidden** and still present in the browser.
4. Confirm the children carry **materials and appearances** from the mother.
5. Reopen the **mother** document and confirm its parameters are **unchanged** — this is what `restore_values` in the `finally` block guarantees.
6. Make an unsaved edit in the mother, leave it open, and run Fill again → it refuses with the "unsaved changes" message.
7. Select four faces where two boxes are the **same size**, and confirm the build is visibly faster than four different sizes would be (one recompute is shared).

Report on all seven. Do not tick this step otherwise.

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_cmds.py
git commit -m "feat: build child components from mother, config and placeholder box"
```

---

### Task 10: Rebuild an already-filled slot

**Files:**
- Modify: `SheetVariants/placeholder_cmds.py`
- Modify: `SheetVariants/build_engine.py`

**Interfaces:**
- Consumes: `placeholder_core.{pair_bodies, migrate_child_recipe, loads_attr}` from Tasks 2 and 5.
- Produces:
  - `build_engine.rebuild_base_feature(component, base, snaps, ops) -> None`
  - `build_engine.find_base_feature(component) -> BaseFeature|None`
  - `placeholder_cmds.attribute_list(found) -> list[Attribute]` — normalises the `AttributeVector` that `Design.findAttributes()` returns (see the note in the code; it is **not** a Fusion collection)
  - `placeholder_cmds.find_children(design) -> dict[slot_id, (occurrence, recipe)]`
  - `placeholder_cmds.rebuild_child(design, occurrence, recipe, snaps, matrix) -> str`

**Prerequisite:** Spike 3 PASSED. If it did not, stop — the freeze-flag alternative is a decision for the user, not a workaround to code around.

- [ ] **Step 1: Add the rebuild primitives to `build_engine`**

Append to `SheetVariants/build_engine.py`:

```python
def find_base_feature(component):
    """The component's first base feature — the one this add-in created to hold
    the mother's geometry. Returns None if it has been deleted."""
    features = component.features.baseFeatures
    return features.item(0) if features.count else None


def base_feature_bodies(component, base):
    """The bodies the base feature owns.

    Spike 3 confirmed ``base.bodies`` stays populated once downstream features
    exist (count 1 with a fillet on top), so it is the exact answer. The
    positional fallback assumes the base feature's bodies are the component's
    first N in creation order, which only holds while downstream features modify
    rather than add bodies — it is a safety net, not the intended path.
    """
    try:
        if base.bodies.count:
            return [base.bodies.item(i) for i in range(base.bodies.count)]
    except Exception:
        pass
    return [component.bRepBodies.item(i) for i in range(component.bRepBodies.count)]


def rebuild_base_feature(component, base, snaps, ops):
    """Swap a base feature's geometry in place so downstream features recompute
    against the new bodies instead of being deleted along with the old ones.

    ``ops`` comes from placeholder_core.pair_bodies and is already ordered
    update-then-add-then-remove, so bodies are only deleted after every op that
    still needs to read them.

    Body references are resolved BEFORE startEdit(), and that ordering is load
    bearing, not tidiness: startEdit() rolls the timeline back to this feature,
    which recomputes and invalidates collections fetched across it. Spike 3 hit
    "RuntimeError: 3 : Bad index parameter" doing it the other way round. (It
    also keeps indices stable, since a removal would shift them.)
    """
    existing = base_feature_bodies(component, base)
    base.startEdit()
    try:
        for kind, old_index, new_index in ops:
            if kind == 'update':
                base.updateBody(existing[old_index], snaps[new_index]['temp'])
            elif kind == 'add':
                component.bRepBodies.add(snaps[new_index]['temp'], base)
            elif kind == 'remove':
                existing[old_index].deleteMe()
    finally:
        base.finishEdit()
```

- [ ] **Step 2: Add child discovery and rebuild to `placeholder_cmds`**

Append to `SheetVariants/placeholder_cmds.py`:

```python
def attribute_list(found):
    """Design.findAttributes() returns an **AttributeVector**, which is NOT a
    Fusion collection — it has no .count or .item(i), and using them raises
    AttributeError. Spike 2 confirmed this; len()/index is the working shape.
    The .count branch is kept as a fallback for builds that expose the collection
    shape instead."""
    try:
        return [found[i] for i in range(len(found))]
    except (TypeError, AttributeError):
        return [found.item(i) for i in range(found.count)]


def find_children(design):
    """{slot id: (occurrence, recipe)} for every child in ``design``.

    findAttributes returns the whole set in one call, so no occurrence tree is
    walked. The attribute is written on the component, so its occurrence is found
    by matching component names against the root's occurrences.
    """
    found = {}
    by_component = {}
    for occurrence in design.rootComponent.occurrences:
        by_component.setdefault(occurrence.component.name, occurrence)
    for attribute in attribute_list(design.findAttributes(
            placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR)):
        recipe = placeholder_core.loads_attr(attribute.value,
                                             placeholder_core.migrate_child_recipe)
        try:
            occurrence = by_component.get(attribute.parent.name)
        except Exception:
            occurrence = None
        if occurrence and recipe['slotId']:
            found[recipe['slotId']] = (occurrence, recipe)
    return found


def rebuild_child(design, occurrence, recipe, snaps, matrix16):
    """Swap a child's geometry and re-place it, keeping the component and anything
    the designer built on top of it. Returns a report line."""
    component = occurrence.component
    base = build_engine.find_base_feature(component)
    if base is None:
        return '{} — cannot rebuild: its base feature was deleted'.format(component.name)
    ops = placeholder_core.pair_bodies(recipe['bodies'], [s['name'] for s in snaps])
    build_engine.rebuild_base_feature(component, base, snaps, ops)
    build_engine.reapply_looks(design, component, snaps)
    matrix = adsk.core.Matrix3D.create()
    matrix.setWithArray(matrix16)
    occurrence.transform2 = matrix
    changed = sum(1 for op in ops if op[0] != 'update')
    return '{} — rebuilt {} bodies{}'.format(
        component.name, len(snaps),
        ', {} added or removed'.format(changed) if changed else '')
```

- [ ] **Step 3: Route already-filled slots through the rebuild**

In `build_children`, replace the Phase 2 loop body's component creation with a branch. Change the block that starts `matrix = adsk.core.Matrix3D.create()` to:

```python
        existing = children.get(slot['slotId']) if slot['slotId'] else None
        if existing:
            occurrence, old_recipe = existing
            report.append(rebuild_child(design, occurrence, old_recipe, snaps,
                                        slot['matrix']))
        else:
            matrix = adsk.core.Matrix3D.create()
            matrix.setWithArray(slot['matrix'])
            occurrence = root.occurrences.addNewComponent(matrix)
            occurrence.component.name = _unique_component_name(root, slot['name'])
            build_engine.add_snapshot(occurrence.component, snaps)
            build_engine.reapply_looks(design, occurrence.component, snaps)
            report.append('{} — built {} bodies'.format(slot['name'], len(snaps)))
```

and add, just before the `for slot in slots:` loop:

```python
    children = find_children(design)
```

Then delete the now-duplicated `report.append('{} — built {} bodies'...)` at the end of the loop, keeping the recipe write, the slot-id stamp and the body hide, which run for both branches.

- [ ] **Step 4: Verify it compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/placeholder_cmds.py SheetVariants/build_engine.py
python -m pyflakes SheetVariants/placeholder_cmds.py SheetVariants/build_engine.py
```

Expected: no output.

- [ ] **Step 5: Verify the rebuild in Fusion** *(manual, user-run)*

This is the step that proves the design's central claim. Using a layout filled in Task 9:

1. On one child, **add a downstream feature by hand** — cut a hole through it, or fillet an edge. Confirm it appears after the base feature in that component's timeline.
2. Re-run **Fill Placeholders** on that same box's front face, choosing a **different config**. Confirm: the geometry changes, the component is **not** recreated, and **your hole is still there** (or is flagged by Fusion as an errored feature, which is the acceptable outcome the spec names — silently vanishing is not).
3. Move the placeholder box, re-run Fill on it → the child moves to the new position and the hole moves with it, staying in the same place *on the cabinet*.
4. Resize the placeholder box, re-run Fill → the child is rebuilt at the new size.
5. Pick a config with a **different number of bodies** than the current one and confirm bodies are added or removed rather than the rebuild failing.

Report on all five, and say explicitly what happened to the hand-made hole in step 2. Do not tick this step otherwise.

- [ ] **Step 6: Commit**

```bash
git add SheetVariants/placeholder_cmds.py SheetVariants/build_engine.py
git commit -m "feat: rebuild a filled slot in place so downstream features survive"
```

---

### Task 11: Documentation and release

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `SheetVariants/SheetVariants.manifest`

- [ ] **Step 1: Bump the manifest version**

In `SheetVariants/SheetVariants.manifest`, change `"version": "1.13.0"` to `"version": "1.14.0"`.

- [ ] **Step 2: Add the CHANGELOG entry**

In `CHANGELOG.md`, directly below the `## Planned / ideas` section, insert:

```markdown
## 1.14.0 — Placeholder instantiation

- **Prepare Mother Model** — record on a saved parametric document which
  parameters its width, depth and height map to, which joint origin is its
  anchor, and which way it faces. Stored on the document, so it travels with
  the file.
- **Fill Placeholders** — select the front face of each placeholder box in a
  layout, pick a prepared mother and one config row from its sheet, and each
  box gets a child component driven to that box's own size and orientation.
  The anchor lands at the box centre; the box is hidden, never deleted.
- **Rebuilds preserve your edits.** Re-running Fill on a filled box swaps the
  geometry inside its base feature via `updateBody()`, so a cut or fillet you
  added downstream recomputes against the new shape instead of being deleted
  with the old one.
- Identical boxes share one recompute of the mother.
- The geometry core is now shared with the sheet-variants build
  (`build_engine.py`), and the new pure logic — schemas, frames, extents,
  matrices, body pairing — is unit-tested on CI in `placeholder_core.py`.
```

- [ ] **Step 3: Add the README section**

In `README.md`, insert a new section directly before `## How the Google connection works`:

````markdown
## Placeholders — building a kitchen from one mother model

Lay out a design as plain boxes, then fill each box with a configuration of a
parametric model. The box's size drives the model; its front face sets which way
the result faces.

**1. Prepare the mother.** Open your parametric model, add a joint origin at the
point that should sit at the centre of a placeholder box, and run **Prepare Mother
Model**. Pick that joint origin as the anchor, say which axis points out of its
front, and map its width, depth and height parameters. This is stored on the
document, so it travels with the file.

The anchor is the only positioning control: to shift the model inside its box,
move the joint origin.

**2. Lay out the boxes.** In your layout design, model one box body per slot —
sketch and extrude them however you like, conventionally grouped in a `Layout`
component and placed first in the timeline so you can always roll back to the
conceptual layout. A box need not be axis-aligned; a corner unit rotated 45° is
measured correctly.

**3. Fill them.** Run **Fill Placeholders**, select the **front face** of each box,
pick the mother and one config from its sheet, and click OK. Each box gets its own
child component, sized to itself, named after the box body. Boxes are hidden once
filled, never deleted.

Selecting several faces at once assigns them all in one go — a run of five base
units is one gesture, and each is still built to its own size.

**4. Change your mind.** Re-run **Fill Placeholders** on a box that already has a
child to give it a different config, or after moving or resizing the box. The child
is rebuilt **in place**: features you added yourself — an extra cut, a fillet — are
recomputed against the new geometry rather than deleted with the old. When a change
breaks one of those references, Fusion marks that feature as errored in the usual
way.
````

- [ ] **Step 4: Verify the whole suite still passes**

Run:

```bash
python -m pytest tests/ -v
python -m py_compile SheetVariants/SheetVariants.py SheetVariants/build_engine.py SheetVariants/placeholder_cmds.py SheetVariants/placeholder_core.py
python -m pyflakes SheetVariants/SheetVariants.py SheetVariants/sheet_core.py SheetVariants/placeholder_core.py SheetVariants/build_engine.py SheetVariants/placeholder_cmds.py
python -m json.tool SheetVariants/SheetVariants.manifest > /dev/null
```

Expected: all tests PASS, no other output.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md SheetVariants/SheetVariants.manifest
git commit -m "docs: document placeholder instantiation and release 1.14.0"
```
