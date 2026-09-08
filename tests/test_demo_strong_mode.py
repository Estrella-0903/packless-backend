import asyncio
import base64
import io
from types import SimpleNamespace

from PIL import Image

from app.services import image_generator as wan
from app.services.redesign_service import create_redesign_plan


def gift_analysis():
    def row(component, material, confidence, evidence):
        return {"component": component, "material": material,
                "confidence": confidence, "evidence": evidence}
    return {
        "product": {"category": "confectionery", "product_name": "mooncake gift box"},
        "packaging": {"materials": [
            row("outer box", "paperboard", .95, "rigid printed presentation box"),
            row("inner tray/insert", "paperboard", .9, "structural tray holding products"),
            row("inner sleeves or labels", "coated paper", .85, "individual food-contact sleeves"),
            row("decorative overlay or window film", "unknown", .6, "translucent decorative overlay; exact material uncertain"),
        ]},
    }


def test_demo_mode_produces_visible_balanced_and_aggressive_plans(monkeypatch):
    monkeypatch.setenv("REDESIGN_MODE", "demo")
    result = create_redesign_plan(gift_analysis())
    opportunities = {item.rule_id for item in result.opportunities}
    assert {"R01", "R02", "R03", "R04", "R05"} <= opportunities
    aggressive = next(item for item in result.options if item.id == "aggressive")
    balanced = next(item for item in result.options if item.id == "balanced")
    assert 3 <= len(aggressive.selected_rule_ids) <= 4
    assert set(balanced.selected_rule_ids) & {"R01", "R02", "R03", "R04"}
    assert result.recommended_option != "low_risk"
    assert result.change_plan.demo_mode
    assert result.change_plan.visual_change_score >= .6
    assert result.change_plan.resize_spec.enabled
    assert result.change_plan.layout_compact
    assert result.before.layers == 4 and result.after.layers == 3
    assert result.after.packaging_weight_g < result.before.packaging_weight_g
    assert result.after.space_utilization > result.before.space_utilization
    assert result.after.carbon_kgco2e < result.before.carbon_kgco2e
    assert all(item.requires_validation and item.estimated for item in result.opportunities)


def test_strict_mode_can_be_restored(monkeypatch):
    monkeypatch.setenv("REDESIGN_MODE", "strict")
    result = create_redesign_plan(gift_analysis())
    assert not result.change_plan.demo_mode


def test_low_visual_change_submits_one_regeneration(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    entry = {
        "status": "RUNNING", "created": 0, "work": None,
        "provider_url": "https://provider.test/first.png",
        "provider_task_id": "provider-first",
        "reference_data_url": "data:image/jpeg;base64,AA==",
        "prompt": "approved structural prompt", "retry_count": 0,
        "local_image_url": "", "error": "", "visual_change_score": None,
    }
    monkeypatch.setattr(wan, "_download_result", lambda _: asyncio.sleep(0, result="/generated/first.png"))
    monkeypatch.setattr(wan, "_visual_change_score", lambda *_: .25)
    monkeypatch.setattr(wan, "_remove_generated_file", lambda *_: None)
    monkeypatch.setattr(wan, "_submit_task", lambda *_: SimpleNamespace(
        status_code=200, output=SimpleNamespace(task_id="provider-retry")))

    async def scenario():
        wan.IMAGE_TASK_CACHE["public-task"] = entry
        result = await wan.finalize_optimized_image("public-task")
        assert result["status"] == "PENDING"
        assert result["regeneration_attempted"] is True
        assert wan.IMAGE_TASK_CACHE["public-task"]["provider_task_id"] == "provider-retry"
        wan.IMAGE_TASK_CACHE.clear()

    asyncio.run(scenario())


def test_visual_change_metric_separates_identical_and_changed_images(monkeypatch, tmp_path):
    monkeypatch.setattr(wan, "GENERATED_DIR", tmp_path)
    before = Image.new("RGB", (120, 120), (245, 240, 225))
    buffer = io.BytesIO()
    before.save(buffer, format="JPEG")
    data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    before.save(tmp_path / "same.png")
    changed = before.copy()
    for x in range(20, 100):
        for y in range(20, 100):
            changed.putpixel((x, y), (24, 65, 42))
    changed.save(tmp_path / "changed.png")
    assert wan._visual_change_score(data_url, "/generated/same.png") < .05
    assert wan._visual_change_score(data_url, "/generated/changed.png") >= .6
