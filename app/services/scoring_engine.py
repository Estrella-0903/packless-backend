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


def _estimated_cost(before: dict, after: dict) -> float | None:
    def total(state):
        rows = state.get("components") or []
        values = [row.get("estimated_weight_g") for row in rows]
        return sum(value * row.get("relative_cost_index", 1) for row, value in zip(rows, values)) if rows and all(v is not None for v in values) else None
    old, new = total(before), total(after)
    return round((new-old)/old*100, 1) if old and new is not None else None


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
    weighted = sum(score*weight for score, weight in usable) / sum(weight for _, weight in usable) if usable else 0
    environment = round(max(45, min(100, weighted)))

    cost_change = _estimated_cost(before, after)
    actions = [action for item in selected for action in item.get("component_actions", [])]
    kinds = {action.get("action") for action in actions}
    material_saving_bonus = min(18, max(-8, -(cost_change or 0) * .6))
    process_bonus = 6 * sum(action.get("action") in {"remove", "integrate_into"} for action in actions)
    volume_bonus = 4 if "resize" in kinds else 0
    new_supplier = any(action.get("action") == "replace_material" for action in actions)
    new_tooling = any(action.get("action") in {"resize", "resize_to_fit", "replace_material"} for action in actions)
    change_complexity_penalty = max(0, len(actions)-1) * 4
    process_change_rank = max([_risk_rank(item.get("risk_assessment", {}).get("process_compatibility", "high")) for item in selected] or [0])
    brand_rank = max([_risk_rank(item.get("risk_assessment", {}).get("brand_experience", "high")) for item in selected] or [0])
    consumer_rank = max([_risk_rank(item.get("risk_assessment", {}).get("consumer_experience", "high")) for item in selected] or [0])
    business = round(max(0, min(100, 82 + material_saving_bonus + process_bonus + volume_bonus
                                 - process_change_rank*8 - brand_rank*6 - consumer_rank*4
                                 - (6 if new_tooling else 0) - (6 if new_supplier else 0)
                                 - (12 if "replace_material" in kinds else 0) - change_complexity_penalty)))

    availability_rank = max([_risk_rank(item.get("risk_assessment", {}).get("material_availability", "high")) for item in selected] or [0])
    transport_rank = max([_risk_rank(item.get("risk_assessment", {}).get("transport_protection", "high")) for item in selected] or [0])
    supply = round(max(0, min(100, 96 - availability_rank*6 - process_change_rank*8 - transport_rank*6
                               - (8 if new_tooling else 0) - (10 if new_supplier else 0)
                               - max(0, len(actions)-1)*2
                               + (4 if kinds == {"remove"} else 0))))
    overall = round(.4*environment + .3*business + .3*supply, 1)
    return {
        "environment_score": environment, "business_score": business,
        "supply_chain_score": supply, "overall_score": overall,
        "estimated_cost_change_percent": cost_change,
        "score_breakdown": {
            "environment": {
                "weight_reduction_percent": round((weight_reduction or 0)*100, 1),
                "plastic_reduction_percent": None if plastic_reduction is None else round(plastic_reduction*100, 1),
                "carbon_reduction_percent": None if carbon_reduction is None else round(carbon_reduction*100, 1),
                "recyclability_improvement": recycle_delta,
                "space_improvement": space_delta,
                **{key: score for key, (score, _) in dimensions.items()},
                "weights_redistributed": any(score is None for score, _ in dimensions.values()),
            },
            "business": {
                "estimated_material_cost_change_percent": cost_change,
                "material_saving_bonus": round(material_saving_bonus, 1),
                "process_steps_removed": sum(action.get("action") in {"remove", "integrate_into"} for action in actions),
                "process_change_risk": ("low", "medium", "high")[process_change_rank],
                "brand_risk": ("low", "medium", "high")[brand_rank],
                "consumer_experience_risk": ("low", "medium", "high")[consumer_rank],
                "new_tooling_required": new_tooling,
                "change_complexity_penalty": change_complexity_penalty,
            },
            "supply_chain": {
                "new_supplier_required": new_supplier,
                "new_tooling_required": new_tooling,
                "production_line_compatibility": ("high", "medium", "low")[process_change_rank],
                "material_availability_risk": ("low", "medium", "high")[availability_rank],
                "transport_protection_risk": ("low", "medium", "high")[transport_rank],
            },
            "estimated": True,
            "basis": "前后包装数字模型、材料属性、DEFRA参考因子与规则风险矩阵",
        },
    }
