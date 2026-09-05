import asyncio

import pytest

from app.services.ai_analyzer import AIAnalyzerError, _parse_analysis, analyze_image


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
    with pytest.raises(AIAnalyzerError, match="invalid JSON"):
        _parse_analysis("not-json", "package.png")


def test_missing_api_key_is_clear(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(AIAnalyzerError, match="DASHSCOPE_API_KEY is not configured"):
        asyncio.run(analyze_image(b"image", "image/png", "package.png"))
