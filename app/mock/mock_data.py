from __future__ import annotations

from app.schemas.models import AnalysisData, Material, RedesignData, RedesignRequest


DEFAULT_ANALYSIS_ID = "analysis_demo_001"
DEFAULT_MATERIALS = ["Paperboard", "PET Plastic", "Plastic Film"]


def build_mock_analysis(filename: str) -> AnalysisData:
    """Mock boundary to replace with a VLM provider in the next phase."""
    return AnalysisData.model_validate(
        {
            "analysis_id": DEFAULT_ANALYSIS_ID,
            "filename": filename,
            "product": {
                "category": "Cosmetics",
                "product_name": "Skincare Gift Box",
            },
            "packaging": {
                "layers": 4,
                "materials": [
                    {"name": "Paperboard", "percentage": 52},
                    {"name": "PET Plastic", "percentage": 28},
                    {"name": "Plastic Film", "percentage": 12},
                    {"name": "Other", "percentage": 8},
                ],
                "space_utilization": 54,
                "recyclability_score": 62,
            },
            "diagnosis": {
                "overall_score": 58,
                "level": "Medium",
                "issue_tags": [
                    "Excessive packaging",
                    "Plastic inner tray",
                    "Mixed materials",
                    "Low space utilization",
                ],
            },
            "environmental_impact": {
                "estimated_packaging_weight_g": 186,
                "estimated_plastic_weight_g": 74,
                "estimated_co2e_g": 420,
            },
            "summary": (
                "The packaging contains multiple layers and a relatively high "
                "proportion of plastic. The plastic inner tray could potentially "
                "be replaced with molded pulp."
            ),
        }
    )


def build_mock_redesign(request: RedesignRequest) -> RedesignData:
    """Mock boundary for a future prompt -> LLM -> structured JSON pipeline."""
    return RedesignData.model_validate(
        {
            "redesign_id": "redesign_demo_001",
            "analysis_id": request.analysis_id or DEFAULT_ANALYSIS_ID,
            "original": {
                "layers": 4,
                "materials": request.current_materials or DEFAULT_MATERIALS,
            },
            "recommended_design": {
                "layers": 2,
                "materials": ["Recycled Paperboard", "Molded Pulp"],
                "changes": [
                    {
                        "from": "PET plastic inner tray",
                        "to": "Molded pulp tray",
                        "reason": "Higher recyclability and lower plastic use",
                    },
                    {
                        "from": "Plastic wrapping film",
                        "to": "Paper sealing structure",
                        "reason": "Reduce single-use plastic",
                    },
                    {
                        "from": "Oversized outer box",
                        "to": "Compact box structure",
                        "reason": "Improve space utilization",
                    },
                ],
            },
            "estimated_improvement": {
                "packaging_reduction_percent": 31,
                "plastic_reduction_percent": 67,
                "co2_reduction_percent": 28,
                "space_utilization_before": 54,
                "space_utilization_after": 81,
                "recyclability_score_before": 62,
                "recyclability_score_after": 89,
            },
            "recommendation": (
                "Replace the PET inner tray with molded pulp, remove unnecessary "
                "plastic film, and reduce the overall packaging dimensions."
            ),
        }
    )


# DEMO / MOCK VALUE: co2_factor values below are illustrative only and have not
# been validated by a formal life-cycle assessment (LCA).
MATERIALS = [
    Material(id="paperboard", name="Paperboard", category="Fiber", recyclability_score=85, plastic_free=True, co2_factor=0.55, recommended=True, description="Widely recyclable fiber-based packaging for cartons and sleeves."),
    Material(id="recycled_paperboard", name="Recycled Paperboard", category="Fiber", recyclability_score=92, plastic_free=True, co2_factor=0.35, recommended=True, description="Paperboard with recycled content for lower-impact rigid packaging."),
    Material(id="molded_pulp", name="Molded Pulp", category="Fiber", recyclability_score=94, plastic_free=True, co2_factor=0.40, recommended=True, description="Fiber-based protective packaging material suitable for replacing plastic trays."),
    Material(id="pet_plastic", name="PET Plastic", category="Plastic", recyclability_score=68, plastic_free=False, co2_factor=1.80, recommended=False, description="Clear rigid plastic commonly used for trays and windows."),
    Material(id="pp_plastic", name="PP Plastic", category="Plastic", recyclability_score=60, plastic_free=False, co2_factor=1.65, recommended=False, description="Durable plastic used for caps, tubs, and protective components."),
    Material(id="plastic_film", name="Plastic Film", category="Plastic", recyclability_score=25, plastic_free=False, co2_factor=2.10, recommended=False, description="Flexible single-use wrapping with limited curbside recyclability."),
    Material(id="glass", name="Glass", category="Mineral", recyclability_score=88, plastic_free=True, co2_factor=1.20, recommended=False, description="Highly recyclable but comparatively heavy packaging material."),
    Material(id="aluminum", name="Aluminum", category="Metal", recyclability_score=95, plastic_free=True, co2_factor=1.50, recommended=True, description="Lightweight metal with strong recycling value when recovered."),
]
