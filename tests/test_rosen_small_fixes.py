# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""Seven small defects found on the Rosen controller (AD 25.8.1, 2026-10-23 to 10-25).

Each was worked around by hand there. The numbers are the Rosen issue list's.

- 4: a close aimed at a phantom copy ("/Hardware/x.SchLib") closed the real
  document, because GetDocumentByPath resolves the phantom's name to it.
- 5: app_checkpoint snapshots the focused project, and with three open it
  backed up the wrong one.
- 11: a template GND port drawn with style "bar" pointed up.
- 22: obj_deselect_all ran Sch:DeSelectAll, which left the selection standing.
- 24: proj_export_pdf / proj_export_image(pdf) open the print dialog and block
  the bridge until a person answers it.
- 25: obj_zoom "fit" is Fit All Objects and clips the sheet border; there was
  no way to ask for Fit Document.
- 26: app_screenshot upscaled the window 2x for no extra detail.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path

import pytest

from eda_agent.tools import application as application_tools
from eda_agent.tools import project as project_tools

REPO = Path(__file__).resolve().parents[1]
PAS = REPO / "scripts" / "altium"


class _Mcp:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register


class _Bridge:
    def __init__(self, projects=None, project_dir=""):
        self.projects = projects or []
        self.project_dir = project_dir
        self.calls: list[tuple[str, dict]] = []

    async def send_command_async(self, command, params=None, timeout=None):
        self.calls.append((command, dict(params or {})))
        if command == "project.get_open_projects":
            return {"projects": [{"project_path": p} for p in self.projects],
                    "count": len(self.projects)}
        if command == "project.get_project_path":
            return {"project_dir": self.project_dir, "project_name": "A.PrjPcb"}
        return {"success": True}


def _tools(module, register, monkeypatch, bridge):
    monkeypatch.setattr(module, "get_bridge", lambda: bridge)
    mcp = _Mcp()
    getattr(module, register)(mcp)
    return mcp.tools


def _pascal(name: str) -> str:
    return (PAS / name).read_text(encoding="utf-8", errors="replace")


def _function(src: str, name: str) -> str:
    start = src.index(f"Function {name}(")
    end = src.index("\nEnd;", start)
    return src[start:end]


# 24 -------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["proj_export_pdf", "proj_export_image"])
def test_the_pdf_exports_refuse_rather_than_open_the_print_dialog(
        monkeypatch, tool):
    bridge = _Bridge()
    fns = _tools(project_tools, "register_project_tools", monkeypatch, bridge)
    out = asyncio.run(fns[tool]("C:/x.pdf"))
    assert out["success"] is False
    assert out["error"] == "PRINT_DIALOG_NOT_SILENT"
    assert "proj_run_outjob" in out["details"]
    assert bridge.calls == []


def test_the_print_dialog_still_opens_when_asked(monkeypatch):
    bridge = _Bridge()
    fns = _tools(project_tools, "register_project_tools", monkeypatch, bridge)
    asyncio.run(fns["proj_export_pdf"]("C:/x.pdf", open_print_dialog=True))
    assert [c for c, _ in bridge.calls] == ["project.export_pdf"]


def test_a_png_export_still_reaches_the_bridge_for_its_own_refusal(monkeypatch):
    bridge = _Bridge()
    fns = _tools(project_tools, "register_project_tools", monkeypatch, bridge)
    asyncio.run(fns["proj_export_image"]("C:/x.png", format="png"))
    assert [c for c, _ in bridge.calls] == ["project.export_image"]


# 5 --------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from eda_agent import config as config_module

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(
        config_module, "config",
        config_module.config.model_copy(update={"workspace_dir": ws}))
    project = tmp_path / "proj"
    project.mkdir()
    (project / "A.PrjPcb").write_text("stub", encoding="utf-8")
    (project / "sheet.SchDoc").write_text("sheet", encoding="utf-8")
    return project


def test_checkpoint_refuses_when_several_projects_are_open(monkeypatch, workspace):
    bridge = _Bridge(projects=[r"R:\a\A.PrjPcb", r"R:\b\B.PrjPcb"],
                     project_dir=str(workspace))
    fns = _tools(application_tools, "register_application_tools",
                 monkeypatch, bridge)
    out = asyncio.run(fns["app_checkpoint"]("x"))
    assert out["checkpoint"] is None
    assert "project_path" in out["error"]
    assert len(out["open_projects"]) == 2
    assert "project.save" not in [c for c, _ in bridge.calls]


