"""Geometry estimates with explicit source priority and no claim of measurement."""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def _dimensions(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict) and isinstance(value.get("value"), dict):
        value = value["value"]
    value = value if isinstance(value, dict) else {}
    result = {key: _number(value.get(key)) for key in ("length_mm", "width_mm", "height_mm")}
    return result if all(result.values()) else None


def estimate_geometry(analysis: dict[str, Any]) -> dict[str, Any]:
    measurements = analysis.get("measurements") or analysis.get("measurement") or {}
    measured = _dimensions(measurements.get("outer_dimensions"))
    visual = analysis.get("geometry_estimate") or {}
    visual_dimensions = _dimensions(visual.get("outer_package"))
    if measured:
        dimensions, source, confidence, estimated = measured, "user_measured", 1.0, False
    elif visual_dimensions:
        dimensions, source, confidence, estimated = visual_dimensions, "ai_visual_estimate", min(1, max(0, float((visual.get("outer_package") or {}).get("confidence") or visual.get("confidence") or .5))), True
    else:
        text = " ".join(str(x) for x in [
            (analysis.get("product") or {}).get("product_name", ""),
            *[r.get("component", "") for r in (analysis.get("packaging") or {}).get("materials", []) if isinstance(r, dict)]])
        if any(word in text.casefold() for word in ("large", "rigid gift", "大型", "大礼盒")):
            dimensions = {"length_mm": 360, "width_mm": 260, "height_mm": 100}
        elif any(word in text.casefold() for word in ("small", "小型")):
            dimensions = {"length_mm": 160, "width_mm": 110, "height_mm": 55}
        else:
            dimensions = {"length_mm": 260, "width_mm": 180, "height_mm": 70}
        source, confidence, estimated = "rule_fallback", .25, True

    current_volume = dimensions["length_mm"] * dimensions["width_mm"] * dimensions["height_mm"]
    ratio = _number(visual.get("product_occupied_ratio"))
    method = "visual_2d_proxy"
    if ratio and ratio <= 1:
        confidence = min(confidence, float(visual.get("confidence") or confidence))
    else:
        utilization = _number((analysis.get("packaging") or {}).get("space_utilization"))
        ratio = utilization / 100 if utilization and 20 <= utilization <= 95 else None
        if ratio is not None:
            # A bounded visual utilization supplied by the analyzer is sufficient
            # evidence for a conditional resize candidate, even when absolute
            # package dimensions still use a category fallback.
            confidence = max(confidence, .55)
    occupied = measurements.get("product_occupied_volume_mm3")
    if isinstance(occupied, dict):
        occupied = occupied.get("value")
    if measured and _number(occupied):
        ratio = _number(occupied) / current_volume
        method = "estimated_3d_volume"
    has_geometry_evidence = bool(measured or visual_dimensions or ratio or (analysis.get("packaging") or {}).get("materials"))
    if not has_geometry_evidence:
        return {"outer_dimensions": dimensions, "outer_volume_mm3": round(current_volume),
                "product_occupied_ratio": None, "space_utilization": None, "method": "pending",
                "source": "rule_fallback", "confidence": 0, "estimated": True,
                "minimum_safe_dimensions": dimensions, "minimum_safe_volume_mm3": round(current_volume),
                "recommended_outer_volume_ratio": 1}
    ratio = min(.95, max(.2, ratio or .65))
    target_ratio = .76
    safe_volume = current_volume if ratio >= .7 else current_volume * ratio / target_ratio
    retained_ratio = min(1, max(.7, safe_volume / current_volume))
    linear_scale = retained_ratio ** (1/3)
    minimum = {key: round(value * linear_scale, 1) for key, value in dimensions.items()}
    return {
        "outer_dimensions": dimensions,
        "outer_volume_mm3": round(current_volume),
        "product_occupied_ratio": round(ratio, 3),
        "space_utilization": round(ratio * 100),
        "method": method,
        "source": source,
        "confidence": round(confidence, 2),
        "estimated": estimated,
        "minimum_safe_dimensions": minimum,
        "minimum_safe_volume_mm3": round(safe_volume),
        "recommended_outer_volume_ratio": round(retained_ratio, 3),
    }
