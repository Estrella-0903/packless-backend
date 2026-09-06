from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    """Strict base model for stable API contracts."""

    model_config = ConfigDict(extra="forbid")


class ErrorDetail(APIModel):
    code: str
    message: str


class ErrorResponse(APIModel):
    success: bool = False
    error: ErrorDetail


DataT = TypeVar("DataT")


class SuccessResponse(APIModel, Generic[DataT]):
    success: bool = True
    data: DataT


class PackagingMaterial(APIModel):
    component: str
    material: str
    confidence: float = Field(ge=0, le=1)
    evidence: str


class ProductInfo(APIModel):
    category: str
    product_name: str


class PackagingInfo(APIModel):
    layers: int | None = Field(default=None, ge=0)
    materials: list[PackagingMaterial]
    space_utilization: int | None = Field(default=None, ge=0, le=100)
    recyclability_score: int | None = Field(default=None, ge=0, le=100)


class Diagnosis(APIModel):
    overall_score: int | None = Field(default=None, ge=0, le=100)
    level: str
    issue_tags: list[str]


class EnvironmentalImpact(APIModel):
    estimated_packaging_weight_g: int | None = Field(default=None, ge=0)
    estimated_plastic_weight_g: int | None = Field(default=None, ge=0)
    estimated_co2e_g: int | None = Field(default=None, ge=0)


class AnalysisData(APIModel):
    carbon_data: dict[str, Any] | None = None
    analysis_id: str
    filename: str
    product: ProductInfo
    packaging: PackagingInfo
    diagnosis: Diagnosis
    environmental_impact: EnvironmentalImpact
    summary: str


class RedesignRequest(APIModel):
    analysis_id: str | None = None
    product_name: str | None = None
    packaging_type: str | None = None
    current_materials: list[str] | None = None
    issue_tags: list[str] | None = None


class RedesignOption(APIModel):
    id: str
    title: str
    summary: str
    environment_score: int = Field(ge=0, le=100)
    business_score: int = Field(ge=0, le=100)
    supply_chain_score: int = Field(ge=0, le=100)
    overall_score: float = Field(ge=0, le=100)
    selected_rule_ids: list[str]
    violates_hard_constraints: bool
    requires_validation: bool
    estimated: bool
    hypothesis: str


class FunctionalCheck(APIModel):
    target: str
    functions: list[str]
    confidence: float = Field(ge=0, le=1)
    estimated: bool
    hypothesis: str


class HardConstraint(APIModel):
    constraint_id: str
    target: str
    requirement: str
    reason: str
    confidence: float = Field(ge=0, le=1)
    requires_validation: bool
    estimated: bool
    hypothesis: str


class RiskAssessment(APIModel):
    cost: str
    brand_experience: str
    consumer_experience: str
    process_compatibility: str
    material_availability: str
    transport_protection: str


class OptimizationOpportunity(APIModel):
    rule_id: str
    target: str
    action: str
    recommended_change: str
    reason: str
    environment_value: str
    commercial_risk: str
    supply_chain_risk: str
    risk_assessment: RiskAssessment
    confidence: float = Field(ge=0, le=1)
    requires_validation: bool
    estimated: bool
    hypothesis: str


class RedesignMetrics(APIModel):
    metric_provenance: dict[str, Any] = Field(default_factory=dict)
    estimation_method: str = "visual_rule_based"
    layers: int | None = Field(default=None, ge=0)
    packaging_weight_g: int | None = Field(default=None, ge=0)
    plastic_weight_g: int | None = Field(default=None, ge=0)
    space_utilization: int | None = Field(default=None, ge=0, le=100)
    recyclability: int | None = Field(default=None, ge=0, le=100)
    estimated: bool
    hypothesis: str


class TrayReplacement(APIModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str


class ChangePlan(APIModel):
    remove_plastic_film: bool
    replace_inner_tray: TrayReplacement
    resize_outer_box: str
    reduce_material_types: bool
    keep_brand_style: bool
    layout_compact: bool


class AfterRenderSpec(APIModel):
    box_scale: float = Field(gt=0, le=1)
    remove_plastic_film: bool
    tray_material: str
    layout_compact: bool
    style: str


class RedesignData(APIModel):
    estimated: bool = True
    estimation_method: str = "visual_rule_based"
    image_task_id: str = ""
    image_generation_status: str = "FAILED"
    carbon_data: dict[str, Any] | None = None
    redesign_id: str
    analysis_id: str | None = None
    recommended_option: str
    functional_checks: list[FunctionalCheck]
    hard_constraints: list[HardConstraint]
    opportunities: list[OptimizationOpportunity]
    options: list[RedesignOption]
    before: RedesignMetrics
    after: RedesignMetrics
    change_plan: ChangePlan
    after_render_spec: AfterRenderSpec
    optimized_image_url: str
    image_generation_failed: bool
    image_generation_error: str


class Material(APIModel):
    id: str
    name: str
    category: str
    recyclability_score: int = Field(ge=0, le=100)
    plastic_free: bool
    co2_factor: float = Field(ge=0)
    recommended: bool
    description: str


AnalysisResponse = SuccessResponse[AnalysisData]
RedesignResponse = SuccessResponse[RedesignData]
MaterialsResponse = SuccessResponse[list[Material]]
