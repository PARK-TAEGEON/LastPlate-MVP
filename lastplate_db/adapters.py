"""Thin adapters for flat Agent output dictionaries. Extra output keys are ignored."""
from .schema import TABLES
from .models import ValidationError


def _adapt(table, result, identities):
    if not isinstance(result, dict):
        raise ValidationError("Agent result must be a dict")
    for key, value in identities.items():
        if key in result and result[key] != value:
            raise ValidationError(f"Conflicting {key}")
    fields = TABLES[table][1]
    data = {key: value for key, value in result.items() if key in fields}
    for key in fields:
        if key.endswith("_json") and key[:-5] in result:
            if key in result:
                raise ValidationError(f"Provide either {key} or {key[:-5]}")
            data[key] = result[key[:-5]]
    return {**data, **identities}


def persist_demand_result(repository, site_id, demand_result):
    return repository.save_prediction(_adapt("predictions", demand_result, {"site_id": site_id}))


def persist_operation_result(repository, site_id, prediction_id, operation_result):
    return repository.save_operation_plan(_adapt("operation_plans", operation_result,
                                                {"site_id": site_id, "prediction_id": prediction_id}))


def persist_actual_result(repository, site_id, actual_result):
    return repository.save_actual_result(_adapt("actual_results", actual_result, {"site_id": site_id}))
