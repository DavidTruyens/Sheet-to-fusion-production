# cutlist_core.py
# Pure, Fusion-free logic for the cut list command. This module MUST NOT
# import adsk so it can be imported and unit-tested outside Fusion.
#
# The command's job is to report, for every part, the smallest rectangular
# blank it can be cut from: X and Y are the two larger sides (grown by the
# offset so there is material to machine away), Z is the smallest side left
# raw, because that is the stock thickness you filter on rather than something
# you cut.
#
# The blank is measured along the design's own axes. An earlier version
# searched for the smallest rotated blank instead; Spike 15 measured what that
# bought on a real assembly and the answer was 0.03% to 0.67% on seven parts
# whose ends happen to be slanted — each one trading more length for less
# width, and reporting lengths longer than the part measures on-axis. Parts are
# modelled and laid out square, so the search was paying for a case that does
# not arise. A part that IS sitting askew is reported instead, by is_tilted().

import math


def cm_to_mm(value):
    """Fusion's API works in centimetres; cut lists are read in millimetres."""
    return float(value) * 10.0


def format_mm(value):
    """A millimetre value as it appears in the CSV: always two decimals.

    Values are snapped to zero below half a displayed unit so a box that is
    flat in one direction cannot come out as "-0.00".
    """
    v = float(value)
    if abs(v) < 0.005:
        v = 0.0
    return '{:.2f}'.format(v)


def blank_dims(du, dv, dz, offset):
    """The blank for one part: (X, Y, Z) in millimetres, longest first.

    Sorting happens before the offset is applied, so the offset can never
    reorder the result — X and Y are the two larger sides of the part itself,
    each grown by ``offset`` on both of its sides, and Z is the part's
    smallest side, untouched.
    """
    longest, middle, shortest = sorted((float(du), float(dv), float(dz)), reverse=True)
    grow = 2.0 * float(offset)
    return (longest + grow, middle + grow, shortest)


def union_extents(boxes):
    """Extents of several boxes taken together, as (dx, dy, dz).

    Each box arrives as (x_centre, x_length, y_centre, y_length, z_centre,
    z_length) — the shape Fusion's oriented bounding box reduces to. A part
    made of several bodies is the span of all of them, which is why centres
    matter and lengths alone will not do.
    """
    if not boxes:
        return None
    lo = [float('inf')] * 3
    hi = [float('-inf')] * 3
    for xc, xl, yc, yl, zc, zl in boxes:
        for i, (centre, length) in enumerate(((xc, xl), (yc, yl), (zc, zl))):
            lo[i] = min(lo[i], centre - length / 2.0)
            hi[i] = max(hi[i], centre + length / 2.0)
    return (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])


def is_tilted(normal_z, tol_deg=0.5):
    """Whether a face's normal points neither straight up nor straight out.

    The blank is measured along the design's axes, so a part resting on a slope
    gets a blank larger than the part in every direction — and, worse, a Z that
    is not its thickness. Such a part is reported rather than silently
    mismeasured. Spike 15 saw this on a plank tilted until its 18 mm thickness
    read as 185 mm.
    """
    nz = min(1.0, max(0.0, abs(float(normal_z))))
    angle = math.degrees(math.acos(nz))
    return tol_deg < angle < (90.0 - tol_deg)


# --------------------------------------------------------------------------- #
# The cut list itself.
# --------------------------------------------------------------------------- #
HEADER = ['Name', 'X', 'Y', 'Z', 'Qty']


def group_parts(parts):
    """One row per distinct blank, from ``(name, x, y, z)`` millimetre parts.

    Grouping is done on the rounded text, not the raw floats, so two instances
    of the same component land in one row even though the measurement can put
    them a fraction of a micron apart. A name repeated inside a group is listed
    once — four identical legs read better as one word than as the same word
    four times — while the count still counts every instance.

    Rows come back longest blank first, the order you would work through them
    at the saw.
    """
    groups, order = {}, []
    for name, x, y, z in parts:
        key = (format_mm(x), format_mm(y), format_mm(z))
        group = groups.get(key)
        if group is None:
            group = groups[key] = {'names': [], 'qty': 0}
            order.append(key)
        if name not in group['names']:
            group['names'].append(name)
        group['qty'] += 1

    rows = [('; '.join(groups[key]['names']),) + key + (groups[key]['qty'],)
            for key in order]
    rows.sort(key=lambda row: (float(row[1]), float(row[2]), float(row[3])),
              reverse=True)
    return rows


def csv_rows(parts):
    """The finished CSV: a header, then one line per distinct blank."""
    rows = [list(HEADER)]
    for names, x, y, z, qty in group_parts(parts):
        rows.append([names, x, y, z, str(qty)])
    return rows
