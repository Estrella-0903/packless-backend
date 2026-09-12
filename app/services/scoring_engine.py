"""Data-driven option scoring. Scores are estimates, not measured outcomes."""
from __future__ import annotations

from typing import Any


def _dict(value: Any) -> dict:
    return value.model_dump() if hasattr(value, "model_dump") else value


def _reduction(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before <= 0:
        return None
    return max(-1, min(1, (before - after) / before))


def _piecewise(value: float | None) -> float | None:
    if value is None:
        return None
    value = max(0, value)
    points = ((0, 0), (.1, 40), (.2, 70), (.3, 100))
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if value <= x2:
            return round(y1 + (value - x1) / (x2 - x1) * (y2 - y1), 1)
    return 100.0


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 2)


def _worst_risk(values: list[str], default: str = "low") -> str:
    """Preserve `unknown` instead of silently treating it as a known high risk."""
    ranks = {"low": 0, "medium": 1, "unknown": 2, "high": 3}
    normalized = [value if value in ranks else "unknown" for value in values]
    return max(normalized or [default], key=ranks.__getitem__)


def _estimated_cost(before: dict, after: dict) -> float | None:
    def total(state):
        rows = state.get("components") or []
        values = [row.get("estimated_weight_g") for row in rows]
        return sum(value * row.get("relative_cost_index", 1) for row, value in zip(rows, values)) if rows and all(v is not None for v in values) else None
    old, new = total(before), total(after)
    return round((new-old)/old*100, 1) if old and new is not None else None


def _bounded(value: float) -> float:
    return round(max(0, min(100, value)), 1)


def _item(key: str, title: str, normalized_score: float | None, weight: float,
          explanation: str, source: str, *, awarded_points: int | None = None,
          status: str = "AI/规则估算") -> dict[str, Any]:
    max_score = round(weight * 100)
    points = (
        awarded_points
        if awarded_points is not None
        else None if normalized_score is None else round(normalized_score * weight)
    )
    return {
        "key": key, "title": title, "score": points,
        "max_score": max_score, "normalized_score": normalized_score,
        "weight_percent": round(weight * 100),
        "points": points, "max_points": max_score,
        "explanation": explanation, "source": source,
        "status": status,
        "requires_validation": True,
    }


def _allocate_integer_points(
    raw_points: list[float], maxima: list[int], total: int
) -> list[int]:
    """Allocate a rounded/penalized total without breaking child-score equality."""
    target = max(0, min(sum(maxima), int(total)))
    raw_total = sum(max(0, value) for value in raw_points)
    scaled = [0.0] * len(raw_points) if raw_total <= 0 else [
        min(maximum, max(0, value) * target / raw_total)
        for value, maximum in zip(raw_points, maxima)
    ]
    points = [min(maximum, int(value)) for value, maximum in zip(scaled, maxima)]
    remaining = target - sum(points)
    order = sorted(
        range(len(points)),
        key=lambda index: (scaled[index] - points[index], maxima[index] - points[index]),
        reverse=True,
    )
    while remaining > 0:
        changed = False
        for index in order:
            if points[index] < maxima[index]:
                points[index] += 1
                remaining -= 1
                changed = True
                if remaining == 0:
                    break
        if not changed:
            break
    return points


