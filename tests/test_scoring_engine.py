"""Dynamic scoring and digital-twin regression tests."""
from app.services.geometry_estimator import estimate_geometry
from app.services.packaging_state import build_packaging_state
from app.services.redesign_service import create_redesign_plan


def row(component, material="paperboard", evidence="visible package component"):
    return {"component": component, "material": material, "confidence": .9, "evidence": evidence}


def fixture(*materials, space=65):
    return {
        "product": {"category": "gift", "product_name": "test package"},
        "packaging": {"materials": list(materials), "space_utilization": space},
    }


def option(plan, option_id):
    return next(item for item in plan.options if item.id == option_id)


def test_scenario_a_little_optimization_space_scores_conservatively():
    result = create_redesign_plan(fixture(row("outer box"), space=85))
    selected = option(result, "low_risk")
    assert 45 <= selected.environment_score <= 60
    assert 80 <= selected.business_score <= 95
    # R05 is now a real low-risk option rather than an empty no-change plan;
    # recycled-content availability/qualification keeps supply risk visible.
    assert 80 <= selected.supply_chain_score <= 90


def test_scenario_b_overpack_has_strong_but_feasible_improvement():
    result = create_redesign_plan(fixture(
        row("decorative outer sleeve", evidence="non-protective decoration only"),
        row("outer box"),
        row("decorative film", "PET", "non-functional decoration only"),
        space=45,
    ))
    selected = option(result, "balanced")
    assert 75 <= selected.environment_score <= 90
    assert 70 <= selected.business_score <= 90
    assert 70 <= selected.supply_chain_score <= 90


def test_scenario_c_aggressive_material_replacement_discloses_risk():
    result = create_redesign_plan(fixture(
        row("outer box"), row("PET inner tray", "PET", "small rigid tray"),
        row("decorative film", "PET", "non-functional decoration only"), space=40,
    ))
    selected = option(result, "aggressive")
    assert selected.environment_score >= 85
    assert 50 <= selected.business_score <= 70
    assert 40 <= selected.supply_chain_score <= 65
    assert selected.score_breakdown["estimated"] is True
    assert (selected.environment_score, selected.business_score, selected.supply_chain_score) != (54, 92, 92)


def test_user_measurements_override_visual_geometry_and_weight():
    analysis = fixture(row("outer box"), space=40)
    analysis["geometry_estimate"] = {"outer_package": {"length_mm": 500, "width_mm": 400, "height_mm": 200}}
    analysis["measurements"] = {
        "outer_dimensions": {"value": {"length_mm": 300, "width_mm": 200, "height_mm": 100}, "source": "user_measured"},
        "product_occupied_volume_mm3": {"value": 3_600_000, "source": "user_measured"},
        "total_weight_g": {"value": 150, "source": "user_measured"},
    }
    geometry = estimate_geometry(analysis)
    state = build_packaging_state(analysis)
    assert geometry["source"] == "user_measured"
    assert geometry["outer_volume_mm3"] == 6_000_000
    assert geometry["space_utilization"] == 60
    assert state["total_weight_g"] == 150
    assert state["total_weight_source"] == "user_measured"


def test_defra_factor_is_used_in_component_carbon_estimate():
    state = build_packaging_state(fixture(row("outer box", "paperboard")))
    component = state["components"][0]
    assert component["carbon_factor_kgco2e_per_kg"] == 1.19396586
    assert "DEFRA" in component["material_property_source"]


def test_no_evidence_keeps_space_pending_instead_of_inventing_precision():
    geometry = estimate_geometry({"product": {}, "packaging": {"materials": []}})
    assert geometry["space_utilization"] is None
    assert geometry["method"] == "pending"


def test_meaningful_balanced_option_beats_no_change_low_risk_option():
    result = create_redesign_plan(fixture(
        row("decorative outer sleeve", evidence="non-protective decoration only"),
        row("outer box"), row("decorative film", "PET", "non-functional decoration only"),
        space=45,
    ))
    chosen = option(result, result.recommended_option)
    unchanged = option(result, "low_risk")
    assert chosen.id == "balanced"
    assert chosen.meaningful_improvement is True
    assert unchanged.meaningful_improvement is False
    assert chosen.score_breakdown["environment"]["items"]
    assert chosen.score_breakdown["business"]["items"]
    assert chosen.score_breakdown["supply_chain"]["items"]


def test_no_change_environment_score_and_overall_are_penalized():
    result = create_redesign_plan(fixture(row("outer box"), space=85))
    low_risk = option(result, "low_risk")
    assert low_risk.meaningful_improvement is False
    assert low_risk.score_breakdown["environment"]["no_improvement_penalty"] == 15
    assert low_risk.overall_score < (
        .4 * low_risk.environment_score
        + .3 * low_risk.business_score
        + .3 * low_risk.supply_chain_score
    )
