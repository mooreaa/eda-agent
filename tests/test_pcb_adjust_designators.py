# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""pcb_adjust_designators: the AdjustDesignators.pas house convention.

Asked for by the Rosen controller session (2026-10-27): designators off the
silkscreen, one per part on Mechanical 10 / 11, centred and fitted to the
part, rerun whenever placement changes, without stopping the bridge to run
the external script. The sizing below is checked against the script's own
arithmetic; the one change, 90 degrees for a tall top part, is Aaron's.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eda_agent.design import designators as desig
from eda_agent.tools import pcb as pcb_tools
from eda_agent.units import MILS_PER_MM

REPO = Path(__file__).resolve().parents[1]
BOARD = r"R:\scratch\board.PcbDoc"


def _part(name, w_mm, h_mm, side="top", source="tracks", x0=1000.0, y0=1000.0):
    return {"designator": name, "side": side, "source": source,
            "x1": x0, "y1": y0, "x2": x0 + w_mm * MILS_PER_MM, "y2": y0 + h_mm * MILS_PER_MM}


OPT = desig.Options()


def test_a_wide_part_fits_its_long_side():
    plan = desig.plan_part(_part("R12", 2.0, 1.2), OPT)
    # 2.0 / 3 = 0.667 < 1.2: the long side wins, not turned.
    assert plan["height_mm"] == pytest.approx(0.6667, abs=1e-4)
    assert plan["stroke_mm"] == pytest.approx(0.1667, abs=1e-4)
    assert plan["rotation"] == 0 and plan["layer"] == "Mechanical10" and not plan["mirror"]
    assert "short_side_fallback" not in plan


def test_a_tall_top_part_turns_90_and_a_bottom_one_270_mirrored():
    top = desig.plan_part(_part("C1", 1.0, 2.0), OPT)
    bottom = desig.plan_part(_part("C2", 1.0, 2.0, side="bottom"), OPT)
    assert top["rotation"] == 90
    assert bottom["rotation"] == 270 and bottom["mirror"] and bottom["layer"] == "Mechanical11"


def test_the_script_fallback_divides_the_short_side_by_the_length_and_is_flagged():
    # 10 x 1.2 mm, "U101": 10/4 = 2.5 >= 1.2, so 1.2/4 = 0.3 by the script.
    plan = desig.plan_part(_part("U101", 10.0, 1.2), OPT)
    assert plan["short_side_fallback"] is True
    assert plan["height_mm"] == pytest.approx(0.3)
    capped = desig.plan_part(_part("U101", 10.0, 1.2), desig.Options(fit="short_side"))
    assert capped["height_mm"] == pytest.approx(1.0)       # 1.2, clamped to 1.0
    assert capped["clamped_from_mm"] == pytest.approx(1.2)


def test_the_clamp_keeps_the_script_stroke_from_before_it():
    big = desig.plan_part(_part("J1", 20.0, 10.0), OPT)       # 20/2 = 10 mm
    assert big["height_mm"] == 1.0 and big["stroke_mm"] == 0.254
    tiny = desig.plan_part(_part("R1000", 0.3, 0.2), OPT)     # 0.3/5 = 0.06 mm
    assert tiny["height_mm"] == 0.1
    assert tiny["stroke_mm"] == pytest.approx(0.015)         # 25 % of 0.06, as the script


def test_a_part_on_neither_side_is_skipped():
    assert "skip" in desig.plan_part(_part("X1", 2, 1, side="other"), OPT)


def test_apply_item_is_in_mils():
    item = desig.apply_item(desig.plan_part(_part("C2", 1.0, 2.0, side="bottom"), OPT))
    fields = dict(f.split("=", 1) for f in item.split(";"))
    assert fields["d"] == "C2" and fields["l"] == "Mechanical11" and fields["m"] == "1"
    assert float(fields["s"]) == pytest.approx(0.5 * MILS_PER_MM, abs=1e-3)
    assert fields["r"] == "270"


def test_check_part_names_each_difference():
    part = _part("R1", 2.0, 1.0)
    plan = desig.plan_part(part, OPT)
    cx = (part["x1"] + part["x2"]) / 2
    cy = (part["y1"] + part["y2"]) / 2
    good = {"layer": "Mechanical 10", "size_mils": plan["height_mm"] * MILS_PER_MM,
            "width_mils": plan["stroke_mm"] * MILS_PER_MM, "rotation": 0, "mirror": False,
            "tt_font": False, "name_on": True, "text_cx": cx, "text_cy": cy}
    assert desig.check_part(plan, part, good) == []
    bad = dict(good, layer="Top Overlay", rotation=90, text_cx=cx + 40)
    issues = desig.check_part(plan, part, bad)
    assert len(issues) == 3 and "layer" in issues[0] and "centre" in issues[2]


class _Mcp:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register


