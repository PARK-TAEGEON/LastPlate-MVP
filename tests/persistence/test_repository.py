import sqlite3
from dataclasses import dataclass
from datetime import datetime
import pytest
from lastplate_db import ValidationError, to_json, from_json


def test_site(repo):
    @dataclass
    class Site:
        site_name: str
        registered_population: int
        meal_capacity: int
    saved = repo.create_site(Site("한글", 600, 550))
    assert repo.get_site(saved["site_id"]) == saved
    assert len(repo.list_sites()) == 2
    assert datetime.fromisoformat(saved["created_at"]).utcoffset().total_seconds() == 0


def test_prediction_and_request(repo):
    payload = dict(site_id="s", target_date="2026-01-01", predicted_diners=100.5,
                   request_id="retry", input_snapshot_json={"weather": [1, "맑음"]})
    saved = repo.save_prediction(payload)
    assert repo.get_prediction(saved["prediction_id"]) == saved
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_prediction(payload)
    assert len(repo.get_predictions_by_site("s", "2026-01-01", "2026-01-01")) == 1
    assert repo.get_predictions_by_site("s", "2026-01-02") == []


def test_plan_latest(repo, prediction):
    data = dict(site_id="s", prediction_id=prediction["prediction_id"], target_date="2026-01-01",
                recommended_servings=120, created_at="2026-01-01T00:00:00+00:00")
    repo.save_operation_plan(data)
    newest = repo.save_operation_plan(data, alerts_json=[{"warning": "DEMO"}])
    assert repo.get_operation_plan(newest["plan_id"])["alerts_json"] == [{"warning": "DEMO"}]
    assert repo.get_operation_plan_by_prediction(prediction["prediction_id"]) == newest


def test_actual_unique_and_update(repo):
    data = dict(site_id="s", target_date="2026-01-01", actual_diners=95)
    saved = repo.save_actual_result(data)
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_actual_result(data)
    updated = repo.update_actual_result("s", "2026-01-01", actual_diners=96, notes="corrected")
    assert updated["actual_diners"] == 96
    assert updated["created_at"] == saved["created_at"]
    assert updated["updated_at"] is not None
    with pytest.raises(ValidationError):
        repo.update_actual_result("s", "2026-01-01", actual_diners=-1)
    assert repo.get_actual_result("s", "2026-01-01")["actual_diners"] == 96


def test_inventory_lots(repo):
    for lot in ("A", "B"):
        repo.save_inventory_snapshot(site_id="s", snapshot_date="2026-01-01", ingredient_name="Rice",
                                     quantity=2.5, unit="kg", lot_id=lot)
    assert len(repo.get_inventory_by_site("s", "2026-01-01")) == 2
    assert repo.get_inventory_by_site("s", "2026-01-02") == []


def test_model_history(repo):
    repo.save_model_version(model_version="v1", model_type="xgb", status="current")
    repo.save_model_version(model_version="bad", model_type="xgb", status="rejected", validation_mae=1000)
    repo.save_model_version(model_version="v2", model_type="xgb", status="candidate")
    assert repo.set_current_model("v2")["model_version"] == "v2"
    assert [r["status"] for r in repo.list_model_versions()] == ["archived", "rejected", "current"]
    with pytest.raises(ValidationError):
        repo.set_current_model("missing")
    assert repo.get_current_model()["model_version"] == "v2"


def test_decision(repo):
    saved = repo.save_decision(site_id="s", target_date="2026-01-01", recommendation_json={"actions": []})
    assert repo.get_decision(saved["decision_id"])["requires_human_approval"] == 1


def test_json_roundtrip():
    value = {"쌀": [1, None, True, {"q": 0.5}]}
    assert from_json(to_json(value)) == value
    assert from_json(None) is None


@pytest.mark.parametrize("value", ['{bad}', 'NaN', 'Infinity', '{"x":1e999}'])
def test_malformed_json(value):
    with pytest.raises(ValidationError):
        from_json(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite(repo, value):
    with pytest.raises(ValidationError):
        repo.save_prediction(site_id="s", target_date="2026-01-01", predicted_diners=value)
    with pytest.raises(ValidationError):
        to_json({"nested": [value]})


@pytest.mark.parametrize("field", ["actual_diners", "prepared_servings", "unserved_leftover_kg",
                                   "plate_waste_kg", "ingredient_waste_kg", "actual_food_cost"])
def test_negative_actual(repo, field):
    data = dict(site_id="s", target_date="2026-01-01", actual_diners=0)
    data[field] = -1
    with pytest.raises(ValidationError):
        repo.save_actual_result(data)


@pytest.mark.parametrize("extra", [{"shortage": 2}, {"actual_diners": 1.5}, {"actual_diners": True},
                                 {"target_date": "2026-02-30"}, {"created_at": "2026-01-01T00:00:00"},
                                 {"unknown": 1}])
def test_invalid_types(repo, extra):
    with pytest.raises(ValidationError):
        repo.save_actual_result({"site_id": "s", "target_date": "2026-01-01", "actual_diners": 0, **extra})


def test_negative_other_tables(repo):
    for method, payload in (
        (repo.create_site, dict(site_name="bad", meal_capacity=-1)),
        (repo.create_site, dict(site_name="bad", registered_population=-1)),
        (repo.save_inventory_snapshot, dict(site_id="s", snapshot_date="2026-01-01", ingredient_name="x", quantity=-1, unit="kg")),
        (repo.save_model_version, dict(model_version="x", model_type="x", training_rows=-1))):
        with pytest.raises(ValidationError):
            method(payload)
