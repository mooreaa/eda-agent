# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""One spelling for a document path, including inside a process string.

Altium keys an open document by the path text it was opened with.
``CanonicalPathValue`` in Main.pas already rewrites a value under a JSON
key ending in "path", so ``file_path`` and ``library_path`` arrive with
backslashes. It cannot see a path inside a process parameter string,
though: ``sch_template._focus`` opened a library it could not focus with
``WorkspaceManager:OpenObject`` and ``ObjectKind=Document|FileName=R:/...``
built from the caller's path. Altium filed that copy as
"/Hardware/Parts Library/Generic/Passive.SchLib", a second document beside
the real one: it read as modified, every reload raised "Save changes?",
and AutoSave failed on the path it built from that name (AD25, 2026-10-23).

So the bridge also rewrites ``FileName=`` in the ``parameters`` / ``params``
string of a process call, and lists under a key ending in "paths". The rule
is the Pascal one exactly: an absolute drive or UNC path has its forward
slashes turned into backslashes and nothing else, so a menu path such as
"File|Open", a relative name, and a directory's trailing separator all
pass through unchanged.
"""
from __future__ import annotations

import ntpath
import os
import re
from typing import Any

_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2})")

#: A FileName field of a pipe-separated process parameter string.
_FILENAME_FIELD = re.compile(r"(?i)(?<![^|])(FileName=)([^|]*)")

#: Keys whose string value is a pipe-separated process parameter string
#: (``application.run_process`` and ``generic.run_process``).
_PROCESS_KEYS = ("parameters", "params")


def is_windows_path(value: Any) -> bool:
    return isinstance(value, str) and bool(_ABSOLUTE.match(value))


def normalize_doc_path(value: Any) -> Any:
    """``value`` with backslashes if it is an absolute Windows path."""
    if not is_windows_path(value):
        return value
    return value.replace("/", "\\")


def _process_string(text: str) -> str:
    return _FILENAME_FIELD.sub(
        lambda m: m.group(1) + normalize_doc_path(m.group(2)), text)


def normalize_params(params: Any) -> Any:
    """A copy of a request's params with every document path in one spelling.

    A key ending in "path" (any case, as CanonicalPathValue matches it), a
    list under a key ending in "paths", and the FileName field of a process
    parameter string, at any depth: template parts carry a ``library_path``
    each."""
    if isinstance(params, dict):
        out = {}
        for k, v in params.items():
            key = k.lower() if isinstance(k, str) else ""
            if key.endswith("path"):
                out[k] = normalize_doc_path(v)
            elif key.endswith("paths") and isinstance(v, list):
                out[k] = [normalize_doc_path(x) for x in v]
            elif key in _PROCESS_KEYS and isinstance(v, str):
                out[k] = _process_string(v)
            else:
                out[k] = normalize_params(v)
        return out
    if isinstance(params, list):
        return [normalize_params(v) for v in params]
    return params


def same_file(a: str, b: str) -> bool:
    """True if two paths name one file, even through different drive
    letters mapped to the same share (os.path.samefile compares the volume
    serial and file index on Windows). Falls back to a case-insensitive
    comparison of the normalised strings when either cannot be stat'ed."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return ntpath.normcase(ntpath.normpath(a)) == ntpath.normcase(ntpath.normpath(b))
