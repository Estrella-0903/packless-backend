from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.models import OptimizationOpportunity, RedesignData, RedesignOption
from app.services.rule_engine import run_rule_engine, violates_hard_constraints
from app.services.material_data_service import build_carbon_data
from app.services.packaging_estimator import estimate_packaging, components, layer_component_names, validate_estimation_consistency
from app.services.prompt_builder import build_visual_change_summary
from app.services.scoring_engine import score_redesign


ENVIRONMENT_VALUE = {
    "R01": 14,
    "R02": 16,
    "R03": 18,
    "R04": 12,
    "R05": 9,
}
OPTION_TITLES = {
    "aggressive": "激进减量方案",
    "balanced": "平衡优化方案",
    "low_risk": "低风险改良方案",
}


def _extract_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 2)


def _select_opportunities(
    profile: str, opportunities: list[OptimizationOpportunity]
) -> list[OptimizationOpportunity]:
    if profile == "aggressive":
        return list(opportunities)

    ranked = sorted(
        opportunities,
        key=lambda item: (
            -(ENVIRONMENT_VALUE.get(item.rule_id, 0) * item.confidence),
            _risk_rank(item.commercial_risk) + _risk_rank(item.supply_chain_risk),
        ),
    )
    if profile == "balanced":
        eligible = [
            item
            for item in ranked
            if _risk_rank(item.commercial_risk) <= 1
            and _risk_rank(item.supply_chain_risk) <= 1
            and item.confidence >= 0.5
        ]
        selected = eligible[:4]
        visible = [o for o in ranked if o.confidence >= .65 and o.visual_impact in {"medium", "high"} and o.component_actions]
        if visible and not any(o in visible for o in selected):
            # All inputs have already passed hard constraints. Higher supply risk
            # remains disclosed and conditional; it is not a safety exemption.
            selected = [visible[0]] + selected[:3]
        return selected

    return [
        item
        for item in ranked
        if (
            item.rule_id == "R05"
            or (item.commercial_risk == "low" and item.supply_chain_risk == "low")
        ) and item.confidence >= 0.65
    ][:2]


def _score(profile: str, selected: list[OptimizationOpportunity], estimates: dict, plan: dict) -> RedesignOption:
    scores = score_redesign(
        estimates["before"]["packaging_state"], estimates["after"]["packaging_state"], selected, plan
    )
    rule_ids = list(dict.fromkeys(item.rule_id for item in selected))
    if rule_ids:
        summary = (
            f"按{OPTION_TITLES[profile]}的风险偏好采用规则 "
            f"{', '.join(rule_ids)}；所有替代与减量动作以验证通过为实施前提。"
        )
    else:
        summary = "当前证据不足以批准低风险结构变更，建议先补充尺寸、功能和供应链验证数据。"
    return RedesignOption(
        id=profile,
        title=OPTION_TITLES[profile],
        summary=summary,
        environment_score=scores["environment_score"],
        business_score=scores["business_score"],
        supply_chain_score=scores["supply_chain_score"],
        overall_score=scores["overall_score"],
        selected_rule_ids=rule_ids,
        violates_hard_constraints=False,
        requires_validation=any(item.requires_validation for item in selected),
        estimated=True,
        hypothesis=(
            "评分来自前后包装数字模型、材料属性、DEFRA参考因子与规则风险；不是实测成本、销量或认证环境结论。"
        ),
        estimated_cost_change_percent=scores["estimated_cost_change_percent"],
        meaningful_improvement=scores["meaningful_improvement"],
        meaningful_improvement_score=scores["meaningful_improvement_score"],
        score_breakdown=scores["score_breakdown"],
    )


def _recommended_option(options: list[RedesignOption]) -> RedesignOption:
    meaningful = [item for item in options if item.meaningful_improvement]
    ranked = sorted(meaningful or options, key=lambda item: item.overall_score, reverse=True)
    if len(ranked) == 1:
        return ranked[0]
    if ranked[0].overall_score - ranked[1].overall_score < 3:
        return max(
            ranked[:2],
            key=lambda item: (
                item.supply_chain_score,
                item.id == "balanced",
            ),
        )
    return ranked[0]


