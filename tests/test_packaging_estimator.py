from copy import deepcopy

import pytest

from app.services.packaging_estimator import (
    LIMITS, estimate_packaging, estimate_co2e, estimate_plastic_weight,
)
from app.services.redesign_service import create_redesign_plan


def gift_fixture():
    # Explicit synthetic analysis, not claimed to be the user's current image.
    return {"product": {"category": "cosmetics", "product_name": "medium gift box"},
            "packaging": {"layers": 1, "space_utilization": 1, "recyclability_score": 1, "materials": [
                {"component": "outer box", "material": "paperboard", "confidence": .9, "evidence": "oversized gift box"},
                {"component": "inner tray", "material": "PET", "confidence": .8, "evidence": "small plastic tray"},
                {"component": "outer film", "material": "plastic film", "confidence": .8, "evidence": "decorative unnecessary film"},
            ]}, "diagnosis": {"issue_tags": ["oversized box", "redundant layers", "unnecessary plastic film"]}}


def approved():
    return [{"rule_id": "R01", "action": "reduce_layers", "target": "outer box"},
            {"rule_id": "R02", "action": "reduce_volume", "target": "outer box"},
            {"rule_id": "R03", "action": "remove_plastic_film", "target": "outer film"},
            {"rule_id": "R04", "action": "simplify_materials", "target": "materials"}]


def test_gift_deterministic_estimates():
    # Explicit selected component actions, not generic rule IDs, drive metrics.
    args = (gift_fixture(), [], approved(), {"remove_plastic_film": True,
        "reduce_layers": True, "remove_components": ["outer film"],
        "resize_spec": {"enabled": True}, "component_actions": [
            {"rule_id": "R03", "component": "outer film", "action": "remove"},
            {"rule_id": "R02", "component": "outer box", "action": "resize", "scale": .825}]})
    result = estimate_packaging(*args)
    assert result == estimate_packaging(*args)
    before, after = result["before"], result["after"]
    assert [before[k] for k in LIMITS] == [3, 63, 126, 65, 61]
    assert [after[k] for k in LIMITS] == [2, 57, 112, 79, 70]
    assert before["estimation_method"] == "material_geometry_digital_twin"
    assert before["metric_provenance"]["layers"]["source"] == "estimated"
    assert before["metric_provenance"]["recyclability"]["source"] == "estimated"
    assert after["metric_provenance"]["layers"]["source"] == "inferred"
    assert after["estimated"]


def test_no_rule_no_improvement_and_no_mutation():
    original = gift_fixture()
    snapshot = deepcopy(original)
    result = estimate_packaging(original, change_plan={"remove_plastic_film": True})
    assert original == snapshot
    for key in LIMITS:
        assert result["before"][key] == result["after"][key]


def test_no_components_pending_but_visible_paper_no_plastic_zero():
    assert estimate_plastic_weight({})["value"] is None
    paper = {"packaging": {"materials": [{"component": "small box", "material": "paperboard"}]}}
    result = estimate_packaging(paper)
    assert result["before"]["plastic_weight_g"] == 0
    assert result["before"]["metric_provenance"]["plastic_weight_g"]["source"] == "estimated"
    assert result["before"]["recyclability"] == 85
    assert result["carbon_estimate"]["before"]["estimated_co2e_kg"] == pytest.approx(.0312)


def test_co2_is_estimated_and_unknown_factor_not_zero():
    result = estimate_co2e([{"material": "paperboard", "weight_g": 300}])
    assert result["estimated_co2e_kg"] == pytest.approx(.358)
    assert result["source"] == "estimated" and result["estimated"]
    assert estimate_co2e([{"material": "unknown", "weight_g": 300}])["estimated_co2e_kg"] is None


@pytest.mark.parametrize("value", [1, .01, .52, -10, 200, float("nan"), float("inf"), True])
def test_bounds_and_bad_percentages(value):
    fixture = gift_fixture()
    fixture["packaging"]["space_utilization"] = value
    result = estimate_packaging(fixture, [], approved(), {"remove_plastic_film": True})
    for phase in ("before", "after"):
        for key, (low, high) in LIMITS.items():
            assert low <= result[phase][key] <= high
    assert result["after"]["packaging_weight_g"] <= result["before"]["packaging_weight_g"]


def test_measured_before_is_not_measured_after():
    fixture = gift_fixture()
    fixture["measurements"] = {"before": {"layers": {"value": 4, "source": "measured", "evidence": "manual disassembly"}}}
    result = estimate_packaging(fixture, [], approved())
    assert result["before"]["layers"] == 4
    assert result["before"]["metric_provenance"]["layers"]["source"] == "measured"
    assert result["after"]["layers"] == 4  # No component action supplied.
    assert result["after"]["metric_provenance"]["layers"]["source"] == "inferred"


def test_replacement_only_with_approved_target_and_action():
    plan = {"replace_inner_tray": {"to": "Molded pulp"}, "component_actions": [
        {"rule_id": "R03", "component": "inner tray", "action": "replace_material", "to": "Molded pulp"}]}
    rule = [{"rule_id": "R03", "action": "replace_inner_tray", "target": "inner tray"}]
    result = estimate_packaging(gift_fixture(), [], rule, plan)
    assert result["after"]["plastic_weight_g"] == 6
    rule[0]["target"] = "some other tray"
    assert estimate_packaging(gift_fixture(), [], rule, plan)["after"]["plastic_weight_g"] == 63


def test_real_rule_engine_integration_preserves_contract():
    plan = create_redesign_plan(gift_fixture())
    assert plan.before.layers == 3
    assert plan.after.layers <= plan.before.layers
    assert 20 <= plan.before.space_utilization <= 95
    assert 0 <= plan.before.recyclability <= 100
    assert "visual_estimate" in plan.carbon_data
    assert plan.options and plan.functional_checks and plan.change_plan
    assert plan.before.metric_provenance["plastic_weight_g"]["estimated"]


def test_mixed_carbon_allocates_total_only_once():
    result = estimate_packaging(gift_fixture())
    carbon = result["carbon_estimate"]["before"]
    assert sum(item["estimated_weight_g"] for item in carbon["materials"]) == pytest.approx(result["before"]["packaging_weight_g"], abs=1)
    assert carbon["estimated_co2e_kg"] == result["before"]["carbon_kgco2e"]


def test_unknown_mass_or_composition_does_not_generate_carbon():
    fixture = gift_fixture()
    fixture["packaging"]["materials"].append({"component": "metal clasp", "material": "metal"})
    result = estimate_packaging(fixture)
    assert result["carbon_estimate"]["before"]["estimated_co2e_kg"] is None
