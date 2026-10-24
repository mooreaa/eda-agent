# SPDX-License-Identifier: Apache-2.0
"""FontId on a sheet entry stopped the bridge (AD25, 2026-10-23).

``obj_query(object_type="eSheetEntry", properties="Name,FontId")`` raised
"Undeclared identifier: FontId" as a modal and the polling loop stopped:
ISch_SheetEntry has no FontId. Its label font is TextFontID
(GetState_TextFontID / SetState_TextFontID in Altium.Sch.Interfaces.dll,
and the SchDoc record field is TextFontID), shared with ISch_HarnessEntry.

These tests pin the guard in the getter, the setter and the preflight, and
check that the new TextFontId property only touches the typed entry locals.
"""
from __future__ import annotations

import re

import pytest

from tests.test_sch_properties_match_their_interface import _routine, _source


def _branch(body, prop):
    branch = body.split(f"Else If PropName = '{prop}' Then", 1)[1]
    return re.split(r"\bElse If PropName\b", branch, maxsplit=1)[0]


def _assert_fontid_access(code):
    capability = _routine(code, "SchObjectHasFontId")
    assert "Result := True" in capability and "Result := False" in capability
    denied = set(re.findall(r"Obj\.ObjectId = (e\w+)", capability))
    assert {"eSheetEntry", "eHarnessEntry"} <= denied
    for routine, diag in (("GetSchProperty", "unreadable"), ("SetSchProperty", "unknown")):
        body = _routine(code, routine)
        fb = _branch(body, "FontId")
        guard = fb.index("If SchObjectHasFontId(Obj) Then")
        assert guard < fb.index("Obj.FontId")
        assert f"NotePropertyDiag('{diag}', PropName)" in fb
        tb = _branch(body, "TextFontId")
        assert not re.search(r"\bObj\.TextFontID\b", tb)
        for local in ("EntryObj", "HarnessEntryObj"):
            assert tb.index(f"{local} := Obj") < tb.index(f"{local}.TextFontID")
        assert f"NotePropertyDiag('{diag}', PropName)" in tb
    pre = _routine(code, "UnsupportedSchProperty")
    assert "(PropName = 'FontId') And (Not SchObjectHasFontId(Obj))" in pre
    assert "(PropName = 'TextFontId')" in pre


def test_fontid_is_gated_and_entry_font_is_typed():
    _assert_fontid_access(_source())


@pytest.mark.parametrize("mutation", ["read_guard", "write_guard", "allow_entry", "preflight"])
def test_fontid_guard_detects_the_original_defect(mutation):
    code = _source()
    if mutation == "allow_entry":
        code = code.replace("If (Obj.ObjectId = eSheetEntry) Or (Obj.ObjectId = eHarnessEntry)",
                            "If (Obj.ObjectId = eHarnessEntry)", 1)
    elif mutation == "preflight":
        code = code.replace("Or ((PropName = 'FontId') And (Not SchObjectHasFontId(Obj)))", "", 1)
    else:
        routine = "GetSchProperty" if mutation == "read_guard" else "SetSchProperty"
        start = code.index(f"Function {routine}(")
        code = code[:start] + code[start:].replace("If SchObjectHasFontId(Obj) Then", "If True Then", 1)
    with pytest.raises((AssertionError, ValueError)):
        _assert_fontid_access(code)
