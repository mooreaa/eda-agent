# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 George Saliba <george.saliba@salitronic.com>
"""Size, place and turn each PCB designator to fit its part.

A port of the AdjustDesignators.pas house script (Mattias Ericson, Omnisys
Instruments) used on REVO boards: every designator goes on a mechanical layer
(Mechanical 10 for a top part, Mechanical 11 mirrored for a bottom one),
centred on its part and scaled to its outline, so the assembly drawing has one
label per part. The outline is the box of the part's tracks on the outline
layers (overlay, Mechanical 13, Mechanical 1), or its bounding rectangle when
it has none there.

The script's sizing, in stroke font: the long side over the text length; if
that is not smaller than the short side, the short side over the text length
instead; the stroke 25 % of that when it is under 1 mm, else 0.254 mm; then
the height clamped to 0.1-1.0 mm (the stroke is not recomputed). A part taller
than wide gets its text turned.

Where this differs from the script, or may yet:

- A part taller than wide gets 90 degrees on top and 270 on the bottom (Aaron,
  2026-10-27). The script meant that, but tested the text's layer for the top
  overlay after moving it to the mechanical layer, so every tall part got 270.
- ``fit="script"`` (the default, undecided) divides the short side by the text
  length when the long side does not fit, which on a narrow part makes the
  text far smaller than the part allows; each such part is marked
  ``short_side_fallback``. ``fit="short_side"`` caps the height at the short
  side instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..units import MILS_PER_MM

FITS = ("script", "short_side")


@dataclass
class Options:
    top_layer: str = "Mechanical10"
    bottom_layer: str = "Mechanical11"
    min_mm: float = 0.1
    max_mm: float = 1.0
    stroke_ratio: float = 0.25
    max_stroke_mm: float = 0.254
    fit: str = "script"


def plan_part(part: dict[str, Any], opt: Options) -> dict[str, Any]:
    """The designator settings for one part from its outline (mils)."""
    text = str(part.get("designator", ""))
    n = max(1, len(text))
    x = abs(float(part["x2"]) - float(part["x1"])) / MILS_PER_MM
    y = abs(float(part["y2"]) - float(part["y1"])) / MILS_PER_MM
    long_side, short_side = (y, x) if y >= x else (x, y)
    size = long_side / n
    fallback = size >= short_side
    if fallback:
        size = short_side / n if opt.fit == "script" else short_side
    stroke = size * opt.stroke_ratio if size < 1.0 else opt.max_stroke_mm
    height = min(max(size, opt.min_mm), opt.max_mm)
    side = part.get("side", "top")
    bottom = side == "bottom"
    rotation = (270 if bottom else 90) if y > x else 0
    out = {"designator": text, "side": side, "source": part.get("source"),
           "outline_mm": [round(x, 4), round(y, 4)],
           "layer": opt.bottom_layer if bottom else opt.top_layer,
           "mirror": bottom, "height_mm": round(height, 4),
           "stroke_mm": round(stroke, 4), "rotation": rotation}
    if height != size:
        out["clamped_from_mm"] = round(size, 4)
    if fallback:
        out["short_side_fallback"] = True
    if side == "other":
        out["skip"] = "the part is on neither top nor bottom"
    return out


def apply_item(plan: dict[str, Any]) -> str:
    """One part for the script's apply op: 'd=..;l=..;s=..;w=..;r=..;m=..'."""
    return ";".join([
        f"d={plan['designator']}", f"l={plan['layer']}",
        f"s={plan['height_mm'] * MILS_PER_MM:.4f}",
        f"w={plan['stroke_mm'] * MILS_PER_MM:.4f}",
        f"r={plan['rotation']}", f"m={1 if plan['mirror'] else 0}"])


def check_part(plan: dict[str, Any], outline: dict[str, Any], got: dict[str, Any],
               centre_tol_mm: float = 0.25) -> list[str]:
    """What did not take on one part, from the script's read-back."""
    issues = []
    if str(got.get("layer", "")).replace(" ", "").upper() != plan["layer"].replace(" ", "").upper():
        issues.append(f"layer {got.get('layer')!r}, wanted {plan['layer']}")
    size_mm = float(got.get("size_mils", 0)) / MILS_PER_MM
    if abs(size_mm - plan["height_mm"]) > 0.002:
        issues.append(f"height {size_mm:.3f} mm, wanted {plan['height_mm']}")
    width_mm = float(got.get("width_mils", 0)) / MILS_PER_MM
    if abs(width_mm - plan["stroke_mm"]) > 0.002:
        issues.append(f"stroke {width_mm:.3f} mm, wanted {plan['stroke_mm']}")
    if round(float(got.get("rotation", 0))) % 360 != plan["rotation"] % 360:
        issues.append(f"rotation {got.get('rotation')}, wanted {plan['rotation']}")
    if bool(got.get("mirror")) != plan["mirror"]:
        issues.append(f"mirror {got.get('mirror')}, wanted {plan['mirror']}")
    if got.get("tt_font"):
        issues.append("still a TrueType font")
    if not got.get("name_on"):
        issues.append("designator hidden")
    cx = (float(outline["x1"]) + float(outline["x2"])) / 2
    cy = (float(outline["y1"]) + float(outline["y2"])) / 2
    off = ((float(got.get("text_cx", cx)) - cx) ** 2
           + (float(got.get("text_cy", cy)) - cy) ** 2) ** 0.5 / MILS_PER_MM
    if off > centre_tol_mm:
        issues.append(f"text centre {off:.2f} mm from the outline centre")
    return issues
