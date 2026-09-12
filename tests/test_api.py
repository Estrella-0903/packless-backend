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
    assert "智减" in response.text
    assert "PackLess AI" not in response.text
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


def test_redesign_returns_renderable_68_point_supply_chain_breakdown() -> None:
    analysis = {
        "analysis_id": "analysis_supply_chain_68",
        "product": {"category": "gift", "product_name": "three-piece gift set"},
        "geometry_estimate": {
            "outer_package": {
                "length_mm": 220, "width_mm": 140, "height_mm": 45,
                "confidence": .7,
            },
            "confidence": .7,
        },
        "packaging": {"space_utilization": 65, "materials": [
            {"component": "outer lid", "material": "paperboard", "confidence": .9,
             "evidence": "visible rigid printed outer lid", "estimated_weight_g": 16.4},
            {"component": "inner tray/base", "material": "paperboard", "confidence": .8,
             "evidence": "visible structural paperboard tray", "estimated_weight_g": 9.2},
            {"component": "interior lining", "material": "unknown", "confidence": .4,
             "evidence": "visible secondary lining; exact material uncertain",
             "essential": False, "protective": False, "barrier": False,
             "brand_critical": False},
        ]},
    }
    response = client.post("/api/redesign", json={"analysis_result": analysis})
    assert response.status_code == 200
    data = response.json()["data"]
    recommended = next(item for item in data["options"] if item["id"] == data["recommended_option"])
    supply = recommended["score_breakdown"]["supply_chain"]
    assert recommended["supply_chain_score"] == supply["total_score"] == 68
    assert [item["score"] for item in supply["items"]] == [16, 19, 15, 12, 6]
    assert sum(item["score"] for item in supply["items"]) == 68


def test_redesign_multipart_generates_image(monkeypatch) -> None:
    async def fake_generate(image_bytes: bytes, prompt: str) -> dict:
        assert image_bytes == b"valid image placeholder"
        assert "Apply only actions explicitly enabled" in prompt
        assert "Authoritative AfterRenderSpec" in prompt
        assert "component_actions" in prompt
        assert "approximate scale" not in prompt
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
    assert recommended["score_breakdown"]["estimated"] is True
    breakdown = recommended["score_breakdown"]
    assert {"environment", "business", "supply_chain"} <= breakdown.keys()
    for family in ("environment", "business", "supply_chain"):
        assert breakdown[family]["items"]
        assert all(
            {"score", "max_score", "explanation", "source"} <= item.keys()
            for item in breakdown[family]["items"]
        )
    supply = breakdown["supply_chain"]
    supply_fields = (
        "material_availability_score", "supplier_change_score",
        "production_line_score", "tooling_score", "transport_protection_score",
    )
    assert sum(supply[field] for field in supply_fields) == supply["total_score"]
    assert supply["total_score"] == recommended["supply_chain_score"]
    assert data["estimation_method"] == "material_geometry_digital_twin"
    assert recommended["overall_score"] == round(
        0.4 * recommended["environment_score"]
        + 0.3 * recommended["business_score"]
        + 0.3 * recommended["supply_chain_score"],
        1,
    )
    assert {item["rule_id"] for item in data["opportunities"]} == {
        "R02",
        "R03",
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


def test_analyze_billing_failure_returns_actionable_503(monkeypatch) -> None:
    async def failed_analyze(*args, **kwargs):
        raise AIAnalyzerError(
            "AI_BILLING_ERROR",
            "AI 分析服务账户余额或计费状态异常，请恢复 DashScope 服务后重试。",
        )

    monkeypatch.setattr(analyze_router, "analyze_image", failed_analyze)
    response = client.post(
        "/api/analyze",
        files={"image": ("package.jpg", b"mock image bytes", "image/jpeg")},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_BILLING_ERROR"
    assert "账户余额" in response.json()["error"]["message"]


def test_analyze_async_submission_returns_immediately(monkeypatch) -> None:
    monkeypatch.setattr(
        analyze_router,
        "submit_analysis_task",
        lambda *args: {"analysis_task_id": "analysis-task-test", "status": "PENDING"},
    )
    response = client.post(
        "/api/analyze",
        headers={"Prefer": "respond-async"},
        files={"image": ("package.jpg", b"mock image bytes", "image/jpeg")},
    )

    assert response.status_code == 202
    assert response.json() == {
        "success": True,
        "data": {"analysis_task_id": "analysis-task-test", "status": "PENDING"},
    }


def test_analyze_async_status_returns_completed_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        analyze_router,
        "get_analysis_task",
        lambda task_id: {
            "analysis_task_id": task_id,
            "status": "SUCCEEDED",
            "result": {
                "analysis_id": "analysis-task-test",
                "filename": "package.jpg",
                "product": {"category": "food", "product_name": "snack"},
                "packaging": {"materials": []},
                "diagnosis": {"level": "", "issue_tags": []},
                "environmental_impact": {},
                "summary": "done",
            },
        },
    )
    response = client.get("/api/analyze/status/analysis-task-test")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["analysis_id"] == "analysis-task-test"


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
