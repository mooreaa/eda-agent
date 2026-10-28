# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""pcb_build_stack: a whole stack through the AD19+ MasterLayerStack.

The Rosen controller (AD 25.8.1, 2026-10-27) needed a 4-layer board turned
into L1 Top / L2 GND / L3 Sig / L4 Pwr / L5 GND / L6 Bottom. Done with the
LayerStack_V7 tools it read back right and came out corrupt. These tests run
the planner and the tool against a fake stack that behaves as AD 25.8.1 did
live on a scratch copy of that board: copper inserted below a layer lands
after that layer's dielectrics, Altium adds a dielectric under each new copper
layer by itself, and no dielectric can be created any other way.
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
             _cu("L3 Signal"), _d(37.4, "core", 4.3), _cu("L4 Power"),
             _d(3.937, "core", 4.3), _cu("L5 GND", True), _d(4.33), _cu("L6 Bottom")]


# Planner ---------------------------------------------------------------------

PLANES_USED = [{"name": "Top Layer", "layer_id": 16777217, "used_by_prims": True},
               {"name": "Internal Plane 1", "layer_id": 16842753, "used_by_prims": True},
               {"name": "Internal Plane 2", "layer_id": 16842754, "used_by_prims": True},
               {"name": "Bottom Layer", "layer_id": 16842751, "used_by_prims": True}]


def test_plan_keeps_the_planes_and_inserts_copper_around_them():
    plan = stack_build.normalise(SIX_LAYER)
    ops = stack_build.plan_ops(FOUR_LAYER, plan, PLANES_USED)
    assert [o for o in ops if o["op"] == "remove"] == []
    finals = {o["name"]: o["new_name"] for o in ops
              if o["op"] == "set_copper" and o["name"].startswith("__")}
    assert set(finals.values()) == {"L1 Top", "L6 Bottom", "L2 GND", "L5 GND"}
    inserts = [(o["kind"], o["name"], o["ref"]) for o in ops if o["op"] == "insert"]
    assert inserts == [("signal", "L3 Signal", "L2 GND"), ("signal", "L4 Power", "L3 Signal")]


def test_dielectric_phase_fits_each_gap_and_sets_it():
    plan = stack_build.normalise(SIX_LAYER)
    back = [{"name": "L1 Top", "kind": "copper"},
            {"name": "Dielectric 1", "kind": "dielectric"},
            {"name": "Dielectric 2", "kind": "dielectric"},
            {"name": "L2 GND", "kind": "copper"},
            {"name": "Dielectric 3", "kind": "dielectric"},
            {"name": "L3 Signal", "kind": "copper"},
            {"name": "Dielectric6", "kind": "dielectric"},
            {"name": "L4 Power", "kind": "copper"},
            {"name": "Dielectric7", "kind": "dielectric"},
            {"name": "L5 GND", "kind": "copper"},
            {"name": "Dielectric 4", "kind": "dielectric"},
            {"name": "Dielectric 5", "kind": "dielectric"},
            {"name": "L6 Bottom", "kind": "copper"}]
    ops = stack_build.dielectric_ops(back, plan)
    assert [o["name"] for o in ops if o["op"] == "remove"] == ["Dielectric 2", "Dielectric 5"]
    finals = [o for o in ops if o["op"] == "set_dielectric" and o["name"].startswith("__")]
    assert [o["new_name"] for o in finals] == [f"Dielectric {n}" for n in range(1, 6)]
    assert finals[2]["thickness_mils"] == "37.4" and finals[2]["type"] == "1"


def test_a_gap_short_of_dielectrics_is_refused():
    plan = stack_build.normalise([_cu("A"), _d(2), _d(2), _cu("B")])
    back = [{"name": "A", "kind": "copper"}, {"name": "D", "kind": "dielectric"},
            {"name": "B", "kind": "copper"}]
    with pytest.raises(stack_build.StackPlanError, match="cannot add one"):
        stack_build.dielectric_ops(back, plan)


def test_copper_that_came_out_wrong_is_refused():
    plan = stack_build.normalise([_cu("A"), _d(2), _cu("B")])
    back = [{"name": "A", "kind": "copper"}, {"name": "D", "kind": "dielectric"},
            {"name": "X", "kind": "copper"}]
    with pytest.raises(stack_build.StackPlanError, match="came out"):
        stack_build.dielectric_ops(back, plan)


def test_a_busy_layer_the_plan_drops_is_refused_before_any_change():
    plan = stack_build.normalise([_cu("A"), _d(4), _cu("B")])
    with pytest.raises(stack_build.StackPlanError, match="Internal Plane 1, Internal Plane 2"):
        stack_build.plan_ops(FOUR_LAYER, plan, PLANES_USED)


def test_an_idle_layer_the_plan_drops_is_removed():
    idle = [dict(i, used_by_prims=False) for i in PLANES_USED]
    plan = stack_build.normalise([_cu("A"), _d(4), _cu("B")])
    ops = stack_build.plan_ops(FOUR_LAYER, plan, idle)
    assert {"op": "remove", "name": "Internal Plane 1"} in ops