def score_redesign(before: dict[str, Any], after: dict[str, Any], opportunities: list[Any], change_plan: dict[str, Any]) -> dict[str, Any]:
    selected = [_dict(item) for item in opportunities]
    weight_reduction = _reduction(before.get("total_weight_g"), after.get("total_weight_g"))
    plastic_before = before.get("plastic_weight_g")
    plastic_reduction = None if plastic_before in (None, 0) else _reduction(plastic_before, after.get("plastic_weight_g"))
    carbon_reduction = _reduction(before.get("carbon_kgco2e"), after.get("carbon_kgco2e"))
    recycle_delta = (after["recyclability"]-before["recyclability"]) if before.get("recyclability") is not None and after.get("recyclability") is not None else None
    space_delta = (after["space_utilization"]-before["space_utilization"]) if before.get("space_utilization") is not None and after.get("space_utilization") is not None else None
    dimensions = {
        "weight_reduction_score": (_piecewise(weight_reduction), .25),
        "plastic_reduction_score": (_piecewise(plastic_reduction), .20),
        "carbon_reduction_score": (_piecewise(carbon_reduction), .30),
        "recyclability_score": (round(max(0, min(100, (recycle_delta or 0)*4)), 1) if recycle_delta is not None else None, .15),
        "space_efficiency_score": (round(max(0, min(100, (space_delta or 0)*4)), 1) if space_delta is not None else None, .10),
    }
    usable = [(score, weight) for score, weight in dimensions.values() if score is not None]
    available_weight = sum(weight for _, weight in usable)
    weighted = sum(score*weight for score, weight in usable) / available_weight if usable else 0
    has_environment_change = any(value > 0 for value in (
        weight_reduction or 0, plastic_reduction or 0, carbon_reduction or 0,
        recycle_delta or 0, space_delta or 0,
    ))
    environment_floor = 45 if has_environment_change else 25
    environment = round(max(environment_floor, min(100, weighted)))

    cost_change = _estimated_cost(before, after)
    actions = [action for item in selected for action in item.get("component_actions", [])]
    kinds = {action.get("action") for action in actions}
    removed_steps = sum(action.get("action") in {"remove", "integrate_into"} for action in actions)
    new_supplier = any(action.get("action") == "replace_material" for action in actions)
    new_tooling = any(action.get("action") in {"resize", "resize_to_fit", "replace_material"} for action in actions)
    speculative_structural_penalty = min(25, round(sum(
        max(0, .5 - float(item.get("confidence") or 0)) * 200
        for item in selected
        if any(action.get("action") in {"remove", "integrate_into"}
               for action in item.get("component_actions", []))
    )))
    complexity = max(0, len(actions)-1)
    process_change_rank = max([_risk_rank(item.get("risk_assessment", {}).get("process_compatibility", "high")) for item in selected] or [0])
    brand_rank = max([_risk_rank(item.get("risk_assessment", {}).get("brand_experience", "high")) for item in selected] or [0])
    consumer_rank = max([_risk_rank(item.get("risk_assessment", {}).get("consumer_experience", "high")) for item in selected] or [0])
    cost_score = _bounded(60 - (cost_change or 0) * 2) if cost_change is not None else 60
    process_score = _bounded(90 + removed_steps*5 - process_change_rank*20 - complexity*2)
    brand_score = _bounded(95 - brand_rank*25)
    consumer_score = _bounded(95 - consumer_rank*25)
    implementation_score = _bounded(95 - (15 if new_tooling else 0) - (15 if new_supplier else 0)
                                    - (15 if "replace_material" in kinds else 0) - complexity*4)
    business_dimensions = ((cost_score, .25), (process_score, .20), (brand_score, .20),
                           (consumer_score, .15), (implementation_score, .20))
    business = round(max(0, sum(score*weight for score, weight in business_dimensions)
                         - speculative_structural_penalty))
    business_points = _allocate_integer_points(
        [score * weight for score, weight in business_dimensions],
        [25, 20, 20, 15, 20], business,
    )

    availability_risk = _worst_risk([
        item.get("risk_assessment", {}).get("material_availability", "unknown")
        for item in selected
    ])
    process_risk = _worst_risk([
        item.get("risk_assessment", {}).get("process_compatibility", "unknown")
        for item in selected
    ])
    transport_risk = _worst_risk([
        item.get("risk_assessment", {}).get("transport_protection", "unknown")
        for item in selected
    ])
    low_confidence_risk_escalated = speculative_structural_penalty > 0
    if low_confidence_risk_escalated:
        # Do not add an invisible sixth deduction to a five-item score. Instead,
        # disclose low-confidence removal/integration as conservative high risk
        # in the affected implementation dimensions.
        availability_risk = "high"
        process_risk = "high"
        transport_risk = "high"

    # Fixed points make the public risk matrix auditable. Values sit inside the
    # ranges shown in the UI and the five awarded point values are the total.
    availability_points = {"low": 24, "medium": 16, "high": 9, "unknown": 14}[availability_risk]
    line_points = {"low": 19, "medium": 15, "high": 8, "unknown": 13}[process_risk]
    transport_points = {"low": 19, "medium": 14, "high": 6, "unknown": 13}[transport_risk]
    line_compatibility = {
        "low": "high", "medium": "medium", "high": "low", "unknown": "unknown"
    }[process_risk]

    explicit_supplier_requirement = [
        item.get("supplier_change_requirement") for item in selected
        if item.get("supplier_change_requirement") in {"required", "possible"}
    ]
    supplier_requirement = (
        "required" if "required" in explicit_supplier_requirement
        else "possible" if new_supplier or "possible" in explicit_supplier_requirement
        else "none"
    )
    supplier_points = {"none": 19, "possible": 14, "required": 8}[supplier_requirement]

    tooling_requirement = (
        "new_tooling" if "replace_material" in kinds
        else "die_adjustment" if kinds & {"resize", "resize_to_fit"}
        else "none"
    )
    tooling_points = {"none": 15, "die_adjustment": 12, "new_tooling": 7}[tooling_requirement]
    supply_points = [
        availability_points, supplier_points, line_points, tooling_points, transport_points
    ]
    supply = sum(supply_points)
    supplier_status = {
        "none": "无需新增供应商",
        "possible": "可能需要新增供应商",
        "required": "必须更换供应商",
    }[supplier_requirement]
    tooling_status = {
        "none": "无需新模具",
        "die_adjustment": "仅刀模调整",
        "new_tooling": "需要新模具",
    }[tooling_requirement]
    risk_label = {"low": "低风险", "medium": "中等风险", "high": "高风险", "unknown": "风险待确认"}
    compatibility_label = {"high": "高兼容", "medium": "中等兼容", "low": "低兼容", "unknown": "兼容性待确认"}
    improvement_values = [value for value in (
        None if weight_reduction is None else weight_reduction*100,
        None if plastic_reduction is None else plastic_reduction*100,
        None if carbon_reduction is None else carbon_reduction*100,
        recycle_delta, space_delta) if value is not None]
    meaningful_score = round(max([0, *improvement_values]), 1)
    meaningful = meaningful_score > 5
    no_improvement_penalty = 0 if meaningful else 15
    overall = round(max(0, .4*environment + .3*business + .3*supply - no_improvement_penalty), 1)
    return {
        "environment_score": environment, "business_score": business,
        "supply_chain_score": supply, "overall_score": overall,
        "estimated_cost_change_percent": cost_change,
        "meaningful_improvement": meaningful,
        "meaningful_improvement_score": meaningful_score,
        "score_breakdown": {
            "environment": {
                "total_score": environment,
                "weight_reduction_percent": round((weight_reduction or 0)*100, 1),
                "plastic_reduction_percent": None if plastic_reduction is None else round(plastic_reduction*100, 1),
                "carbon_reduction_percent": None if carbon_reduction is None else round(carbon_reduction*100, 1),
                "recyclability_improvement": recycle_delta,
                "space_improvement": space_delta,
                **{key: score for key, (score, _) in dimensions.items()},
                "weights_redistributed": any(score is None for score, _ in dimensions.values()),
                "no_improvement_penalty": no_improvement_penalty,
                "items": [
                    _item("weight", "包装减量", dimensions["weight_reduction_score"][0], .25,
                          f"包装重量预计减少 {round((weight_reduction or 0)*100, 1)}%。", "AI估算"),
                    _item("plastic", "塑料减量", dimensions["plastic_reduction_score"][0], .20,
                          "未识别明确塑料，不作为扣分项。" if plastic_reduction is None else f"塑料重量预计减少 {round(plastic_reduction*100, 1)}%。", "AI识别 + 材料估算"),
                    _item("carbon", "碳排改善", dimensions["carbon_reduction_score"][0], .30,
                          "缺少可用材料因子。" if carbon_reduction is None else f"参考碳排预计减少 {round(carbon_reduction*100, 1)}%。", "DEFRA 2024 + AI质量估算"),
                    _item("recycle", "可回收性", dimensions["recyclability_score"][0], .15,
                          f"可回收评分预计提高 {recycle_delta or 0} 分。", "规则估算"),
                    _item("space", "空间效率", dimensions["space_efficiency_score"][0], .10,
                          f"空间利用率预计提高 {space_delta or 0} 个百分点。", "几何估算"),
                ],
                "baseline_adjustment": round(max(0, 45-weighted), 1),
            },
            "business": {
                "total_score": business,
                "speculative_structural_penalty": speculative_structural_penalty,
                "estimated_material_cost_change_percent": cost_change,
                "process_steps_removed": removed_steps,
                "process_change_risk": ("low", "medium", "high")[process_change_rank],
                "brand_risk": ("low", "medium", "high")[brand_rank],
                "consumer_experience_risk": ("low", "medium", "high")[consumer_rank],
                "new_tooling_required": new_tooling,
                "change_complexity_penalty": complexity*4,
                "items": [
                    _item("cost", "材料成本", cost_score, .25, "预计基本持平。" if cost_change is None else f"材料成本预计变化 {cost_change}%。", "AI材料质量 + 成本代理", awarded_points=business_points[0]),
                    _item("process", "工艺改动", process_score, .20, f"预计减少 {removed_steps} 道独立包装工序。", "规则估算", awarded_points=business_points[1]),
                    _item("brand", "品牌影响", brand_score, .20, f"品牌体验风险为 {('低','中等','高')[brand_rank]}。", "规则评估", awarded_points=business_points[2]),
                    _item("consumer", "消费者体验", consumer_score, .15, f"消费者体验风险为 {('低','中等','高')[consumer_rank]}。", "规则评估", awarded_points=business_points[3]),
                    _item("implementation", "一次性投入", implementation_score, .20, "需要新模具或供应商验证。" if new_tooling or new_supplier else "可沿用现有供应与主要工艺。", "规则评估", awarded_points=business_points[4]),
                ],
            },
            "supply_chain": {
                "material_availability_score": supply_points[0],
                "supplier_change_score": supply_points[1],
                "production_line_score": supply_points[2],
                "tooling_score": supply_points[3],
                "transport_protection_score": supply_points[4],
                "total_score": supply,
                "speculative_structural_penalty": 0,
                "new_supplier_required": supplier_requirement != "none",
                "new_tooling_required": tooling_requirement == "new_tooling",
                "production_line_compatibility": line_compatibility,
                "material_availability_risk": availability_risk,
                "transport_protection_risk": transport_risk,
                "supplier_change_status": supplier_status,
                "supplier_change_requirement": supplier_requirement,
                "tooling_status": tooling_status,
                "tooling_requirement": tooling_requirement,
                "low_confidence_risk_escalated": low_confidence_risk_escalated,
                "items": [
                    _item("availability", "材料可得性", None, .25,
                          "替代或再生材料需要确认供应稳定性与批次一致性。" if availability_risk != "low" else "现有材料体系供应成熟，仍建议确认批次一致性。",
                          "AI材料识别 + 供应链风险规则", awarded_points=supply_points[0], status=risk_label[availability_risk]),
                    _item("supplier", "供应商变更", None, .20,
                          "建议先询价并确认供货周期。" if supplier_requirement != "none" else "预计可沿用现有供应商，需确认新规格供货能力。",
                          "材料替换动作规则", awarded_points=supply_points[1], status=supplier_status),
                    _item("line", "产线兼容性", None, .20,
                          "现有包装线可能需要轻度调整与试机确认。" if line_compatibility == "medium" else "需要评估现有产线适配能力。" if line_compatibility == "low" else "预计可兼容现有主要包装工序。",
                          "工艺兼容风险规则", awarded_points=supply_points[2], status=compatibility_label[line_compatibility]),
                    _item("tooling", "模具/刀模", None, .15,
                          "预计只需修改刀模，无需新增复杂模具。" if tooling_requirement == "die_adjustment" else "需要新模具并以打样验证为准。" if tooling_requirement == "new_tooling" else "无需新增主要模具，仍需首件确认。",
                          "结构动作规则", awarded_points=supply_points[3], status=tooling_status),
                    _item("transport", "运输保护", None, .20,
                          "缩容或结构调整后建议进行跌落、振动与运输测试。" if transport_risk != "low" else "结构风险较低，仍建议进行基础运输验证。",
                          "运输保护风险规则", awarded_points=supply_points[4], status=risk_label[transport_risk]),
                ],
            },
            "estimated": True,
            "basis": "前后包装数字模型、材料属性、DEFRA参考因子与规则风险矩阵",
        },
    }
