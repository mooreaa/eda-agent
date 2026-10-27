# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""pcb_build_stack: a whole stack through the AD19+ MasterLayerStack.

The Rosen controller (AD 25.8.1, 2026-10-27) needed a 4-layer board turned
into L1 Top / L2 GND / L3 Sig / L4 Pwr / L5 GND / L6 Bottom. Done with the
LayerStack_V7 tools it read back right and came out corrupt. These tests run
the planner and the tool against a fake stack that behaves like the
MasterLayerStack: physical layers in a list, inserts relative to a named
layer, the outer copper kept.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eda_agent.design import stack_build
from eda_agent.tools import pcb as pcb_tools

REPO = Path(__file__).resolve().parents[1]
BOARD = r"R:\scratch\board.PcbDoc"

FOUR_LAYER = [
    {"name": "Top Overlay", "kind": "overlay", "thickness_mils": 0.25},
    {"name": "Top Solder", "kind": "solder_mask", "thickness_mils": 0.4, "dielectric_type": 3,
     "constant": 3.5},
    {"name": "Top Layer", "kind": "copper", "thickness_mils": 0.7},
    {"name": "Dielectric 1", "kind": "dielectric", "thickness_mils": 4.7244, "dielectric_type": 2,
     "constant": 4.3},
    {"name": "Dielectric 2", "kind": "dielectric", "thickness_mils": 4.7244, "dielectric_type": 2,
     "constant": 4.3},
    {"name": "Internal Plane 1", "kind": "copper", "thickness_mils": 0.7},
    {"name": "Dielectric 3", "kind": "dielectric", "thickness_mils": 55.1181, "dielectric_type": 1,
     "constant": 4.55},
    {"name": "Internal Plane 2", "kind": "copper", "thickness_mils": 0.7},
    {"name": "Dielectric 4", "kind": "dielectric", "thickness_mils": 9.4488, "dielectric_type": 2,
     "constant": 4.3},
    {"name": "Bottom Layer", "kind": "copper", "thickness_mils": 0.7},
    {"name": "Bottom Solder", "kind": "solder_mask", "thickness_mils": 0.4, "dielectric_type": 3,
     "constant": 3.5},
]


def _cu(name, plane=False):
    return {"kind": "copper", "name": name, "thickness_mils": 1.378, "plane": plane}


def _d(t, kind="prepreg", dk=4.0):
    return {"kind": "dielectric", "type": kind, "thickness_mils": t, "constant": dk,
            "material": "FR-4"}


SIX_LAYER = [_cu("L1 Top"), _d(4.33), _cu("L2 GND", True), _d(3.937, "core", 4.3),
             _cu("L3 Signal"), _d(37.4, "core", 4.3), _cu("L4 Power", True),
             _d(3.937, "core", 4.3), _cu("L5 GND", True), _d(4.33), _cu("L6 Bottom")]


# Planner ---------------------------------------------------------------------

def test_plan_removes_inner_renames_outer_then_inserts_top_down():
    plan = stack_build.normalise(SIX_LAYER)
    ops = stack_build.plan_ops(FOUR_LAYER, plan)
    removes = [o["name"] for o in ops if o["op"] == "remove"]
    assert removes == ["Dielectric 1", "Dielectric 2", "Internal Plane 1", "Dielectric 3",
                       "Internal Plane 2", "Dielectric 4"]
    inserts = [(o["kind"], o["name"], o["ref"]) for o in ops if o["op"] == "insert"]
    assert inserts[0] == ("dielectric", "Dielectric 1", "L1 Top")
    assert inserts[1] == ("plane", "L2 GND", "Dielectric 1")
    assert inserts[3] == ("signal", "L3 Signal", "Dielectric 2")
    assert len(inserts) == 9
    first_insert = next(i for i, o in enumerate(ops) if o["op"] == "insert")
    last_remove = max(i for i, o in enumerate(ops) if o["op"] == "remove")
    assert last_remove < first_insert


@pytest.mark.parametrize("bad,why", [
    ([_cu("A"), _cu("B"), _cu("C")], "no dielectric"),
    ([_d(4), _cu("A"), _d(4)], "starts and ends with copper"),
    ([_cu("A", True), _d(4), _cu("B")], "signal layers"),
    ([_cu("A"), _d(4), _cu("A")], "used twice"),
    ([_cu("A"), _d(0), _cu("B")], "positive"),
    ([_cu("A"), {"kind": "dielectric", "type": "glass", "thickness_mils": 4}, _cu("B")], "core or prepreg"),
    ([_cu("A")], "at least"),
])
def test_bad_plans_are_refused(bad, why):
    with pytest.raises(stack_build.StackPlanError, match=why):
        stack_build.normalise(bad)


def test_two_dielectrics_in_a_row_are_allowed():
    plan = stack_build.normalise([_cu("A"), _d(2), _d(2), _cu("B")])
    assert [p["name"] for p in plan] == ["A", "Dielectric 1", "Dielectric 2", "B"]


def test_check_reports_each_difference():
    plan = stack_build.normalise([_cu("A"), _d(4.33), _cu("B")])
    back = [{"name": "A", "kind": "copper", "thickness_mils": 1.378},
            {"name": "Dielectric 1", "kind": "dielectric", "thickness_mils": -0.39,
             "dielectric_type": 1, "constant": 4.0},
            {"name": "B", "kind": "copper", "thickness_mils": 1.378}]
    checks = [m["check"] for m in stack_build.check(back, plan)]
    assert checks == ["thickness_mils", "type"]


# The tool against a fake MasterLayerStack ---------------------------------------

