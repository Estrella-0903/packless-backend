from app.services.redesign_service import create_redesign_plan


def test_unknown_measurements_stay_null() -> None:
    plan = create_redesign_plan(
        {
            "analysis_id": "analysis_unknown",
            "packaging": {"materials": []},
            "environmental_impact": {},
        }
    )
    assert plan.before.packaging_weight_g is None
    assert plan.after.packaging_weight_g is None
    assert plan.before.space_utilization is None
    assert plan.after.space_utilization is None


def test_after_metrics_do_not_invent_precise_values() -> None:
    plan = create_redesign_plan(
        {
            "packaging": {
                "layers": 4,
                "space_utilization": 54,
                "recyclability_score": 62,
                "materials": [],
            },
            "environmental_impact": {
                "estimated_packaging_weight_g": 200,
                "estimated_plastic_weight_g": 80,
            },
        }
    )
    assert plan.after.layers == 4  # No identified component may be deleted.
    assert plan.after.packaging_weight_g is None
    assert plan.after.plastic_weight_g is None
    assert 54 <= plan.after.space_utilization <= 95
    assert plan.after.recyclability is None
    assert plan.after.estimated is True
    assert "估算" in plan.after.hypothesis


def test_recommendation_uses_weighted_score_and_tie_break() -> None:
    plan = create_redesign_plan(
        {
            "product": {"category": "cosmetics", "product_name": "cream"},
            "packaging": {
                "layers": 4,
                "space_utilization": 52,
                "materials": [
                    {
                        "component": "outer box",
                        "material": "paperboard",
                        "confidence": 0.9,
                        "evidence": "visible carton",
                    },
                    {
                        "component": "inner tray",
                        "material": "PET",
                        "confidence": 0.85,
                        "evidence": "transparent rigid tray",
                    },
                ],
            },
        }
    )
    by_id = {option.id: option for option in plan.options}
    recommended = by_id[plan.recommended_option]
    assert recommended.overall_score == round(
        0.4 * recommended.environment_score
        + 0.3 * recommended.business_score
        + 0.3 * recommended.supply_chain_score,
        1,
    )
    ranked = sorted(plan.options, key=lambda item: item.overall_score, reverse=True)
    if len(ranked) > 1 and ranked[0].overall_score - ranked[1].overall_score < 3:
        assert recommended.supply_chain_score == max(
            ranked[0].supply_chain_score, ranked[1].supply_chain_score
        )
