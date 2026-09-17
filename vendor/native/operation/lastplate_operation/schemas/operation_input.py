from typing import Literal
from decimal import Decimal
from pydantic import Field, StrictBool, JsonValue, model_validator, field_validator
from .base import Model, Name, Number
from ..config.operation_policy import OperationPolicy


class PredictionInterval(Model):
    lower: Number = Field(le=1000000)
    upper: Number = Field(le=1000000)


class Applicability(Model):
    """Proposed extension: no OOD schema exists in the inspected ML-v2 receipt."""
    status: Literal["IN_DOMAIN", "OOD", "NOT_APPLICABLE", "UNKNOWN"] = "UNKNOWN"
    reasons: list[Name] = Field(default_factory=list)


class DemandWarning(Model):
    code: Name
    category: Literal["OOD", "NOT_APPLICABLE", "EVIDENCE_UNKNOWN", "OTHER"]
    severity: Literal["INFO", "MEDIUM", "HIGH"]
    message: Name


class DemandResult(Model):
    prediction: Number = Field(le=1000000)
    prediction_interval: PredictionInterval | None = None
    model_version: Name | None = None
    input_snapshot_id: Name | None = None
    applicability: Applicability = Field(default_factory=Applicability)
    warnings: list[DemandWarning] = Field(default_factory=list)
    # Existing LastPlate-ML-v2 tools/demand.py receipt names, preserved verbatim.
    operational_eligible: StrictBool | None = None
    availability_status: Literal["validated_declared_receipts", "historical_unknown"] | None = None
    prediction_id: Name | None = None
    created_at: Name | None = None
    target_date: Name | None = None
    deadline_at: Name | None = None
    timezone: Name | None = None
    mode: Name | None = None
    input_data: dict[str, JsonValue] | None = None
    availability: JsonValue = None
    weather: JsonValue = None
    policy: dict[str, JsonValue] | None = None

    @field_validator("input_data", "availability", "weather", "policy", mode="before")
    @classmethod
    def metadata_json_numbers(cls, value):
        def convert(item):
            if isinstance(item, (Decimal, float)):
                exact = Decimal(str(item))
                if not exact.is_finite() or Decimal(str(float(exact))) != exact:
                    raise ValueError("Native metadata must round-trip as finite JSON numbers")
                return float(exact)
            if isinstance(item, dict):
                return {key:convert(v) for key,v in item.items()}
            if isinstance(item, list):
                return [convert(v) for v in item]
            return item
        return convert(value)

    @model_validator(mode="after")
    def interval_contains_prediction(self):
        if self.prediction_interval:
            if not self.prediction_interval.lower <= self.prediction <= self.prediction_interval.upper:
                raise ValueError("Require lower <= prediction <= upper")
        return self


class RecipeRow(Model):
    menu_name: Name
    ingredient: Name
    amount_per_serving: Number = Field(gt=0)
    unit: Name


class InventoryRow(Model):
    ingredient: Name
    stock: Number
    unit: Name


class OrderRow(Model):
    ingredient: Name
    planned_order: Number
    unit: Name

    @model_validator(mode="after")
    def whole_item_purchase(self):
        if self.unit == "ea" and self.planned_order != self.planned_order.to_integral_value():
            raise ValueError("ea planned_order must contain whole purchased items")
        return self


class OperationInput(Model):
    demand_result: DemandResult
    recipe_data: list[RecipeRow]
    inventory_data: list[InventoryRow]
    planned_orders: list[OrderRow]
    config: OperationPolicy = Field(default_factory=OperationPolicy)
