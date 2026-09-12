import asyncio
from http import HTTPStatus
from types import SimpleNamespace

import pytest

from app.services.ai_analyzer import (
    AIAnalyzerError,
    _parse_analysis,
    _provider_failure,
    analyze_image,
    clean_model_output,
)
from app.services.analysis_normalizer import normalize_analysis_result


VALID_MODEL_JSON = """{
  "product": {"category": "food", "product_name": "snack"},
  "packaging": {
    "layers": 2,
    "materials": [{
      "component": "outer pouch",
      "material": "unknown",
      "confidence": 0.4,
      "evidence": "flexible reflective surface"
    }],
    "space_utilization": null,
    "recyclability_score": null
  },
  "diagnosis": {"overall_score": null, "level": "uncertain", "issue_tags": []},
  "environmental_impact": {
    "estimated_packaging_weight_g": null,
    "estimated_plastic_weight_g": null,
    "estimated_co2e_g": null
  },
  "summary": "Material cannot be confirmed from the image."
}"""


def test_parse_analysis_strips_markdown_fence_and_validates() -> None:
    result = _parse_analysis(f"```json\n{VALID_MODEL_JSON}\n```", "snack.png")
    assert result.filename == "snack.png"
    assert result.packaging.materials[0].material == "unknown"
    assert result.environmental_impact.estimated_co2e_g is None


def test_parse_analysis_rejects_invalid_json() -> None:
    with pytest.raises(AIAnalyzerError, match="non-JSON"):
        _parse_analysis("not-json", "package.png")


def test_clean_model_output_extracts_json_from_explanation_and_fence() -> None:
    text = f"Here is the JSON:\n```json\n{VALID_MODEL_JSON}\n```\nHope this helps."
    assert clean_model_output(text) == VALID_MODEL_JSON


def test_parse_analysis_reports_malformed_json_specifically() -> None:
    with pytest.raises(AIAnalyzerError, match="JSON parse failed"):
        _parse_analysis('Result: {"product": }', "package.png")


def test_normalizer_accepts_aliases_missing_fields_and_material_variants() -> None:
    raw = {
        "product_info": {"type": "cosmetics", "name": "Serum"},
        "packaging": {
            "layers": "about 3 layers",
            "materials": [
                {"name": "Paperboard", "percentage": 30},
                {"material": "PET", "ratio": 20},
                "Plastic film",
            ],
            "space_usage": "unknown",
        },
        "diagnosis": {"issues": "mixed materials, excess space"},
        "impact": {"packaging_weight": "cannot determine"},
    }

    normalized = normalize_analysis_result(raw, "serum.png")

    assert normalized["filename"] == "serum.png"
    assert normalized["product"] == {
        "category": "cosmetics",
        "product_name": "Serum",
    }
    assert normalized["packaging"]["layers"] == 3
    assert normalized["packaging"]["space_utilization"] is None
    assert [item["material"] for item in normalized["packaging"]["materials"]] == [
        "Paperboard",
        "PET",
        "Plastic film",
    ]
    assert normalized["diagnosis"]["issue_tags"] == [
        "mixed materials",
        "excess space",
    ]
    assert normalized["environmental_impact"]["estimated_packaging_weight_g"] is None
    assert normalized["summary"] == ""


def test_missing_api_key_is_clear(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(AIAnalyzerError, match="DASHSCOPE_API_KEY is not configured"):
        asyncio.run(analyze_image(b"image", "image/png", "package.png"))


def test_provider_arrearage_is_reported_as_actionable_billing_error() -> None:
    response = SimpleNamespace(
        status_code=HTTPStatus.BAD_REQUEST,
        code="Arrearage",
        message="Access denied due to overdue payment",
        request_id="request-test",
    )

    error = _provider_failure(response)

    assert error.code == "AI_BILLING_ERROR"
    assert "账户余额" in error.message


def test_provider_rate_limit_is_classified() -> None:
    response = SimpleNamespace(
        status_code=HTTPStatus.TOO_MANY_REQUESTS,
        code="Throttling.RateQuota",
        message="Too many requests",
        request_id="request-test",
    )

    error = _provider_failure(response)

    assert error.code == "AI_RATE_LIMITED"
