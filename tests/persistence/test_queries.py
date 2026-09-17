import pytest
from lastplate_db import (Repository, ValidationError, get_learning_dataset, get_site_kpis,
    get_retraining_readiness, persist_demand_result, persist_operation_result, persist_actual_result)
from lastplate_db.seed import seed_demo


def test_demo_kpis(repo):
    site = seed_demo(repo)
    sid = site["site_id"]
    rows = get_learning_dataset(repo, sid, include_demo=True)
    assert len(rows) == 1
    assert rows[0]["predicted_diners"] == 487
    assert rows[0]["recommended_servings"] == 523
    assert rows[0]["actual_diners"] == 495
    assert get_site_kpis(repo, sid, eligible_only=False) == dict(prediction_mae=8.0, average_leftover_kg=8.5,
        average_plate_waste_kg=12.1, shortage_rate=0.0, average_overprep_servings=28.0)
    assert get_retraining_readiness(repo, sid, legacy_all_rows=True) == dict(site_id=sid,
        new_actual_records=1, eligible_new_actual_records=0, all_new_actual_records=1,
        required_records=30, ready=False)


def test_join_latest_plan_no_fanout(repo, prediction):
    for servings in (110, 120):
        repo.save_operation_plan(site_id="s", target_date="2026-01-01", prediction_id=prediction["prediction_id"], recommended_servings=servings,
                                  created_at="2026-01-01T02:00:00Z")
    repo.save_actual_result(site_id="s", target_date="2026-01-01", actual_diners=90, created_at="2026-01-01T03:00:00Z")
    rows = get_learning_dataset(repo, include_unvalidated=True)
    assert len(rows) == 1
    assert rows[0]["recommended_servings"] == 120


def test_join_without_plan(repo, prediction):
    repo.save_actual_result(site_id="s", target_date="2026-01-01", actual_diners=90, created_at="2026-01-01T03:00:00Z")
    assert get_learning_dataset(repo, include_unvalidated=True)[0]["recommended_servings"] is None
    assert get_learning_dataset(repo, "other") == []


def test_kpi_daily_weight(repo, prediction):
    repo.save_prediction(site_id="s", target_date="2026-01-01", predicted_diners=95)
    repo.save_actual_result(site_id="s", target_date="2026-01-01", actual_diners=90, unserved_leftover_kg=10, prepared_servings=80)
    repo.save_actual_result(site_id="s", target_date="2026-01-02", actual_diners=100, unserved_leftover_kg=20, prepared_servings=120, shortage=True)
    kpi = get_site_kpis(repo, "s", eligible_only=False)
    assert kpi["prediction_mae"] == 5
    assert kpi["average_leftover_kg"] == 15
    assert kpi["shortage_rate"] == 0.5
    assert kpi["average_overprep_servings"] == 10
    assert len(get_learning_dataset(repo, include_unvalidated=True)) == 1


def test_readiness_cutoff(repo):
    repo.save_model_version(model_version="v", model_type="x", status="current", trained_at="2026-01-02T09:00:00+09:00")
    for day in (1, 2, 3):
        repo.save_actual_result(site_id="s", target_date=f"2026-01-0{day}", actual_diners=1,
                                created_at=f"2026-01-0{day}T00:00:00+00:00")
    assert get_retraining_readiness(repo, "s", 1, legacy_all_rows=True)["ready"] is True
    assert get_retraining_readiness(repo, "s", legacy_all_rows=True)["new_actual_records"] == 1
    repo.update_actual_result("s", "2026-01-01", actual_diners=2)
    assert get_retraining_readiness(repo, "s", legacy_all_rows=True)["new_actual_records"] == 1
    assert get_retraining_readiness(repo, "s", since="2025-01-01T00:00:00Z", legacy_all_rows=True)["new_actual_records"] == 3
    with pytest.raises(ValidationError):
        get_retraining_readiness(repo, "s", 0)


def test_empty():
    with Repository(":memory:") as r:
        assert r.list_sites() == []
        assert r.get_site("missing") is None
        assert r.get_current_model() is None
        assert get_learning_dataset(r) == []
        assert all(v is None for v in get_site_kpis(r, "missing").values())
        assert get_retraining_readiness(r, "missing")["ready"] is False


def test_adapters(repo):
    p = persist_demand_result(repo, "s", dict(target_date="2026-01-01", predicted_diners=90, input_snapshot={"x": 1}, agent_extra=42))
    assert p["input_snapshot_json"] == {"x": 1}
    plan = persist_operation_result(repo, "s", p["prediction_id"], dict(target_date="2026-01-01", recommended_servings=100, alerts=[]))
    assert plan["alerts_json"] == []
    assert persist_actual_result(repo, "s", dict(target_date="2026-01-01", actual_diners=95))["actual_diners"] == 95
    with pytest.raises(ValidationError, match="predicted_diners"):
        persist_demand_result(repo, "s", dict(target_date="2026-01-01"))
    with pytest.raises(ValidationError, match="Conflicting"):
        persist_demand_result(repo, "s", dict(site_id="other"))


def test_two_connections_duplicate_request(tmp_path):
    import sqlite3
    path = tmp_path / "shared.db"
    with Repository(path) as a, Repository(path) as b:
        a.create_site(site_id="s", site_name="Shared")
        payload = dict(site_id="s", target_date="2026-01-01", predicted_diners=1, request_id="same")
        a.save_prediction(payload)
        with pytest.raises(sqlite3.IntegrityError):
            b.save_prediction(payload)
        assert len(b.get_predictions_by_site("s")) == 1
