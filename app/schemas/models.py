from __future__ import annotations

from typing import Generic, TypeVar

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


class MaterialShare(APIModel):
    name: str
    percentage: int = Field(ge=0, le=100)


class ProductInfo(APIModel):
    category: str
    product_name: str


class PackagingInfo(APIModel):
    layers: int = Field(ge=0)
    materials: list[MaterialShare]
    space_utilization: int = Field(ge=0, le=100)
    recyclability_score: int = Field(ge=0, le=100)


class Diagnosis(APIModel):
    overall_score: int = Field(ge=0, le=100)
    level: str
    issue_tags: list[str]


class EnvironmentalImpact(APIModel):
    estimated_packaging_weight_g: int = Field(ge=0)
    estimated_plastic_weight_g: int = Field(ge=0)
    estimated_co2e_g: int = Field(ge=0)


class AnalysisData(APIModel):
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


class OriginalDesign(APIModel):
    layers: int = Field(ge=0)
    materials: list[str]


class DesignChange(APIModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    reason: str


class RecommendedDesign(APIModel):
    layers: int = Field(ge=0)
    materials: list[str]
    changes: list[DesignChange]


class EstimatedImprovement(APIModel):
    packaging_reduction_percent: int = Field(ge=0, le=100)
    plastic_reduction_percent: int = Field(ge=0, le=100)
    co2_reduction_percent: int = Field(ge=0, le=100)
    space_utilization_before: int = Field(ge=0, le=100)
    space_utilization_after: int = Field(ge=0, le=100)
    recyclability_score_before: int = Field(ge=0, le=100)
    recyclability_score_after: int = Field(ge=0, le=100)


class RedesignData(APIModel):
    redesign_id: str
    analysis_id: str
    original: OriginalDesign
    recommended_design: RecommendedDesign
    estimated_improvement: EstimatedImprovement
    recommendation: str


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
