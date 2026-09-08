from __future__ import annotations

from typing import Any, Generic, TypeVar, Literal

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
    visual_fraction: float | None = Field(default=None, ge=0, le=1)
    size_category: str = ""
    functions: list[str] = Field(default_factory=list)
    essential: bool = False
    brand_critical: bool = False


class ProductInfo(APIModel):
    category: str
    product_name: str


class PackagingInfo(APIModel):
    layers: int | None = Field(default=None, ge=0)
    materials: list[PackagingMaterial]
    space_utilization: int | None = Field(default=None, ge=0, le=100)
    recyclability_score: int | None = Field(default=None, ge=0, le=100)


class Dimensions(APIModel):
    length_mm: float | None = Field(default=None, gt=0)
    width_mm: float | None = Field(default=None, gt=0)
    height_mm: float | None = Field(default=None, gt=0)
    estimated: bool = True
    confidence: float = Field(default=0, ge=0, le=1)
    source: str = "ai_visual_estimate"


class GeometryEstimate(APIModel):
    outer_package: Dimensions = Field(default_factory=Dimensions)
    product_occupied_ratio: float | None = Field(default=None, ge=0, le=1)
    estimated_aspect_ratio: float | None = Field(default=None, gt=0)
    method: str = "visual_2d_proxy"
    confidence: float = Field(default=0, ge=0, le=1)


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
    geometry_estimate: GeometryEstimate = Field(default_factory=GeometryEstimate)
    measurements: dict[str, Any] = Field(default_factory=dict)
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
    estimated_cost_change_percent: float | None = None
    meaningful_improvement: bool = False
    meaningful_improvement_score: float = Field(default=0, ge=0, le=100)
    score_breakdown: dict[str, Any] = Field(default_factory=dict)


class FunctionalCheck(APIModel):
    material: str = "unknown"
    essential: bool = True
    potentially_redundant: bool = False
    decorative: bool = False
    protective: bool = True
    barrier: bool = False
    brand_critical: bool = False
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


class ComponentAction(APIModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    component: str
    action: Literal["remove", "resize", "resize_to_fit", "replace_material", "lightweight", "integrate_into", "increase_recycled_content"]
    rule_id: str
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    requires_validation: bool = True
    estimated: bool = True
    hypothesis: str = "Validate functionality, manufacturing and material suitability before implementation."
    scale: float | None = Field(default=None, gt=0, le=1)
    scale_basis: str = "outer_volume_ratio"
    resize_axis: str = "overall"
    layout_strategy: str = ""
    follow_outer_box: bool = False
    target_component: str = ""
    method: str = ""
    from_: str = Field(default="", alias="from", serialization_alias="from")
    to: str = ""
    preserve_shape: bool = False
    demo_assumption: bool = False


class ResizeSpec(APIModel):
    enabled: bool = False
    component: str = ""
    scale: float = Field(default=1, gt=0, le=1)
    scale_basis: str = "outer_volume_ratio"
    estimated_reduction_percent: float = Field(default=0, ge=0, le=100)
    resize_axis: str = "overall"
    layout_strategy: str = ""


class OptimizationOpportunity(APIModel):
    visual_impact: Literal["high", "medium", "low"] = "low"
    component_actions: list[ComponentAction] = Field(default_factory=list)
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
    demo_assumption: bool = False


class RedesignMetrics(APIModel):
    metric_provenance: dict[str, Any] = Field(default_factory=dict)
    estimation_method: str = "material_geometry_digital_twin"
    layers: int | None = Field(default=None, ge=0)
    packaging_weight_g: int | None = Field(default=None, ge=0)
    plastic_weight_g: int | None = Field(default=None, ge=0)
    space_utilization: int | None = Field(default=None, ge=0, le=100)
    recyclability: int | None = Field(default=None, ge=0, le=100)
    estimated: bool
    hypothesis: str
    carbon_kgco2e: float | None = Field(default=None, ge=0)
    packaging_state: dict[str, Any] = Field(default_factory=dict)


class TrayReplacement(APIModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str


class ChangePlan(APIModel):
    reduce_layers: bool = False
    target_layer_count: int | None = Field(default=None, ge=1, le=8)
    remove_components: list[str] = Field(default_factory=list)
    merge_components: list[ComponentAction] = Field(default_factory=list)
    component_actions: list[ComponentAction] = Field(default_factory=list)
    preserve_components: list[str] = Field(default_factory=list)
    resize_spec: ResizeSpec = Field(default_factory=ResizeSpec)
    visual_change_strength: Literal["high", "medium", "low"] = "low"
    visual_change_summary: str = ""
    visual_change_note: str = ""
    remove_plastic_film: bool
    replace_inner_tray: TrayReplacement
    resize_outer_box: str
    reduce_material_types: bool
    keep_brand_style: bool
    layout_compact: bool
    demo_mode: bool = False
    visual_change_score: float = Field(default=0, ge=0, le=1)


class AfterRenderSpec(APIModel):
    target_layer_count: int | None = None
    remove_components: list[str] = Field(default_factory=list)
    component_actions: list[ComponentAction] = Field(default_factory=list)
    preserve_components: list[str] = Field(default_factory=list)
    void_reduction: str = "none"
    scale_basis: str = "outer_volume_ratio"
    brand_preservation: str = "Preserve product identity, logos, brand colors and mandatory information."
    box_scale: float = Field(gt=0, le=1)
    remove_plastic_film: bool
    tray_material: str
    layout_compact: bool
    style: str


class RedesignData(APIModel):
    estimated: bool = True
    estimation_method: str = "material_geometry_digital_twin"
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
