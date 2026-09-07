"""Build and transform a transparent packaging digital-twin estimate."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.geometry_estimator import estimate_geometry
from app.services.material_data_service import get_emission_factor

PROPERTIES_PATH = Path(__file__).resolve().parents[2] / "data" / "materials" / "material_properties.json"


def load_material_properties() -> list[dict[str, Any]]:
    try:
        data = json.loads(PROPERTIES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def material_property(name: str) -> dict[str, Any] | None:
    key = " ".join(str(name).casefold().split())
    for item in load_material_properties():
        names = [item.get("material", ""), *(item.get("aliases") or [])]
        if key in {" ".join(str(value).casefold().split()) for value in names}:
            return item
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def _surface_area_m2(dimensions: dict[str, float]) -> float:
    length, width, height = (dimensions[key] / 1000 for key in ("length_mm", "width_mm", "height_mm"))
    return 2 * (length * width + length * height + width * height)


def _infer_material(row: dict[str, Any], analysis: dict[str, Any]) -> tuple[str, str, float]:
    """Conservative component-shape inference used only when material is unknown."""
    original = str(row.get("material") or "unknown")
    if material_property(original):
        return original, "ai_identified", float(row.get("confidence") or .5)
    if original.casefold().strip() not in {"", "unknown", "uncertain", "未知", "不确定"}:
        return original, "ai_identified_unmapped", min(float(row.get("confidence") or .4), .4)
    text = " ".join(str(row.get(key) or "") for key in ("component", "evidence")).casefold()
    known = " ".join(str(item.get("material") or "") for item in
                     ((analysis.get("packaging") or {}).get("materials") or []) if isinstance(item, dict)).casefold()
    if any(word in text for word in ("film", "wrap", "薄膜", "覆膜", "window film")):
        return "plastic_film", "component_shape_inference", .35
    if any(word in text for word in ("box", "carton", "盒", "箱")):
        return "paperboard", "component_shape_inference", .4
    if any(word in text for word in ("sleeve", "label", "sheet", "套", "标签", "纸张")):
        return "paper", "component_shape_inference", .35
    if any(word in known for word in ("paper", "cardboard", "carton", "纸")):
        return "paperboard", "dominant_material_proxy", .25
    return original, "unresolved", 0


def _role_share(name: str) -> float:
    name = name.casefold()
    if any(word in name for word in ("box", "carton", "盒", "箱")):
        return .68
    if any(word in name for word in ("tray", "insert", "内托")):
        return .22
    if any(word in name for word in ("film", "wrap", "薄膜", "覆膜")):
        return .05
    if any(word in name for word in ("sleeve", "label", "套", "标签")):
        return .08
    return .12


def _fallback_total_weight(analysis: dict[str, Any], geometry: dict[str, Any], known_sum: float) -> float:
    impact = analysis.get("environmental_impact") or {}
    supplied = _number(impact.get("estimated_packaging_weight_g"))
    if supplied and 10 <= supplied <= 2000:
        return supplied
    text = " ".join((str((analysis.get("product") or {}).get("category") or ""),
                     str((analysis.get("product") or {}).get("product_name") or ""),
                     *[str(item.get("component") or "") for item in
                       ((analysis.get("packaging") or {}).get("materials") or []) if isinstance(item, dict)])).casefold()
    if any(word in text for word in ("large rigid", "大型硬质", "大型礼盒")):
        category_midpoint = 420
    elif any(word in text for word in ("gift", "礼盒", "mooncake", "月饼")):
        category_midpoint = 180
    elif any(word in text for word in ("small", "小型")):
        category_midpoint = 70
    else:
        category_midpoint = 120
    geometry_box = _surface_area_m2(geometry["outer_dimensions"]) * 350 * 1.15
    return round(max(known_sum * 1.08, min(category_midpoint, geometry_box * 1.8)), 1)


def allocate_material_weights(analysis: dict[str, Any], components: list[dict[str, Any]],
                              geometry: dict[str, Any]) -> dict[str, Any]:
    """Fill missing component masses using visual share/role allocation after direct estimates."""
    missing = [item for item in components if item.get("estimated_weight_g") is None]
    known_sum = sum(float(item["estimated_weight_g"]) for item in components
                    if item.get("estimated_weight_g") is not None)
    method = "component_estimates"
    if missing:
        total = _fallback_total_weight(analysis, geometry, known_sum)
        remaining = max(total-known_sum, max(4.0, known_sum*.08))
        raw_rows = {str(item.get("component") or "").casefold(): item for item in
                    ((analysis.get("packaging") or {}).get("materials") or []) if isinstance(item, dict)}
        shares = []
        for item in missing:
            raw = raw_rows.get(item["name"].casefold(), {})
            visual = _number(raw.get("visual_fraction"))
            shares.append(visual if visual is not None and 0 < visual <= 1 else _role_share(item["name"]))
        share_total = sum(shares) or len(missing)
        for item, share in zip(missing, shares):
            item["estimated_weight_g"] = round(remaining * share/share_total, 1)
            item["weight_source"] = "visual_fraction_allocation" if _number(
                raw_rows.get(item["name"].casefold(), {}).get("visual_fraction")) else "category_role_allocation"
            item["confidence"] = min(item.get("confidence") or .3, .35)
            item["estimation_method"] = "总质量估计 × 视觉占比/组件类型权重"
        method = "proportional_allocation"

    # If only a secondary component lacks a factor, use the weighted factor of
    # recognized components instead of discarding the entire package estimate.
    known_factor_rows = [item for item in components if item.get("carbon_factor_kgco2e_per_kg") is not None]
    factor_weight = sum(item["estimated_weight_g"] for item in known_factor_rows if item.get("estimated_weight_g") is not None)
    weighted_factor = (sum(item["estimated_weight_g"] * item["carbon_factor_kgco2e_per_kg"]
                           for item in known_factor_rows if item.get("estimated_weight_g") is not None) / factor_weight
                       if factor_weight else None)
    for item in components:
        if item.get("carbon_factor_kgco2e_per_kg") is None and weighted_factor is not None:
            item["carbon_factor_kgco2e_per_kg"] = round(weighted_factor, 8)
            item["material_property_source"] = "已识别主要材料的加权排放因子代理"
            item["carbon_factor_inferred"] = True
            item["confidence"] = min(item.get("confidence") or .25, .25)
    allocation: dict[str, float] = {}
    for item in components:
        if item.get("estimated_weight_g") is not None:
            allocation[item["material"]] = round(allocation.get(item["material"], 0) + item["estimated_weight_g"], 1)
    return {"by_material_g": allocation, "method": method, "estimated": True,
            "requires_validation": True}


def _component_weight(row: dict[str, Any], geometry: dict[str, Any]) -> tuple[float | None, str, float, str]:
    explicit = _number(row.get("weight_g"))
    if explicit is not None and row.get("weight_source") in {"measured", "user_measured", "user_supplied"}:
        return explicit, "user_measured", 1.0, "用户提供的组件质量"
    explicit = _number(row.get("estimated_weight_g"))
    if explicit is not None:
        return explicit, "ai_visual_estimate", float(row.get("confidence") or .45), "视觉模型提供的组件质量估计"
    name = str(row.get("component") or "").casefold()
    if (any(word in name for word in ("lining", "liner", "内衬", "衬层"))
            and row.get("_material_inference_source") in {"dominant_material_proxy", "unresolved"}):
        return 7.0, "component_type_fallback", .35, "内衬典型质量范围4–12g的保守中值"
    prop = material_property(row.get("material", ""))
    if not prop:
        return None, "pending", 0, "材料属性库无对应材料"
    area = _surface_area_m2(geometry["outer_dimensions"])
    gsm_low, gsm_high = prop["typical_gsm_range"]
    gsm = (gsm_low + gsm_high) / 2
    thickness = sum(prop["typical_thickness_mm"]) / 2
    density = prop["density_g_cm3"]
    if any(word in name for word in ("box", "carton", "盒", "箱")):
        weight, method = area * gsm * 1.15, "外盒表面积 × 材料克重 × 结构余量"
    elif any(word in name for word in ("film", "wrap", "薄膜", "覆膜")):
        # 1 m² × 1 mm = 1,000 cm³.
        weight, method = area * .9 * thickness * density * 1000, "覆盖表面积 × 薄膜厚度 × 材料密度"
    elif any(word in name for word in ("tray", "insert", "内托")):
        footprint = geometry["outer_dimensions"]["length_mm"] * geometry["outer_dimensions"]["width_mm"] / 1_000_000
        if prop["material"] in {"pet_plastic", "molded_pulp"}:
            weight, method = footprint * 1.6 * thickness * density * 1000, "内托展开体积 × 材料厚度 × 有效密度"
        else:
            weight, method = footprint * gsm * .85, "内托投影面积 × 材料等效克重"
    elif any(word in name for word in ("sleeve", "label", "套", "标签")):
        weight, method = area * gsm * .55, "包覆表面积 × 材料克重"
    else:
        fraction = _number(row.get("visual_fraction"))
        if fraction is None or fraction > 1:
            return None, "rule_fallback", .2, "缺少可用几何形态，暂无法估算"
        weight, method = area * gsm * fraction, "视觉面积占比 × 表面积 × 材料克重"
    confidence = min(float(row.get("confidence") or .5), geometry["confidence"], .7)
    return round(weight, 1), "material_geometry_estimate", confidence, method


def _totals(state: dict[str, Any]) -> dict[str, Any]:
    components = state["components"]
    known = [item["estimated_weight_g"] for item in components]
    total = round(sum(known), 1) if components and all(value is not None for value in known) else None
    plastic = round(sum(item["estimated_weight_g"] for item in components
                        if item["estimated_weight_g"] is not None and item["material_family"] == "plastic"), 1) if components else None
    carbon_parts = [item["estimated_carbon_kgco2e"] for item in components]
    carbon = round(sum(carbon_parts), 4) if components and all(value is not None for value in carbon_parts) else None
    if total:
        recycle = round(sum(item["recyclability_base"] * item["estimated_weight_g"] for item in components
                            if item["estimated_weight_g"] is not None) / total)
        families = {item["material"] for item in components}
        if len(families) == 1:
            recycle = min(100, recycle + 3)
        elif len(families) >= 3:
            recycle = max(0, recycle - 8)
    else:
        recycle = None
    allocation: dict[str, float] = {}
    for item in components:
        if item.get("estimated_weight_g") is not None:
            allocation[item["material"]] = round(allocation.get(item["material"], 0) + item["estimated_weight_g"], 1)
    allocation_meta = state.get("material_weight_allocation") or {}
    state["material_weight_allocation"] = {**allocation_meta, "by_material_g": allocation,
                                           "estimated": True, "requires_validation": True}
    state.update(total_weight_g=total, plastic_weight_g=plastic, carbon_kgco2e=carbon,
                 recyclability=recycle, layer_count=len([x for x in components
                    if not any(word in x["name"].casefold() for word in ("label", "logo", "标签", "标识"))]))
    return state


def build_packaging_state(analysis: dict[str, Any]) -> dict[str, Any]:
    geometry = estimate_geometry(analysis)
    components = []
    for index, row in enumerate((analysis.get("packaging") or {}).get("materials") or []):
        if not isinstance(row, dict):
            continue
        inferred_material, material_source, material_confidence = _infer_material(row, analysis)
        working_row = {**row, "material": inferred_material,
                       "_material_inference_source": material_source,
                       "confidence": min(float(row.get("confidence") or .5), material_confidence or float(row.get("confidence") or .5))}
        prop = material_property(inferred_material)
        weight, source, confidence, method = _component_weight(working_row, geometry)
        material = prop["material"] if prop else str(row.get("material") or "unknown")
        factor_reference = get_emission_factor(inferred_material)
        carbon_factor = (factor_reference.get("factor_kgco2e_per_kg")
                         if factor_reference.get("factor_available") else prop.get("carbon_factor") if prop else None)
        components.append({
            "name": str(row.get("component") or f"组件{index + 1}"), "material": material,
            "original_material": str(row.get("material") or "unknown"),
            "material_inference_source": material_source,
            "material_family": "plastic" if material in {"pet_plastic", "plastic_film", "hdpe", "ldpe_lldpe", "pp", "ps", "pvc"} else "fiber" if material in {"paperboard", "paper", "molded_pulp"} else "other",
            "estimated_weight_g": weight, "weight_source": source, "confidence": round(confidence, 2),
            "estimation_method": method, "carbon_factor_kgco2e_per_kg": carbon_factor,
            "geometry_basis": geometry["outer_dimensions"],
            "estimated_carbon_kgco2e": round(weight / 1000 * carbon_factor, 4) if weight is not None and carbon_factor is not None else None,
            "recyclability_base": prop.get("recyclability_base", 40) if prop else 40,
            "relative_cost_index": prop.get("relative_cost_index", 1.0) if prop else 1.0,
            "material_property_source": factor_reference.get("source") or (prop.get("source") if prop else None),
        })
    fallback_sources = {"component_type_fallback", "pending", "rule_fallback"}
    known_weight_g = round(sum(item["estimated_weight_g"] for item in components
                               if item.get("estimated_weight_g") is not None
                               and item.get("weight_source") not in fallback_sources), 1)
    unknown_component_count = sum(item.get("weight_source") in fallback_sources for item in components)
    allocation = allocate_material_weights(analysis, components, geometry)
    for item in components:
        factor, weight = item.get("carbon_factor_kgco2e_per_kg"), item.get("estimated_weight_g")
        if item.get("material_inference_source") not in {"ai_identified", "ai_identified_unmapped"} and factor is not None:
            item["carbon_factor_inferred"] = True
            item["material_property_source"] = f"材料类别推断代理；{item.get('material_property_source') or '参考材料因子'}"
        item["estimated_carbon_kgco2e"] = round(weight / 1000 * factor, 4) if weight is not None and factor is not None else None
    state = {"components": components, "material_weight_allocation": allocation,
             "known_weight_g": known_weight_g, "unknown_component_count": unknown_component_count,
             "outer_dimensions": geometry["outer_dimensions"],
             "outer_volume_mm3": geometry["outer_volume_mm3"], "space_utilization": geometry["space_utilization"],
             "geometry": geometry, "estimated": geometry["estimated"], "confidence": geometry["confidence"]}
    state = _totals(state)
    measurements = analysis.get("measurements") or analysis.get("measurement") or {}
    measured_total = _number(measurements.get("total_weight_g"))
    if measured_total is not None and state["total_weight_g"]:
        factor = measured_total / state["total_weight_g"]
        for item in state["components"]:
            item["estimated_weight_g"] = round(item["estimated_weight_g"] * factor, 1)
            item["weight_source"] = "scaled_to_user_measured_total"
            if item["carbon_factor_kgco2e_per_kg"] is not None:
                item["estimated_carbon_kgco2e"] = round(item["estimated_weight_g"] / 1000 * item["carbon_factor_kgco2e_per_kg"], 4)
        state = _totals(state)
        state["total_weight_g"] = measured_total
        state["total_weight_source"] = "user_measured"
    else:
        state["total_weight_source"] = "component_sum" if state["total_weight_g"] is not None else "pending"
    total = state.get("total_weight_g")
    if total:
        state["total_weight_confidence"] = round(sum(
            item["estimated_weight_g"] * item.get("confidence", 0) for item in state["components"]
        ) / total, 2)
    else:
        state["total_weight_confidence"] = 0
    state["requires_validation"] = any(item.get("weight_source") != "user_measured" for item in state["components"])
    return state


def apply_change_plan(before: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    after = deepcopy(before)
    actions = plan.get("component_actions") or []
    by_name = {item["name"].casefold(): item for item in after["components"]}
    for action in actions:
        item = by_name.get(str(action.get("component", "")).casefold())
        if not item:
            continue
        kind = action.get("action")
        if kind in {"remove", "integrate_into"}:
            after["components"].remove(item)
            by_name.pop(item["name"].casefold(), None)
        elif kind in {"resize", "resize_to_fit"} and item["estimated_weight_g"] is not None and not (kind == "resize_to_fit" and item["material_family"] == "plastic"):
            scale = float(action.get("scale") or (plan.get("resize_spec") or {}).get("scale") or 1)
            item["estimated_weight_g"] = round(item["estimated_weight_g"] * scale ** (2/3), 1)
        elif kind == "lightweight" and item["estimated_weight_g"] is not None:
            item["estimated_weight_g"] = round(item["estimated_weight_g"] * float(action.get("scale") or .7), 1)
        elif kind == "replace_material":
            old = material_property(item["material"])
            new = material_property(action.get("to", ""))
            if new:
                if old and any(word in item["name"].casefold() for word in ("tray", "insert", "内托")):
                    old_basis = old["density_g_cm3"] * sum(old["typical_thickness_mm"]) / 2
                    new_basis = new["density_g_cm3"] * sum(new["typical_thickness_mm"]) / 2
                else:
                    old_basis = sum(old["typical_gsm_range"]) / 2 if old else 1
                    new_basis = sum(new["typical_gsm_range"]) / 2
                if item["estimated_weight_g"] is not None:
                    item["estimated_weight_g"] = round(item["estimated_weight_g"] * new_basis / old_basis, 1)
                factor_reference = get_emission_factor(str(action.get("to") or ""))
                carbon_factor = (factor_reference.get("factor_kgco2e_per_kg")
                                 if factor_reference.get("factor_available") else new["carbon_factor"])
                item.update(material=new["material"], material_family="fiber", recyclability_base=new["recyclability_base"],
                            carbon_factor_kgco2e_per_kg=carbon_factor, relative_cost_index=new["relative_cost_index"],
                            material_property_source=factor_reference.get("source") or new["source"])
        elif kind == "increase_recycled_content":
            item["recyclability_base"] = min(100, item["recyclability_base"] + 3)
    resize_action = next((action for action in actions if action.get("action") == "resize"), {})
    scale = float((plan.get("resize_spec") or {}).get("scale") or resize_action.get("scale") or 1)
    if (plan.get("resize_spec") or {}).get("enabled") and scale < 1:
        linear = scale ** (1/3)
        after["outer_dimensions"] = {key: round(value * linear, 1) for key, value in before["outer_dimensions"].items()}
        after["outer_volume_mm3"] = round(before["outer_volume_mm3"] * scale)
        after["space_utilization"] = min(95, round(before["space_utilization"] / scale))
    for item in after["components"]:
        factor = item.get("carbon_factor_kgco2e_per_kg")
        weight = item.get("estimated_weight_g")
        item["estimated_carbon_kgco2e"] = round(weight / 1000 * factor, 4) if weight is not None and factor is not None else None
        item["weight_source"] = "change_plan_simulation"
        item["confidence"] = min(item.get("confidence", .5), .55)
    return _totals(after)
