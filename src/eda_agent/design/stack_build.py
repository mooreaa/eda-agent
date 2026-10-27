# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""Plan a whole PCB layer stack as AD19+ stack edits, and check the result.

``pcb_build_stack`` takes the copper and dielectric layers top to bottom and
turns them into ``pcb.stack_edit`` operations on the MasterLayerStack, where a
dielectric is a layer of its own. The older route, LayerStack_V7 with one
"dielectric below" per copper layer, read back as intended on AD 25.8.1 while
the real stack came out corrupt (Rosen controller, 2026-10-27).

The plan keeps the top and bottom copper objects (renamed and re-thicknessed)
and replaces everything between them, so the result does not depend on how
the old stack was laid out. A layer between them that carries primitives is
refused by the script, never deleted with its contents.
"""
from __future__ import annotations

from typing import Any

#: Altium's dielectric type numbers.
DIELECTRIC_TYPE_NUMBERS = {"none": 0, "core": 1, "prepreg": 2, "surface_material": 3}

_TOL_MILS = 0.01


class StackPlanError(ValueError):
    pass


def _dielectric_type(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text.isdigit():
        return int(text)
    if text not in DIELECTRIC_TYPE_NUMBERS:
        raise StackPlanError(f"dielectric type {value!r}: use core or prepreg")
    return DIELECTRIC_TYPE_NUMBERS[text]


def normalise(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check a plan and fill in dielectric names; raise StackPlanError."""
    if not isinstance(plan, list) or len(plan) < 3:
        raise StackPlanError("a stack needs at least copper, dielectric, copper")
    out: list[dict[str, Any]] = []
    names: set[str] = set()
    dielectric_no = 0
    for i, raw in enumerate(plan):
        if not isinstance(raw, dict):
            raise StackPlanError(f"layer {i} is not an object")
        kind = str(raw.get("kind", "")).lower()
        if kind not in ("copper", "dielectric"):
            raise StackPlanError(f"layer {i}: kind is copper or dielectric")
        try:
            thickness = float(raw["thickness_mils"])
        except (KeyError, TypeError, ValueError):
            raise StackPlanError(f"layer {i}: thickness_mils is required") from None
        if thickness <= 0:
            raise StackPlanError(f"layer {i}: thickness_mils must be positive")
        entry: dict[str, Any] = {"kind": kind, "thickness_mils": thickness}
        if kind == "copper":
            name = str(raw.get("name", "")).strip()
            if not name:
                raise StackPlanError(f"layer {i}: a copper layer needs a name")
            entry["plane"] = bool(raw.get("plane", False))
        else:
            dielectric_no += 1
            name = str(raw.get("name", "")).strip() or f"Dielectric {dielectric_no}"
            entry["type"] = _dielectric_type(raw.get("type", "prepreg"))
            if "constant" in raw:
                entry["constant"] = float(raw["constant"])
            if raw.get("material"):
                entry["material"] = str(raw["material"])
        if name.upper() in names:
            raise StackPlanError(f"layer {i}: the name {name!r} is used twice")
        names.add(name.upper())
        entry["name"] = name
        out.append(entry)
    if out[0]["kind"] != "copper" or out[-1]["kind"] != "copper":
        raise StackPlanError("the stack starts and ends with copper")
    if out[0].get("plane") or out[-1].get("plane"):
        raise StackPlanError("top and bottom copper are signal layers")
    for upper, lower in zip(out, out[1:]):
        if upper["kind"] == "copper" and lower["kind"] == "copper":
            raise StackPlanError(f"no dielectric between {upper['name']} and {lower['name']}")
    return out


def board_section(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copper and dielectric layers from the top copper to the bottom copper."""
    copper = [i for i, layer in enumerate(layers) if layer.get("kind") == "copper"]
    if not copper:
        return []
    return [layer for layer in layers[copper[0]:copper[-1] + 1]
            if layer.get("kind") in ("copper", "dielectric")]


def plan_ops(current: list[dict[str, Any]], plan: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The stack_edit operations that turn the current stack into the plan.

    ``current`` is pcb_physical_stack's ``layers``; ``plan`` is normalised.
    """
    section = board_section(current)
    if len(section) < 2 or section[0]["kind"] != "copper" or section[-1]["kind"] != "copper":
        raise StackPlanError("the board has no top and bottom copper to build on")
    top, bottom, inner = section[0], section[-1], section[1:-1]
    ops: list[dict[str, str]] = []
    for layer in inner:
        ops.append({"op": "remove", "name": layer["name"]})
    # Rename the outer copper after the inner layers are gone, so a planned
    # name an old inner layer still held is free. A temporary name first
    # covers a plan that swaps the two outer names.
    for layer, temp in ((top, "__stack_top__"), (bottom, "__stack_bottom__")):
        ops.append({"op": "set_copper", "name": layer["name"], "new_name": temp})
    ops.append({"op": "set_copper", "name": "__stack_top__", "new_name": plan[0]["name"],
                "thickness_mils": f"{plan[0]['thickness_mils']:g}"})
    ops.append({"op": "set_copper", "name": "__stack_bottom__", "new_name": plan[-1]["name"],
                "thickness_mils": f"{plan[-1]['thickness_mils']:g}"})
    ref = plan[0]["name"]
    for layer in plan[1:-1]:
        op = {"op": "insert", "ref": ref, "where": "below", "name": layer["name"],
              "thickness_mils": f"{layer['thickness_mils']:g}"}
        if layer["kind"] == "dielectric":
            op["kind"] = "dielectric"
            op["type"] = str(layer["type"])
            if "constant" in layer:
                op["constant"] = f"{layer['constant']:g}"
            if "material" in layer:
                op["material"] = layer["material"]
        else:
            op["kind"] = "plane" if layer.get("plane") else "signal"
        ops.append(op)
        ref = layer["name"]
    return ops


def check(readback: list[dict[str, Any]], plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where the stack read back from Altium differs from the plan."""
    got = board_section(readback)
    out: list[dict[str, Any]] = []
    if len(got) != len(plan):
        out.append({"check": "count", "got": [g.get("name") for g in got],
                    "expected": [p["name"] for p in plan]})
        return out
    for i, (g, p) in enumerate(zip(got, plan)):
        if g.get("kind") != p["kind"]:
            out.append({"check": "kind", "order": i, "got": g.get("kind"), "expected": p["kind"]})
        if str(g.get("name", "")).upper() != p["name"].upper():
            out.append({"check": "name", "order": i, "got": g.get("name"), "expected": p["name"]})
        t = g.get("thickness_mils")
        if t is None or abs(float(t) - p["thickness_mils"]) > _TOL_MILS:
            out.append({"check": "thickness_mils", "order": i, "layer": p["name"],
                        "got": t, "expected": p["thickness_mils"]})
        if p["kind"] == "dielectric":
            if g.get("dielectric_type") is not None and int(g["dielectric_type"]) != p["type"]:
                out.append({"check": "type", "order": i, "layer": p["name"],
                            "got": g.get("dielectric_type"), "expected": p["type"]})
            if "constant" in p and (g.get("constant") is None
                                    or abs(float(g["constant"]) - p["constant"]) > 0.001):
                out.append({"check": "constant", "order": i, "layer": p["name"],
                            "got": g.get("constant"), "expected": p["constant"]})
    return out
