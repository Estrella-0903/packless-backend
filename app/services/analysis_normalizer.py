from __future__ import annotations

import re
from typing import Any
from uuid import uuid4


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _number(value: Any, *, minimum: float = 0, maximum: float | None = None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if not match:
            return None
        value = match.group(0)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number < minimum or (maximum is not None and number > maximum):
        return None
    return int(round(number))


def _confidence(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        if not match:
            return 0.0
        value = match.group(0)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if 1 < number <= 100:
        number /= 100
    return round(min(1.0, max(0.0, number)), 3)


def _decimal(value: Any, *, minimum: float = 0, maximum: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= minimum and (maximum is None or number <= maximum) else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,，;；\n]", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        return []
    return [text for item in values if (text := _text(item))]


def _materials(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            name = _text(item)
            if name:
                normalized.append(
                    {
                        "component": "",
                        "material": name,
                        "confidence": 0.0,
                        "evidence": "",
                    }
                )
            continue
        if not isinstance(item, dict):
            continue

        material = _text(_first(item, "material", "name", "material_name", "type"))
        component = _text(_first(item, "component", "part", "packaging_component"))
        evidence = _text(_first(item, "evidence", "reason", "visual_evidence"))
        share = _first(item, "percentage", "ratio", "share")
        if share is not None and not evidence:
            share_text = _text(share)
            evidence = f"Model-reported material share: {share_text}" if share_text else ""
        if not material:
            material = "unknown"
        normalized.append(
            {
                "component": component,
                "material": material,
                "confidence": _confidence(_first(item, "confidence", "certainty")),
                "evidence": evidence,
                "visual_fraction": _decimal(item.get("visual_fraction"), maximum=1),
                "size_category": _text(item.get("size_category")),
                "functions": _string_list(item.get("functions")),
                "essential": item.get("essential") is True,
                "brand_critical": item.get("brand_critical") is True,
            }
        )
    return normalized


def normalize_analysis_result(raw: dict[str, Any], filename: str) -> dict[str, Any]:
    """Normalize a loosely structured model object into the stable analysis contract."""
    if not isinstance(raw, dict):
        raise ValueError("Missing required root object")

    payload = _mapping(raw.get("data")) or raw
    product = _mapping(_first(payload, "product", "product_info", "productInfo"))
    packaging = _mapping(
        _first(payload, "packaging", "packaging_info", "package", "package_info")
    )
    diagnosis = _mapping(
        _first(payload, "diagnosis", "assessment", "analysis", "diagnostic")
    )
    impact = _mapping(
        _first(payload, "environmental_impact", "impact", "environmentalImpact")
    )
    geometry = _mapping(_first(payload, "geometry_estimate", "geometry", "geometryEstimate"))
    outer = _mapping(_first(geometry, "outer_package", "outer_dimensions", "outerPackage"))

    category = _first(product, "category", "type", "product_type")
    product_name = _first(product, "product_name", "name", "productName")
    issues = _first(diagnosis, "issue_tags", "issues", "issueTags", default=[])

    return {
        "analysis_id": f"analysis_{uuid4().hex[:12]}",
        "filename": filename,
        "product": {
            "category": _text(category),
            "product_name": _text(product_name),
        },
        "packaging": {
            "layers": _number(_first(packaging, "layers", "layer_count", "layerCount")),
            "materials": _materials(
                _first(packaging, "materials", "material", "material_list", default=[])
            ),
            "space_utilization": _number(
                _first(packaging, "space_utilization", "space_utilisation", "space_usage"),
                maximum=100,
            ),
            "recyclability_score": _number(
                _first(packaging, "recyclability_score", "recyclability", "recycle_score"),
                maximum=100,
            ),
        },
        "diagnosis": {
            "overall_score": _number(
                _first(diagnosis, "overall_score", "score", "overallScore"),
                maximum=100,
            ),
            "level": _text(_first(diagnosis, "level", "rating", "severity")),
            "issue_tags": _string_list(issues),
        },
        "environmental_impact": {
            "estimated_packaging_weight_g": _number(
                _first(
                    impact,
                    "estimated_packaging_weight_g",
                    "packaging_weight_g",
                    "packaging_weight",
                )
            ),
            "estimated_plastic_weight_g": _number(
                _first(
                    impact,
                    "estimated_plastic_weight_g",
                    "plastic_weight_g",
                    "plastic_weight",
                )
            ),
            "estimated_co2e_g": _number(
                _first(impact, "estimated_co2e_g", "co2e_g", "carbon_emissions_g")
            ),
        },
        "geometry_estimate": {
            "outer_package": {
                "length_mm": _decimal(_first(outer, "length_mm", "length")),
                "width_mm": _decimal(_first(outer, "width_mm", "width")),
                "height_mm": _decimal(_first(outer, "height_mm", "height")),
                "estimated": True,
                "confidence": _confidence(_first(outer, "confidence", default=geometry.get("confidence"))),
                "source": "ai_visual_estimate",
            },
            "product_occupied_ratio": _decimal(_first(geometry, "product_occupied_ratio", "occupied_ratio"), maximum=1),
            "estimated_aspect_ratio": _decimal(_first(geometry, "estimated_aspect_ratio", "aspect_ratio")),
            "method": "visual_2d_proxy",
            "confidence": _confidence(geometry.get("confidence")),
        },
        "measurements": {},
        "summary": _text(_first(payload, "summary", "description", "conclusion")),
    }
