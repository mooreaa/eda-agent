# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""DisplayMode and FootprintPinMap on a placed component (2026-10-24).

House schematic style draws every MOSFET on the generic NMOS symbol in its
compact alternate (display mode 1) and maps its lettered pins to numbered
pads through the footprint model's pin map. The bridge could read neither
and write neither, so both were set by hand (Properties -> Mode, and the
PCB Model dialog).

The names are Altium's, confirmed in the script engine's property table
(ScriptingSystem.dll), in Altium.SDK.Interfaces.dll and in the Schematic
API reference:

* ISch_Component.DisplayMode : TDisplayMode, read GetState_DisplayMode,
  write SetState_DisplayMode;
* ISch_Component.DisplayModeCount : Integer, read GetState_DisplayModeCount;
* ISch_Implementation.MapAsString : WideString, read GetState_MapAsString,
  write SetState_MapAsString, documented as '(SchematicPin:ModelPin)'
  entries such as '(1:1),(2:2)'.

On any type but a component these are undeclared identifiers, which raise
a modal Try/Except cannot contain and stop the polling loop, so these tests
pin the type guard in the getter, the setter and the preflight, the range
check on the mode, and the read-back and restore around the map write.

The map's string helpers are pure, so they are also run: as extracted
Pascal under FPC when it is installed, and through a line-for-line Python
mirror on the same cases otherwise.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

from tests.test_sch_properties_match_their_interface import (
    GENERIC, _decommented, _routine, _source)

GUARD = "If Obj.ObjectId = eSchComponent Then"
GET_MODE = "Else If (PropName = 'DisplayMode') Or (PropName = 'DisplayModeCount') Then"
SET_MODE = "Else If PropName = 'DisplayMode' Then"
MAP = "Else If PropName = 'FootprintPinMap' Then"
PREFLIGHT = re.compile(
    r"\(\(PropName = 'DisplayMode'\) Or \(PropName = 'DisplayModeCount'\)\s+"
    r"Or \(PropName = 'FootprintPinMap'\)\) And \(Obj\.ObjectId <> eSchComponent\)")


def _branch(body, header):
    assert header in body, f"missing branch {header!r}"
    tail = body.split(header, 1)[1]
    return re.split(r"\bElse If \(?PropName\b", tail, maxsplit=1)[0]


def _in_order(text, *needles):
    at = [text.index(n) for n in needles]
    assert at == sorted(at), f"out of order: {needles}"


def _assert_display_mode(code):
    get = _routine(code, "GetSchProperty")
    gb = _branch(get, GET_MODE)
    _in_order(gb, GUARD, "Comp := Obj", "Comp.DisplayMode")
    assert "Comp.DisplayModeCount" in gb
    assert "NotePropertyDiag('unreadable', PropName)" in gb
    assert not re.search(r"\bObj\.DisplayMode", gb)

    sb = _branch(_routine(code, "SetSchProperty"), SET_MODE)
    _in_order(sb, GUARD, "Comp := Obj", "ModeCount := Comp.DisplayModeCount",
              "(NewMode < 0) Or (NewMode >= ModeCount)", "WroteOK := False",
              "Comp.DisplayMode := NewMode", "WroteOK := (Comp.DisplayMode = NewMode)")
    assert "Matched := False" in sb
    assert not re.search(r"\bObj\.DisplayMode", sb)


def _assert_pin_map(code):
    gb = _branch(_routine(code, "GetSchProperty"), MAP)
    _in_order(gb, GUARD, "Comp := Obj", "ReadPlacedPinMap(Comp)")
    assert "NotePropertyDiag('unreadable', PropName)" in gb
    sb = _branch(_routine(code, "SetSchProperty"), MAP)
    _in_order(sb, GUARD, "Comp := Obj", "WroteOK := WritePlacedPinMap(Comp, Value)")
    assert "Matched := False" in sb

    write = _routine(code, "WritePlacedPinMap")
    _in_order(write,
              "If (Wanted = '') And (Trim(Value) <> '') Then Exit;",
              "If Impl = Nil Then Exit;",
              "Old := Impl.MapAsString;",
              "If Not HaveOld Then Exit;",
              "SchBeginModify(Impl);",
              "Impl.MapAsString := Wanted;",
              "SchEndModify(Impl);",
              "Back := Impl.MapAsString;",
              "Result := SamePinMap(Back, Wanted);",
              "If Not Result Then",
              "Impl.MapAsString := Old;")
    for name in ("ReadPlacedPinMap", "WritePlacedPinMap"):
        assert "Impl : ISch_Implementation;" in _routine(code, name)
    # MapAsString is reached only through the typed implementation local.
    assert set(re.findall(r"(\w+)\.MapAsString\b", _decommented(code))) == {"Impl"}


