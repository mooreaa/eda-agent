# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""sch_place_components puts a part on the footprint it names (2026-10-24).

Gen_PlaceSchComponentsFromLibrary read the ``footprint`` field of each
placement and dropped it, so a part always came out on whichever PCB model
its library marks current. On AD 25.8 an NMOS from Mosfet.SchLib asked for
on ``PowerPAK SC-70 (S)`` was placed with ``IsCurrent=T`` still on
LFPAK33-8, one of its twenty models, and FootprintPinMap, which maps the
CURRENT model, then wrote LFPAK33-8's map.

Now the name must be one of the symbol's own PCBLIB models (case aside),
and that model becomes the only current one: every other PCBLIB model is
cleared, it is set, and every flag is read back. A name the symbol lacks is
refused before the part is placed (FOOTPRINT_NOT_ON_SYMBOL, the names it
has in ``footprint_hint``), and a choice that does not read back takes the
part off the sheet again (FOOTPRINT_NOT_APPLIED).

The one Altium name written, ISch_Implementation.IsCurrent (read
GetState_IsCurrent, write SetState_IsCurrent), is in the script engine's
property table in ScriptingSystem.dll next to MapAsString, and on
SCH.ISch_Implementation in Altium.SDK.Interfaces.dll; Library.pas already
writes it both ways.

