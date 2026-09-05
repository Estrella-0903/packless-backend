from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_serves_frontend() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PackLess AI" in response.text
    assert "https://packless-backend.onrender.com" not in response.text
    assert 'fetch("/api/analyze"' in response.text


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


def test_analyze_accepts_image_upload_and_uses_filename() -> None:
    response = client.post(
        "/api/analyze",
        files={"image": ("package.jpg", b"mock image bytes", "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["data"]["filename"] == "package.jpg"


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