def test_free_documents_do_not_make_the_focus_ambiguous(monkeypatch, workspace):
    bridge = _Bridge(projects=["Free Documents", str(workspace / "A.PrjPcb")],
                     project_dir=str(workspace))
    fns = _tools(application_tools, "register_application_tools",
                 monkeypatch, bridge)
    out = asyncio.run(fns["app_checkpoint"]("x"))
    assert out["checkpoint"]["file_count"] >= 1


def test_checkpoint_of_a_named_project_saves_and_snapshots_that_one(
        monkeypatch, workspace):
    named = str(workspace / "A.PrjPcb")
    bridge = _Bridge(projects=[r"R:\other\B.PrjPcb", named],
                     project_dir=r"R:\other")
    fns = _tools(application_tools, "register_application_tools",
                 monkeypatch, bridge)
    out = asyncio.run(fns["app_checkpoint"]("x", project_path=named))
    assert out["saved"] is True
    assert out["checkpoint"]["file_count"] >= 1
    saves = [p for c, p in bridge.calls if c == "project.save"]
    assert saves == [{"project_path": named}]
    assert "project.get_project_path" not in [c for c, _ in bridge.calls]


def test_checkpoint_of_a_missing_project_file_is_refused(monkeypatch, workspace):
    bridge = _Bridge()
    fns = _tools(application_tools, "register_application_tools",
                 monkeypatch, bridge)
    out = asyncio.run(fns["app_checkpoint"](
        "x", project_path=str(workspace / "Nope.PrjPcb")))
    assert out["checkpoint"] is None and "not found" in out["error"]


# 11 -------------------------------------------------------------------------

def _one_pin():
    from eda_agent.design.sch_template import place_symbol_pins

    return {"R1": place_symbol_pins("R1", [
        {"designator": "1", "name": "1", "x": -100, "y": 0,
         "orientation": 2, "length": 100}], 0, 0)}


@pytest.mark.parametrize("net,style,expected", [
    ("GND", "bar", 3), ("AGND", "", 3), ("GND", "gnd_signal", 3),
    ("+3V3", "bar", 1), ("+3V3", "", 1),
])
def test_template_ground_ports_point_down_whatever_their_style(net, style, expected):
    from eda_agent.design.sch_template import build

    port = {"net": net, "at": "R1.1"}
    if style:
        port["style"] = style
    drawing = build({"parts": [{"designator": "R1"}], "ports": [port]}, _one_pin())
    assert drawing.ports[0]["orientation"] == expected


def test_an_explicit_orientation_still_wins():
    from eda_agent.design.sch_template import build

    drawing = build({"parts": [{"designator": "R1"}], "ports": [
        {"net": "GND", "at": "R1.1", "style": "bar", "orientation": 1}]},
        _one_pin())
    assert drawing.ports[0]["orientation"] == 1


# 26 -------------------------------------------------------------------------

def test_capture_png_is_native_unless_ocr_asks_for_more():
    from eda_agent.ui import ocr

    assert inspect.signature(ocr.capture_png).parameters["scale"].default == 1
    assert "scale=2" in inspect.getsource(ocr.read_window_text)


# 22, 25, 4 (Pascal) -----------------------------------------------------------

def test_schematic_deselect_runs_sch_deselect_with_action_all():
    body = _pascal("Generic.pas")
    start = body.index("Procedure SchDeselectAllObjects(")
    proc = body[start:body.index("\nEnd;", start)]
    assert "RunProcess('Sch:DeSelect')" in proc
    assert "AddStringParameter('Action', 'All')" in proc
    assert "Sch:DeSelectAll" not in proc


def test_zoom_document_is_fit_document_on_a_schematic_only():
    fn = _function(_pascal("Generic.pas"), "Gen_Zoom")
    assert "(Action <> 'document')" in fn
    assert re.search(r"\(Action = 'document'\) And \(ZoomProcess <> 'Sch:Zoom'\)", fn)
    assert "AddStringParameter('Action', 'Document')" in fn


def test_close_refuses_a_document_resolved_under_another_name():
    src = _pascal("Application.pas")
    fn = _function(src, "App_CloseDocument")
    assert fn.index("SameDocPath(ServerDoc.FileName, FilePath)") < fn.index(
        "Client.CloseDocument(ServerDoc)")
    assert "PATH_MISMATCH" in fn
    same = _function(src, "SameDocPath")
    assert same.count("StringReplace(") == 2 and "LowerCase(" in same
