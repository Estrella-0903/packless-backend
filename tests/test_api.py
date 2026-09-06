from app.routers import analyze as analyze_router
from app.routers import redesign as redesign_router
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.models import AnalysisData
from app.services.ai_analyzer import AIAnalyzerError


client = TestClient(app)


def test_root_serves_frontend() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PackLess AI" in response.text
    assert "https://packless-backend.onrender.com" not in response.text
    assert 'fetch("/api/analyze"' in response.text
    assert 'fetch("/api/redesign"' in response.text
    assert 'id="beforeImage"' in response.text
    assert 'id="afterImage"' in response.text
    assert 'let comparisonState={' in response.text
    assert "optimized-package-stage" not in response.text
    assert "pointerdown" in response.text
    assert "pointermove" in response.text
    assert "pointerup" in response.text
    assert "object-fit:contain" in response.text
    assert "aspect-ratio:16/10" in response.text


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_materials_returns_required_library() -> None:
    response = client.get("/api/materials")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["data"]}
    assert {"Paperboard", "Molded Pulp", "Aluminum"} <= names


def test_redesign_accepts_partial_json() -> None:
    response = client.post("/api/redesign", json={"analysis_id": "custom-id"})
    assert response.status_code == 200
    assert response.json()["data"]["analysis_id"] == "custom-id"


def test_redesign_multipart_generates_image(monkeypatch) -> None:
    async def fake_generate(image_bytes: bytes, prompt: str) -> dict:
        assert image_bytes == b"valid image placeholder"
        assert "Apply only actions explicitly enabled" in prompt
        return {
            "success": True,
            "task_id": "test-task",
            "raw_response": {"output": {"task_status": "SUCCEEDED"}},
            "error": "",
        }

    monkeypatch.setattr(redesign_router, "submit_optimized_image_task", fake_generate)
    analysis = {
        "analysis_id": "analysis_redesign_test",
        "product": {"category": "Cosmetics", "product_name": "Cream"},
        "packaging": {
            "layers": 4,
            "materials": [
                {"component": "outer film", "material": "plastic film"},
                {"component": "inner tray", "material": "PET"},
                {"component": "outer box", "material": "paperboard"},
            ],
            "space_utilization": 54,
            "recyclability_score": 62,
        },
        "diagnosis": {"issue_tags": ["excess plastic film"]},
        "environmental_impact": {
            "estimated_packaging_weight_g": 180,
            "estimated_plastic_weight_g": 70,
        },
    }
    response = client.post(
        "/api/redesign",
        data={"analysis_result": __import__("json").dumps(analysis)},
        files={"image": ("package.jpg", b"valid image placeholder", "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert [option["id"] for option in data["options"]] == [
        "aggressive",
        "balanced",
        "low_risk",
    ]
    option_by_id = {option["id"]: option for option in data["options"]}
    recommended = option_by_id[data["recommended_option"]]
    assert recommended["overall_score"] == round(
        0.4 * recommended["environment_score"]
        + 0.3 * recommended["business_score"]
        + 0.3 * recommended["supply_chain_score"],
        1,
    )
    assert {item["rule_id"] for item in data["opportunities"]} == {
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
    }
    assert data["optimized_image_url"] == ""
    assert data["image_task_id"] == "test-task"
    assert data["image_generation_status"] == "PENDING"
    assert data["image_generation_failed"] is False
    assert data["image_generation_error"] == ""


def test_redesign_image_failure_preserves_plan(monkeypatch) -> None:
    async def fake_failure(*args, **kwargs):
        return {
            "success": False,
            "image_url": "",
            "raw_response": {},
            "error": "provider unavailable",
        }

    monkeypatch.setattr(redesign_router, "submit_optimized_image_task", fake_failure)
    response = client.post(
        "/api/redesign",
        data={"analysis_result": '{"analysis_id":"analysis_failed_image"}'},
        files={"image": ("package.jpg", b"image placeholder", "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["options"]) == 3
    assert data["optimized_image_url"] == ""
    assert data["image_generation_failed"] is True
    assert data["image_generation_error"] == "provider unavailable"


def test_analyze_accepts_image_upload_and_uses_filename(monkeypatch) -> None:
    async def fake_analyze_image(
        image_bytes: bytes, content_type: str, filename: str
    ) -> AnalysisData:
        assert image_bytes == b"mock image bytes"
        assert content_type == "image/jpeg"
        return AnalysisData.model_validate(
            {
                "analysis_id": "analysis_test",
                "filename": filename,
                "product": {"category": "Cosmetics", "product_name": "Bottle"},
                "packaging": {
                    "layers": 2,
                    "materials": [
                        {
                            "component": "outer box",
                            "material": "paperboard",
                            "confidence": 0.91,
                            "evidence": "visible fibrous carton surface",
                        }
                    ],
                    "space_utilization": None,
                    "recyclability_score": None,
                },
                "diagnosis": {
                    "overall_score": None,
                    "level": "uncertain",
                    "issue_tags": [],
                },
                "environmental_impact": {
                    "estimated_packaging_weight_g": None,
                    "estimated_plastic_weight_g": None,
                    "estimated_co2e_g": None,
                },
                "summary": "Visible paperboard outer packaging.",
            }
        )

    monkeypatch.setattr(analyze_router, "analyze_image", fake_analyze_image)
    response = client.post(
        "/api/analyze",
        files={"image": ("package.jpg", b"mock image bytes", "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["data"]["filename"] == "package.jpg"
    assert response.json()["data"]["environmental_impact"]["estimated_co2e_g"] is None


def test_analyze_returns_clear_ai_failure(monkeypatch) -> None:
    async def failed_analyze(*args, **kwargs):
        raise AIAnalyzerError("AI_ANALYSIS_FAILED", "AI packaging analysis failed.")

    monkeypatch.setattr(analyze_router, "analyze_image", failed_analyze)
    response = client.post(
        "/api/analyze",
        files={"image": ("package.jpg", b"mock image bytes", "image/jpeg")},
    )
    assert response.status_code == 502
    assert response.json() == {
        "success": False,
        "error": {
            "code": "AI_ANALYSIS_FAILED",
            "message": "AI packaging analysis failed.",
        },
    }


def test_analyze_rejects_non_image_upload() -> None:
    response = client.post(
        "/api/analyze",
        files={"image": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json() == {
        "success": False,
        "error": {
            "code": "INVALID_FILE_TYPE",
            "message": "Please upload an image file.",
        },
    }


def test_openapi_and_swagger_docs_are_available() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {
        "/api/analyze",
        "/api/redesign",
        "/api/materials",
        "/health",
    } <= set(paths)

    docs_response = client.get("/docs")
    assert docs_response.status_code == 200
    assert "url: '/openapi.json'" in docs_response.text


def test_cors_preflight_is_enabled() -> None:
    response = client.options(
        "/api/materials",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