class _FakeAltium:
    def __init__(self, layers, modified=False, fail_on=None, drift=None):
        self.layers = [dict(layer) for layer in layers]
        self.modified = modified
        self.fail_on = fail_on
        self.drift = drift
        self.calls: list[tuple[str, dict]] = []
        self.closed = False
        self.reopened = False

    def _find(self, name):
        return next((i for i, layer in enumerate(self.layers)
                     if layer["name"].upper() == name.upper()), None)

    async def send_command_async(self, command, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append((command, params))
        if command == "application.set_active_document":
            return {"success": True}
        if command == "application.get_open_documents":
            return [{"file_path": BOARD, "modified": self.modified, "loaded": True}]
        if command == "pcb.physical_stack":
            return {"layers": [dict(layer) for layer in self.layers]}
        if command == "application.close_document":
            self.closed = True
            return {"closed": True}
        if command == "application.run_process":
            self.reopened = True
            return {"success": True}
        if command != "pcb.stack_edit":
            raise AssertionError(command)
        if self.fail_on and params.get("name") == self.fail_on:
            raise RuntimeError("LAYER_IN_USE")
        op = params["op"]
        if op == "remove":
            del self.layers[self._find(params["name"])]
            return {"removed": True}
        if op == "set_copper":
            layer = self.layers[self._find(params["name"])]
            layer["name"] = params.get("new_name") or layer["name"]
            if "thickness_mils" in params:
                layer["thickness_mils"] = float(params["thickness_mils"])
            return {"name": layer["name"]}
        if op == "insert":
            at = self._find(params["ref"]) + (1 if params["where"] == "below" else 0)
            kind = "dielectric" if params["kind"] == "dielectric" else "copper"
            t = float(params["thickness_mils"])
            if self.drift and params["name"] == self.drift:
                t += 1.0
            new = {"name": params["name"], "kind": kind, "thickness_mils": t}
            if kind == "dielectric":
                new["dielectric_type"] = int(params["type"])
                new["constant"] = float(params.get("constant", 1))
            self.layers.insert(at, new)
            return {"name": new["name"]}
        raise AssertionError(op)


class _Mcp:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register


def _build(monkeypatch, fake, **kwargs):
    monkeypatch.setattr(pcb_tools, "get_bridge", lambda: fake)
    mcp = _Mcp()
    pcb_tools.register_pcb_tools(mcp)
    return asyncio.run(mcp.tools["pcb_build_stack"](BOARD, SIX_LAYER, **kwargs))


def _edits(fake):
    return [c for c, _ in fake.calls if c == "pcb.stack_edit"]


def test_dry_run_changes_nothing(monkeypatch):
    fake = _FakeAltium(FOUR_LAYER)
    out = _build(monkeypatch, fake)
    assert out["ok"] and out["dry_run"] and out["ops"]
    assert _edits(fake) == []


def test_a_build_gives_the_planned_six_layer_stack(monkeypatch):
    fake = _FakeAltium(FOUR_LAYER)
    out = _build(monkeypatch, fake, dry_run=False)
    assert out["ok"] is True, out.get("mismatches")
    section = stack_build.board_section(fake.layers)
    assert [s["name"] for s in section] == [
        "L1 Top", "Dielectric 1", "L2 GND", "Dielectric 2", "L3 Signal", "Dielectric 3",
        "L4 Power", "Dielectric 4", "L5 GND", "Dielectric 5", "L6 Bottom"]
    assert fake.layers[0]["name"] == "Top Overlay" and fake.layers[-1]["name"] == "Bottom Solder"
    assert not fake.closed and "pcb_stack_from_file" in out["next"]


def test_an_unsaved_board_is_refused(monkeypatch):
    fake = _FakeAltium(FOUR_LAYER, modified=True)
    out = _build(monkeypatch, fake, dry_run=False)
    assert out["ok"] is False and "Save it first" in out["reason"]
    assert _edits(fake) == []


def test_a_failed_step_is_undone_by_closing_unsaved(monkeypatch):
    fake = _FakeAltium(FOUR_LAYER, fail_on="Internal Plane 1")
    out = _build(monkeypatch, fake, dry_run=False)
    assert out["ok"] is False and out["failure"]["op"]["name"] == "Internal Plane 1"
    assert out["undone"] is True and fake.closed and fake.reopened
    close = next(p for c, p in fake.calls if c == "application.close_document")
    assert close["discard"] == "true"


def test_a_read_back_difference_is_undone(monkeypatch):
    fake = _FakeAltium(FOUR_LAYER, drift="Dielectric 3")
    out = _build(monkeypatch, fake, dry_run=False)
    assert out["ok"] is False and out["undone"] is True
    assert out["mismatches"][0]["layer"] == "Dielectric 3"


def test_a_bad_plan_never_reaches_the_bridge(monkeypatch):
    fake = _FakeAltium(FOUR_LAYER)
    monkeypatch.setattr(pcb_tools, "get_bridge", lambda: fake)
    mcp = _Mcp()
    pcb_tools.register_pcb_tools(mcp)
    out = asyncio.run(mcp.tools["pcb_build_stack"](BOARD, [_cu("A"), _cu("B"), _cu("C")]))
    assert out["ok"] is False and fake.calls == []


def test_the_script_inserts_through_the_master_layer_stack():
    src = (REPO / "scripts" / "altium" / "PCB.pas").read_text(encoding="utf-8", errors="replace")
    start = src.index("Function PCB_StackEdit(")
    body = src[start:src.index("\nEnd;", start)]
    for call in ("MLS.CreateLayer(Id)", "MLS.InsertBelow(Ref, NewL)", "MLS.InsertAbove(Ref, NewL)",
                 "MLS.RemoveLayer(L)", "L.UsedByPrims", "DL.DielectricHeight"):
        assert call in body, call
    assert "LayerStack_V7" not in body
    assert "'stack_edit':" in src