@pytest.mark.parametrize("layer_id,kind", [
    (16842753, "plane"), (16777218, "signal"), (39, "plane"), (2, "signal"), (None, "signal")])
def test_copper_type_from_layer_id(layer_id, kind):
    assert stack_build.copper_type(layer_id) == kind


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
        self.auto = 0

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
        if command == "pcb.stack_edit" and params.get("op") == "inspect":
            return {"layers": [dict(i) for i in PLANES_USED]}
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
            if params["kind"] == "dielectric":
                raise RuntimeError("NOT_CREATED")
            at = self._find(params["ref"]) + 1
            while at < len(self.layers) and self.layers[at]["kind"] == "dielectric":
                at += 1
            self.auto += 1
            self.layers[at:at] = [
                {"name": params["name"], "kind": "copper",
                 "thickness_mils": float(params["thickness_mils"])},
                {"name": f"Dielectric{5 + self.auto}", "kind": "dielectric",
                 "thickness_mils": 12.6, "dielectric_type": 0, "constant": 4.8}]
            return {"name": params["name"]}
        if op == "set_dielectric":
            layer = self.layers[self._find(params["name"])]
            layer["name"] = params.get("new_name") or layer["name"]
            if "thickness_mils" in params:
                t = float(params["thickness_mils"])
                if self.drift and layer["name"] == self.drift:
                    t += 1.0
                layer["thickness_mils"] = t
            if "type" in params:
                layer["dielectric_type"] = int(params["type"])
            if "constant" in params:
                layer["constant"] = float(params["constant"])
            return {"name": layer["name"]}
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
    return [c for c, p in fake.calls if c == "pcb.stack_edit" and p.get("op") != "inspect"]


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
    fake = _FakeAltium(FOUR_LAYER, fail_on="L3 Signal")
    out = _build(monkeypatch, fake, dry_run=False)
    assert out["ok"] is False and out["failure"]["op"]["name"] == "L3 Signal"
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


def test_the_script_never_writes_the_v7_dielectric_fields():
    """Only LayerObj.Dielectric.* corrupted the Rosen stack. Copper goes in
    through the V7 stack (that part works); every dielectric value is written
    on the AD19+ dielectric layer object."""
    src = (REPO / "scripts" / "altium" / "PCB.pas").read_text(encoding="utf-8", errors="replace")
    start = src.index("Function PCB_StackEdit(")
    body = src[start:src.index("\nEnd;", start)]
    for call in ("LS7.InsertInStackBelow(RefObj, NewObj)", "LS7.InsertInStackAbove(RefObj, NewObj)",
                 "MLS.RemoveLayer(L)", "L.UsedByPrims", "DL.DielectricHeight",
                 "EL.CopperThickness", "'set_dielectric'"):
        assert call in body, call
    assert ".Dielectric.Dielectric" not in body
    assert "'stack_edit':" in src


def test_copper_left_additive_is_a_mismatch():
    flags = [{"name": "L1 Top", "additive": False, "resistivity": 0},
             {"name": "L3 Signal", "additive": True, "resistivity": 2147483647.0},
             {"name": "Dielectric 1"}]
    out = stack_build.check_copper_flags(flags)
    assert [(m["check"], m["layer"]) for m in out] == [
        ("additive", "L3 Signal"), ("non_conductive", "L3 Signal")]


def test_an_insert_that_stays_additive_fails_and_undoes(monkeypatch):
    class _Additive(_FakeAltium):
        async def send_command_async(self, command, params=None, timeout=None):
            out = await super().send_command_async(command, params, timeout)
            if command == "pcb.stack_edit" and (params or {}).get("op") == "insert":
                out["ordinary_copper"] = False
            return out

    fake = _Additive(FOUR_LAYER)
    out = _build(monkeypatch, fake, dry_run=False)
    assert out["ok"] is False and "additive" in out["failure"]["error"]
    assert out["undone"] is True


def test_the_script_makes_inserted_copper_ordinary():
    src = (REPO / "scripts" / "altium" / "PCB.pas").read_text(encoding="utf-8", errors="replace")
    start = src.index("Function StackMakeOrdinaryCopper(")
    body = src[start:src.index("\nEnd;", start)]
    assert "EL.IsAdditiveLayer := False" in body
    assert "EL.ElectricalResistivity := TopEL.ElectricalResistivity" in body
    edit = src[src.index("Function PCB_StackEdit("):]
    assert edit.count("StackMakeOrdinaryCopper(MLS,") == 2


def test_loss_tangent_reaches_the_dielectric_edit():
    plan = stack_build.normalise([_cu("A"), dict(_d(4.33), loss_tangent=0.02), _cu("B")])
    back = [{"name": "A", "kind": "copper"}, {"name": "D", "kind": "dielectric"},
            {"name": "B", "kind": "copper"}]
    final = [o for o in stack_build.dielectric_ops(back, plan)
             if o["op"] == "set_dielectric" and o["name"].startswith("__")]
    assert final[0]["loss_tangent"] == "0.02"
