# SPDX-License-Identifier: Apache-2.0
"""Document paths reach Altium in backslash form, and an aliased open is reused.

``_focus`` opened a library with ``FileName=R:/Hardware/.../Passive.SchLib``
in an OpenObject parameter string, which CanonicalPathValue in Main.pas
never sees. Altium filed it as "/Hardware/.../Passive.SchLib": a phantom
copy that read as modified, raised save prompts and broke AutoSave (AD25,
2026-10-23).
"""
from __future__ import annotations

import asyncio

import pytest

from eda_agent.bridge import docpaths
from eda_agent.bridge.docpaths import normalize_doc_path, normalize_params
from eda_agent.tools import sch_template as tool


@pytest.mark.parametrize("raw, expected", [
    ("R:/Hardware/Parts Library/Generic/Passive.SchLib",
     "R:\\Hardware\\Parts Library\\Generic\\Passive.SchLib"),
    ("R:\\Hardware\\Generic\\Passive.SchLib", "R:\\Hardware\\Generic\\Passive.SchLib"),
    ("R:/Hardware\\Generic/Passive.SchLib", "R:\\Hardware\\Generic\\Passive.SchLib"),
    ("//server/share/lib/X.SchLib", "\\\\server\\share\\lib\\X.SchLib"),
    ("R:/out/", "R:\\out\\"),                  # a directory keeps its separator
])
def test_absolute_windows_paths_become_backslash_form(raw, expected):
    assert normalize_doc_path(raw) == expected


@pytest.mark.parametrize("value", ["File|Open", "Passive.SchLib", "", None, 3, "relative/dir/x.SchDoc"])
def test_other_values_pass_through(value):
    assert normalize_doc_path(value) == value


def test_params_are_normalised_by_key_including_nested_parts():
    params = {
        "file_path": "R:/a/b.SchDoc",
        "ProjectPath": "R:/a/p.PrjPcb",
        "menu_path": "File|Open",
        "template": {"parts": [{"designator": "R1", "library_path": "R:/lib/Passive.SchLib"}]},
        "file_paths": ["R:/a/1.SchDoc", "R:/a/2.SchDoc"],
        "comment": "R:/a/b.SchDoc",
    }
    out = normalize_params(params)
    assert out["file_path"] == "R:\\a\\b.SchDoc"
    assert out["ProjectPath"] == "R:\\a\\p.PrjPcb"
    assert out["menu_path"] == "File|Open"
    assert out["template"]["parts"][0]["library_path"] == "R:\\lib\\Passive.SchLib"
    assert out["file_paths"] == ["R:\\a\\1.SchDoc", "R:\\a\\2.SchDoc"]
    assert out["comment"] == "R:/a/b.SchDoc"                   # not a path key
    assert params["file_path"] == "R:/a/b.SchDoc"              # input left alone


@pytest.mark.parametrize("key", ["parameters", "params"])
def test_filename_inside_a_process_string_is_normalised(key):
    out = normalize_params({key: "ObjectKind=Document|FileName=R:/a/b.SchLib|Mode=1"})
    assert out[key] == "ObjectKind=Document|FileName=R:\\a\\b.SchLib|Mode=1"
    first = normalize_params({key: "filename=//srv/x/y.PcbLib"})
    assert first[key] == "filename=\\\\srv\\x\\y.PcbLib"


@pytest.mark.parametrize("text", [
    "ObjectKind=Document|FileName=b.SchLib",          # relative: untouched
    "Action=Open|DestFileName=R:/a/b.SchLib",         # another field
    "Expr=a/b",
])
def test_other_process_fields_pass_through(text):
    assert normalize_params({"parameters": text})["parameters"] == text


class FakeBridge:
    def __init__(self, open_docs, loaded):
        self.open_docs, self.loaded, self.sent = open_docs, set(loaded), []

    async def send_command_async(self, command, params=None, **kw):
        self.sent.append((command, dict(params or {})))
        if command == "application.set_active_document":
            if params["file_path"] in self.loaded:
                return {"success": True, "file_path": params["file_path"]}
            return {"success": False, "error": "Document not loaded"}
        if command == "application.get_open_documents":
            return self.open_docs
        if command == "application.run_process":
            return {"success": True}
        return {"success": True}


def test_focus_opens_with_backslash_path():
    lib = "R:\\Hardware\\Generic\\Passive.SchLib"
    bridge = FakeBridge([], loaded=[])
    asyncio.run(tool._focus(bridge, "R:/Hardware/Generic/Passive.SchLib"))
    opened = [p for c, p in bridge.sent if c == "application.run_process"]
    assert opened and f"FileName={lib}" in opened[0]["parameters"]
    assert all(p.get("file_path", lib) == lib for c, p in bridge.sent
               if c == "application.set_active_document")


def test_focus_reuses_a_document_open_under_another_drive_letter(monkeypatch):
    open_name = "R:\\Hardware\\Generic\\Passive.SchLib"
    asked = "M:\\SCM\\Hardware\\Generic\\Passive.SchLib"
    monkeypatch.setattr(tool, "same_file", lambda a, b: {a, b} == {open_name, asked})
    bridge = FakeBridge([{"file_path": open_name, "loaded": True}], loaded=[open_name])
    reply = asyncio.run(tool._focus(bridge, asked))
    assert reply["success"] is True
    assert not any(c == "application.run_process" for c, _ in bridge.sent)


def test_same_file_falls_back_to_normalised_comparison():
    assert docpaths.same_file("Z:/nope/A.SchLib", "z:\\NOPE\\a.schlib")
    assert not docpaths.same_file("Z:/nope/A.SchLib", "Z:/nope/B.SchLib")
