# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""Put each port's cross-reference at the port's free end.

With the project's Port Cross References option on, Altium draws a port's
"Sheet[1B]" reference as a ``CrossRef`` parameter beside the end it treats as
unwired. A port moved while it had no wire keeps whichever end it had, so
after a block move the reference can sit on the wire, or run off the sheet,
and neither a compile nor a nudge puts it back. On the Rosen controller
(2026-10-26) the only fix was a byte edit of the closed file.

The reference is just a parameter: Location (end of the port, 20 mil out,
at the port's Y) and Justification (3 = text runs right from the anchor,
5 = text runs left). Both are writable, so the fix is two property writes
per port once the wired end is known. Altium's own answer to that is the
port's ConnectedEnd (1 origin, 2 extremity), which it derives from the
wiring and does not let a script set; the wire geometry here is the
fallback when it reads 0 or 3, and a cross-check otherwise. The planning is
pure, so it can be tested without Altium; ``sch_fix_port_crossrefs`` reads
the sheet and applies the plan.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

#: Gap Altium leaves between the port end and its reference, in mils.
CROSSREF_OFFSET = 20.0
#: Justification values of a CrossRef parameter.
JUST_RUNS_RIGHT = 3
JUST_RUNS_LEFT = 5
#: ISch_Port.ConnectedEnd values.
CONNECTED_NONE, CONNECTED_ORIGIN, CONNECTED_EXTREMITY, CONNECTED_BOTH = 0, 1, 2, 3
#: Port styles whose body runs along X (none, left, right, left_right).
HORIZONTAL_STYLES = {0, 1, 2, 3}
#: How far a reference may sit from its exact place and still count as at
#: the right end. Altium puts it exactly 20 mil out; one moved by hand onto
#: the 10 mil grid is a few mil off, which nobody can see.
PLACE_TOLERANCE = 10.0
#: Average glyph advance of Arial 7 on a schematic, mils per character.
#: Measured off the Rosen sheets; only used to warn, never to place.
ARIAL7_CHAR_MILS = 31.0

#: Sheet frame sizes in mils, as Altium's sheet styles define them.
SHEET_SIZES = {
    "A": (9500, 7500), "B": (15000, 9500), "C": (20000, 15000),
    "D": (32000, 20000), "E": (42000, 32000),
    "A4": (11500, 7600), "A3": (15500, 11100), "A2": (22300, 15700),
    "A1": (31500, 22300), "A0": (44600, 31500),
}
#: Width of the zone border inside the sheet frame, in mils.
ZONE_BORDER = 200


def _num(obj: dict, key: str) -> Optional[float]:
    try:
        return float(obj.get(key))
    except (TypeError, ValueError):
        return None


def _segments(wires: Iterable[dict]) -> list[tuple[float, float, float, float]]:
    """Wire segments from obj_query ``Vertices`` dumps (``x1,y1;x2,y2;...``)."""
    segs = []
    for w in wires:
        pts = []
        for pair in str(w.get("Vertices", "")).split(";"):
            xy = pair.split(",")
            if len(xy) != 2:
                continue
            try:
                pts.append((float(xy[0]), float(xy[1])))
            except ValueError:
                continue
        segs.extend((a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))
    return segs


def _on_segment(x: float, y: float, seg: tuple[float, float, float, float],
                tol: float = 0.5) -> bool:
    x1, y1, x2, y2 = seg
    if not (min(x1, x2) - tol <= x <= max(x1, x2) + tol
            and min(y1, y2) - tol <= y <= max(y1, y2) + tol):
        return False
    # Distance from the line, scaled by the segment length.
    cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
    length = max(abs(x2 - x1), abs(y2 - y1), 1e-9)
    return abs(cross) / length <= tol


def _touched(x: float, y: float, segs, points) -> bool:
    if any(abs(px - x) <= 0.5 and abs(py - y) <= 0.5 for px, py in points):
        return True
    return any(_on_segment(x, y, s) for s in segs)


def border_for(sheet_size: str, width: float = 0, height: float = 0
               ) -> Optional[tuple[float, float]]:
    """The x range inside the zone border, or None for an unknown sheet."""
    size = SHEET_SIZES.get(str(sheet_size).strip().upper())
    w = size[0] if size else width
    if not w:
        return None
    return (ZONE_BORDER, w - ZONE_BORDER)