def _assert_preflight(code):
    assert PREFLIGHT.search(_routine(code, "UnsupportedSchProperty"))


def _assert_all(code):
    _assert_display_mode(code)
    _assert_pin_map(code)
    _assert_preflight(code)


def test_display_mode_and_pin_map_are_gated_and_typed():
    _assert_all(_source())


def test_helpers_are_defined_before_the_property_routines():
    """DelphiScript resolves names top-down and has no Forward."""
    code = _source()
    names = ["CurrentFootprintImpl", "PinMapAsAltium", "PinMapKey", "PinMapKeyWithin",
             "SamePinMap", "ReadPlacedPinMap", "WritePlacedPinMap",
             "GetSchProperty", "SetSchProperty", "SetPlacedFootprintLibrary"]
    at = [re.search(rf"(?m)^Function {n}\b", code).start() for n in names]
    assert at == sorted(at)
    assert len(re.findall(r"(?m)^Function CurrentFootprintImpl\b", code)) == 1


def test_nothing_writes_the_mode_count_or_opens_the_map_dialog():
    """The count comes from the symbol; Map_Import_FromUser is a dialog."""
    for path in sorted(GENERIC.parent.glob("*.pas")):
        if path.name == "Altium_MCP.pas":
            continue
        code = _decommented(path.read_text(encoding="utf-8", errors="replace"))
        assert not re.search(r"\.DisplayModeCount\s*:=", code), path.name
        for ident in ("SetState_DisplayModeCount_Check", "Map_Import_FromUser",
                      "DefinerByInterfaceDesignator"):
            assert ident not in code, f"{path.name} uses {ident}"


_MUTATIONS = {
    "read_guard": ("GetSchProperty", GET_MODE, GUARD, "If True Then"),
    "write_guard": ("SetSchProperty", SET_MODE, GUARD, "If True Then"),
    "range_check": ("SetSchProperty", SET_MODE,
                    "If (NewMode < 0) Or (NewMode >= ModeCount) Then", "If False Then"),
    "read_back": ("SetSchProperty", SET_MODE,
                  "WroteOK := (Comp.DisplayMode = NewMode);", "WroteOK := True;"),
    "untyped": ("SetSchProperty", SET_MODE,
                "Comp.DisplayMode := NewMode", "Obj.DisplayMode := NewMode"),
    "map_read_guard": ("GetSchProperty", MAP, GUARD, "If True Then"),
    "map_write_guard": ("SetSchProperty", MAP, GUARD, "If True Then"),
    "map_unread_old": ("WritePlacedPinMap", "Begin", "If Not HaveOld Then Exit;", ""),
    "map_no_restore": ("WritePlacedPinMap", "Begin",
                       "Try Impl.MapAsString := Old; Except End;", ""),
    "map_no_compare": ("WritePlacedPinMap", "Begin",
                       "Result := SamePinMap(Back, Wanted);", "Result := True;"),
    "preflight": ("UnsupportedSchProperty", "Begin",
                  "Or (PropName = 'FootprintPinMap')) And (Obj.ObjectId <> eSchComponent)",
                  "Or (PropName = 'FootprintPinMap')) And False"),
}


@pytest.mark.parametrize("mutation", sorted(_MUTATIONS))
def test_the_checks_detect_each_removed_safeguard(mutation):
    routine, anchor, old, new = _MUTATIONS[mutation]
    code = _source()
    start = re.search(rf"(?m)^Function {routine}\b", code).start()
    at = code.index(anchor, start)
    at = code.index(old, at)
    mutant = code[:at] + new + code[at + len(old):]
    with pytest.raises((AssertionError, ValueError)):
        _assert_all(mutant)


# ---------------------------------------------------------------------------
# The map's string helpers, run.
# ---------------------------------------------------------------------------

#: (value written, what PinMapAsAltium hands to MapAsString)
AS_ALTIUM = [
    ("G->1;D->2;S->3", "(G:1),(D:2),(S:3)"),
    (" G -> 1 ; D->2 ;", "(G:1),(D:2)"),
    ("G->1;;D->2", "(G:1),(D:2)"),
    ("D->2,5", "(D:2,5)"),
    ("(G:1),(D:2),(S:3)", "(G:1),(D:2),(S:3)"),
    ("  (1:1) ", "(1:1)"),
    ("", ""),
    ("G->;D->2", ""),
    ("->1", ""),
    ("G -> ", ""),
]

