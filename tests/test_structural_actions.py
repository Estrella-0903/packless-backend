"""Synthetic engineering fixtures: these are not claims of measured performance."""
import pytest

from app.services import redesign_service as service
from app.services.rule_engine import run_rule_engine, RuleEngineResult
from app.services.packaging_estimator import validate_estimation_consistency
from app.services.prompt_builder import build_image_generation_prompt


def row(name, material="paperboard", evidence="visible printed component", **extra):
    return {"component": name, "material": material, "confidence": .9, "evidence": evidence, **extra}


def fixture(*parts, space=80):
    return {"product": {"category": "cosmetics", "product_name": "gift set"},
            "packaging": {"materials": list(parts), "space_utilization": space}}


def test_a_sleeve_removed_and_plan_metrics_prompt_agree():
    analysis = fixture(row("decorative outer sleeve", evidence="non-protective decoration only"),
                       row("rigid outer box"), row("inner tray"))
    plan = service.create_redesign_plan(analysis)
    assert plan.before.layers == 3 and plan.after.layers == 2
    assert plan.change_plan.reduce_layers
    assert plan.change_plan.remove_components == ["decorative outer sleeve"]
    assert plan.after_render_spec.target_layer_count == 2
    assert "inner tray" in plan.after_render_spec.preserve_components
    assert plan.change_plan.component_actions[0].rule_id == "R01"
    prompt = build_image_generation_prompt(analysis, plan.change_plan.model_dump(by_alias=True), plan.after_render_spec.model_dump(by_alias=True))
    assert "REMOVE decorative outer sleeve" in prompt
    assert "approximate scale" not in prompt
    assert "DO NOT merely restyle" in prompt


@pytest.mark.parametrize("space,scale", [(38,.78),(48,.825),(65,.885),(70,1),(85,1)])
def test_b_resize_bands_and_tray_adaptation(space, scale):
    analysis = fixture(row("outer box"), row("inner tray"), space=space)
    engine = run_rule_engine(analysis)
    balanced = service._select_opportunities("balanced", engine.opportunities)
    plan = service._change_plan(analysis, balanced)
    assert plan["resize_spec"]["scale"] == scale
    if scale < 1:
        assert plan["layout_compact"]
        assert any(a["action"] == "resize_to_fit" and a["follow_outer_box"] for a in plan["component_actions"])
        estimates = service.estimate_packaging(analysis, engine.functional_checks, balanced, plan)
        assert estimates["after"]["space_utilization"] >= estimates["before"]["space_utilization"]


def test_c_plastic_tray_replacement_and_sensitive_categories():
    analysis = fixture(row("outer box"), row("PET inner tray", "PET", "small rigid tray"))
    engine = run_rule_engine(analysis)
    selected = service._select_opportunities("aggressive", engine.opportunities)
    plan = service._change_plan(analysis, selected)
    result = service.estimate_packaging(analysis, engine.functional_checks, selected, plan)
    assert plan["replace_inner_tray"]["to"] == "Molded pulp"
    assert any(a["action"] == "replace_material" and a["preserve_shape"] for a in plan["component_actions"])
    assert result["before"]["plastic_weight_g"] > result["after"]["plastic_weight_g"]
    for category in ("food", "electronics"):
        analysis["product"]["category"] = category
        assert not any(o.action == "replace_inner_tray" for o in run_rule_engine(analysis).opportunities)


def test_d_decorative_plastic_integration():
    analysis = fixture(row("paperboard outer box"), row("plastic decorative insert", "PET", "non-protective decoration only"))
    result = service.create_redesign_plan(analysis)
    merged = result.change_plan.merge_components
    assert merged and merged[0].rule_id == "R04"
    assert merged[0].target_component == "paperboard outer box"
    assert merged[0].method == "printed/embossed paper feature"
    assert result.after.layers == 1


