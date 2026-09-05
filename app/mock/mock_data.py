from __future__ import annotations

from app.schemas.models import Material


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
