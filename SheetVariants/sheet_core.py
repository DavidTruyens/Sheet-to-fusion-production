# sheet_core.py
# Pure, Fusion-free logic for the SheetVariants add-in. This module MUST NOT
# import adsk so it can be imported and unit-tested outside Fusion.

import re
import io
import csv
import json
import zipfile
import xml.etree.ElementTree as ET

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
    rid = raw.get("id")
    return {
        "id": str(rid) if rid else fallback_id,
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
        normalized = []
        used_ids = []
        for p in profiles:
            prof = _normalize_profile(p if isinstance(p, dict) else {}, None)
            pid = prof["id"]
            if not pid or pid in used_ids:
                pid = next_profile_id(used_ids)
                prof["id"] = pid
            used_ids.append(pid)
            normalized.append(prof)
        data["profiles"] = normalized
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


def select_component_names(present, targets):
    """Split target component names into (included, missing) against the names
    present in the design, preserving the order of ``targets``."""
    present_set = set(present or [])
    included, missing = [], []
    for name in (targets or []):
        (included if name in present_set else missing).append(name)
    return included, missing


def summarize_results(results):
    """Build the end-of-run message box text from per-profile result dicts."""
    lines = []
    built = [r for r in results if not r.get("skipped")]
    if built:
        lines.append("Built:")
        for r in built:
            # Variants dropped by their component toggles are reported, never
            # silent: a variant missing from an output design with no
            # explanation reads as a bug in the add-in.
            notes = list(r.get("warnings") or [])
            dropped = r.get("skipped_variants") or []
            if dropped:
                notes.append("{} variant(s) had nothing to build: {}".format(
                    len(dropped), ", ".join(dropped)))
            warn = (" — " + "; ".join(notes)) if notes else ""
            lines.append("  • {} ({} variant(s)){}".format(r.get("name", "Export"),
                                                           r.get("built", 0), warn))
    skipped = [r for r in results if r.get("skipped")]
    if skipped:
        lines.append("Skipped:")
        for r in skipped:
            reason = "; ".join(r["warnings"]) if r.get("warnings") else "nothing to export"
            lines.append("  • {} — {}".format(r.get("name", "Export"), reason))
    return "\n".join(lines) if lines else "Nothing was built."


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKGREL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def extract_spreadsheet_id(url):
    """Return the /d/<id>/ spreadsheet id, or None for published /d/e/ links
    and anything that is not a standard Sheets URL."""
    url = (url or "").strip()
    if re.search(r"/spreadsheets/d/e/", url):
        return None  # published-to-web: different id space, no xlsx export
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else None


def xlsx_export_url(spreadsheet_id):
    return ("https://docs.google.com/spreadsheets/d/{}/export?format=xlsx"
            .format(spreadsheet_id))


def parse_workbook_tabs(xlsx_bytes):
    """Return worksheet (tab) names in workbook order."""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = []
    for sheet in wb.findall(".//{%s}sheet" % _MAIN_NS):
        name = sheet.get("name")
        if name:
            names.append(name)
    return names


def normalize_number(text):
    """Render a spreadsheet number without a spurious trailing zero/dot.
    Leaves non-numeric text untouched."""
    try:
        f = float(text)
    except (TypeError, ValueError):
        return text
    if f == int(f):
        return str(int(f))
    return repr(f).rstrip("0").rstrip(".") if "." in str(f) else str(f)


def _col_index(cell_ref):
    """'A1' -> 0, 'B2' -> 1, 'AA3' -> 26."""
    letters = re.match(r"[A-Z]+", cell_ref or "")
    if not letters:
        return 0
    idx = 0
    for ch in letters.group(0):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _shared_strings(z):
    try:
        sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in sst.findall("{%s}si" % _MAIN_NS):
        out.append("".join(t.text or "" for t in si.iter("{%s}t" % _MAIN_NS)))
    return out


def _worksheet_path_for(z, tab_name):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rid = None
    for sheet in wb.findall(".//{%s}sheet" % _MAIN_NS):
        if sheet.get("name") == tab_name:
            rid = sheet.get("{%s}id" % _REL_NS)
            break
    if rid is None:
        raise RuntimeError('Tab "{}" was not found in the sheet.'.format(tab_name))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("{%s}Relationship" % _PKGREL_NS):
        if rel.get("Id") == rid:
            target = rel.get("Target")
            return target if target.startswith("xl/") else "xl/" + target
    raise RuntimeError('Could not locate data for tab "{}".'.format(tab_name))


def read_tab_rows(xlsx_bytes, tab_name):
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
        strings = _shared_strings(z)
        path = _worksheet_path_for(z, tab_name)
        sheet = ET.fromstring(z.read(path))

    parsed_rows = []
    sheet_maxcol = -1
    for row_el in sheet.findall(".//{%s}row" % _MAIN_NS):
        cells = {}
        for c in row_el.findall("{%s}c" % _MAIN_NS):
            j = _col_index(c.get("r", ""))
            t = c.get("t")
            if t == "inlineStr":
                is_el = c.find("{%s}is" % _MAIN_NS)
                val = "".join(x.text or "" for x in is_el.iter("{%s}t" % _MAIN_NS)) if is_el is not None else ""
            else:
                v = c.find("{%s}v" % _MAIN_NS)
                raw = v.text if v is not None else ""
                if t == "s":
                    val = strings[int(raw)] if raw != "" else ""
                elif t in (None, "n"):
                    val = normalize_number(raw)
                else:  # 'str' (formula), 'b', etc.
                    val = raw or ""
            cells[j] = val
            if j > sheet_maxcol:
                sheet_maxcol = j
        parsed_rows.append(cells)

    # Pad every row to the sheet's overall width (not just this row's own
    # highest cell) so a trailing blank cell that was omitted from the XML
    # (e.g. a gap in the last column) still comes back as "" rather than
    # silently shortening the row.
    rows = []
    for cells in parsed_rows:
        row = [cells.get(j, "") for j in range(sheet_maxcol + 1)]
        if any(v.strip() for v in row):
            rows.append(row)
    return rows


_COMMA_DECIMAL = re.compile(r"^\s*[+-]?\d+,\d+\s*$")
_UNITLESS = re.compile(r"^\s*[+-]?\d+(\.\d+)?\s*$")


def classify_value(text):
    s = (text or "").strip()
    if s == "":
        return "empty"
    if _COMMA_DECIMAL.match(s):
        return "comma_decimal"
    if _UNITLESS.match(s):
        return "unitless"
    return "ok"


TOGGLE_ON = ("true", "1", "yes", "y", "on")
TOGGLE_OFF = ("false", "0", "no", "n", "off")


def parse_toggle(text):
    """Read a component on/off cell.

    Returns True (component stays in), False (component is dropped for this
    variant), or None for a value that is neither — which the caller must
    report as an error rather than guess at. A blank cell returns True,
    matching the existing rule that a blank parameter cell leaves things
    unchanged; the alternative would make adding a column to a long sheet
    mean editing every row.

    None is deliberately distinct from False. A typo that silently meant
    "off" would be invisible in the output, because a missing part looks
    exactly like a part you meant to remove.
    """
    s = (text or "").strip().lower()
    if s == "":
        return True
    if s in TOGGLE_ON:
        return True
    if s in TOGGLE_OFF:
        return False
    return None


def classify_columns(header, param_names, top_level_names, all_component_names=()):
    """Decide what each header column after "Name" means, against the model.

    A header is a parameter column, a component on/off column, or a problem.
    Precedence is deliberate: a name that is BOTH a parameter and a top-level
    component is read as a parameter, so no sheet that worked before this
    feature can change meaning. The collision is reported so the designer is
    not left guessing which way it went.

    A header naming a component that exists but is not top-level is separated
    from a header naming nothing at all, because they need different advice:
    one is "this cannot be switched off", the other is "this is a typo".

    Column indices are into the ROW, so column A ("Name") is 0 and the first
    header after it is 1. That is what row_toggles and the build loop index
    with, so no caller has to remember an offset.
    """
    params = set(param_names or ())
    top_level = set(top_level_names or ())
    all_components = set(all_component_names or ()) | top_level

    out = {"parameters": [], "toggles": [], "unknown": [],
           "sub_components": [], "collisions": []}
    for index, raw in enumerate(header or []):
        if index == 0:
            continue                      # column A is the variant name
        name = (raw or "").strip()
        if not name:
            # A column with data but no header is reported, not skipped. Today's
            # validate_mapping errors on it, and a column you filled in that
            # quietly does nothing is invisible in the output.
            out["unknown"].append(name)
            continue
        if name in params:
            out["parameters"].append((index, name))
            if name in top_level:
                out["collisions"].append(name)
        elif name in top_level:
            out["toggles"].append((index, name))
        elif name in all_components:
            out["sub_components"].append(name)
        else:
            out["unknown"].append(name)
    return out


def row_toggles(row, toggle_columns):
    """{component name: is it in} for one variant row.

    A cell the row does not reach is treated as blank (component stays in):
    a spreadsheet often omits trailing empty cells entirely, and the parameter
    path already treats a short row the same way.

    An unrecognised value also keeps the component. validate_mapping blocks
    the build before a build can ever see one, so this is a defensive default
    rather than a rule — and it fails toward the recoverable direction, since
    an unwanted part is visible in the output while a missing one is not.

    Keyed by component name, so if the same component is named by two columns
    the rightmost wins.
    """
    out = {}
    for index, name in toggle_columns or []:
        raw = row[index] if index < len(row) else ""
        value = parse_toggle(raw)
        out[name] = True if value is None else value
    return out


def config_plan(header, row, model_name, param_names, top_level_names,
                all_component_names=()):
    """What one config row means for one model: values to drive, components to
    leave out, and any reason to refuse.

    Fill Placeholders and Update Children both need exactly this, and both used
    to work it out themselves by checking every column against the model's
    parameters. Only the Build Variants path learned about component columns, so
    a column naming a component to switch off read as a parameter that does not
    exist and aborted the whole run. Sharing one function is the point: the two
    placeholder commands drifted apart precisely because the rule lived in three
    places.

    Returns ``errors`` rather than raising, so a caller that validates one child
    among many can fail that child alone. Every problem is reported at once —
    fixing a sheet one error per run is miserable.
    """
    cols = classify_columns(header, param_names, top_level_names,
                            all_component_names)
    errors = []

    # classify_columns files a BLANK header under "unknown" alongside a typo,
    # which is right for the Build dialog's Check (it reports one column at a
    # time and can say "column F has no header"). Joined into one message here
    # it would read "...in "mother1": " and name nothing. Worse, read_tab_rows
    # pads every row out to the tab's widest column, so a stray note beside the
    # table gives the header row trailing blanks — which would abort sheets that
    # have no component columns at all and worked perfectly before. So an empty
    # column is ignored, and a blank header is only reported when this row
    # actually has data under it, named by its spreadsheet letter.
    named_unknown = [name for name in cols["unknown"] if name]
    if named_unknown:
        errors.append('These columns do not match any parameter or top-level '
                      'component in "{}": {}'.format(
                          model_name, ", ".join(named_unknown)))
    headless = [_cell_ref(index, "")
                for index, raw in enumerate(header or [])
                if index > 0 and not (raw or "").strip()
                and index < len(row or []) and (row[index] or "").strip()]
    if headless:
        errors.append('These columns in "{}" have data but no header: {}'.format(
            model_name, ", ".join(headless)))

    if cols["sub_components"]:
        errors.append('These columns name sub-components of "{}", which cannot '
                      'be switched on or off: {}'.format(
                          model_name, ", ".join(cols["sub_components"])))

    # row_toggles collapses parse_toggle's three-valued answer to two, keeping
    # the component on whatever the cell says. Its docstring justifies that with
    # "validate_mapping blocks the build before a build can ever see one" — true
    # of the Build dialog, false here: nothing validates a sheet before Fill
    # Placeholders or Update Children read it. So the cells are re-read for the
    # one case that matters. A typo silently meaning "keep" would build a child
    # WITH a part the designer switched off and report it as a success, which is
    # exactly the "looks accepted, does nothing" outcome this whole change set
    # exists to remove.
    unreadable = ['{} ("{}")'.format(name, (row[index] if index < len(row) else ""))
                  for index, name in cols["toggles"]
                  if parse_toggle(row[index] if index < len(row) else "") is None]
    if unreadable:
        errors.append('These on/off cells in "{}" are not yes/no values: {}'
                      .format(model_name, ", ".join(unreadable)))

    values = {name: (row[index].strip() if index < len(row) else "")
              for index, name in cols["parameters"]}
    toggles = row_toggles(row, cols["toggles"])
    return {"values": values,
            "off_names": sorted(n for n, keep in toggles.items() if not keep),
            "errors": errors,
            "collisions": cols["collisions"]}


def _cell_ref(col_index, row_number):
    letters = ""
    n = col_index + 1
    while n:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return "{}{}".format(letters, row_number)


class ValidationReport:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.mapped_columns = 0
        self.toggle_columns = 0
        self.row_count = 0

    @property
    def ok(self):
        return not self.errors

    def summary(self):
        # The on/off clause is omitted entirely when there are none, so a
        # sheet with no toggle columns produces the exact string it always did.
        toggles = ", {} on/off".format(self.toggle_columns) if self.toggle_columns else ""
        if self.ok and not self.warnings:
            return "✓ {} columns mapped{}, {} rows OK".format(
                self.mapped_columns, toggles, self.row_count)
        if self.ok:
            return "✓ {} columns mapped{}, {} rows — {} warning(s)".format(
                self.mapped_columns, toggles, self.row_count, len(self.warnings))
        return "✗ {} error(s), {} warning(s) — fix before building".format(
            len(self.errors), len(self.warnings))

    def to_html(self):
        lines = ["<b>{}</b>".format(self.summary())]
        for e in self.errors:
            lines.append('<font color="#c0392b">✗ {}</font>'.format(e))
        for w in self.warnings:
            lines.append('<font color="#b9770e">⚠ {}</font>'.format(w))
        return "<br/>".join(lines)


def validate_mapping(header, rows, known_param_names, driveable_param_names,
                     top_level_names=(), all_component_names=()):
    rep = ValidationReport()
    rep.row_count = len(rows)
    header = [h.strip() for h in header]

    if not header or header[0] != "Name":
        rep.errors.append('The first column header must be "Name".')
        return rep

    cols = classify_columns(header, known_param_names, top_level_names,
                            all_component_names)
    rep.mapped_columns = len(cols["parameters"])
    rep.toggle_columns = len(cols["toggles"])

    # Every unknown entry becomes an error, INCLUDING the empty string that a
    # blank header contributes. That is deliberate: a column with data but no
    # header errored before component columns existed and must keep erroring.
    # Skipping empty names here would silently let it through.
    for name in cols["unknown"]:
        rep.errors.append(
            'Column "{}" matches no parameter or top-level component in the model.'
            .format(name))
    for name in cols["sub_components"]:
        rep.errors.append(
            'Column "{}" is a sub-component — only top-level components can be '
            'switched on or off.'.format(name))
    for name in cols["collisions"]:
        rep.warnings.append(
            'Column "{}" is both a parameter and a component — read as a parameter.'
            .format(name))

    covered = set(name for _, name in cols["parameters"])
    for pname in driveable_param_names:
        if pname not in covered:
            rep.warnings.append(
                'Parameter "{}" has no column — keeps its current value.'.format(pname))

    empty_count = 0
    blank_toggles = 0
    for ri, row in enumerate(rows, start=2):  # row 2 = first data row in the sheet
        for ci, name in cols["parameters"]:
            val = row[ci] if ci < len(row) else ""
            kind = classify_value(val)
            if kind == "comma_decimal":
                rep.errors.append(
                    'Cell {} ("{}") looks like a comma decimal — use a dot and a unit, e.g. "18.2 mm".'
                    .format(_cell_ref(ci, ri), val.strip()))
            elif kind == "empty":
                empty_count += 1
        for ci, name in cols["toggles"]:
            val = row[ci] if ci < len(row) else ""
            if not (val or "").strip():
                blank_toggles += 1
            elif parse_toggle(val) is None:
                rep.errors.append(
                    'Cell {} ("{}") is not a yes/no value — use TRUE or FALSE.'
                    .format(_cell_ref(ci, ri), val.strip()))
    if empty_count:
        rep.warnings.append("{} empty cell(s) left unchanged.".format(empty_count))
    if blank_toggles:
        rep.warnings.append(
            "{} blank on/off cell(s) — those components stay in.".format(blank_toggles))
    return rep


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
