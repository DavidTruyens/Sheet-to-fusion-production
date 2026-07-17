# sheet_core.py
# Pure, Fusion-free logic for the SheetVariants add-in. This module MUST NOT
# import adsk so it can be imported and unit-tested outside Fusion.

import re
import io
import csv
import json

SHARING_HELP = (
    'Make sure the sheet is shared so anyone with the link can read it: in Google '
    'Sheets, Share > General access > "Anyone with the link" > Viewer. '
    '(Or publish it: File > Share > Publish to web.) Then paste that link here.')


def csv_url_candidates(url):
    """Turn a share / edit / publish link into one or more CSV-export links.

    Uses the ``/export?format=csv`` endpoint, which returns cell values exactly
    as typed. For sheets shared as "anyone with the link", supplying a ``gid``
    makes the signed redirect fail with HTTP 400, so the default first tab is
    requested without a gid; a gid is only added when the link explicitly points
    at a non-first tab.
    """
    url = url.strip()
    if 'output=csv' in url or 'format=csv' in url:
        return [url]
    if re.search(r'/spreadsheets/d/e/[^/]+/pub', url):
        sep = '&' if '?' in url else '?'
        return [url + sep + 'output=csv']
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    if m:
        sheet_id = m.group(1)
        base = 'https://docs.google.com/spreadsheets/d/{}/export?format=csv'.format(sheet_id)
        gid_match = re.search(r'[#&?]gid=(\d+)', url)
        gid = gid_match.group(1) if gid_match else None
        if gid and gid != '0':
            return [base + '&gid=' + gid, base]
        return [base]
    return [url]


def parse_sheet_csv(raw):
    """Parse downloaded CSV text into a list of non-empty rows.

    Raises RuntimeError if the text looks like an HTML page (usually a sign-in
    wall) or does not contain at least a header plus one data row.
    """
    head = raw.lstrip()[:200].lower()
    if head.startswith('<!doctype html') or '<html' in head:
        raise RuntimeError(
            'That URL returned a web page instead of CSV, which usually means the '
            'sheet is not readable without signing in.\n\n' + SHARING_HELP)
    rows = [r for r in csv.reader(io.StringIO(raw)) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise RuntimeError('The sheet needs a header row plus at least one variant row.')
    return rows


def unquote_text(expression):
    """Strip surrounding single/double quotes from a text-parameter expression
    (e.g. 'A-6' -> A-6). Leaves numeric expressions like '50 mm' untouched and
    passes None through unchanged."""
    s = (expression or '').strip()
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    return expression


VALID_RULES = ("whole_model", "named_components")


def default_profiles():
    return [{"id": "p1", "name": "Full model", "enabled": True,
             "rule": "whole_model", "components": []}]


def _normalize_profile(raw, fallback_id):
    raw = raw if isinstance(raw, dict) else {}
    rule = raw.get("rule") if raw.get("rule") in VALID_RULES else "whole_model"
    comps = [str(c).strip() for c in (raw.get("components") or []) if str(c).strip()]
    return {
        "id": str(raw.get("id") or fallback_id),
        "name": str(raw.get("name") or "Export"),
        "enabled": bool(raw.get("enabled", True)),
        "rule": rule,
        "components": comps,
    }


def migrate_settings(data):
    """Return a copy of the settings dict with a well-formed 'profiles' list.
    Missing/empty profiles yield the single default whole-model profile so
    upgrading users reproduce today's behaviour exactly."""
    data = dict(data or {})
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        data["profiles"] = default_profiles()
    else:
        data["profiles"] = [_normalize_profile(p, "p%d" % (i + 1))
                            for i, p in enumerate(profiles)]
    return data


def load_settings(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    return migrate_settings(data)


def save_settings(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def next_profile_id(existing_ids):
    existing = set(existing_ids or [])
    n = 1
    while ("p%d" % n) in existing:
        n += 1
    return "p%d" % n
