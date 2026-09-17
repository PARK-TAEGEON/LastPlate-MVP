from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .context import AnalysisScope, Provenance, RecheckRequest, ScopeSelector

Check = Literal["PASS", "FAIL", "UNKNOWN"]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Upstream(BaseModel):
    # Preserve upstream provenance/extension fields, but never infer decisions from them.
    model_config = ConfigDict(extra="allow", strict=True)
    provenance_notes: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    is_demo: bool = False
    data_sources: dict[str, str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    source_payload: dict = Field(default_factory=dict)


class Checks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    shortage: Check = "UNKNOWN"
    expiry: Check = "UNKNOWN"
    allergy: Check = "UNKNOWN"
    nutrition: Check = "UNKNOWN"
    restriction: Check = "UNKNOWN"
    supply: Check = "UNKNOWN"


class Nutrition(Upstream):
    status: Check = "UNKNOWN"


class DemandResult(Upstream):
    provenance: Provenance = Field(default_factory=Provenance)
    mode: str | None = None
    operational_eligible: bool | None = None
    availability_status: str | None = None
    prediction: NonNegative | None = None
    model_version: str | None = None
    prediction_id: str | None = None
    validation_mae: NonNegative | None = None
    input_summary: dict = Field(default_factory=dict)
    applied_event_ids: list[str] = Field(default_factory=list)


class Order(Upstream):
    scope: ScopeSelector = Field(default_factory=ScopeSelector)
    menu: str | None = None
    ingredient: str = Field(min_length=1)
    planned_order: NonNegative | None = None
    recommended_min: NonNegative | None = None
    recommended_max: NonNegative | None = None
    unit: str | None = None
    status: Literal["OVER", "UNDER", "OK", "UNKNOWN"] = "UNKNOWN"
    constraints: Checks = Field(default_factory=Checks)

    @model_validator(mode="after")
    def valid_range(self):
        if self.recommended_min is not None and self.recommended_max is not None:
            if self.recommended_min > self.recommended_max:
                raise ValueError("recommended_min must not exceed recommended_max")
        return self


class OperationResult(Upstream):
    current_plan: AnalysisScope = Field(default_factory=AnalysisScope)
    provenance: Provenance = Field(default_factory=Provenance)
    recommended_servings: int | None = Field(default=None, ge=0)
    safety_margin: NonNegative | None = None
    shortage_probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    nutrition_constraints: Nutrition = Field(default_factory=Nutrition)
    constraints: Checks = Field(default_factory=Checks)
    order_recommendations: list[Order] = Field(default_factory=list)
    applied_event_ids: list[str] = Field(default_factory=list)


class Alert(Upstream):
    scope: ScopeSelector = Field(default_factory=ScopeSelector)
    cause_event_ids: list[str] = Field(default_factory=list)
    type: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    message: str
    ingredient: str | None = None
    candidate_id: str | None = None
    menu: str | None = None


class Risk(Upstream):
    scope: ScopeSelector = Field(default_factory=ScopeSelector)
    cause_event_ids: list[str] = Field(default_factory=list)
    ingredient: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    message: str = "위험 검토 필요"
    unavailable: bool = False
    inventory_sufficient: bool | None = None
    affected_menus: list[str | dict] = Field(default_factory=list)


class Candidate(Upstream):
    scope: ScopeSelector = Field(default_factory=ScopeSelector)
    candidate_id: str
    kind: Literal['ingredient_substitution', 'menu_substitution', 'priority_inventory_use'] = 'ingredient_substitution'
    ingredient: str | None = None
    candidate_menu: str | None = None
    ingredients: list[str] = Field(default_factory=list)
    cause_event_ids: list[str] = Field(default_factory=list)
    menu: str | None = None
    replaces: str | None = None
    reason: str = "대체 후보 검토"
    constraints: Checks = Field(default_factory=Checks)
    # Scores are supplied by upstream agents on a common 0..1 scale; higher is better.
    soft_scores: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scores(self):
        from math import isfinite
        allowed = {"shortage", "safety", "nutrition", "supply", "waste", "cost", "preference"}
        if any(k not in allowed or not isfinite(v) or not 0 <= v <= 1
               for k, v in self.soft_scores.items()):
            raise ValueError("soft_scores must use policy objectives with finite 0..1 values")
        return self


class InventoryUse(Candidate):
    # Inventory use identifies a physical ingredient and its quantity unit.
    # Keep Candidate.ingredient optional for menu-level substitutions.
    ingredient: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(...)
    quantity: NonNegative | None = None
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(...)
    days_to_expiry: int | None = None


class NutritionResult(Nutrition):
    scope: ScopeSelector = Field(default_factory=ScopeSelector)
    candidate_id: str | None = None
    ingredient: str | None = None
    menu: str | None = None


class InventoryRiskResult(Upstream):
    provenance: Provenance = Field(default_factory=Provenance)
    detected_events: list[dict] = Field(default_factory=list)
    adapter_notes: list[str] = Field(default_factory=list)
    status: Literal["ok", "partial", "error", "needs_clarification", "invalid_input"] = "partial"
    alerts: list[Alert] = Field(default_factory=list)
    price_risks: list[Risk] = Field(default_factory=list)
    supply_risks: list[Risk] = Field(default_factory=list)
    affected_menus: list[str | dict] = Field(default_factory=list)
    affected_ingredients: list[str] = Field(default_factory=list)
    inventory_recommendations: list[InventoryUse] = Field(default_factory=list)
    substitute_candidates: list[Candidate] = Field(default_factory=list)
    nutrition_results: list[NutritionResult] = Field(default_factory=list)
    cost_impacts: list[dict] = Field(default_factory=list)
    recommended_rechecks: list[str | RecheckRequest] = Field(default_factory=list)
    decision_trace: list[dict | str] = Field(default_factory=list)
    applied_event_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [c.candidate_id for c in self.inventory_recommendations + self.substitute_candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate_id must be unique")
        return self


class UserEvent(Upstream):
    @model_validator(mode="before")
    @classmethod
    def canonical_event(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            original = value.get("event_type")
            aliases = {"supply_risk":"supply_event", "inventory_expiry_event":"expiry_event"}
            if original in aliases:
                value.setdefault("source_event_type", original)
                value["event_type"] = aliases[original]
            if "scope" not in value:
                value["scope"] = {k:v for k,v in {
                    "target_date":value.get("date"), "end_date":value.get("end_date"),
                    "meal_type":value.get("meal_type"), "ingredient":value.get("ingredient")}.items() if v is not None}
        return value

    scope: ScopeSelector = Field(default_factory=ScopeSelector)
    needs_clarification: bool = False
    event_id: str | None = None
    event_type: str
    attendance_delta: int | None = None
    ingredient: str | None = None
    restriction: Literal["do_not_use"] | None = None
    reason: str = "사용자 이벤트"

    @model_validator(mode="after")
    def event_fields(self):
        if self.event_type == "attendance_event" and self.attendance_delta is None and not self.needs_clarification:
            raise ValueError("attendance_event requires attendance_delta")
        if self.event_type == "ingredient_restriction_event" and (
            not self.ingredient or self.restriction != "do_not_use"
        ):
            raise ValueError("restriction event requires ingredient and do_not_use")
        return self


class DecisionInput(BaseModel):
    input_revision: str | None = None
    model_config = ConfigDict(extra="forbid", strict=True)
    demand_result: DemandResult = Field(default_factory=DemandResult)
    operation_result: OperationResult = Field(default_factory=OperationResult)
    inventory_risk_result: InventoryRiskResult = Field(default_factory=InventoryRiskResult)
    user_events: list[UserEvent] = Field(default_factory=list)