def plan_crossref_fixes(
    ports: list[dict],
    wires: list[dict],
    crossrefs: list[dict],
    pins: Iterable[dict] = (),
    x_range: Optional[tuple[float, float]] = None,
    char_mils: float = ARIAL7_CHAR_MILS,
) -> dict[str, Any]:
    """Work out where each horizontal port's reference belongs.

    ``ports``: obj_query ePort rows (Name, Location.X, Location.Y, Width,
    Style). ``wires``: eWire rows with Vertices. ``crossrefs``: eParameter
    rows named CrossRef (Text, Location.X, Location.Y, Justification).
    ``pins``: optional ePin rows with ConnectionX/ConnectionY, for a port
    sitting directly on a pin.

    Returns ``moves`` (one per reference at the wrong end), ``ok``,
    ``unresolved`` (neither or both ends wired, or no reference found) and
    ``off_sheet`` (a reference whose text, at ``char_mils`` per character,
    runs past ``x_range``).
    """
    segs = _segments(wires)
    points = [(float(p["ConnectionX"]), float(p["ConnectionY"]))
              for p in pins
              if _num(p, "ConnectionX") is not None
              and _num(p, "ConnectionY") is not None]
    refs = [r for r in crossrefs
            if _num(r, "Location.X") is not None
            and _num(r, "Location.Y") is not None]
    used: set[int] = set()
    moves, ok, unresolved, off_sheet = [], [], [], []

    for port in ports:
        name = str(port.get("Name", ""))
        x0, y, width = (_num(port, "Location.X"), _num(port, "Location.Y"),
                        _num(port, "Width"))
        style = int(_num(port, "Style") or 0)
        if x0 is None or y is None or not width:
            unresolved.append({"port": name, "reason": "no location or width"})
            continue
        if style not in HORIZONTAL_STYLES:
            unresolved.append({"port": name, "reason": "vertical port, not handled"})
            continue
        x1 = x0 + width

        # The reference on this port's row nearest either end.
        best, best_d = None, None
        for i, r in enumerate(refs):
            if i in used or abs(float(r["Location.Y"]) - y) > 1:
                continue
            rx = float(r["Location.X"])
            if not (x0 - 4 * CROSSREF_OFFSET <= rx <= x1 + 4 * CROSSREF_OFFSET):
                continue
            d = min(abs(rx - (x0 - CROSSREF_OFFSET)), abs(rx - (x1 + CROSSREF_OFFSET)))
            if best_d is None or d < best_d:
                best, best_d = i, d
        if best is None:
            unresolved.append({"port": name, "reason": "no CrossRef on this port"})
            continue
        used.add(best)
        ref = refs[best]

        # Altium's own answer first; the geometry when it has none.
        wire_left = _touched(x0, y, segs, points)
        wire_right = _touched(x1, y, segs, points)
        altium = _num(port, "ConnectedEnd")
        altium = int(altium) if altium is not None else None
        if altium in (CONNECTED_ORIGIN, CONNECTED_EXTREMITY):
            left = altium == CONNECTED_ORIGIN
            source = "ConnectedEnd"
        elif wire_left != wire_right:
            left = wire_left
            source = "wires"
        else:
            unresolved.append({
                "port": name,
                "reason": ("both ends wired" if wire_left or altium == CONNECTED_BOTH
                           else "neither end wired"),
                "connected_end": altium,
                "crossref_x": ref["Location.X"]})
            continue

        if left:     # wired at the origin, reference at the extremity
            want_x, want_j, end = x1 + CROSSREF_OFFSET, JUST_RUNS_RIGHT, CONNECTED_ORIGIN
        else:
            want_x, want_j, end = x0 - CROSSREF_OFFSET, JUST_RUNS_LEFT, CONNECTED_EXTREMITY
        have_x = float(ref["Location.X"])
        have_j = int(_num(ref, "Justification") or 0)
        row = {"port": name, "port_x": port["Location.X"],
               "port_y": port["Location.Y"], "width": width,
               "wired_end": "left" if left else "right",
               "decided_by": source,
               "connected_end": end,
               "from_x": ref["Location.X"], "from_y": ref["Location.Y"],
               "from_justification": have_j,
               "to_x": round(want_x, 4), "to_justification": want_j,
               "text": ref.get("Text", "")}

        length = len(str(ref.get("Text", ""))) * char_mils
        if x_range is not None:
            lo, hi = x_range
            if want_j == JUST_RUNS_RIGHT and want_x + length > hi:
                off_sheet.append({**row, "runs_to_x": round(want_x + length), "border_x": hi})
            elif want_j == JUST_RUNS_LEFT and want_x - length < lo:
                off_sheet.append({**row, "runs_to_x": round(want_x - length), "border_x": lo})

        if abs(have_x - want_x) <= PLACE_TOLERANCE and have_j == want_j:
            ok.append(row)
        else:
            moves.append(row)

    return {"moves": moves, "ok": ok, "unresolved": unresolved,
            "off_sheet": off_sheet,
            "unmatched_crossrefs": len(refs) - len(used)}
