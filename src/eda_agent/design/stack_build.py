# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""Plan a whole PCB layer stack as stack edits, and check the result.

``pcb_build_stack`` takes the copper and dielectric layers top to bottom. The
older route, LayerStack_V7 with one "dielectric below" per copper layer, read
back as intended on AD 25.8.1 while the real stack came out corrupt (Rosen
controller, 2026-10-27). What was learnt on that build, live:

- a script cannot create a dielectric there: MasterLayerStack.CreateLayer gave
  Nil for every id tried;
- copper inserted through the V7 stack (InsertInStackBelow) lands below the
  reference layer's dielectrics, and Altium adds a dielectric under it in the
  physical stack by itself;
- MasterLayerStack.RemoveLayer, a layer's Name, CopperThickness and the
  dielectric layer's own fields (type, height, Dk, material) all write
  correctly.

So the build runs in two phases. Copper: existing inner planes and signal
layers are matched in order to planned ones of the same type and kept (a plane
keeps its contents), the rest removed, the outer copper renamed, and new
copper inserted top down, each below the copper planned above it. Dielectrics:
from the stack read back, each copper gap keeps as many of Altium's
dielectrics as the plan has there (extras removed) and each is set to the
plan's name, type, thickness, Dk and material. A gap with fewer dielectrics
than the plan is refused, since none can be added.
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
            if "loss_tangent" in raw:
                entry["loss_tangent"] = float(raw["loss_tangent"])
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


def copper_type(layer_id: Any) -> str:
    """'plane' or 'signal' from a layer id, AD19+ (0x101xxxx planes) or V7 (39-54)."""
    try:
        n = int(layer_id)
    except (TypeError, ValueError):
        return "signal"
    if n >> 16 == 0x101 or 39 <= n <= 54:
        return "plane"
    return "signal"


def plan_ops(current: list[dict[str, Any]], plan: list[dict[str, Any]],
             inspect: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """Phase one, copper: the stack_edit operations that give the plan's copper.

    ``current`` is pcb_physical_stack's ``layers``; ``plan`` is normalised;
    ``inspect`` is stack_edit inspect's ``layers`` (layer ids and whether
    primitives sit on each), without which every inner copper layer counts
    as a signal layer in use. Dielectrics are left for ``dielectric_ops``.
    """
    section = board_section(current)
    if len(section) < 2 or section[0]["kind"] != "copper" or section[-1]["kind"] != "copper":
        raise StackPlanError("the board has no top and bottom copper to build on")
    info = {str(i.get("name", "")).upper(): i for i in (inspect or [])}
    top, bottom, inner = section[0], section[-1], section[1:-1]
    old_copper = [layer for layer in inner if layer["kind"] == "copper"]
    planned_inner = [p for p in plan[1:-1] if p["kind"] == "copper"]

    keep: dict[int, str] = {}           # id(planned layer) -> existing layer name
    pointer = 0
    for p in planned_inner:
        want = "plane" if p.get("plane") else "signal"
        for j in range(pointer, len(old_copper)):
            name = old_copper[j]["name"]
            if copper_type(info.get(name.upper(), {}).get("layer_id")) == want:
                keep[id(p)] = name
                pointer = j + 1
                break
    kept = set(keep.values())
    drop = [layer["name"] for layer in old_copper if layer["name"] not in kept]
    busy = [n for n in drop if info.get(n.upper(), {}).get("used_by_prims", inspect is None)]
    if busy:
        raise StackPlanError(
            "these layers would be removed but carry primitives: " + ", ".join(busy)
            + ". Plan a layer of the same type in their place, or clear them first")

    ops: list[dict[str, str]] = [{"op": "remove", "name": n} for n in drop]
    renames = [(top["name"], "__stack_top__", plan[0]),
               (bottom["name"], "__stack_bottom__", plan[-1])]
    for k, p in enumerate(planned_inner):
        if id(p) in keep:
            renames.append((keep[id(p)], f"__stack_keep_{k}__", p))
    for old, temp, _ in renames:
        ops.append({"op": "set_copper", "name": old, "new_name": temp})
    for _, temp, p in renames:
        ops.append({"op": "set_copper", "name": temp, "new_name": p["name"],
                    "thickness_mils": f"{p['thickness_mils']:g}"})
    ref = plan[0]["name"]
    for p in planned_inner:
        if id(p) not in keep:
            ops.append({"op": "insert", "kind": "plane" if p.get("plane") else "signal",
                        "ref": ref, "where": "below", "name": p["name"],
                        "thickness_mils": f"{p['thickness_mils']:g}"})
        ref = p["name"]
    return ops


def dielectric_ops(readback: list[dict[str, Any]], plan: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Phase two, dielectrics: fit Altium's dielectrics in each gap to the plan."""
    section = board_section(readback)
    got_copper = [layer["name"] for layer in section if layer["kind"] == "copper"]
    want_copper = [p["name"] for p in plan if p["kind"] == "copper"]
    if [n.upper() for n in got_copper] != [n.upper() for n in want_copper]:
        raise StackPlanError(f"the copper came out as {got_copper}, not {want_copper}")

    def gaps(layers):
        out, current = [], None
        for layer in layers:
            if layer["kind"] == "copper":
                if current is not None:
                    out.append(current)
                current = []
            elif current is not None:
                current.append(layer)
        return out

    got_gaps, want_gaps = gaps(section), gaps(plan)
    removes: list[dict[str, str]] = []
    temps: list[dict[str, str]] = []
    finals: list[dict[str, str]] = []
    for k, (got, want) in enumerate(zip(got_gaps, want_gaps)):
        if len(got) < len(want):
            raise StackPlanError(
                f"between {want_copper[k]} and {want_copper[k + 1]} Altium has "
                f"{len(got)} dielectric(s) and the plan {len(want)}; a script cannot "
                "add one. Plan one dielectric per gap")
        for extra in got[len(want):]:
            removes.append({"op": "remove", "name": extra["name"]})
        for j, (g, w) in enumerate(zip(got, want)):
            temp = f"__stack_d{k}_{j}__"
            temps.append({"op": "set_dielectric", "name": g["name"], "new_name": temp})
            op = {"op": "set_dielectric", "name": temp, "new_name": w["name"],
                  "type": str(w["type"]), "thickness_mils": f"{w['thickness_mils']:g}"}
            if "constant" in w:
                op["constant"] = f"{w['constant']:g}"
            if "loss_tangent" in w:
                op["loss_tangent"] = f"{w['loss_tangent']:g}"
            if "material" in w:
                op["material"] = w["material"]
            finals.append(op)
    return removes + temps + finals


def check_copper_flags(inspected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copper that is printed-electronics additive or non-conductive.

    Copper inserted through the V7 stack came out that way on AD 25.8.1
    (Rosen, 2026-10-27): right thickness, but the board drew paper-thin in
    3D with no holes. stack_edit now makes it ordinary; this checks it.
    """
    out = []
    for layer in inspected:
        if "additive" not in layer:
            continue
        if layer.get("additive"):
            out.append({"check": "additive", "layer": layer.get("name"),
                        "got": True, "expected": False})
        if float(layer.get("resistivity") or 0) >= 1e9:
            out.append({"check": "non_conductive", "layer": layer.get("name"),
                        "got": layer.get("resistivity"), "expected": "copper"})
    return out


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
