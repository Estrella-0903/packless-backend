from app.schemas.models import OptimizationOpportunity
from app.services.rule_engine import run_rule_engine, violates_hard_constraints


def _analysis(category: str = "cosmetics") -> dict:
    return {
        "product": {"category": category, "product_name": "Sample product"},
        "packaging": {
            "layers": 4,
            "space_utilization": 50,
            "materials": [
                {
                    "component": "outer plastic film",
                    "material": "plastic film",
                    "confidence": 0.9,
                    "evidence": "clear outer film",
                },
                {
                    "component": "inner tray",
                    "material": "PET",
                    "confidence": 0.86,
                    "evidence": "transparent rigid tray",
                },
                {
                    "component": "outer box",
                    "material": "paperboard",
                    "confidence": 0.92,
                    "evidence": "printed carton",
                },
            ],
        },
        "diagnosis": {"issue_tags": ["mixed materials", "low space utilization"]},
    }


def test_engine_outputs_all_five_rule_families_and_uncertainty() -> None:
    result = run_rule_engine(_analysis())
    assert {item.rule_id for item in result.opportunities} == {
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
    }
    assert result.functional_checks
    assert result.hard_constraints
    assert all(0 <= item.confidence <= 1 for item in result.opportunities)
    assert all(item.hypothesis for item in result.opportunities)
    assert all(item.estimated is True for item in result.opportunities)
    assert all(item.risk_assessment.cost != "unknown" for item in result.opportunities)
    assert all(
        item.risk_assessment.transport_protection != "unknown"
        for item in result.opportunities
    )


def test_food_category_adds_food_safety_constraint() -> None:
    result = run_rule_engine(_analysis("packaged food"))
    constraint_ids = {item.constraint_id for item in result.hard_constraints}
    assert "HC_FOOD_SAFETY" in constraint_ids
    film_rules = [item for item in result.opportunities if "film" in item.target]
    assert film_rules
    assert all(item.requires_validation for item in film_rules)
    assert all(item.action != "remove_plastic_film" for item in film_rules)


def test_hard_constraint_filter_rejects_removing_protective_component() -> None:
    result = run_rule_engine(_analysis())
    unsafe = OptimizationOpportunity(
        rule_id="R03",
        target="inner tray",
        action="remove_component",
        recommended_change="Remove tray",
        reason="test",
        environment_value="test",
        commercial_risk="low",
        supply_chain_risk="low",
        risk_assessment={
            "cost": "low",
            "brand_experience": "low",
            "consumer_experience": "low",
            "process_compatibility": "low",
            "material_availability": "low",
            "transport_protection": "high",
        },
        confidence=0.9,
        requires_validation=False,
        estimated=True,
        hypothesis="test hypothesis",
    )
    assert violates_hard_constraints(
        [unsafe], result.functional_checks, result.hard_constraints
    ) is True
