# Update Children Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `Update Children` command that shows every child in a layout grouped by its mother, flags the ones whose mother has moved on or whose box has changed, and rebuilds the ones you tick.

**Architecture:** Plan 2 adds **no geometry code**. Everything that builds or swaps bodies already exists in `build_engine.py` and `placeholder_cmds.build_children` / `rebuild_child` from Plan 1; this plan only decides *which* children to send through that path. The decision logic — staleness comparison, resize and move detection, grouping, labels — is pure and lives in `placeholder_core.py` with CI coverage; the Fusion side is resolution and a table dialog.

**Tech Stack:** Python 3 (Fusion's bundled interpreter), Autodesk Fusion API (`adsk.core`, `adsk.fusion`), stdlib only at runtime, pytest for tests.

**Spec:** [2026-08-08-placeholder-instantiation-design.md](../specs/2026-08-08-placeholder-instantiation-design.md)
**Prerequisite:** [Plan 1](2026-08-08-placeholder-fill.md) complete through Task 10, with Task 10 Step 5 confirmed in Fusion. Plan 2 calls `rebuild_child()` directly; if that is not proven working, this plan has nothing to stand on.

## Global Constraints

Identical to Plan 1 — reproduced here because a task's implementer may only see this file:

- **Runtime code is stdlib-only.** No third-party imports in any `SheetVariants/*.py`.
- **`placeholder_core.py` and `sheet_core.py` must never import `adsk`.**
- **`SheetVariants.py`, `build_engine.py` and `placeholder_cmds.py` import `adsk` at module top** — never write a test that imports them.
- **Personal-licence-safe.** Geometry copied in-memory via `TemporaryBRepManager` only.
- **Internal units are centimetres**; parameter expressions carry an explicit `cm` suffix.
- **Attribute group is `SheetVariants`.**
- **All matrices are row-major flat 16-float lists**, matching `Matrix3D.asArray()`.
- **Never claim a Fusion-side task works on the basis of `py_compile`/`pyflakes`.** Steps labelled *(manual, user-run)* are verified by the user inside Fusion.
- **Commit each completed task.**

## Known limitation this plan makes explicit

A child's front direction was chosen by picking a face at fill time and is **not
stored** — it is recovered from the child's own occurrence transform. That is exact
for a box that has moved or been resized, because a box's centre is the same in any
frame. It is *not* exact for a box that has been **rotated**, which would be
measured in the old frame and get its width and depth wrong.

Rather than store the normal, Task 1 adds a pure check that detects exactly this
case — a box whose faces are no longer parallel to the child's frame — and the
dialog reports it as `rotated — re-run Fill Placeholders`, which is the operation
that asks for a face again. Silent wrong sizing is the failure this avoids.

---

### Task 1: Staleness, change detection and labels

**Files:**
- Modify: `SheetVariants/placeholder_core.py`
- Modify: `tests/test_placeholder_core.py`

**Interfaces:**
- Consumes: `dot`, `occurrence_matrix`, `extents_in_frame`, `migrate_child_recipe` from Plan 1 Tasks 2–4.
- Produces:
  - `STALE_UNKNOWN = "unknown"`, `STALE_CURRENT = "up_to_date"`, `STALE_OUT_OF_DATE = "out_of_date"`
  - `staleness(stored_version, current_version) -> str`
  - `frame_from_matrix(matrix16) -> (width_axis, depth_axis, up_axis)`
  - `matrices_differ(a, b, tolerance=1e-6) -> bool`
  - `is_axis_aligned(vertices, frame, tolerance=1e-4) -> bool`
  - `child_status(recipe, current_version, box_dims_cm, moved, rotated, mother_found, box_found) -> dict` with keys `staleness`, `resized`, `moved`, `rotated`, `problem`, `tick`
  - `status_label(status) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_placeholder_core.py`:

```python
def test_staleness_compares_versions():
    assert pc.staleness(12, 14) == pc.STALE_OUT_OF_DATE
    assert pc.staleness(12, 12) == pc.STALE_CURRENT


def test_staleness_flags_a_reverted_mother_too():
    assert pc.staleness(14, 12) == pc.STALE_OUT_OF_DATE


def test_staleness_is_unknown_without_both_versions():
    assert pc.staleness(None, 12) == pc.STALE_UNKNOWN
    assert pc.staleness(12, None) == pc.STALE_UNKNOWN
    assert pc.staleness("12", 12) == pc.STALE_UNKNOWN


def test_frame_from_matrix_round_trips_occurrence_matrix():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    m = pc.occurrence_matrix((3.0, 4.0, 5.0), frame)
    assert pc.frame_from_matrix(m) == frame


def test_frame_from_matrix_round_trips_a_rotated_frame():
    import math as m
    c = m.cos(m.pi / 4)
    frame = pc.target_frame((c, -c, 0.0))
    got = pc.frame_from_matrix(pc.occurrence_matrix((0.0, 0.0, 0.0), frame))
    for axis, expected in zip(got, frame):
        assert _close(axis, expected, 1e-12)


def test_matrices_differ_detects_a_translation():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    a = pc.occurrence_matrix((0.0, 0.0, 0.0), frame)
    b = pc.occurrence_matrix((0.0, 20.0, 0.0), frame)
    assert pc.matrices_differ(a, b)
    assert not pc.matrices_differ(a, list(a))


def test_matrices_differ_ignores_floating_point_noise():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    a = pc.occurrence_matrix((1.0, 2.0, 3.0), frame)
    b = [v + 1e-12 for v in a]
    assert not pc.matrices_differ(a, b)


def test_matrices_differ_on_missing_input():
    assert pc.matrices_differ(None, [0.0] * 16)
    assert pc.matrices_differ([0.0] * 16, [0.0] * 4)


def test_is_axis_aligned_true_for_a_box_in_its_own_frame():
    frame = pc.target_frame((0.0, -1.0, 0.0))
    assert pc.is_axis_aligned(_box_vertices(0, 0, 0, 60, 58, 72), frame)


def test_is_axis_aligned_false_for_a_rotated_box():
    import math as m
    c = m.cos(m.pi / 4)
    verts = [(x * c - y * c, x * c + y * c, z)
             for x, y, z in _box_vertices(-30, -29, 0, 30, 29, 72)]
    assert not pc.is_axis_aligned(verts, pc.target_frame((0.0, -1.0, 0.0)))


def _stored(version=12, dims=(60.0, 58.0, 72.0)):
    return pc.new_child_recipe(
        slot_id="slot-abc",
        mother={"fileId": "urn:x", "name": "m.f3d", "version": version},
        config="C", sheet_url="", tab="", dims_cm=dims,
        bodies=[], built_at="2026-08-08T00:00:00")


def test_child_status_up_to_date_is_not_ticked():
    s = pc.child_status(_stored(), 12, (60.0, 58.0, 72.0), False, False, True, True)
    assert s["staleness"] == pc.STALE_CURRENT
    assert s["tick"] is False
    assert pc.status_label(s) == "up to date"


def test_child_status_out_of_date_is_ticked():
    s = pc.child_status(_stored(), 14, (60.0, 58.0, 72.0), False, False, True, True)
    assert s["tick"] is True
    assert pc.status_label(s) == "out of date"


def test_child_status_detects_a_resize():
    s = pc.child_status(_stored(), 12, (100.0, 58.0, 72.0), False, False, True, True)
    assert s["resized"] is True
    assert s["tick"] is True
    assert "resized" in pc.status_label(s)


def test_child_status_ignores_a_sub_micron_dimension_difference():
    s = pc.child_status(_stored(), 12, (60.00000001, 58.0, 72.0),
                        False, False, True, True)
    assert s["resized"] is False


def test_child_status_combines_flags_in_the_label():
    s = pc.child_status(_stored(), 14, (100.0, 58.0, 72.0), True, False, True, True)
    assert pc.status_label(s) == "out of date, resized, moved"


def test_child_status_missing_mother_is_a_problem_and_not_ticked():
    s = pc.child_status(_stored(), None, (60.0, 58.0, 72.0), False, False, False, True)
    assert s["problem"] == "mother not found"
    assert s["tick"] is False
    assert pc.status_label(s) == "mother not found"


def test_child_status_missing_placeholder_is_a_problem():
    s = pc.child_status(_stored(), 12, None, False, False, True, False)
    assert s["problem"] == "placeholder missing"
    assert s["tick"] is False


def test_child_status_rotated_is_a_problem_not_a_rebuild():
    s = pc.child_status(_stored(), 12, (60.0, 58.0, 72.0), False, True, True, True)
    assert s["tick"] is False
    assert "re-run Fill Placeholders" in pc.status_label(s)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_placeholder_core.py -v -k "stale or status or matrices or aligned or frame_from"`
Expected: FAIL — `AttributeError: module 'placeholder_core' has no attribute 'staleness'`

- [ ] **Step 3: Write the implementation**

Append to `SheetVariants/placeholder_core.py`:

```python
STALE_UNKNOWN = "unknown"
STALE_CURRENT = "up_to_date"
STALE_OUT_OF_DATE = "out_of_date"

# A micron. Below this, a dimension difference is floating-point noise from
# measuring the same box twice, not a resize the user made.
_DIMS_TOLERANCE_CM = 1e-4


def staleness(stored_version, current_version):
    """Whether a child's mother has moved on since the child was built.

    Any difference counts, not just an increase — reverting a mother to an older
    version is still a change the children have not seen. A version that is not an
    int (a mother that was never saved, or could not be resolved) is unknown rather
    than stale, so a resolution failure never masquerades as an update."""
    if not isinstance(stored_version, int) or not isinstance(current_version, int):
        return STALE_UNKNOWN
    return STALE_OUT_OF_DATE if stored_version != current_version else STALE_CURRENT


def frame_from_matrix(matrix16):
    """The (width, depth, up) axes carried by a child's occurrence transform.

    The front direction the user picked at fill time is not stored; it is recovered
    from here. Exact for a box that moved or resized, since a box's centre is the
    same measured in any frame — but not for one that was rotated, which
    is_axis_aligned() detects separately."""
    return ((matrix16[0], matrix16[4], matrix16[8]),
            (matrix16[1], matrix16[5], matrix16[9]),
            (matrix16[2], matrix16[6], matrix16[10]))


def matrices_differ(a, b, tolerance=1e-6):
    """Whether two row-major matrices describe different placements. Used to spot a
    moved box without storing a placement, by comparing the child's live transform
    against one freshly computed from its box."""
    if not a or not b or len(a) != len(b):
        return True
    return any(abs(x - y) > tolerance for x, y in zip(a, b))


def is_axis_aligned(vertices, frame, tolerance=1e-4):
    """Whether these vertices form a box whose faces are parallel to ``frame``.

    A box aligned to a frame projects onto exactly two distinct coordinates per
    axis. More than two means the box has been rotated relative to the frame, so
    measuring it there would report the wrong width and depth."""
    for axis in frame:
        values = sorted(dot(v, axis) for v in vertices)
        distinct = [values[0]]
        for value in values[1:]:
            if value - distinct[-1] > tolerance:
                distinct.append(value)
        if len(distinct) != 2:
            return False
    return True


def child_status(recipe, current_version, box_dims_cm, moved, rotated,
                 mother_found, box_found):
    """What the Update dialog should say about one child, and whether to tick it.

    Problems (a missing mother, a deleted placeholder, a rotated box) are reported
    and left unticked: none of them can be fixed by rebuilding, so pre-selecting
    them would invite a run that cannot help.
    """
    status = {"staleness": STALE_UNKNOWN, "resized": False, "moved": False,
              "rotated": False, "problem": "", "tick": False}
    if not mother_found:
        status["problem"] = "mother not found"
        return status
    if not box_found:
        status["problem"] = "placeholder missing"
        return status
    if rotated:
        status["rotated"] = True
        status["problem"] = "rotated — re-run Fill Placeholders"
        return status

    recipe = migrate_child_recipe(recipe)
    status["staleness"] = staleness(recipe["mother"]["version"], current_version)
    status["moved"] = bool(moved)
    if box_dims_cm is not None:
        stored = recipe["dims_cm"]
        status["resized"] = any(
            abs(measured - was) > _DIMS_TOLERANCE_CM
            for measured, was in zip(box_dims_cm,
                                     (stored["w"], stored["d"], stored["h"])))
    status["tick"] = (status["staleness"] == STALE_OUT_OF_DATE
                      or status["resized"] or status["moved"])
    return status


def status_label(status):
    """The human-readable status shown in the dialog's last column."""
    if status["problem"]:
        return status["problem"]
    parts = []
    if status["staleness"] == STALE_OUT_OF_DATE:
        parts.append("out of date")
    if status["resized"]:
        parts.append("resized")
    if status["moved"]:
        parts.append("moved")
    if parts:
        return ", ".join(parts)
    return "unknown version" if status["staleness"] == STALE_UNKNOWN else "up to date"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS — all Plan 1 tests plus 18 new ones

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_core.py tests/test_placeholder_core.py
git commit -m "feat(core): staleness, resize/move/rotation detection and status labels"
```

---

### Task 2: Resolve children against their mothers and boxes

**Files:**
- Modify: `SheetVariants/placeholder_cmds.py`

**Interfaces:**
- Consumes: `placeholder_cmds.find_children`, `_body_vertices`, `read_slot_id` (Plan 1 Tasks 8 and 10); `placeholder_core.{frame_from_matrix, extents_in_frame, occurrence_matrix, matrices_differ, is_axis_aligned, child_status}` (Task 1).
- Produces: `placeholder_cmds.survey_children(design) -> list[dict]`, each `{"occurrence", "recipe", "body", "status", "dims_cm", "matrix", "name"}`, sorted by mother name then child name.

- [ ] **Step 1: Add the survey**

Append to `SheetVariants/placeholder_cmds.py`:

```python
def find_slot_bodies(design):
    """{slot id: body} for every placeholder in ``design``, in one call."""
    bodies = {}
    attributes = design.findAttributes(placeholder_core.ATTR_GROUP,
                                       placeholder_core.SLOT_ID_ATTR)
    for i in range(attributes.count):
        attribute = attributes.item(i)
        try:
            bodies[attribute.value] = attribute.parent
        except Exception:
            continue
    return bodies


def _current_versions(recipes):
    """{fileId: versionNumber or None}, resolving each mother exactly once. A
    kitchen has a handful of mothers, so one data-panel lookup each is cheap; doing
    it per child would not be."""
    versions = {}
    for recipe in recipes:
        file_id = recipe['mother']['fileId']
        if not file_id or file_id in versions:
            continue
        try:
            data_file = app.data.findFileById(file_id)
            versions[file_id] = data_file.versionNumber if data_file else None
        except Exception:
            versions[file_id] = None
    return versions


def survey_children(design):
    """Everything the Update dialog needs, resolved once.

    Each child's front direction is recovered from its own occurrence transform,
    because the face the user picked at fill time is not stored. That is exact for
    a box that moved or resized; a rotated box is detected by is_axis_aligned and
    reported rather than silently mis-measured.
    """
    children = find_children(design)
    slot_bodies = find_slot_bodies(design)
    versions = _current_versions([recipe for _occ, recipe in children.values()])

    rows = []
    for slot_id, (occurrence, recipe) in children.items():
        body = slot_bodies.get(slot_id)
        current = versions.get(recipe['mother']['fileId'])
        mother_found = current is not None
        dims = matrix = None
        rotated = False

        if body is not None:
            try:
                live = list(occurrence.transform2.asArray())
                frame = placeholder_core.frame_from_matrix(live)
                vertices = _body_vertices(body)
                rotated = not placeholder_core.is_axis_aligned(vertices, frame)
                if not rotated:
                    width, depth, height, centre = placeholder_core.extents_in_frame(
                        vertices, frame)
                    dims = (width, depth, height)
                    matrix = placeholder_core.occurrence_matrix(centre, frame)
            except Exception:
                body = None

        moved = bool(matrix) and placeholder_core.matrices_differ(
            matrix, list(occurrence.transform2.asArray()))
        rows.append({
            'occurrence': occurrence,
            'recipe': recipe,
            'body': body,
            'dims_cm': dims,
            'matrix': matrix,
            'name': occurrence.component.name,
            'status': placeholder_core.child_status(
                recipe, current, dims, moved, rotated,
                mother_found, body is not None),
        })
    rows.sort(key=lambda r: (r['recipe']['mother']['name'], r['name']))
    return rows
```

- [ ] **Step 2: Verify it compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/placeholder_cmds.py
python -m pyflakes SheetVariants/placeholder_cmds.py
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add SheetVariants/placeholder_cmds.py
git commit -m "feat: survey children against their mothers' versions and their boxes"
```

---

### Task 3: The `Update Children` dialog

**Files:**
- Modify: `SheetVariants/placeholder_cmds.py`

**Interfaces:**
- Consumes: `survey_children` (Task 2), `placeholder_core.status_label` (Task 1).
- Produces: `placeholder_cmds.UPDATE_CMD_ID = 'sheetVariantsUpdateChildrenCmd'`, and the dialog. This task shows the table and reports the selection on OK — it does **not** rebuild yet, so the survey can be verified on its own.

- [ ] **Step 1: Add the dialog**

Append to `SheetVariants/placeholder_cmds.py`:

```python
UPDATE_CMD_ID = 'sheetVariantsUpdateChildrenCmd'
UPDATE_CMD_NAME = 'Update Children'
UPDATE_CMD_DESC = ('Rebuild children whose mother model has moved on, or whose '
                   'placeholder box has been moved or resized.')

# The survey is resolved when the dialog opens and reused by the execute handler,
# so opening the dialog does its data-panel lookups exactly once.
_survey = []


def _mother_heading(row):
    recipe = row['recipe']
    stored = recipe['mother']['version']
    if row['status']['problem'] == 'mother not found':
        return '{} — missing'.format(recipe['mother']['name'] or '(unnamed)')
    if row['status']['staleness'] == placeholder_core.STALE_OUT_OF_DATE:
        return '{} — v{} is out of date'.format(recipe['mother']['name'], stored)
    return '{} — v{}'.format(recipe['mother']['name'], stored)


class UpdateCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = args.command
        inputs = cmd.commandInputs
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            inputs.addTextBoxCommandInput('err', '', 'Open a layout design first.',
                                          2, True)
            return

        global _survey
        _survey = survey_children(design)
        if not _survey:
            inputs.addTextBoxCommandInput(
                'err', '',
                'This design has no children yet. Run Fill Placeholders first.',
                2, True)
            return

        table = inputs.addTableCommandInput('children', 'Children', 4, '1:3:3:4')
        table.maximumVisibleRows = 14
        table.minimumVisibleRows = 6
        last_mother = None
        for index, row in enumerate(_survey):
            heading = _mother_heading(row)
            if heading != last_mother:
                last_mother = heading
                label = inputs.addTextBoxCommandInput(
                    'head{}'.format(index), '', '<b>{}</b>'.format(heading), 1, True)
                table.addCommandInput(label, table.rowCount, 0, 0, 3)

            tick = inputs.addBoolValueInput(
                'tick{}'.format(index), '', True, '', row['status']['tick'])
            tick.isEnabled = not row['status']['problem']
            name = inputs.addTextBoxCommandInput(
                'name{}'.format(index), '', row['name'], 1, True)
            config = inputs.addTextBoxCommandInput(
                'cfg{}'.format(index), '', row['recipe']['config'], 1, True)
            state = inputs.addTextBoxCommandInput(
                'st{}'.format(index), '',
                placeholder_core.status_label(row['status']), 1, True)
            table_row = table.rowCount
            table.addCommandInput(tick, table_row, 0)
            table.addCommandInput(name, table_row, 1)
            table.addCommandInput(config, table_row, 2)
            table.addCommandInput(state, table_row, 3)

        handler = UpdateExecuteHandler()
        cmd.execute.add(handler)
        _handlers.append(handler)
        cmd.setDialogInitialSize(560, 520)


def _ticked_rows(inputs):
    picked = []
    for index, row in enumerate(_survey):
        tick = inputs.itemById('tick{}'.format(index))
        if tick and tick.value and not row['status']['problem']:
            picked.append(row)
    return picked


class UpdateExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            picked = _ticked_rows(inputs)
            if not picked:
                ui.messageBox('Nothing ticked — nothing to update.')
                return
            ui.messageBox('DRY RUN — would rebuild:\n\n'
                          + '\n'.join('{} ({})'.format(r['name'],
                                                       placeholder_core.status_label(r['status']))
                                      for r in picked))
        except Exception:
            import traceback
            ui.messageBox('Update Children failed:\n' + traceback.format_exc())
```

- [ ] **Step 2: Register the command**

In `placeholder_cmds.register(panel)`, after the fill command is added:

```python
    update_existing = ui.commandDefinitions.itemById(UPDATE_CMD_ID)
    if update_existing:
        update_existing.deleteMe()
    update_definition = ui.commandDefinitions.addButtonDefinition(
        UPDATE_CMD_ID, UPDATE_CMD_NAME, UPDATE_CMD_DESC)
    update_handler = UpdateCreatedHandler()
    update_definition.commandCreated.add(update_handler)
    _handlers.append(update_handler)
    panel.controls.addCommand(update_definition)
```

And in `unregister()`, change the tuple to
`for cmd_id in (PREPARE_CMD_ID, FILL_CMD_ID, UPDATE_CMD_ID):`.

- [ ] **Step 3: Verify it compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/placeholder_cmds.py
python -m pyflakes SheetVariants/placeholder_cmds.py
```

Expected: no output.

- [ ] **Step 4: Verify the survey in Fusion** *(manual, user-run)*

Using a layout filled from two different mothers:

1. Run **Update Children** with nothing changed → every child reads `up to date`, none ticked.
2. Open one mother, change a parameter, **save it** (creating a new version), close it, re-run → only that mother's children read `out of date` and are ticked, grouped under a heading naming the mother and its stored version.
3. Move one placeholder box, re-run → that child reads `moved` and is ticked.
4. Resize one placeholder box, re-run → that child reads `resized` and is ticked.
5. **Rotate** one placeholder box 30° about Z, re-run → that child reads
   `rotated — re-run Fill Placeholders`, its tick box is **disabled**, and it is
   not pre-selected.
6. Delete one placeholder box, re-run → that child reads `placeholder missing` and is disabled.
7. Tick some, click OK → the dry-run message lists exactly what you ticked.

Report all seven. Do not tick this step otherwise.

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_cmds.py
git commit -m "feat: Update Children dialog groups children by mother and flags changes"
```

---

### Task 4: Execute the update

**Files:**
- Modify: `SheetVariants/placeholder_cmds.py`

**Interfaces:**
- Consumes: `placeholder_cmds.{_open_mother, _row_values, _snapshot_for, rebuild_child}` from Plan 1 Tasks 9 and 10; `survey_children` from Task 2.
- Produces: `placeholder_cmds.update_children(rows) -> list[str]` — one report line per child. Replaces the dry run.

- [ ] **Step 1: Add the executor**

Append to `SheetVariants/placeholder_cmds.py`:

```python
def update_children(rows):
    """Rebuild the given children, phased exactly as build_children is: everything
    needing a mother happens with that mother active, then the layout is
    reactivated once and every child is swapped in place.

    Children are grouped by mother so each mother is opened once, and by size
    within a mother so identical units share one recompute.
    """
    layout_doc = app.activeDocument
    import SheetVariants

    by_mother = {}
    for row in rows:
        by_mother.setdefault(row['recipe']['mother']['fileId'], []).append(row)

    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show('Updating children', 'Child %v of %m', 0, len(rows), 0)

    snapshots, versions, failures = {}, {}, []
    done = 0
    try:
        # Phase 1 — one mother at a time, layout in the background.
        for file_id, group in by_mother.items():
            mother = group[0]['recipe']['mother']
            try:
                doc, opened_by_us = _open_mother(file_id)
            except RuntimeError as err:
                failures.extend('{} — {}'.format(r['name'], err) for r in group)
                continue
            try:
                doc.activate()
                adsk.doEvents()
                mother_design = adsk.fusion.Design.cast(app.activeProduct)
                setup = read_mother_setup(mother_design)
                errors = placeholder_core.validate_mother_setup(setup)
                if errors:
                    failures.extend('{} — mother not prepared: {}'
                                    .format(r['name'], '; '.join(errors))
                                    for r in group)
                    continue
                versions[file_id] = doc.dataFile.versionNumber if doc.dataFile else None
                for row in group:
                    if progress.wasCancelled:
                        raise RuntimeError('Cancelled by user.')
                    recipe = row['recipe']
                    key = (file_id, recipe['config'],
                           tuple(round(v, 6) for v in row['dims_cm']))
                    if key in snapshots:
                        continue
                    try:
                        rows_url = recipe['sheetUrl'] or ''
                        sheet_rows = SheetVariants.get_rows(
                            rows_url, recipe['tab'] or None)
                        values = _row_values(sheet_rows, recipe['config'])
                        snapshots[key] = _snapshot_for(
                            mother_design, setup, values, row['dims_cm'])
                    except Exception as err:
                        failures.append('{} — {}'.format(row['name'], err))
            finally:
                if opened_by_us:
                    doc.close(False)
                adsk.doEvents()

        # Phase 2 — back in the layout, with every snapshot already in hand.
        layout_doc.activate()
        adsk.doEvents()
        design = adsk.fusion.Design.cast(app.activeProduct)
        tbm = adsk.fusion.TemporaryBRepManager.get()
        built_at = datetime.datetime.now().isoformat(timespec='seconds')
        report = []
        for row in rows:
            recipe = row['recipe']
            file_id = recipe['mother']['fileId']
            key = (file_id, recipe['config'],
                   tuple(round(v, 6) for v in row['dims_cm']))
            template = snapshots.get(key)
            if template is None:
                continue  # already recorded in failures
            snaps = [{'temp': tbm.copy(s['temp']), 'appearance': s['appearance'],
                      'material': s['material'], 'name': s['name']}
                     for s in template]
            report.append(rebuild_child(design, row['occurrence'], recipe,
                                        snaps, row['matrix']))
            updated = placeholder_core.new_child_recipe(
                slot_id=recipe['slotId'],
                mother={'fileId': file_id, 'name': recipe['mother']['name'],
                        'version': versions.get(file_id)},
                config=recipe['config'], sheet_url=recipe['sheetUrl'],
                tab=recipe['tab'], dims_cm=row['dims_cm'],
                bodies=[s['name'] for s in snaps], built_at=built_at)
            row['occurrence'].component.attributes.add(
                placeholder_core.ATTR_GROUP, placeholder_core.CHILD_RECIPE_ATTR,
                placeholder_core.dumps_attr(updated))
            done += 1
            progress.progressValue = done
    finally:
        progress.hide()
    return report + failures
```

- [ ] **Step 2: Replace the dry run**

In `UpdateExecuteHandler.notify`, replace the `ui.messageBox('DRY RUN …')` call with:

```python
            report = update_children(picked)
            ui.messageBox('\n'.join(report) if report else 'Nothing was updated.')
```

- [ ] **Step 3: Verify it compiles and lints**

Run:

```bash
python -m py_compile SheetVariants/placeholder_cmds.py
python -m pyflakes SheetVariants/placeholder_cmds.py SheetVariants/placeholder_core.py SheetVariants/build_engine.py
```

Expected: no output.

- [ ] **Step 4: Verify the update in Fusion** *(manual, user-run)*

The full loop, on a layout filled from two mothers, one child carrying a hand-made cut:

1. Change and **save** a mother. Run **Update Children** → its children are ticked. Click OK.
2. Confirm each rebuilt child shows the mother's new geometry.
3. Confirm the **hand-made cut survives** on the child that had one — or is flagged by Fusion as errored, which is acceptable. Silently vanishing is not.
4. Re-run **Update Children** immediately → everything now reads `up to date` and nothing is ticked. This proves the stored version was rewritten.
5. Move a box, update → the child moves; its hand-made cut moves with it, staying in the same place on the cabinet.
6. Confirm the other mother's children were **not** touched.
7. Reopen a mother and confirm its parameters are unchanged.
8. Start an update over several children and press **Cancel** midway → some children are updated and none are half-built.

Report on all eight, and say explicitly what happened to the hand-made cut in step 3. Do not tick this step otherwise.

- [ ] **Step 5: Commit**

```bash
git add SheetVariants/placeholder_cmds.py
git commit -m "feat: Update Children rebuilds picked children and records the new version"
```

---

### Task 5: Documentation and release

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `SheetVariants/SheetVariants.manifest`

- [ ] **Step 1: Bump the manifest version**

In `SheetVariants/SheetVariants.manifest`, change `"version": "1.14.0"` to `"version": "1.15.0"`.

- [ ] **Step 2: Add the CHANGELOG entry**

In `CHANGELOG.md`, directly below the `## Planned / ideas` section and above `## 1.14.0`, insert:

```markdown
## 1.15.0 — Update children

- **Update Children** — one dialog listing every child in the layout, grouped by
  its mother and showing that mother's stored version against its current one.
  Children whose mother has moved on, or whose placeholder box has been moved or
  resized, are flagged and pre-ticked; tick what to rebuild and go.
- Rebuilds go through the same in-place `updateBody()` path as a re-fill, so
  features added downstream of the generated geometry survive.
- Each mother is opened once per run, and identical boxes share one recompute.
- A child whose mother is missing, whose placeholder was deleted, or whose box
  has been **rotated** is reported and left unticked rather than silently
  rebuilt wrong — a rotated box needs its front face picking again, so it is
  sent back to **Fill Placeholders**.
```

- [ ] **Step 3: Extend the README**

In `README.md`, replace the section that begins `**4. Change your mind.**` with:

````markdown
**4. Change your mind.** Re-run **Fill Placeholders** on a box that already has a
child to give it a different config, or after rotating the box. The child is
rebuilt **in place**: features you added yourself — an extra cut, a fillet — are
recomputed against the new geometry rather than deleted with the old. When a change
breaks one of those references, Fusion marks that feature as errored in the usual
way.

**5. Keep up with the mother.** When you improve a mother model and save it, run
**Update Children** in the layout. It lists every child grouped by its mother,
compares the version each child was built from against the mother's current
version, and also flags boxes you have moved or resized. Tick what to rebuild.

```
Update children

  base-cabinet.f3d — v12 is out of date
    [x] B60_2drawer      Base_2drawer   out of date
    [x] B90_sink         Base_sink      out of date, resized
    [x] B60_corner       Base_2drawer   out of date, moved

  tall-unit.f3d — v3
    [ ] TALL_60          Tall_oven      up to date

  wall-unit.f3d — missing
    [ ] W80              Wall_2door     mother not found
```

Children that cannot be helped by rebuilding are shown but not selectable: a
missing mother, a deleted placeholder box, or a box that has been **rotated**.
A rotated box needs its front face choosing again, so run **Fill Placeholders**
on it instead.
````

- [ ] **Step 4: Verify everything passes**

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
git commit -m "docs: document Update Children and release 1.15.0"
```
