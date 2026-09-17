"""Explicit count-only compatibility bridge for Inventory & Risk v0.2.3."""
from datetime import date
from copy import deepcopy
from .schemas.operation_output import OperationOutput


def to_inventory_forecast(meal_plans, *, forecast_version, input_snapshot_id):
    """meal_plans: [{date: ISO date, meal_type: str, operation_report: dict}].

    This translates serving counts only. Send original Operation reports separately
    to Decision: the v0.2.3 forecast wrapper does not accept procurement quantities.
    """
    if not isinstance(forecast_version, str) or not forecast_version.strip():
        raise ValueError("forecast_version is required")
    if not isinstance(input_snapshot_id, str) or not input_snapshot_id.strip():
        raise ValueError("input_snapshot_id is required")
    rows, seen = [], set()
    for meal in meal_plans:
        report = OperationOutput.model_validate(meal["operation_report"])
        if report.status in {"invalid_input", "needs_clarification"} or report.constraints.status in {"FAIL", "UNKNOWN"}:
            raise ValueError("Resolve invalid, missing or failed constraints before bridging")
        if report.recommended_servings is None:
            raise ValueError("No serving count available")
        day = date.fromisoformat(meal["date"]).isoformat()
        meal_type = meal["meal_type"]
        if not isinstance(meal_type, str) or not meal_type.strip():
            raise ValueError("meal_type is required")
        key = (day, meal_type)
        if key in seen:
            raise ValueError("Duplicate date/meal_type")
        seen.add(key)
        rows.append(dict(date=day, meal_type=meal_type, expected_max_diners=report.recommended_servings))
    if not rows:
        raise ValueError("At least one meal plan required")
    return dict(forecast_version=forecast_version, input_snapshot_id=input_snapshot_id, rows=rows)


def to_decision_payload(operation_report, inventory_risk_report):
    """Transport full reports without granting approval or interpreting Risk events."""
    report = OperationOutput.model_validate(operation_report).model_dump(mode="json")
    return {"operation_report": report, "inventory_risk_report": deepcopy(inventory_risk_report)}
