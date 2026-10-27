# SPDX-License-Identifier: Apache-2.0
"""sch_fix_port_crossrefs: a port's reference belongs at its unwired end.

Found on the Rosen controller (2026-10-26): ports moved while unwired kept
their cross-references at the end that was then wired, and one ran off the
sheet. Neither a compile nor nudging the port moved them back; the fix was
a byte edit of the closed file. The reference is a CrossRef parameter whose
Location and Justification are writable, so the tool plans the two writes.
"""
from __future__ import annotations

import pytest

from eda_agent.tools.port_crossrefs import (
    CONNECTED_EXTREMITY,
    CONNECTED_ORIGIN,
    JUST_RUNS_LEFT,
    JUST_RUNS_RIGHT,
    border_for,
    plan_crossref_fixes,
)


def _port(name, x, y, width, style=2, connected_end=None):
    row = {"Name": name, "Location.X": x, "Location.Y": y,
           "Width": width, "Style": style}
    if connected_end is not None:
        row["ConnectedEnd"] = connected_end
    return row


def _ref(x, y, j, text="Rosen EShade Controller[1B]"):
    return {"Name": "CrossRef", "Text": text, "Location.X": x,
            "Location.Y": y, "Justification": j}


def _wire(*pts):
    return {"Vertices": ";".join(f"{x},{y}" for x, y in pts)}


def test_reference_on_the_wired_left_end_moves_right():
    """The PCI_PWR case: wired at its origin, reference drawn there."""
    plan = plan_crossref_fixes(
        [_port("PCI_PWR", 13300, 2800, 484.68)],
        [_wire((13200, 2800), (13300, 2800))],
        [_ref(13280, 2800, JUST_RUNS_LEFT)])
    assert len(plan["moves"]) == 1
    m = plan["moves"][0]
    assert m["wired_end"] == "left"
    assert m["to_x"] == pytest.approx(13300 + 484.68 + 20)
    assert m["to_justification"] == JUST_RUNS_RIGHT
    assert m["connected_end"] == CONNECTED_ORIGIN
    # The filter values are the ones the query returned, unchanged.
    assert (m["from_x"], m["from_y"]) == (13280, 2800)


def test_reference_on_the_wired_right_end_moves_left():
    plan = plan_crossref_fixes(
        [_port("LED_IPC_RED", 7300, 1300, 600)],
        [_wire((7900, 1300), (8100, 1300), (8100, 1500))],
        [_ref(7920, 1300, JUST_RUNS_RIGHT)])
    m = plan["moves"][0]
    assert m["wired_end"] == "right"
    assert m["to_x"] == pytest.approx(7280)
    assert m["to_justification"] == JUST_RUNS_LEFT
    assert m["connected_end"] == CONNECTED_EXTREMITY


def test_a_reference_already_in_place_is_left_alone():
    plan = plan_crossref_fixes(
        [_port("PCI_PWR_nFAULT", 11200, 3000, 752)],
        [_wire((10900, 3000), (11200, 3000))],
        [_ref(11972, 3000, JUST_RUNS_RIGHT)])
    assert plan["moves"] == []
    assert [r["port"] for r in plan["ok"]] == ["PCI_PWR_nFAULT"]


def test_a_reference_a_few_mil_off_is_at_the_right_end():
    """PCI_PWR after its byte edit: 13800, Altium would say 13804.68."""
    plan = plan_crossref_fixes(
        [_port("PCI_PWR", 13300, 2800, 484.68, connected_end=CONNECTED_ORIGIN)],
        [], [_ref(13800, 2800, JUST_RUNS_RIGHT)])
    assert plan["moves"] == [] and len(plan["ok"]) == 1


def test_a_wire_running_through_the_end_counts_as_wired():
    """The end sits mid-segment, not on a vertex."""
    plan = plan_crossref_fixes(
        [_port("A", 1000, 500, 400)],
        [_wire((800, 500), (1200, 500)), _wire((1000, 300), (1000, 700))],
        [_ref(980, 500, JUST_RUNS_LEFT)])
    assert plan["moves"][0]["wired_end"] == "left"


def test_a_port_on_a_pin_counts_as_wired():
    plan = plan_crossref_fixes(
        [_port("B", 1000, 500, 400)], [],
        [_ref(1420, 500, JUST_RUNS_RIGHT)],
        pins=[{"ConnectionX": 1400, "ConnectionY": 500}])
    assert plan["moves"][0]["wired_end"] == "right"


def test_altiums_connected_end_wins_over_the_geometry():
    """A port wired through something the geometry does not see (here
    nothing at all) still gets its reference moved, by ConnectedEnd."""
    plan = plan_crossref_fixes(
        [_port("V_IN_ACBUS_28V", 1400, 8250, 700, style=0,
               connected_end=CONNECTED_EXTREMITY)],
        [], [_ref(2120, 8250, JUST_RUNS_RIGHT)])
    m = plan["moves"][0]
    assert m["wired_end"] == "right" and m["decided_by"] == "ConnectedEnd"
    assert m["to_justification"] == JUST_RUNS_LEFT


def test_the_geometry_decides_when_altium_says_none():
    plan = plan_crossref_fixes(
        [_port("A", 1000, 500, 400, connected_end=0)],
        [_wire((900, 500), (1000, 500))], [_ref(980, 500, JUST_RUNS_LEFT)])
    assert plan["moves"][0]["decided_by"] == "wires"