def _compatible_opportunities(selected):
    """Avoid deleting/replacing the same component twice or changing a removed one."""
    result, removed, modified = [], set(), set()
    ordered = sorted(selected, key=lambda o: o.rule_id == "R05")
    for opportunity in ordered:
        changed = {a.component for a in opportunity.component_actions}
        deleted = {a.component for a in opportunity.component_actions if a.action in {"remove", "integrate_into"}}
        recipients = {a.target_component for a in opportunity.component_actions if a.target_component}
        if changed & removed or deleted & modified or recipients & removed:
            continue
        result.append(opportunity)
        removed |= deleted
        modified |= changed
    return result


def _change_plan(analysis, selected):
    component_actions = [a.model_dump(by_alias=True, exclude_none=True)
                         for o in selected for a in o.component_actions]
    remove = list(dict.fromkeys(a["component"] for a in component_actions if a["action"] == "remove"))
    merge = [a for a in component_actions if a["action"] == "integrate_into"]
    resize = next((a for a in component_actions if a["action"] == "resize"), None)
    tray = next((a for a in component_actions if a["action"] == "replace_material"), None)
    known = [r["component"] for r in components(analysis)]
    eliminated = {name.casefold() for name in remove} | {a["component"].casefold() for a in merge}
    layers = estimate_packaging(analysis)["before"]["layers"]
    removed_layers = len(eliminated & layer_component_names(analysis))
    target_layers = max(1, layers-removed_layers) if layers is not None else None
    reduce_layers = bool(removed_layers and layers is not None and target_layers < layers)
    scale = resize["scale"] if resize else 1
    strength = "high" if any(o.visual_impact == "high" for o in selected) else "medium" if any(o.visual_impact == "medium" for o in selected) else "low"
    result = {
        "component_actions": component_actions, "remove_components": remove,
        "merge_components": merge, "reduce_layers": reduce_layers, "target_layer_count": target_layers,
        "preserve_components": [name for name in known if name.casefold() not in eliminated],
        "remove_plastic_film": any(a["rule_id"] == "R03" and a["action"] == "remove" for a in component_actions),
        "replace_inner_tray": {"from": tray["from"] if tray else "", "to": tray["to"] if tray else ""},
        "resize_outer_box": f"外包装体积预计减少约 {round((1-scale)*100,1)}%，产品尺寸保持不变。" if resize else "证据不足，暂时保持当前外包装体积。",
        "resize_spec": {"enabled": bool(resize), "component": resize["component"] if resize else "",
                        "scale": scale, "scale_basis": "outer_volume_ratio", "resize_axis": "overall",
                        "estimated_reduction_percent": round((1-scale)*100,1),
                        "layout_strategy": resize["layout_strategy"] if resize else ""},
        "reduce_material_types": bool(merge), "keep_brand_style": True, "layout_compact": bool(resize),
        "visual_change_strength": strength,
        "visual_change_note": "本方案以材料来源优化为主，结构变化较小。" if strength == "low" else "",
    }
    result["visual_change_summary"] = build_visual_change_summary(result)
    return result


