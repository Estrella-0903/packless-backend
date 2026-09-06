import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import analyze as analyze_router
from app.schemas.models import AnalysisData
from app.services import material_data_service as service


@pytest.mark.parametrize("name,value", [("PET", 3.85491851), ("PET plastic", 3.85491851), ("paperboard", 1.19396586), ("cardboard", 1.19396586), ("plastic film", 2.91046529)])
def test_exact(name, value):
    result = service.get_emission_factor(name)
    assert result["match_type"] == "exact"
    assert result["factor_kgco2e_per_kg"] == pytest.approx(value)
    assert result["confidence"] == 1.0
    assert result["provenance"]["cell"]


@pytest.mark.parametrize("name", ["unknown", "plastic", "metal", "recycled PET", "molded pulp", "PET-ish", ""])
def test_unknown(name):
    result = service.get_emission_factor(name)
    assert result["factor_kgco2e_per_kg"] is None
    assert result["requires_validation"]


def test_ambiguous_bottle():
    result = service.get_emission_factor("plastic bottle")
    assert result["match_type"] == "inferred_but_ambiguous"
    assert result["factor_kgco2e_per_kg"] is None
    assert result["confidence"] < 0.5


def test_units_and_origins():
    rows = service.load_emission_factors()
    assert len(rows) == 18
    for row in rows:
        assert row["factor_kgco2e_per_kg"] == row["original_value"] / 1000
    recycled = service.get_emission_factor("PET", origin="closed_loop_source")
    assert recycled["factor_kgco2e_per_kg"] == pytest.approx(2.20491851)


@pytest.mark.parametrize("mass", [None, -1, True, "unknown", float("nan"), float("inf")])
def test_no_valid_weight_no_emissions(mass):
    result = service.calculate_material_carbon("PET", mass)
    assert result["factor_available"]
    assert result["estimated_material_co2e_kg"] is None
    assert result["requires_weight_measurement"]


def test_measured_weight():
    assert service.calculate_material_carbon("PET", 0.1)["estimated_material_co2e_kg"] == pytest.approx(0.385491851)
    assert service.calculate_material_carbon("PET", 0)["estimated_material_co2e_kg"] == 0


@pytest.mark.parametrize("content", ["{broken", "[]", '{"aliases": []}', '{"aliases": {"pet": 4}}', '{"aliases": {"pet": {"material": [], "match_type": "exact"}}}'])
def test_bad_mapping(tmp_path, content):
    path = tmp_path / "mappings/material_factor_mapping.json"
    path.parent.mkdir()
    path.write_text(content)
    assert service.get_emission_factor("PET", tmp_path)["factor_kgco2e_per_kg"] is None


def test_missing_data(tmp_path):
    assert service.load_emission_factors(tmp_path) == []
    assert service.load_packaging_data(tmp_path) == []
    assert not service.get_emission_factor("PET", tmp_path)["factor_available"]


def test_invalid_factor_rows(tmp_path):
    path = tmp_path / "processed/defra_emission_factors.json"
    path.parent.mkdir()
    bad = service.load_emission_factors()[0].copy()
    bad["factor_kgco2e_per_kg"] *= 1000
    path.write_text(json.dumps([None, [], bad, {}]))
    assert service.load_emission_factors(tmp_path) == []


def test_c_data_counts_and_reference():
    assert len(service.load_packaging_data()) == 50
    assert service.get_material_reference("plastic film")["recognition_reference_count"] == 1


def test_image_estimates_never_become_mass():
    data = {"packaging": {"materials": [{"material": "PET", "weight_kg": 5}]}, "environmental_impact": {"estimated_packaging_weight_g": 200}}
    result = service.build_carbon_data(data)
    assert result["estimated_total_co2e_kg"] is None
    assert result["requires_weight_measurement"]


def test_complete_bom_and_per_material_mass():
    data = {"packaging": {"bill_of_materials_complete": True, "materials": [
        {"component": "tray", "material": "PET", "weight_kg": 0.1, "weight_source": "measured", "material_verified": True},
        {"component": "box", "material": "paperboard", "weight_kg": 0.2, "weight_source": "measured", "material_verified": True},
    ]}}
    result = service.build_carbon_data(data)
    assert result["estimated_total_co2e_kg"] == pytest.approx(0.1 * 3.85491851 + 0.2 * 1.19396586)
    data["packaging"]["bill_of_materials_complete"] = False
    assert service.build_carbon_data(data)["estimated_total_co2e_kg"] is None
    data["packaging"]["bill_of_materials_complete"] = True
    data["packaging"]["materials"][1]["material"] = "unknown"
    assert service.build_carbon_data(data)["estimated_total_co2e_kg"] is None


def test_analyze_and_redesign_integration(monkeypatch):
    data = {"analysis_id": "test_data", "filename": "test.png", "product": {"category": "", "product_name": ""},
            "packaging": {"materials": [{"component": "tray", "material": "PET", "confidence": 0.7, "evidence": "visual hypothesis"}]},
            "diagnosis": {"level": "", "issue_tags": []}, "environmental_impact": {}, "summary": ""}
    async def analyze(*args):
        return AnalysisData.model_validate(data)
    monkeypatch.setattr(analyze_router, "analyze_image", analyze)
    with TestClient(app) as client:
        response = client.post("/api/analyze", files={"image": ("test.png", b"fixture", "image/png")})
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["carbon_data"]["factor_available"]
        assert body["carbon_data"]["estimated_total_co2e_kg"] is None
        response = client.post("/api/redesign", json=body)
        assert response.status_code == 200
        assert response.json()["data"]["carbon_data"]["factor_available"]
        for route in ("/", "/health", "/docs", "/openapi.json", "/api/materials"):
            assert client.get(route).status_code == 200