@pytest.mark.parametrize("wires,reason", [
    ([], "neither end wired"),
    ([_wire((900, 500), (1000, 500)), _wire((1400, 500), (1500, 500))],
     "both ends wired"),
])
def test_an_ambiguous_port_is_reported_not_moved(wires, reason):
    plan = plan_crossref_fixes(
        [_port("C", 1000, 500, 400)], wires, [_ref(1420, 500, JUST_RUNS_RIGHT)])
    assert plan["moves"] == []
    assert plan["unresolved"][0]["reason"] == reason


def test_a_vertical_port_is_not_handled():
    plan = plan_crossref_fixes(
        [_port("V", 1000, 500, 400, style=4)], [], [_ref(1000, 920, 3)])
    assert plan["unresolved"][0]["reason"].startswith("vertical")


def test_a_port_without_a_reference_is_reported():
    plan = plan_crossref_fixes([_port("D", 1000, 500, 400)],
                               [_wire((900, 500), (1000, 500))], [])
    assert plan["unresolved"][0]["reason"] == "no CrossRef on this port"


def test_references_on_another_row_are_not_taken():
    plan = plan_crossref_fixes(
        [_port("E", 1000, 500, 400)], [_wire((900, 500), (1000, 500))],
        [_ref(1420, 600, JUST_RUNS_RIGHT)])
    assert plan["unresolved"][0]["reason"] == "no CrossRef on this port"
    assert plan["unmatched_crossrefs"] == 1


def test_a_reference_running_past_the_border_is_flagged():
    """PCI_PWR at its old place: 27 characters from x 14600 pass 14800."""
    plan = plan_crossref_fixes(
        [_port("PCI_PWR", 14100, 2800, 480)],
        [_wire((14000, 2800), (14100, 2800))],
        [_ref(14080, 2800, JUST_RUNS_LEFT)],
        x_range=border_for("B"))
    assert plan["off_sheet"] and plan["off_sheet"][0]["border_x"] == 14800


def test_border_for_known_and_custom_sheets():
    assert border_for("B") == (200, 14800)
    assert border_for("a4") == (200, 11300)
    assert border_for("Custom", 12000) == (200, 11800)
    assert border_for("Custom") is None


# --------------------------------------------------------------------------
# the tool: reads, plans, and writes only when asked
# --------------------------------------------------------------------------

class _SheetBridge:
    """Answers the four queries from canned rows; records every call."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def send_command_async(self, command, params=None, timeout=None):
        params = params or {}
        self.calls.append((command, params))
        if command == "application.set_active_document":
            return {"success": True}
        if command == "generic.query_objects":
            return {"objects": self.rows.get(params["object_type"], [])}
        if command == "generic.get_document_info":
            return {"sheet_size": "B"}
        if command == "generic.modify_objects":
            return {"matched": 1, "saved": False}
        return {}


def _tool(monkeypatch, bridge):
    from eda_agent.tools import generic as g
    captured = {}

    class DummyMcp:
        def tool(self):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    monkeypatch.setattr(g, "get_bridge", lambda: bridge)
    g.register_generic_tools(DummyMcp())
    return captured["sch_fix_port_crossrefs"]


_ROWS = {
    "ePort": [_port("PCI_PWR", 13300, 2800, 484.68, connected_end=CONNECTED_ORIGIN)],
    "eWire": [_wire((13200, 2800), (13300, 2800))],
    "eParameter": [_ref(13280, 2800, JUST_RUNS_LEFT)],
    "ePin": [],
}
_SHEET = "R:\\Hardware\\Scratch\\Smoke.SchDoc"


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(monkeypatch):
    bridge = _SheetBridge(_ROWS)
    out = await (_tool(monkeypatch, bridge))(sheet_path=_SHEET)
    assert out["dry_run"] is True and len(out["moves"]) == 1
    assert out["border_x"] == [200, 14800]
    assert not [c for c, _ in bridge.calls if c == "generic.modify_objects"]
    queried = [p["object_type"] for c, p in bridge.calls
               if c == "generic.query_objects"]
    assert set(queried) == {"ePort", "eWire", "eParameter", "ePin"}
    ref_query = next(p for c, p in bridge.calls if c == "generic.query_objects"
                     and p["object_type"] == "eParameter")
    assert ref_query["filter"] == "Name=CrossRef"
    assert ref_query["scope"] == f"doc:{_SHEET}"
    port_query = next(p for c, p in bridge.calls if c == "generic.query_objects"
                      and p["object_type"] == "ePort")
    assert "ConnectedEnd" in port_query["properties"]


@pytest.mark.asyncio
async def test_apply_moves_only_the_reference(monkeypatch):
    """ConnectedEnd is Altium's, derived from the wiring: never written."""
    bridge = _SheetBridge(_ROWS)
    out = await (_tool(monkeypatch, bridge))(sheet_path=_SHEET, dry_run=False)
    writes = [p for c, p in bridge.calls if c == "generic.modify_objects"]
    assert [p["object_type"] for p in writes] == ["eParameter"]
    ref_write = writes[0]
    assert ref_write["filter"] == "Name=CrossRef|Location.X=13280|Location.Y=2800"
    assert ref_write["set"].startswith("Location.X=13804.68")
    assert ref_write["set"].endswith(f"|Justification={JUST_RUNS_RIGHT}")
    assert out["failed"] == [] and len(out["applied"]) == 1
    assert out["saved"] is False
