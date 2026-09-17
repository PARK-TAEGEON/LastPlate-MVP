"""Transport-only contracts matching lastplate-integrated v0.1.2 /api/plan.

Nested agent data remains intact. Native agents validate their own domain rules.
No model, recipe arithmetic, evidence projection or decision policy is imported.
"""
from datetime import date
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

JsonObject = dict[str, JsonValue]


class AgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    request_id: str = Field(min_length=1, max_length=100)
    site_id: str = Field(min_length=1)
    target_date: str
    as_of: str
    meal_type: Literal['lunch'] = 'lunch'
    meal_capacity: int = Field(ge=0, strict=True)
    attendance: JsonObject
    availability: JsonObject | None = None
    weekly_menu: list[JsonObject] = Field(min_length=1)
    recipes: list[JsonObject]
    inventory: list[JsonObject]
    planned_orders: list[JsonObject]
    nutrition: list[JsonObject]
    prices: list[JsonObject]
    monthly_prices: list[JsonObject]
    supply_events: list[JsonObject]
    sources: dict[str, str]
    operation_policy: JsonObject
    event: str | JsonObject | None = None

    @model_validator(mode='after')
    def validate_transport(self):
        if not self.request_id.strip() or not self.site_id.strip():
            raise ValueError('site_id and request_id cannot be blank')
        if len(self.site_id + ':' + self.request_id) > 200:
            raise ValueError('Combined site_id:request_id exceeds the native ML limit of 200 characters')
        for value in (self.target_date, self.as_of):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError('target_date and as_of must be YYYY-MM-DD dates (not timestamps)')
        if self.as_of > self.target_date:
            raise ValueError('as_of must not exceed target_date')
        json.dumps(self.model_dump(mode='json'), allow_nan=False)
        return self


class AgentPipelineResult(BaseModel):
    # Preserve additional fields introduced by the upstream service.
    model_config = ConfigDict(extra='allow', allow_inf_nan=False, strict=True)
    pipeline_status: Literal['COMPLETE', 'PARTIAL', 'FAILED']
    demand: JsonObject | None
    operation: JsonObject | None
    inventory_risk: JsonObject | None
    decision: JsonObject | None
    errors: list[JsonObject]
    warnings: list[JsonObject]
    timings: dict[str, float]
    input_revision: str | None
    advisory_only: Literal[True]


def failed_result(code: str, message: str, status: int, *, stage: str = 'backend') -> dict:
    return dict(pipeline_status='FAILED', demand=None, operation=None, inventory_risk=None,
                decision=None, errors=[dict(stage=stage, code=code, message=message,
                http_status=status, kind='input' if status == 422 else 'server')],
                warnings=[], timings={}, input_revision=None, advisory_only=True)