The selection is also run: a line-for-line Python mirror of the three
helpers against implementations whose setter behaves in each way Altium's
might, since which of those it is has not been measured.
"""
from __future__ import annotations

import re

import pytest

from tests.test_sch_properties_match_their_interface import (
    _decommented, _routine, _source)

HANDLER = "Gen_PlaceSchComponentsFromLibrary"


def _in_order(text, *needles):
    at = []
    start = 0
    for n in needles:
        i = text.index(n, start)
        at.append(i)
        start = i + len(n)
    return at


def _assert_handler(code):
    body = _routine(code, HANDLER)
    at = _in_order(body,
                   "Footprint := GetBatchField(Op, 'footprint');",
                   "Comp := SchServer.LoadComponentFromLibrary(LibRef, LibPath);",
                   "If FootprintModelIndex(Comp, Footprint, FpNames) < 0 Then",
                   ":FOOTPRINT_NOT_ON_SYMBOL'",
                   "Continue;",
                   "PutLoadedComponent(SchDoc, Comp, X, Y, Rotation, Desig);",
                   "If Not SelectPlacedFootprint(Comp, Footprint) Then",
                   "SchDoc.RemoveSchObject(Comp);",
                   ":FOOTPRINT_NOT_APPLIED'",
                   "Continue;",
                   "Inc(FpChosen);",
                   "Inc(Placed);",
                   "',\"footprints_chosen\":'",
                   "',\"footprint_hint\":\"'")
    # Both footprint steps run only when a footprint was asked for.
    assert re.search(r"If Footprint <> '' Then\s+If FootprintModelIndex\(", body)
    assert re.search(r"If Footprint <> '' Then\s+Begin\s+If Not SelectPlacedFootprint\(",
                     body)
    # The refusal sits before the part reaches the sheet.
    assert at[3] < at[5]
    assert body.count("PutLoadedComponent(") == 1


def _assert_index(code):
    body = _routine(code, "FootprintModelIndex")
    _in_order(body, "Result := -1;", "Names := '';",
              "If UpperCase(MT) = 'PCBLIB' Then",
              "Names := Names + MN;",
              "If SameText(Trim(MN), Trim(Name)) Then Result := K;",
              "Inc(K);")
    assert "Impl : ISch_Implementation;" in body
    assert "Impl.ModelName :=" not in body and ".IsCurrent :=" not in body


def _assert_make_current(code):
    body = _routine(code, "MakeFootprintModelCurrent")
    _in_order(body,
              "Result := False;",
              "If ModelIdx < 0 Then Exit;",
              "For Pass := 0 To 2 Do",
              "If UpperCase(MT) = 'PCBLIB' Then",
              "If (Pass = 0) And (K <> ModelIdx) Then",
              "SchBeginModify(Impl);",
              "Try Impl.IsCurrent := False; Except End;",
              "SchEndModify(Impl);",
              "Else If (Pass = 1) And (K = ModelIdx) Then",
              "SchBeginModify(Impl);",
              "Try Impl.IsCurrent := True; Except End;",
              "SchEndModify(Impl);",
              "Else If Pass = 2 Then",
              "Try IsCur := Impl.IsCurrent; Except End;",
              "If IsCur Then Inc(Currents);",
              "If IsCur And (K = ModelIdx) Then TargetCur := True;",
              "Inc(K);",
              "Result := TargetCur And (Currents = 1);")
    assert "Impl : ISch_Implementation;" in body


def _assert_select(code):
    body = _routine(code, "SelectPlacedFootprint")
    _in_order(body,
              "ModelIdx := FootprintModelIndex(Comp, Name, Names);",
              "Result := MakeFootprintModelCurrent(Comp, ModelIdx);",
              "If Not Result Then Exit;",
              "Impl := CurrentFootprintImpl(Comp);",
              "Try Back := Impl.ModelName; Except End;",
              "Result := SameText(Trim(Back), Trim(Name));")


def _assert_all(code):
    _assert_handler(code)
    _assert_index(code)
    _assert_make_current(code)
    _assert_select(code)


def test_the_placement_chooses_the_footprint_it_was_given():
    _assert_all(_source())


def test_the_footprint_is_no_longer_dropped():
    body = _routine(_source(), HANDLER)
    assert "Footprint override skipped" not in _source()
    # Read, and then used: more than the one assignment.
    assert len(re.findall(r"\bFootprint\b", body)) > 2


def test_helpers_are_defined_before_the_handler():
    """DelphiScript resolves names top-down and has no Forward."""
    code = _source()
    names = ["CurrentFootprintImpl", "FootprintModelIndex", "MakeFootprintModelCurrent",
             "SelectPlacedFootprint", HANDLER]
    at = [re.search(rf"(?m)^Function {n}\b", code).start() for n in names]
    assert at == sorted(at)
    for n in names[1:4]:
        assert len(re.findall(rf"(?m)^Function {n}\b", code)) == 1


def test_is_current_is_written_only_through_a_typed_implementation():
    """A component has no IsCurrent; only the typed local may carry it."""
    code = _decommented(_source())
    assert set(re.findall(r"(\w+)\.IsCurrent\s*:=", code)) == {"Impl"}


def test_the_tool_documents_and_escapes_the_footprint(monkeypatch):
    import asyncio

    from eda_agent.tools import generic as g

    sent = {}

    class Bridge:
        async def send_command_async(self, command, params=None, **kw):
            sent[command] = params
            return {"placed": 1}

    captured = {}

    class Mcp:
        def tool(self):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    monkeypatch.setattr(g, "get_bridge", lambda: Bridge())
    g.register_generic_tools(Mcp())
    place = captured["sch_place_components"]
    assert "FOOTPRINT_NOT_ON_SYMBOL" in place.__doc__
    asyncio.run(place([{"lib_reference": "NMOS", "library_path": "L.SchLib",
                        "designator": "Q1", "footprint": "PowerPAK SC-70 (S)"},
                       {"lib_reference": "NMOS", "library_path": "L.SchLib",
                        "designator": "Q2", "footprint": "A;x=99"}]))
    ops = sent["generic.place_sch_components_from_library"]["placements"].split("~~")
    assert ops[0].endswith(";footprint=PowerPAK SC-70 (S)")
    assert ops[1].endswith(";footprint=A,x=99")


_MUTATIONS = {
    "dropped_again": (HANDLER, "If Not SelectPlacedFootprint(Comp, Footprint) Then",
                      "If False Then"),
    "no_refusal": (HANDLER, "If FootprintModelIndex(Comp, Footprint, FpNames) < 0 Then",
                   "If False Then"),
    "left_on_sheet": (HANDLER, "Try SchDoc.RemoveSchObject(Comp); Except End;", ""),
    "others_kept": ("MakeFootprintModelCurrent",
                    "Try Impl.IsCurrent := False; Except End;", ""),
    "no_read_back": ("MakeFootprintModelCurrent",
                     "Result := TargetCur And (Currents = 1);", "Result := True;"),
    "two_current": ("MakeFootprintModelCurrent", "(Currents = 1)", "(Currents >= 1)"),
    "any_model_type": ("MakeFootprintModelCurrent",
                       "If UpperCase(MT) = 'PCBLIB' Then", "If True Then"),
    "no_name_check": ("SelectPlacedFootprint",
                      "Result := SameText(Trim(Back), Trim(Name));", ""),
    "case_sensitive": ("FootprintModelIndex",
                       "If SameText(Trim(MN), Trim(Name)) Then", "If MN = Name Then"),
}


@pytest.mark.parametrize("mutation", sorted(_MUTATIONS))
def test_the_checks_detect_each_removed_safeguard(mutation):
    routine, old, new = _MUTATIONS[mutation]
    code = _source()
    start = re.search(rf"(?m)^Function {routine}\b", code).start()
    at = code.index(old, start)
    mutant = code[:at] + new + code[at + len(old):]
    with pytest.raises((AssertionError, ValueError)):
        _assert_all(mutant)


# ---------------------------------------------------------------------------
# The selection, run against implementations that behave as Altium might.
# ---------------------------------------------------------------------------

class Impl:
    """One eImplementation child. ``setter`` is how IsCurrent := behaves:
    'plain' sets the flag, 'exclusive' also clears the other models of the
    same type (as the PCB Model list does), 'ignores' drops the write, and
    'promotes' makes another PCBLIB model current when the current one is
    cleared."""

    def __init__(self, siblings, model_type, name, current=False, setter="plain"):
        self.siblings, self.model_type, self.model_name = siblings, model_type, name
        self._current, self.setter = current, setter
        self.writes = 0

    @property
    def is_current(self):
        return self._current

    @is_current.setter
    def is_current(self, value):
        self.writes += 1
        if self.setter == "ignores":
            return
        if self.setter == "promotes" and self._current and not value:
            self._current = False
            for other in self.siblings:
                if other is not self and other.model_type.upper() == "PCBLIB":
                    other._current = True
                    break
            return
        if self.setter == "exclusive" and value:
            for other in self.siblings:
                if other.model_type == self.model_type:
                    other._current = False
        self._current = value


NMOS_MODELS = ["LFPAK33-8", "SOT-23", "SOT-323", "SOT-523", "SOT-723", "SC-89",
               "DFN1006-3", "PowerPAK SC-70 (S)", "PowerPAK SC-70 (D)", "TSOP-6",
               "SOT-363", "SOT-563", "PowerPAK 1212-8", "PowerPAK SO-8", "SO-8",
               "DPAK", "D2PAK", "TO-220", "TO-252", "WDFN-6"]


def _part(names=NMOS_MODELS, current="LFPAK33-8", setter="plain", extra=()):
    impls = []
    for kind, name, cur in extra:
        impls.append(Impl(impls, kind, name, cur, setter))
    for name in names:
        impls.append(Impl(impls, "PCBLIB", name, name == current, setter))
    return impls


def current_footprint_impl(impls):
    """Mirror: Generic.pas CurrentFootprintImpl."""
    first = None
    for impl in impls:
        if impl.model_type.upper() == "PCBLIB":
            if first is None:
                first = impl
            if impl.is_current:
                return impl
    return first


def footprint_model_index(impls, name):
    """Mirror: Generic.pas FootprintModelIndex. Returns (index, names)."""
    result, names, k = -1, "", 0
    for impl in impls:
        if impl.model_type.upper() == "PCBLIB":
            mn = impl.model_name
            if names != "":
                names += ", "
            names += mn
            if result < 0:
                if mn.strip().lower() == name.strip().lower():
                    result = k
            k += 1
    return result, names


def make_footprint_model_current(impls, model_idx):
    """Mirror: Generic.pas MakeFootprintModelCurrent."""
    if model_idx < 0:
        return False
    currents, target_cur = 0, False
    for pass_ in range(3):
        k = 0
        for impl in impls:
            if impl.model_type.upper() == "PCBLIB":
                if pass_ == 0 and k != model_idx:
                    impl.is_current = False
                elif pass_ == 1 and k == model_idx:
                    impl.is_current = True
                elif pass_ == 2:
                    cur = impl.is_current
                    if cur:
                        currents += 1
                    if cur and k == model_idx:
                        target_cur = True
                k += 1
    return target_cur and currents == 1


def select_placed_footprint(impls, name):
    """Mirror: Generic.pas SelectPlacedFootprint."""
    model_idx, _ = footprint_model_index(impls, name)
    if not make_footprint_model_current(impls, model_idx):
        return False
    impl = current_footprint_impl(impls)
    back = impl.model_name if impl is not None else ""
    return back.strip().lower() == name.strip().lower()


def _currents(impls, kind="PCBLIB"):
    return [i.model_name for i in impls if i.model_type == kind and i.is_current]


@pytest.mark.parametrize("setter", ["plain", "exclusive"])
def test_the_named_model_becomes_the_only_current_one(setter):
    """The run that found it: twenty models, LFPAK33-8 current."""
    part = _part(setter=setter)
    assert select_placed_footprint(part, "PowerPAK SC-70 (S)")
    assert _currents(part) == ["PowerPAK SC-70 (S)"]
    assert current_footprint_impl(part).model_name == "PowerPAK SC-70 (S)"


def test_the_name_matches_regardless_of_case_and_spaces():
    part = _part()
    assert select_placed_footprint(part, "  powerpak sc-70 (s) ")
    assert _currents(part) == ["PowerPAK SC-70 (S)"]


def test_a_model_the_symbol_lacks_is_found_missing_and_nothing_is_written():
    part = _part()
    index, names = footprint_model_index(part, "SOT-89")
    assert index == -1
    assert names.split(", ") == NMOS_MODELS
    assert not select_placed_footprint(part, "SOT-89")
    assert sum(i.writes for i in part) == 0
    assert _currents(part) == ["LFPAK33-8"]


def test_a_symbol_with_no_footprint_model_names_none():
    part = _part(names=[], extra=[("SIM", "NMOS", True)])
    assert footprint_model_index(part, "SOT-23") == (-1, "")
    assert not select_placed_footprint(part, "SOT-23")


def test_other_model_types_keep_their_current_model():
    part = _part(extra=[("SIM", "2N7002", True), ("SI", "IBIS", True)])
    assert select_placed_footprint(part, "SOT-23")
    assert _currents(part) == ["SOT-23"]
    assert _currents(part, "SIM") == ["2N7002"] and _currents(part, "SI") == ["IBIS"]
    assert all(i.writes == 0 for i in part if i.model_type != "PCBLIB")


def test_a_duplicated_name_chooses_the_first_and_clears_the_second():
    part = _part(names=["SOT-23", "SO-8", "SOT-23"], current="SO-8")
    assert select_placed_footprint(part, "SOT-23")
    assert [i.is_current for i in part] == [True, False, False]


def test_the_model_already_current_stays_the_only_one():
    part = _part(names=["SOT-23", "SO-8"], current="SOT-23")
    part[1]._current = True                      # two current, as a bad library has
    assert select_placed_footprint(part, "SOT-23")
    assert _currents(part) == ["SOT-23"]


@pytest.mark.parametrize("setter", ["ignores", "promotes"])
def test_a_choice_that_does_not_hold_is_reported(setter):
    """Not claimed: the handler then takes the part off the sheet."""
    part = _part(setter=setter)
    assert not select_placed_footprint(part, "PowerPAK SC-70 (S)")
