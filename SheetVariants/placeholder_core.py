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
