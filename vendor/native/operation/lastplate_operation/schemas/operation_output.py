from typing import Any, Literal
from pydantic import Field
from .base import Model
from .operation_trace import Alert, Trace
from .provenance import EvidenceBundle


class Requirement(Model):
    ingredient: str
    edible_required: float
    raw_required: float = Field(description="Raw quantity before any rounding; approximate JSON number. Use raw_required_exact for exact comparisons.")
    raw_required_exact: dict[str, str] = Field(description="Exact rational quantity: numerator / denominator in canonical unit")
    cooking_required: float
    cooking_extra: float
    rounding_policy: Literal["legacy_combined", "purchase_only", "cooking_and_purchase"]
    gross_required: float = Field(deprecated=True, description="Alias of edible_required; migrate to edible_required")
    trim_loss_pct: float
    adjusted_required: float = Field(deprecated=True, description="Alias of cooking_required; migrate to cooking_required, not raw_required")
    stock: float
    purchase_need: float
    unit: Literal["g", "ml", "ea"]
    recommended_min: float
    recommended_max: float


class OrderReview(Model):
    ingredient: str
    planned_order: float
    recommended_min: float
    recommended_max: float
    status: Literal["UNDER", "OK", "OVER"]
    difference: float  # unsigned distance to nearest violated boundary
    unit: Literal["g", "ml", "ea"]


class ConstraintReport(Model):
    status: Literal["PASS", "FAIL", "UNKNOWN", "NOT_CONFIGURED"]
    checks: list[dict[str, Any]] = Field(default_factory=list)


class OperationOutput(Model):
    schema_version: Literal["2.0"] = "2.0"
    status: Literal["ok", "review", "needs_clarification", "invalid_input"]
    predicted_diners: float | None = None
    base_demand: float | None = None
    safety_margin_pct: float | None = None
    recommended_servings: int | None = None
    required_servings: int | None = None
    capacity_servings: int | None = None
    capacity_excess: int | None = None
    provenance: EvidenceBundle = Field(default_factory=EvidenceBundle)
    ingredient_requirements: list[Requirement] = Field(default_factory=list)
    order_reviews: list[OrderReview] = Field(default_factory=list)
    constraints: ConstraintReport = Field(default_factory=lambda: ConstraintReport(status="UNKNOWN"))
    alerts: list[Alert] = Field(default_factory=list)
    decision_trace: list[Trace] = Field(default_factory=list)
    requires_human_approval: Literal[True] = True
    advisory_only: Literal[True] = True
    data_mode: Literal["DEMO", "REAL", "UNSPECIFIED"] = "UNSPECIFIED"
    source: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
