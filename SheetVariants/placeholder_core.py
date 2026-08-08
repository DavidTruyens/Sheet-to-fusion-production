# placeholder_core.py
# Pure, Fusion-free logic for the placeholder-instantiation feature: attribute
# schemas, frame construction, extents, matrices and body pairing. This module
# MUST NOT import adsk so it can be imported and unit-tested outside Fusion.
#
# Kept separate from sheet_core.py deliberately: that module is about reading
# Google Sheets, this one is about geometry and stored schemas.

import json
import uuid

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