#: (read back, asked for, same?)
SAME = [
    ("(G:1),(D:2),(S:3)", "(S:3),(G:1),(D:2)", True),
    ("(G:1), (D:2)", "(G:1),(D:2)", True),
    ("(G:1),(D:2)", "(G:1),(D:3)", False),
    ("(G:1),(D:2)", "(G:1)", False),
    ("(G:1)", "(G:1),(D:2)", False),
    ("(G:1),(G:1)", "(G:1),(D:2)", False),
    ("", "", True),
    ("", "(G:1)", False),
    ("(G:1)", "", False),
    ("G=1 D=2", "G=1 D=2", True),
    ("G=1 D=2", "G=1", False),
]


def _pos(sub, s):
    return s.find(sub) + 1


def _copy(s, index, count):
    return s[index - 1:index - 1 + count] if index >= 1 else s[:count]


def pin_map_as_altium(value):
    """Mirror: Generic.pas PinMapAsAltium."""
    result = value.strip()
    if _pos("->", result) == 0:
        return result
    remaining, result = result, ""
    while remaining != "":
        sep = _pos(";", remaining)
        if sep > 0:
            entry = _copy(remaining, 1, sep - 1).strip()
            remaining = _copy(remaining, sep + 1, len(remaining))
        else:
            entry, remaining = remaining.strip(), ""
        if entry == "":
            continue
        arrow = _pos("->", entry)
        if arrow < 2 or arrow + 1 >= len(entry):
            return ""
        if result != "":
            result += ","
        result += ("(" + _copy(entry, 1, arrow - 1).strip() + ":"
                   + _copy(entry, arrow + 2, len(entry)).strip() + ")")
    return result


def pin_map_key(m):
    """Mirror: Generic.pas PinMapKey."""
    result, bare, entry, depth = ";", "", "", 0
    for ch in m:
        if ch != " ":
            bare += ch
            if ch == "(":
                depth, entry = 1, ""
            if depth > 0:
                entry += ch
            if ch == ")" and depth > 0:
                depth = 0
                result += entry + ";"
    if result == ";" and bare != "":
        result = ";" + bare + ";"
    return result


def pin_map_key_within(key_a, key_b):
    """Mirror: Generic.pas PinMapKeyWithin."""
    rest = _copy(key_a, 2, len(key_a))
    while rest != "":
        sep = _pos(";", rest)
        if sep == 0:
            break
        entry = _copy(rest, 1, sep - 1)
        rest = _copy(rest, sep + 1, len(rest))
        if _pos(";" + entry + ";", key_b) == 0:
            return False
    return True


def same_pin_map(a, b):
    """Mirror: Generic.pas SamePinMap."""
    ka, kb = pin_map_key(a), pin_map_key(b)
    return pin_map_key_within(ka, kb) and pin_map_key_within(kb, ka)


@pytest.mark.parametrize("value,expected", AS_ALTIUM)
def test_pin_map_is_written_in_altiums_form(value, expected):
    assert pin_map_as_altium(value) == expected


@pytest.mark.parametrize("back,wanted,same", SAME)
def test_read_back_is_compared_as_a_set_of_entries(back, wanted, same):
    assert same_pin_map(back, wanted) is same


def test_what_is_written_reads_back_as_itself():
    for value, expected in AS_ALTIUM:
        assert same_pin_map(expected, pin_map_as_altium(value))


def test_extracted_pin_map_helpers_under_fpc(tmp_path):
    """The shipped routines, compiled; not a claim about Altium's engine."""
    fpc = shutil.which("fpc")
    if not fpc:
        pytest.skip("Free Pascal Compiler (fpc) is not installed or not on PATH")
    source = _source()
    routines = "\n".join(_routine(source, name) for name in
                         ("PinMapAsAltium", "PinMapKey", "PinMapKeyWithin", "SamePinMap"))
    checks = [f"  if PinMapAsAltium('{v}') <> '{e}' then Halt({i});"
              for i, (v, e) in enumerate(AS_ALTIUM, 1)]
    base = len(checks)
    checks += [f"  if SamePinMap('{b}', '{w}') <> {str(s)} then Halt({base + i});"
               for i, (b, w, s) in enumerate(SAME, 1)]
    program = ("program pin_map_helpers;\n{$mode delphi}\nuses SysUtils;\n" + routines
               + "\nbegin\n" + "\n".join(checks) + "\nend.\n")
    path = tmp_path / "pin_map_helpers.pas"
    path.write_text(program, encoding="utf-8")
    compiled = subprocess.run([fpc, str(path)], cwd=tmp_path, capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    exe = tmp_path / ("pin_map_helpers.exe" if os.name == "nt" else "pin_map_helpers")
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    assert result.returncode == 0, f"case {result.returncode} failed"
