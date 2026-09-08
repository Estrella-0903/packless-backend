"""Deterministic MVP scenarios, not measurements or certified assessments.

Only selected, hard-constraint-safe opportunities may change the after state.
Ranges are engineering-demo assumptions, not statistical confidence intervals.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy

from app.services.material_data_service import get_emission_factor
from app.services.packaging_state import apply_change_plan, build_packaging_state

LIMITS = {"layers": (1, 8), "plastic_weight_g": (0, 500),
          "packaging_weight_g": (10, 2000), "space_utilization": (20, 95), "recyclability": (0, 100)}
PLASTIC_HYPOTHESIS = "Estimated from visible plastic component size; physical weighing required for validation."
RECYCLE_HYPOTHESIS = "Rule-based recyclability estimate for MVP demonstration; not a certified recyclability assessment."


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) else None


def metric(value=None, source="estimated", bounds=None, hypothesis="", confidence=0.5):
    return {"value": value, "source": source if value is not None else "pending",
            "range": list(bounds) if bounds else None, "confidence": confidence if value is not None else 0,
            "estimated": value is not None and source != "measured", "requires_validation": source != "measured",
            "hypothesis": hypothesis}


def components(analysis):
    rows = (analysis.get("packaging") or {}).get("materials") or []
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("component") or "").strip().casefold()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(dict(row, component=name))
    return result


def text(row):
    return " ".join(str(row.get(k) or "") for k in ("component", "material", "evidence", "size_category")).casefold()


def contains(value, words):
    return any(w in value for w in words)


def is_plastic(row):
    value = str(row.get("material") or "").casefold()
    return contains(value, ("plastic", "塑料", "塑胶")) or bool(re.search(r"\b(pet|pp|pe|hdpe|ldpe|pvc|ps)\b", value))


def is_paper(row):
    return contains(str(row.get("material") or "").casefold(), ("paper", "cardboard", "纸", "pulp"))


def plastic_parts(analysis):
    parts = []
    for row in components(analysis):
        value = text(row)
        if not is_plastic(row) and not contains(value, ("plastic film", "plastic tray", "pet insert", "plastic bag", "塑料薄膜", "塑料内托", "塑料袋")):
            continue
        if contains(value, ("film", "wrap", "薄膜", "覆膜")):
            low, high, chosen, kind = 2, 12, 6, "film"
        elif contains(value, ("tray", "insert", "内托")):
            low, high, chosen, kind = (10, 35, 24, "tray") if contains(value, ("small", "小型", "小尺寸")) else (25, 80, 40, "tray")
        elif contains(value, ("bag", "袋")):
            low, high, chosen, kind = 3, 20, 8, "bag"
        else:
            # Identity alone doesn't support a mass for bottles, caps, etc.
            low, high, chosen, kind = 0, 500, None, "unknown"
        share = number(row.get("visual_fraction"))
        if chosen is not None and share is not None and 0 <= share <= 1:
            chosen = round(low + (high-low)*min(0.65, max(0.25, share)))
        parts.append({"component": row["component"], "material": row.get("material", "unknown"),
                      "kind": kind, "weight_g": chosen, "range": [low, high]})
    return parts


def layer_component_names(analysis):
    return {r["component"] for r in components(analysis)
            if not contains(r["component"], ("logo", "印刷", "标识"))}


def estimate_layers(analysis):
    value = len(layer_component_names(analysis)) or number((analysis.get("packaging") or {}).get("layers"))
    return metric(min(8, max(1, round(value))) if value else None, bounds=(1, 8),
                  hypothesis="Visible distinct packaging components approximate layers; overlapping components are not verified nested layers.")


def estimate_plastic_weight(analysis):
    parts = plastic_parts(analysis)
    if not components(analysis):
        return metric(hypothesis="No visible packaging components available.")
    if any(p["weight_g"] is None for p in parts):
        return metric(hypothesis="Plastic component shape/size is unsupported; physical weighing required.")
    value = min(500, sum(p["weight_g"] for p in parts))
    bounds = (min(500, sum(p["range"][0] for p in parts)), min(500, sum(p["range"][1] for p in parts)))
    return metric(value, bounds=bounds, hypothesis=PLASTIC_HYPOTHESIS + (" No plastic identified in visible components; hidden plastic is not ruled out." if not parts else ""))


def estimate_packaging_weight(analysis):
    rows = components(analysis)
    if not rows:
        return metric(hypothesis="No component/size evidence for total mass.")
    explicit = number((analysis.get("environmental_impact") or {}).get("estimated_packaging_weight_g"))
    if explicit is not None and 10 <= explicit <= 2000:
        return metric(round(explicit), bounds=(max(10, round(explicit*.7)), min(2000, round(explicit*1.3))), hypothesis="AI mass estimate with visible component context; physical weighing required.")
    boxes = [r for r in rows if contains(text(r), ("box", "carton", "盒", "箱")) and is_paper(r)]
    if not boxes:
        return metric(hypothesis="No supported paper-box type identified for total mass.")
    value = text(boxes[0]) + " " + str((analysis.get("product") or {}).get("product_name", "")).casefold()
    bounds, chosen = ((250, 700), 420) if contains(value, ("large", "大型")) and contains(value, ("rigid", "硬", "gift", "礼盒")) else ((100, 300), 180) if contains(value, ("gift", "礼盒", "medium", "中型")) else ((40, 100), 70) if contains(value, ("small", "小型")) else ((40, 300), 120)
    plastic = estimate_plastic_weight(analysis)["value"]
    chosen = max(chosen, plastic or 0)
    return metric(chosen, bounds=(bounds[0], max(bounds[1], chosen)), hypothesis="Paper-box type range and visible components; mass includes packaging, not product. Weigh to validate.")


def estimate_space_utilization(analysis):
    pack = analysis.get("packaging") or {}
    value = number(pack.get("space_utilization"))
    if value is not None and 0 < value < 1:
        value *= 100
    if value is not None and 20 <= value <= 95:
        return metric(round(value), bounds=(max(20, round(value-10)), min(95, round(value+10))), hypothesis="AI visual space estimate; visible area is not measured 3D utilization.")
    if not components(analysis):
        return metric(hypothesis="No packaging geometry evidence.")
    evidence = " ".join(text(r) for r in components(analysis)) + " " + str((analysis.get("diagnosis") or {}).get("issue_tags", "")).casefold()
    band = pack.get("space_utilization_level")
    if band not in ("very_low", "low", "medium", "high"):
        band = "low" if contains(evidence, ("oversiz", "empty space", "大盒小", "空隙", "过大")) else "high" if contains(evidence, ("compact", "紧凑")) else "medium"
    low, high, chosen = {"very_low": (30,45,38), "low": (45,60,48), "medium": (60,75,65), "high": (75,90,82)}[band]
    return metric(chosen, bounds=(low, high), hypothesis=f"Visual utilization band={band}; medium is a conservative prior when visible packaging lacks a clearer size cue. Not volumetric measurement.", confidence=0.4)


def estimate_recyclability(analysis):
    rows = components(analysis)
    if not rows:
        return metric(hypothesis="No materials identified for a rule score.")
    plastics = plastic_parts(analysis)
    paper = any(is_paper(r) for r in rows)
    only_paper = all(is_paper(r) for r in rows)
    kinds = {p["kind"] for p in plastics}
    score = 80 if only_paper else 50 if paper and {"film", "tray"} <= kinds else 65 if paper and plastics else 40
    return metric(score, source="inferred", bounds=(max(0,score-10), min(100,score+10)), hypothesis=RECYCLE_HYPOTHESIS)


def estimate_co2e(material_weights, material_data=None):
    """Sum only allocated material masses; missing factors never become zero."""
    items = []
    for row in material_weights:
        ref = get_emission_factor(row["material"])
        weight = number(row.get("weight_g"))
        factor = ref.get("factor_kgco2e_per_kg")
        value = weight/1000*factor if weight is not None and weight >= 0 and factor is not None else None
        items.append(dict(row, factor_kgco2e_per_kg=factor, source=ref.get("source"), estimated_co2e_kg=value))
    total = sum(i["estimated_co2e_kg"] for i in items) if items and all(i["estimated_co2e_kg"] is not None for i in items) else None
    return {"estimated_co2e_kg": round(total, 3) if total is not None else None, "source": "estimated" if total is not None else "pending",
            "estimated": True, "requires_validation": True, "materials": items,
            "hypothesis": "AI estimated material mass × DEFRA primary-material reference factor; not measured carbon or a full lifecycle assessment."}


def _estimate_packaging_legacy(analysis_result, functional_checks=(), opportunities=(), change_plan=None, material_data=None):
    analysis = analysis_result.get("data", analysis_result)
    plan = change_plan or {}
    approved = [o.model_dump() if hasattr(o, "model_dump") else o for o in opportunities]
    approved = [o for o in approved if isinstance(o, dict)]
    actions = {o.get("action") for o in approved}
    rules = {o.get("rule_id") for o in approved}
    concrete = [a for a in plan.get("component_actions", [])
                if a.get("rule_id") in rules and any(
                    o.get("rule_id") == a.get("rule_id") and
                    str(o.get("target", "")).casefold() == str(a.get("component", "")).casefold()
                    for o in approved)]
    before = {"layers": estimate_layers(analysis), "plastic_weight_g": estimate_plastic_weight(analysis),
              "packaging_weight_g": estimate_packaging_weight(analysis), "space_utilization": estimate_space_utilization(analysis),
              "recyclability": estimate_recyclability(analysis)}
    # Explicit caller-supplied measurements take precedence; never trust model estimates as measured.
    measurements = analysis.get("measurements") or {}
    for key, entry in (measurements.get("before") or {}).items():
        if key not in LIMITS or not isinstance(entry, dict):
            continue
        value = number(entry.get("value"))
        if entry.get("source") == "measured" and entry.get("evidence") and value is not None and LIMITS[key][0] <= value <= LIMITS[key][1]:
            before[key] = metric(round(value), "measured", (round(value),round(value)), str(entry["evidence"]), 1)
    after = deepcopy(before)
    # An unchanged planned after-state is still a hypothesis, not a measurement.
    for entry in after.values():
        if entry["value"] is not None:
            entry.update(source="inferred", estimated=True, requires_validation=True, confidence=min(.5, entry["confidence"]),
                         hypothesis="Retain before estimate unless selected rules approve a change; validate the actual redesigned package.")
    def improve(key, value, explanation):
        low, high = LIMITS[key]
        after[key] = metric(round(min(high,max(low,value))), "inferred", (low, high), explanation, .5)
    eliminated = {a["component"].casefold() for a in concrete if a["action"] in {"remove", "integrate_into"}}
    layer_count = len(eliminated & layer_component_names(analysis))
    if plan.get("reduce_layers") and layer_count and before["layers"]["value"] is not None:
        improve("layers", before["layers"]["value"]-layer_count, "Named approved components removed/integrated; retain at least one protective layer.")
    parts = plastic_parts(analysis)
    removed = 0
    for part in parts:
        part["after_weight_g"] = part["weight_g"]
        # Selected actions are the authority, not unselected opportunities or rule IDs alone.
        matched = next((a for a in concrete if a["rule_id"] == "R03" and a["component"].casefold() == part["component"]), None)
        if matched and part["weight_g"] is not None:
            if matched["action"] == "remove":
                part["after_weight_g"] = 0
            elif matched["action"] == "replace_material" and matched.get("to") == "Molded pulp":
                part["after_weight_g"] = 0
            elif matched["action"] == "lightweight":
                part["after_weight_g"] = round(part["weight_g"]*matched.get("scale", 1))
            removed += part["weight_g"] - part["after_weight_g"]
    plastic = before["plastic_weight_g"]["value"]
    if removed and plastic is not None:
        improve("plastic_weight_g", max(0,plastic-removed), "R03 selected component changes applied to visual plastic estimate; replacement fiber is not plastic.")
    space = before["space_utilization"]["value"]
    resize = next((a for a in concrete if a["rule_id"] == "R02" and a["action"] == "resize"), None)
    if resize and (plan.get("resize_spec") or {}).get("enabled") and space is not None:
        improve("space_utilization", min(95,space/resize["scale"]), "R02 retained outer-volume ratio applied with unchanged product volume; validate fit and dimensions.")
    weight = before["packaging_weight_g"]["value"]
    if weight is not None and actions & {"reduce_layers", "reduce_volume", "remove_plastic_film", "lightweight_plastic_film"}:
        scale = (0.9 if after["layers"]["value"] != before["layers"]["value"] else 1)*(0.9 if resize else 1)
        film_saved = sum((p["weight_g"] or 0)-(p["after_weight_g"] or 0) for p in parts if p["kind"] == "film")
        improve("packaging_weight_g", max(after["plastic_weight_g"]["value"] or 0, weight*scale-film_saved), "Selected R01/R02: 10% mass reduction each; subtract selected film savings. Tray replacement does not assume net mass savings.")
    recycle = before["recyclability"]["value"]
    if recycle is not None:
        increase = (10 if removed else 0)+(12 if any(a["action"] == "integrate_into" for a in concrete) else 0)+(5 if any(a["rule_id"] == "R05" for a in concrete) else 0)
        if increase:
            improve("recyclability", recycle+increase, RECYCLE_HYPOTHESIS + " Selected R03 +10, R04 +12, R05 +5 where applicable.")
    # A single identified material can use total mass. Mixed unallocated mass stays pending.
    rows = components(analysis)
    names = {str(r.get("material") or "unknown") for r in rows}
    def carbon(side, after_state=False):
        mass = side["packaging_weight_g"]["value"]
        if len(names) == 1 and mass is not None:
            return estimate_co2e([{"material": next(iter(names)), "weight_g": mass}], material_data)
        paper_names = {str(r.get("material")) for r in rows if is_paper(r)}
        plastic_components = {p["component"] for p in parts}
        # Only a supported paper + individually estimated plastic BOM may allocate
        # residual total mass to paper. Never assign one total to multiple factors.
        if mass is not None and len(paper_names) == 1 and all(is_paper(r) or r["component"] in plastic_components for r in rows):
            field = "after_weight_g" if after_state else "weight_g"
            if all(p[field] is not None for p in parts):
                plastic_mass = sum(p[field] for p in parts)
                if 0 <= plastic_mass <= mass:
                    bom = [{"material": p["material"], "weight_g": p[field]} for p in parts if p[field] > 0]
                    bom.append({"material": next(iter(paper_names)), "weight_g": mass-plastic_mass})
                    return estimate_co2e(bom, material_data)
        return estimate_co2e([], material_data)
    carbon_before = carbon(before)
    carbon_after = estimate_co2e([], material_data) if actions & {"replace_inner_tray", "simplify_materials"} or "R05" in rules else carbon(after, True)
    def flatten(side):
        return {**{k:v["value"] for k,v in side.items()}, "metric_provenance": side,
                "estimated": True, "hypothesis": "AI/规则估算；最终以实际测量和工程验证为准。", "estimation_method": "visual_rule_based"}
    return {"before": flatten(before), "after": flatten(after), "estimated": True,
            "estimation_method": "visual_rule_based", "carbon_estimate": {"before": carbon_before, "after": carbon_after}}


def estimate_packaging(analysis_result, functional_checks=(), opportunities=(), change_plan=None, material_data=None):
    """Prefer geometry/material digital-twin estimates; use legacy rules per missing metric."""
    analysis = analysis_result.get("data", analysis_result)
    plan = deepcopy(change_plan or {})
    if opportunities:
        allowed = set()
        for opportunity in opportunities:
            opportunity = opportunity.model_dump() if hasattr(opportunity, "model_dump") else opportunity
            nested = opportunity.get("component_actions") or []
            if nested:
                allowed.update((str(action.get("rule_id") or opportunity.get("rule_id")), str(action.get("component", "")).casefold()) for action in nested)
            else:
                allowed.add((str(opportunity.get("rule_id")), str(opportunity.get("target", "")).casefold()))
        plan["component_actions"] = [action for action in plan.get("component_actions", [])
                                     if (str(action.get("rule_id")), str(action.get("component", "")).casefold()) in allowed]
    legacy = _estimate_packaging_legacy(analysis, functional_checks, opportunities, plan, material_data)
    before_state = build_packaging_state(analysis)
    after_state = apply_change_plan(before_state, plan)

    state_keys = {
        "layers": "layer_count", "plastic_weight_g": "plastic_weight_g",
        "packaging_weight_g": "total_weight_g", "space_utilization": "space_utilization",
        "recyclability": "recyclability",
    }
    measurements = analysis.get("measurements") or analysis.get("measurement") or {}
    measured_keys = {"layers": "layers", "packaging_weight_g": "total_weight_g",
                     "plastic_weight_g": "plastic_weight_g", "space_utilization": "space_utilization",
                     "recyclability": "recyclability"}

    def phase(state, fallback, is_after=False):
        result, provenance = {}, {}
        for key, state_key in state_keys.items():
            value = state.get(state_key)
            source = "inferred" if is_after else "estimated"
            confidence = state.get("confidence", .4)
            hypothesis = "材料属性与包装几何数字模型估算；需要尺寸、称重和工程验证。"
            measured = measurements.get(measured_keys[key])
            if isinstance(measured, dict):
                measured = measured.get("value") if measured.get("source") in {"measured", "user_measured", "user_supplied"} else None
            legacy_measured = (measurements.get("before") or {}).get(key)
            if isinstance(legacy_measured, dict) and legacy_measured.get("source") == "measured" and legacy_measured.get("evidence"):
                measured = legacy_measured.get("value")
            if not is_after and measured is not None and number(measured) is not None:
                value, source, confidence = number(measured), "measured", 1
                hypothesis = "用户提供的测量值；系统未独立验证。"
            if value is None or (key == "layers" and value == 0):
                value = fallback.get(key)
                legacy_meta = (fallback.get("metric_provenance") or {}).get(key, {})
                source = legacy_meta.get("source", "pending")
                confidence = legacy_meta.get("confidence", 0)
                hypothesis = "几何或材料数据不足，使用规则区间回退。" if value is not None else legacy_meta.get("hypothesis", "暂无法估算")
            value = round(value) if value is not None else None
            low, high = LIMITS[key]
            value = min(high, max(low, value)) if value is not None else None
            result[key] = value
            provenance[key] = metric(value, source, (low, high), hypothesis, confidence)
        result.update(metric_provenance=provenance, estimated=True,
                      hypothesis="AI/规则估算；最终以实际测量和工程验证为准。",
                      estimation_method="material_geometry_digital_twin",
                      carbon_kgco2e=state.get("carbon_kgco2e"), packaging_state=state)
        return result

    before = phase(before_state, legacy["before"])
    if plan.get("target_layer_count") is not None:
        after_state["layer_count"] = plan["target_layer_count"]
    after = phase(after_state, legacy["after"], True)
    if not plan.get("component_actions"):
        for key in state_keys:
            after[key] = before[key]
            after["metric_provenance"][key] = metric(before[key], "inferred", LIMITS[key],
                "方案未批准影响此指标的结构动作，沿用优化前数值；优化后仍需验证。", .5)
    carbon_before = {"estimated_co2e_kg": before_state.get("carbon_kgco2e"), "source": "estimated",
                     "estimated": True, "requires_validation": True, "materials": before_state.get("components", []),
                     "hypothesis": "估算材料质量 × 材料属性库中的DEFRA 2024参考因子。"}
    carbon_after = {**carbon_before, "estimated_co2e_kg": after_state.get("carbon_kgco2e"),
                    "materials": after_state.get("components", [])}
    if carbon_before["estimated_co2e_kg"] is None:
        carbon_before = legacy["carbon_estimate"]["before"]
    if carbon_after["estimated_co2e_kg"] is None:
        carbon_after = legacy["carbon_estimate"]["after"]
    return {"before": before, "after": after, "estimated": True,
            "estimation_method": "material_geometry_digital_twin",
            "carbon_estimate": {"before": carbon_before, "after": carbon_after}}


def validate_estimation_consistency(estimates, plan):
    """Fail internally rather than send metrics that contradict the image plan."""
    before, after = estimates["before"], estimates["after"]
    actions = plan.get("component_actions", [])
    rules = {a["rule_id"] for a in actions}
    def changed(key, direction):
        return before[key] is not None and after[key] is not None and direction*(after[key]-before[key]) > 0
    if changed("layers", -1) and not (plan.get("reduce_layers") and
            (plan.get("remove_components") or plan.get("merge_components")) and
            any(a["action"] in {"remove", "integrate_into"} for a in actions)):
        raise ValueError("Layer estimate has no approved component removal/integration")
    if plan.get("target_layer_count") is not None and after["layers"] != plan["target_layer_count"]:
        raise ValueError("After layer estimate contradicts target_layer_count")
    if changed("space_utilization", 1) and not ("R02" in rules and
            ((plan.get("resize_spec") or {}).get("enabled") or plan.get("layout_compact"))):
        raise ValueError("Utilization estimate has no approved resize/layout action")
    if changed("plastic_weight_g", -1) and not (rules & {"R01", "R03"} or any(a["rule_id"] == "R04" and a["action"] == "integrate_into" for a in actions)):
        raise ValueError("Plastic estimate has no approved plastic removal/replacement action")
    if changed("recyclability", 1) and not rules & {"R01", "R03", "R04", "R05"}:
        raise ValueError("Recyclability estimate has no supporting rule")
