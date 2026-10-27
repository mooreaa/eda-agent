# SPDX-License-Identifier: Apache-2.0
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

@pytest.mark.parametrize("handler,kind,write", [
    ("Gen_PlacePort", "ePort", "SchPort.FontId := FontToUse"),
    ("Gen_PlacePowerPort", "ePowerObject", "PowerObj.FontId := FontToUse"),
    ("Gen_PlaceTextFrame", "eTextFrame", "TF.FontId := FontToUse"),
    ("Gen_PlaceSheetEntry", "eSheetEntry", "Entry.TextFontID := FontToUse"),
])
def test_new_objects_take_the_sheets_font(funcs, handler, kind, write):
    body = funcs[handler]
    ask = body.find(f"PlacementFontId(SchDoc, {kind}, Params)")
    made = body.find("SchObjectFactory(")
    assert ask != -1, f"{handler} no longer picks a font for the new object"
    assert ask < made, (
        f"{handler} must read the sheet's font BEFORE creating the object: "
        f"read after, the new object votes for Times itself")
    assert write in body


def test_the_font_falls_back_to_the_net_labels(funcs):
    body = funcs["InferSheetFontFor"]
    assert "VoteSheetFonts(SchDoc, eNetLabel" in body
    assert "font_id" in funcs["PlacementFontId"], "an explicit font_id must win"


def test_a_sheet_entry_font_is_read_as_textfontid(funcs):
    """FontId on a sheet entry is an undeclared identifier (stops the bridge)."""
    body = funcs["VoteSheetFonts"]
    assert "EntryObj.TextFontID" in body
    assert "SchObjectHasFontId(Obj)" in body


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

def test_tidy_runs_on_every_placed_part(funcs):
    body = funcs["Gen_PlaceSchComponentsFromLibrary"]
    tidy = body.find("TidyPlacedComponent(Comp, LinkName, LibRef, DesigFont)")
    placed = body.rfind("Inc(Placed)")
    assert -1 < tidy < placed
    assert "<> 'false'" in body, "tidy is on unless the caller turns it off"
    assert body.find("InferSheetFontFor(SchDoc, eDesignator") < body.find(
        "LoadComponentFromLibrary"), "the designator font is read before any part lands"
    assert body.find("LinkName := ExtractFileName(LibPath)") < body.find(
        "ResolveSchLibForLoad"), "the link names the library the caller gave"


def test_tidy_links_hides_and_sets_the_font(funcs):
    body = funcs["TidyPlacedComponent"]
    for write in ("Comp.SourceLibraryName := LibName", "Comp.UseLibraryName := True",
                  "Comp.DesignItemId := LibRef", "Param.IsHidden := True",
                  "Comp.Designator.FontId := DesigFont"):
        assert write in body, write
    # The component's own parameters are the first level; only the ones
    # below it (the model's) are hidden.
    assert "SetState_IterationDepth(eIterateFirstLevel)" in body
    assert "Own.IndexOf(IntToStr(Addr)) < 0" in body


def test_value_also_writes_the_value_parameter(funcs):
    body = funcs["Gen_SetSchComponentsParameters"]
    at = body.find("If Key = 'Value' Then")
    assert at != -1
    assert "SetExistingCompParamText(Comp, 'Value', Val)" in body[at:at + 600]


def test_a_created_parameter_is_hidden(funcs):
    body = funcs["SetCompParamText"]
    assert "NewParam.IsHidden := True" in body
    assert body.find("NewParam.IsHidden := True") < body.find("Comp.AddSchObject(NewParam)")


def test_setting_an_existing_parameter_never_creates_one(funcs):
    body = funcs["SetExistingCompParamText"]
    assert "SchObjectFactory" not in body


# --------------------------------------------------------------------------
# pin queries see only live pins; port properties
# --------------------------------------------------------------------------

def test_a_sheet_pin_query_skips_hidden_copies(funcs):
    body = funcs["ProcessSchDocObjects"]
    assert ("(ObjTypeInt = ePin) And (Not IsLibDoc) And "
            "(Pos('OwnerPart', FilterStr) = 0)") in body
    assert "(Not Skip) And MatchesFilter(Obj, FilterStr)" in body
    assert "DeadPins.Free" in body
    dead = funcs["DeadPinAddresses"]
    assert "PinShownOn(Comp, Pin)" in dead
    assert "OwnerPartDisplayMode" in dead


@pytest.mark.parametrize("routine", ["GetSchProperty", "SetSchProperty"])
def test_port_autosize_and_connected_end_are_port_only(funcs, routine):
    body = funcs[routine]
    at = body.find("(PropName = 'AutoSize') Or (PropName = 'ConnectedEnd')")
    assert at != -1
    branch = body[at:at + 900]
    assert "Obj.ObjectId = ePort" in branch
    assert "PortObj.AutoSize" in branch and "PortObj.ConnectedEnd" in branch


def test_port_properties_are_refused_on_other_types(funcs):
    body = funcs["UnsupportedSchProperty"]
    assert "(PropName = 'AutoSize') Or (PropName = 'ConnectedEnd')" in body


# --------------------------------------------------------------------------
# the Python side forwards the new arguments
# --------------------------------------------------------------------------

def test_tools_forward_the_new_arguments():
    from eda_agent.tools import generic as g
    src = inspect.getsource(g)
    for needle in ('"width": str(int(width))', '"font_id": str(int(font_id))',
                   '"tidy": "true" if tidy else "false"',
                   "fields.append(f\"part_id={int(p['part_id'])}\")"):
        assert needle in src, needle
    assert "part_id" in g.PLACEMENT_KEYS


def test_templates_write_values_through_the_value_key():
    from eda_agent.tools import sch_template
    src = inspect.getsource(sch_template)
    assert 'fields["Value"] = str(p["value"])' in src
    assert 'fields["Comment"] = str(p["value"])' not in src
