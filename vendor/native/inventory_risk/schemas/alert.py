from typing import Any, Literal
from pydantic import Field, field_validator
from .models import Model

ALERT_ALIASES = {
    "excess_inventory": "overstock", "excess_order": "over_order",
    "price_anomaly": "price_risk", "menu_restriction_conflict": "menu_conflict",
    "nutrition_constraint_violation": "nutrition_violation",
}

class Alert(Model):
    type: str = Field(min_length=1)
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    message: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    ingredient: str | None = None
    candidate_id: str | None = None
    candidate_action: str | None = None
    cause_event_ids: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def canonical_type(cls, value):
        return ALERT_ALIASES.get(value, value)
