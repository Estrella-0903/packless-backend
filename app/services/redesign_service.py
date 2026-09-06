from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.models import OptimizationOpportunity, RedesignData, RedesignOption
from app.services.rule_engine import run_rule_engine, violates_hard_constraints
from app.services.material_data_service import build_carbon_data
from app.services.packaging_estimator import estimate_packaging


RISK_PENALTY = {"low": 2, "medium": 6, "high": 14}
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


def _nullable_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return None


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
        return eligible[:4]

    return [
        item
        for item in ranked
        if item.commercial_risk == "low"
        and item.supply_chain_risk == "low"
        and item.confidence >= 0.65
    ][:2]


def _score(profile: str, selected: list[OptimizationOpportunity]) -> RedesignOption:
    environment_score = min(
        100,
        round(
            45
            + sum(
                ENVIRONMENT_VALUE.get(item.rule_id, 0) * item.confidence
                for item in selected
            )
        ),
    )
    commercial_penalty = sum(
        RISK_PENALTY.get(item.commercial_risk, 14) for item in selected
    )
    supply_penalty = sum(
        RISK_PENALTY.get(item.supply_chain_risk, 14) for item in selected
    )
    validation_penalty = sum(2 for item in selected if item.requires_validation)
    if selected:
        business_score = max(0, 100 - commercial_penalty - validation_penalty)
        supply_chain_score = max(0, 100 - supply_penalty - validation_penalty)
    else:
        # Doing nothing is operationally easy, but is not a perfect business option:
        # it leaves identified sustainability and material-efficiency needs unresolved.
        business_score = 80
        supply_chain_score = 85
    overall_score = round(
        0.4 * environment_score
        + 0.3 * business_score
        + 0.3 * supply_chain_score,
        1,
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
        environment_score=environment_score,
        business_score=business_score,
        supply_chain_score=supply_chain_score,
        overall_score=overall_score,
        selected_rule_ids=rule_ids,
        violates_hard_constraints=False,
        requires_validation=any(item.requires_validation for item in selected),
        estimated=True,
        hypothesis=(
            "Scores are rule-based decision estimates, not measured cost, sales, weight, carbon or performance outcomes."
        ),
    )


def _recommended_option(options: list[RedesignOption]) -> RedesignOption:
    ranked = sorted(options, key=lambda item: item.overall_score, reverse=True)
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


def _component_material(analysis: dict[str, Any], target: str) -> str:
    packaging = analysis.get("packaging") or {}
    for item in packaging.get("materials") or []:
        if isinstance(item, dict) and str(item.get("component") or "") == target:
            return str(item.get("material") or "")
    return ""


def _change_plan(
    analysis: dict[str, Any], selected: list[OptimizationOpportunity]
) -> dict[str, Any]:
    actions = {item.action for item in selected}
    tray = next(
        (item for item in selected if item.action == "replace_inner_tray"),
        None,
    )
    return {
        "remove_plastic_film": "remove_plastic_film" in actions,
        "replace_inner_tray": {
            "from": _component_material(analysis, tray.target) if tray else "",
            "to": "Molded pulp" if tray else "",
        },
        "resize_outer_box": (
            "Evaluate a 15–25% outer-volume reduction (estimated; validate transport protection)"
            if "reduce_volume" in actions
            else "Retain current outer-box volume pending evidence"
        ),
        "reduce_material_types": "simplify_materials" in actions,
        "keep_brand_style": True,
        "layout_compact": "reduce_volume" in actions,
    }


def create_redesign_plan(payload: dict[str, Any]) -> RedesignData:
    analysis = _extract_analysis(payload)
    packaging = analysis.get("packaging") or {}
    # Feed bounded visual estimates to existing rules so malformed 1%/1-layer
    # model values do not suppress legitimate opportunities. Do not mutate input.
    baseline = estimate_packaging(analysis)["before"]
    engine_analysis = {**analysis, "packaging": {**packaging,
        "layers": baseline["layers"], "space_utilization": baseline["space_utilization"],
        "metric_provenance": baseline["metric_provenance"]}}
    engine = run_rule_engine(engine_analysis)

    selected_by_profile: dict[str, list[OptimizationOpportunity]] = {}
    options: list[RedesignOption] = []
    for profile in ("aggressive", "balanced", "low_risk"):
        selected = _select_opportunities(profile, engine.opportunities)
        if violates_hard_constraints(
            selected, engine.functional_checks, engine.hard_constraints
        ):
            continue
        selected_by_profile[profile] = selected
        options.append(_score(profile, selected))

    # A no-change low-risk option is always hard-constraint-safe and keeps the API
    # usable even when all proposed changes are filtered out.
    if not options:
        selected_by_profile["low_risk"] = []
        options = [_score("low_risk", [])]

    recommended = _recommended_option(options)
    selected = selected_by_profile[recommended.id]
    selected_actions = {item.action for item in selected}
    plan = _change_plan(analysis, selected)
    carbon_data = build_carbon_data(analysis)
    estimates = estimate_packaging(analysis, engine.functional_checks, selected, plan, carbon_data)
    carbon_data["visual_estimate"] = estimates["carbon_estimate"]

    return RedesignData.model_validate(
        {
            "redesign_id": f"redesign_{uuid4().hex[:12]}",
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
                "box_scale": 0.8 if "reduce_volume" in selected_actions else 1.0,
                "remove_plastic_film": plan["remove_plastic_film"],
                "tray_material": plan["replace_inner_tray"]["to"],
                "layout_compact": plan["layout_compact"],
                "style": "keep_original_brand",
            },
            "optimized_image_url": "",
            "image_generation_failed": True,
            "image_generation_error": "Original image was not provided or generation has not started.",
        }
    )