def test_e_only_fiber_sourcing_no_invented_structure():
    analysis = fixture(row("outer box"), space=None)
    engine = run_rule_engine(analysis)
    selected = service._select_opportunities("balanced", engine.opportunities)
    plan = service._change_plan(analysis, selected)
    result = service.estimate_packaging(analysis, engine.functional_checks, selected, plan)
    assert {a["rule_id"] for a in plan["component_actions"]} == {"R05"}
    assert plan["visual_change_strength"] == "low"
    assert plan["visual_change_summary"] == ""
    assert plan["visual_change_note"]
    assert result["before"]["layers"] == result["after"]["layers"]


def test_f_filter_unsafe_action_without_dropping_profile(monkeypatch):
    analysis = fixture(row("outer box"))
    engine = run_rule_engine(analysis)
    unsafe = engine.opportunities[0].model_copy(update={"rule_id": "R01", "action": "remove_component"})
    monkeypatch.setattr(service, "run_rule_engine", lambda _: RuleEngineResult(engine.functional_checks, engine.hard_constraints, [unsafe, *engine.opportunities]))
    result = service.create_redesign_plan(analysis)
    assert len(result.options) == 3
    assert "R05" in next(o for o in result.options if o.id == "balanced").selected_rule_ids
    assert all("R01" not in o.selected_rule_ids for o in result.options)


def test_barrier_brand_and_low_confidence_are_not_deleted():
    for extra in ({"functions": ["barrier"]}, {"brand_critical": True}, {"confidence": .4}):
        analysis = fixture(row("outer box"), row("decorative sleeve", evidence="non-protective decoration only", **extra))
        assert not any(o.rule_id == "R01" for o in run_rule_engine(analysis).opportunities)


def test_film_removal_vs_lightweight():
    for evidence, action in [("non-functional decoration only", "remove"), ("sealed moisture barrier", "lightweight")]:
        result = run_rule_engine(fixture(row("outer box"), row("decorative film", "PET", evidence)))
        film = next(o for o in result.opportunities if o.rule_id == "R03")
        assert film.component_actions[0].action == action


def test_explicitly_protective_sleeve_is_not_redundant():
    result = run_rule_engine(fixture(row("outer box"), row("protective decorative sleeve", evidence="protects product from damage")))
    assert not any(o.rule_id == "R01" for o in result.opportunities)


def current_gift_analysis():
    # Regression fixture transcribed from the earlier Qwen analysis of the user's
    # mooncake gift-box image. No new provider call or physical measurement.
    return {"product": {"category": "confectionery", "product_name": "mooncake"},
        "packaging": {"materials": [
            row("outer box", confidence=.95, evidence="rigid, foldable structure with printed surface and die-cut details typical of paperboard"),
            row("inner tray/insert", confidence=.9, evidence="same structural appearance as outer box; integrated die-cut elements"),
            row("inner sleeves or labels", "coated paper", "thin, flexible sheets with high-gloss print and fine line detail", confidence=.85),
            row("decorative overlay or window film", "unknown", "translucent sheen in upper image; could be thin plastic or metallized paper—insufficient visual resolution to confirm", confidence=.6),
        ]}, "diagnosis": {"issue_tags": ["excessive layers", "mixed-material assembly", "ornamental complexity"]}}


def test_current_gift_does_not_remove_ambiguous_brand_sheet_or_barrier():
    plan = service.create_redesign_plan(current_gift_analysis())
    assert not plan.change_plan.remove_components
    assert plan.change_plan.visual_change_strength == "low"
    assert plan.before.layers == plan.after.layers == 3
    assert plan.before.space_utilization == plan.after.space_utilization == 65


@pytest.mark.parametrize("key,value", [("layers",1),("plastic_weight_g",0),("space_utilization",90),("recyclability",99)])
def test_consistency_rejects_unexplained_metrics(key, value):
    estimates = {"before": dict(layers=3,plastic_weight_g=20,space_utilization=50,recyclability=50)}
    estimates["after"] = dict(estimates["before"], **{key:value})
    with pytest.raises(ValueError):
        validate_estimation_consistency(estimates, {})