class _Board:
    def __init__(self, parts, modified=False, drop_rotation=None):
        self.parts = parts
        self.modified = modified
        self.drop_rotation = drop_rotation
        self.calls = []

    async def send_command_async(self, command, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append((command, params))
        if command == "application.set_active_document":
            return {"success": True}
        if command == "application.get_open_documents":
            return [{"file_path": BOARD, "modified": self.modified}]
        assert command == "pcb.designators"
        if params["op"] == "outlines":
            assert params["board_path"] == BOARD
            want = params.get("designators")
            names = set(want.split(",")) if want else None
            return {"board": BOARD, "parts": [dict(p) for p in self.parts
                                              if names is None or p["designator"] in names]}
        out = []
        for item in params["items"].split("~~"):
            f = dict(kv.split("=", 1) for kv in item.split(";"))
            part = next(p for p in self.parts if p["designator"] == f["d"])
            rot = float(f["r"])
            if f["d"] == self.drop_rotation:
                rot = 0
            out.append({"designator": f["d"], "layer": f["l"].replace("Mechanical", "Mechanical "),
                        "size_mils": float(f["s"]), "width_mils": float(f["w"]),
                        "rotation": rot, "mirror": f["m"] == "1", "tt_font": False,
                        "name_on": True,
                        "text_cx": (part["x1"] + part["x2"]) / 2,
                        "text_cy": (part["y1"] + part["y2"]) / 2})
        return {"applied": len(out), "parts": out}


PARTS = [_part("R12", 2.0, 1.2), _part("C1", 1.0, 2.0), _part("U101", 10.0, 1.2),
         _part("C2", 1.0, 2.0, side="bottom", source="bounding_rectangle")]


def _run(monkeypatch, board, **kwargs):
    monkeypatch.setattr(pcb_tools, "get_bridge", lambda: board)
    mcp = _Mcp()
    pcb_tools.register_pcb_tools(mcp)
    return asyncio.run(mcp.tools["pcb_adjust_designators"](BOARD, **kwargs))


def test_dry_run_lists_the_flags_and_writes_nothing(monkeypatch):
    board = _Board(PARTS)
    out = _run(monkeypatch, board)
    assert out["dry_run"] and out["totals"]["to_adjust"] == 4
    assert out["turned"] == ["C1", "C2"]
    assert out["short_side_fallback"] == ["C1", "U101", "C2"]   # 2/2 = 1.0 >= 1.0 on C1, C2
    assert out["bounding_rectangle"] == ["C2"]
    assert not any(p.get("op") == "apply" for _, p in board.calls)


def test_apply_reads_back_and_lists_what_did_not_take(monkeypatch):
    board = _Board(PARTS, drop_rotation="C1")
    out = _run(monkeypatch, board, dry_run=False)
    assert out["applied"] == 4 and out["ok"] is False
    assert [n["designator"] for n in out["not_taken"]] == ["C1"]
    assert "close the board without saving" in out["undo"]


def test_a_clean_apply_is_ok_and_only_named_parts_are_touched(monkeypatch):
    board = _Board(PARTS)
    out = _run(monkeypatch, board, dry_run=False, designators=["R12", "NOPE"])
    assert out["ok"] is True and out["applied"] == 1 and out["not_found"] == ["NOPE"]


@pytest.mark.parametrize("kwargs", [{"fit": "squash"}, {"comment": "delete"}])
def test_bad_options_never_reach_the_board(monkeypatch, kwargs):
    board = _Board(PARTS)
    out = _run(monkeypatch, board, **kwargs)
    assert out["ok"] is False and board.calls == []


def test_the_script_keeps_the_house_text_settings():
    src = (REPO / "scripts" / "altium" / "PCB.pas").read_text(encoding="utf-8", errors="replace")
    start = src.index("Function PCB_Designators(")
    body = src[start:src.index("\nEnd;", start)]
    for line in ("Comp.NameOn := True", "Desig.UseTTFonts := False", "Desig.FontName := 'Default'",
                 "Desig.Bold := True", "Comp.ChangeNameAutoposition(eAutoPos_CenterCenter)",
                 "PCBServer.SystemOptions.DoOnlineDRC := WasOnline", "'WRONG_BOARD'"):
        assert line in body, line
    assert "'designators':" in src


def test_an_off_centre_text_is_reported_not_failed(monkeypatch):
    class _OffCentre(_Board):
        async def send_command_async(self, command, params=None, timeout=None):
            out = await super().send_command_async(command, params, timeout)
            if command == "pcb.designators" and (params or {}).get("op") == "apply":
                for p in out["parts"]:
                    p["text_cx"] += 20.0
            return out

    out = _run(monkeypatch, _OffCentre(PARTS), dry_run=False)
    assert out["ok"] is True and out["not_taken"] == []
    assert len(out["off_centre"]) == 4
