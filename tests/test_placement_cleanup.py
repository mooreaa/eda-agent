# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""What a new object needs so it matches the sheet it lands on.

Every one of these was fixed by hand, object by object, on the Rosen
controller (eda-agent 0.7.x on AD 25.8.1, 2026-10-23 to 10-26):

* ports, power ports, text frames and sheet entries came in as Times New
  Roman 10 on sheets drawn in Arial 7;
* a port's width did not hold (it auto-sized onto a neighbouring wire);
* a text frame's typed ``\\n`` printed as text;
* a placed part kept SourceLibraryName ``*``, showed its simulation
  parameters at the sheet origin, and kept the library's designator font;
* the ``Value`` key wrote only the Comment, so ``*K`` stayed on the sheet,
  and a parameter it created drew visible at the sheet origin;
* a pin query on a sheet answered every hidden copy of a multi-part pin;
* a port's AutoSize and ConnectedEnd could not be read or written.

These checks read the Pascal, so they run without Altium.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tests.pascal_source import load

GENERIC_PAS = Path(__file__).resolve().parents[1] / "scripts" / "altium" / "Generic.pas"


@pytest.fixture(scope="module")
def funcs() -> dict[str, str]:
    return load(GENERIC_PAS)


# --------------------------------------------------------------------------
# fonts on placement
# --------------------------------------------------------------------------


def test_a_port_width_is_set_with_autosize_off(funcs):
    body = funcs["Gen_PlacePort"]
    off = body.find("SchPort.AutoSize := False")
    width = body.find("SchPort.Width := MilsToCoordF(WantWidth)")
    assert off != -1 and width != -1 and off < width
    assert body.find("SchPort.FontId := FontToUse") < width, (
        "the font sizes the text, so it is set before the width")


def test_a_typed_backslash_n_becomes_a_line_break(funcs):
    body = funcs["Gen_PlaceTextFrame"]
    fold = body.find("StringReplace(TextStr, '\\' + 'n', #10")
    crlf = body.find("StringReplace(TextStr, #10, #13 + #10")
    assign = body.find("TF.Text := TextStr")
    assert -1 < fold < crlf < assign


# --------------------------------------------------------------------------
# the tidy step after a part is placed
# --------------------------------------------------------------------------


def test_tidy_links_hides_and_sets_the_font(funcs):
    body = funcs["TidyPlacedComponent"]
    for write in ("Comp.SourceLibraryName := LibName", "Comp.UseLibraryName := True",
                  "Comp.DesignItemId := LibRef", "ParamObj.IsHidden := True",
                  "Comp.Designator.FontId := DesigFont"):
        assert write in body, write
    # The component's own parameters are the first level, told apart by
    # name; only the ones below it (the model's) are hidden.
    assert "SetState_IterationDepth(eIterateFirstLevel)" in body
    assert "Own.IndexOf(ParamName) < 0" in body


@pytest.mark.parametrize("routine", ["TidyPlacedComponent", 
                                      "ProcessSchDocObjects"])
def test_new_code_avoids_what_stopped_the_loop(funcs, routine):
    """The first versions stopped the polling loop on AD 25.8.1 with
    "Could not convert variant of type (Dispatch) into type (Boolean)".
    Both used object addresses and a TStringList tested against Nil;
    the rewrite uses neither (obj_delete's own address use is mainline's
    and is left alone)."""
    body = funcs[routine]
    if routine != "ProcessSchDocObjects":
        assert "I_ObjectAddress" not in body
    assert "DeadPins <> Nil" not in body


def test_a_created_parameter_is_hidden(funcs):
    body = funcs["SetCompParamText"]
    assert "NewParam.IsHidden := True" in body
    assert body.find("NewParam.IsHidden := True") < body.find("Comp.AddSchObject(NewParam)")


# --------------------------------------------------------------------------
# pin queries see only live pins; port properties
# --------------------------------------------------------------------------


def test_port_autosize_and_connected_end_read_on_ports_only(funcs):
    body = funcs["GetSchProperty"]
    at = body.find("(PropName = 'AutoSize') Or (PropName = 'ConnectedEnd')")
    assert at != -1
    branch = body[at:at + 600]
    assert "Obj.ObjectId = ePort" in branch
    assert "PortObj.AutoSize" in branch and "PortObj.ConnectedEnd" in branch


# --------------------------------------------------------------------------
# the Python side forwards the new arguments
# --------------------------------------------------------------------------


def test_templates_write_values_through_the_value_key():
    from eda_agent.tools import sch_template
    src = inspect.getsource(sch_template)
    assert 'fields["Value"] = str(p["value"])' in src
    assert 'fields["Comment"] = str(p["value"])' not in src