def create_redesign_plan(payload: dict[str, Any]) -> RedesignData:
    analysis = _extract_analysis(payload)
    packaging = analysis.get("packaging") or {}
    # Feed bounded visual estimates to existing rules so malformed 1%/1-layer
    # model values do not suppress legitimate opportunities. Do not mutate input.
    baseline = estimate_packaging(analysis)["before"]
    geometry = baseline["packaging_state"]["geometry"]
    engine_analysis = {**analysis, "packaging": {**packaging,
        "layers": baseline["layers"], "space_utilization": baseline["space_utilization"],
        "recommended_outer_volume_ratio": geometry["recommended_outer_volume_ratio"],
        "minimum_safe_dimensions": geometry["minimum_safe_dimensions"],
        "geometry_confidence": geometry["confidence"],
        "geometry_source": geometry["source"],
        "metric_provenance": baseline["metric_provenance"]}}
    engine = run_rule_engine(engine_analysis)

    selected_by_profile: dict[str, list[OptimizationOpportunity]] = {}
    plan_by_profile: dict[str, dict] = {}
    estimates_by_profile: dict[str, dict] = {}
    options: list[RedesignOption] = []
    safe_opportunities = [o for o in engine.opportunities if not violates_hard_constraints([o], engine.functional_checks, engine.hard_constraints)]
    for profile in ("aggressive", "balanced", "low_risk"):
        selected = _compatible_opportunities(_select_opportunities(profile, safe_opportunities))
        selected_by_profile[profile] = selected
        candidate_plan = _change_plan(analysis, selected)
        candidate_estimates = estimate_packaging(analysis, engine.functional_checks, selected, candidate_plan)
        validate_estimation_consistency(candidate_estimates, candidate_plan)
        plan_by_profile[profile] = candidate_plan
        estimates_by_profile[profile] = candidate_estimates
        options.append(_score(profile, selected, candidate_estimates, candidate_plan))

    # A no-change low-risk option is always hard-constraint-safe and keeps the API
    # usable even when all proposed changes are filtered out.
    if not options:
        selected_by_profile["low_risk"] = []
        candidate_plan = _change_plan(analysis, [])
        candidate_estimates = estimate_packaging(analysis, engine.functional_checks, [], candidate_plan)
        plan_by_profile["low_risk"] = candidate_plan
        estimates_by_profile["low_risk"] = candidate_estimates
        options = [_score("low_risk", [], candidate_estimates, candidate_plan)]

    recommended = _recommended_option(options)
    selected = selected_by_profile[recommended.id]
    plan = plan_by_profile[recommended.id]
    carbon_data = build_carbon_data(analysis)
    estimates = estimates_by_profile[recommended.id]
    carbon_data["visual_estimate"] = estimates["carbon_estimate"]
    before_state = estimates["before"]["packaging_state"]
    estimated_weight = before_state.get("total_weight_g")
    estimated_carbon = before_state.get("carbon_kgco2e")
    carbon_data.update({
        "weight_kg": round(estimated_weight / 1000, 4) if estimated_weight is not None else None,
        "estimated_material_co2e_kg": estimated_carbon,
        "estimated_total_co2e_kg": estimated_carbon,
        "requires_weight_measurement": True,
        "requires_complete_bill_of_materials": True,
        "digital_twin_materials": before_state.get("components", []),
        "weight_source": before_state.get("total_weight_source"),
    })

    return RedesignData.model_validate(
        {
            "redesign_id": f"redesign_{uuid4().hex[:12]}",
            "estimation_method": "material_geometry_digital_twin",
            "carbon_data": carbon_data,
            "analysis_id": analysis.get("analysis_id"),
            "recommended_option": recommended.id,
            "functional_checks": [item.model_dump() for item in engine.functional_checks],
            "hard_constraints": [item.model_dump() for item in engine.hard_constraints],
            "opportunities": [item.model_dump() for item in engine.opportunities],
            "options": [item.model_dump() for item in options],
            "before": estimates["before"],
            "after": estimates["after"],
            "change_plan": plan,
            "after_render_spec": {
                "box_scale": plan["resize_spec"]["scale"],
                "target_layer_count": plan["target_layer_count"],
                "remove_components": plan["remove_components"],
                "component_actions": plan["component_actions"],
                "preserve_components": plan["preserve_components"],
                "void_reduction": "moderate" if plan["layout_compact"] else "none",
                "remove_plastic_film": plan["remove_plastic_film"],
                "tray_material": plan["replace_inner_tray"]["to"],
                "layout_compact": plan["layout_compact"],
                "style": "keep_original_brand",
            },
            "optimized_image_url": "",
            "image_generation_failed": True,
            "image_generation_error": "未提供原始图片，或图片生成尚未开始。",
        }
    )
