from datetime import date
from typing import Any, Literal
from pydantic import Field
from .models import Model
from .alert import Alert
from .errors import ErrorDetail
from .event import EventParseResult

class RiskReport(Model):
    schema_version: str = "2.0"
    advisory_only: Literal[True] = True
    as_of: date | None = None
    analysis_mode: Literal["full", "event"] = "full"
    status: Literal["ok", "partial", "needs_clarification", "error"] = "ok"
    parsing_result: EventParseResult | None = None
    validation_warnings: list[dict[str, Any]] = Field(default_factory=list)
    period: dict[str, str | None] = Field(default_factory=dict)
    forecast_version: str | None = None
    input_snapshot_id: str | None = None
    clarification: dict[str, Any] = Field(default_factory=dict)
    recheck_status: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    errors: list[ErrorDetail] = Field(default_factory=list)
    inventory_status: list[dict[str, Any]] = Field(default_factory=list)
    allocation_audit: list[dict[str, Any]] = Field(default_factory=list)
    current_plan_checks: dict[str,str] = Field(default_factory=dict)
    evidence_projection: dict[str,Any] = Field(default_factory=dict)
    detected_events: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    price_risks: list[dict[str, Any]] = Field(default_factory=list)
    supply_risks: list[dict[str, Any]] = Field(default_factory=list)
    affected_menus: list[dict[str, Any]] = Field(default_factory=list)
    affected_ingredients: list[str] = Field(default_factory=list)
    substitute_candidates: list[dict[str, Any]] = Field(default_factory=list)
    priority_use_candidates: list[dict[str, Any]] = Field(default_factory=list)
    nutrition_results: list[dict[str, Any]] = Field(default_factory=list)
    cost_impacts: list[dict[str, Any]] = Field(default_factory=list)
    recommended_rechecks: list[str] = Field(default_factory=list)
    decision_trace: list[str] = Field(default_factory=list)
    data_sources: dict[str, str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
