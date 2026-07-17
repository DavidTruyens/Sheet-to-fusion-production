# sheet_core.py
# Pure, Fusion-free logic for the SheetVariants add-in. This module MUST NOT
# import adsk so it can be imported and unit-tested outside Fusion.

import re

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
