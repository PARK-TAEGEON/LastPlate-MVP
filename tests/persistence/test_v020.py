import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from lastplate_db import (Repository, ValidationError, get_training_dataset, get_learning_dataset,
    get_dashboard_kpis, get_dashboard_readiness, get_site_kpis, get_retraining_readiness)


def model(repo, version="m1", **extra):
    return repo.save_model_version({"model_version": version, "model_type": "x", "source_type": "MODEL",
                                   "record_status": "VALIDATED", **extra})


def deploy(repo, version="m1", site="s", role="demand", **extra):
    return repo.deploy_model(site, version, role, actor="operator", reason="Reviewed release", **extra)


def raw_deploy(repo, **extra):
    data = dict(deployment_id="raw", site_id="s", model_version="m1", model_role="demand", status="current",
        effective_at="2026-01-01T00:00:00.000000+00:00", created_at="2026-01-01T00:00:00.000000+00:00",
        actor="sql", reason="release", source_type="MANUAL", is_demo=0, record_status="VALIDATED")
    data.update(extra)
    with repo.transaction():
        repo.connection.execute(f"INSERT INTO model_deployments({','.join(data)}) VALUES ({','.join('?' for _ in data)})", list(data.values()))


def actual(repo, **extra):
    return repo.save_actual_result({"site_id": "s", "target_date": "2026-01-02", "actual_diners": 95,
        "created_at": "2026-01-02T12:00:00Z", "source_type": "USER_UPLOAD", "record_status": "VALIDATED", **extra})


def snapshot_prediction(repo, **extra):
    return repo.save_prediction({"site_id": "s", "target_date": "2026-01-02", "predicted_diners": 100,
        "created_at": "2026-01-02T10:00:00Z", "source_type": "MODEL", "record_status": "VALIDATED",
        "feature_schema_version": "demand-v1", "observed_at": "2026-01-02T09:00:00Z", "source_lineage_id": "upload-123",
        "input_snapshot_json": {"population": 200, "weekday": 4}, **extra})


def test_site_role_deployment_history_isolated_from_global_current(repo):
    repo.create_site(site_id="b", site_name="B")
    model(repo)
    model(repo, "m2")
    legacy = repo.save_model_version(model_version="legacy", model_type="x", status="current")
    first = deploy(repo)
    other_site = deploy(repo, site="b")
    other_role = deploy(repo, role="nutrition")
    replacement = deploy(repo, "m2", audit_metadata={"review_ticket": "R-12"})
    assert repo.get_current_deployment("s")["deployment_id"] == replacement["deployment_id"]
    assert repo.get_deployment(first["deployment_id"])["status"] == "retired"
    assert repo.get_deployment(first["deployment_id"])["retired_at"] == replacement["effective_at"]
    assert repo.get_current_deployment("b") == other_site
    assert repo.get_current_deployment("s", "nutrition") == other_role
    assert repo.get_current_model() == legacy
    assert len(repo.list_model_deployments("s", "demand")) == 2


@pytest.mark.parametrize("bad", [{"source_type": "DEMO"}, {"is_demo": True},
    {"record_status": "INVALID"}, {"record_status": "UNVALIDATED"}, {"status": "rejected"}])
def test_ineligible_model_deployment_api_and_raw_sql(repo, bad):
    model(repo)
    current = deploy(repo)
    model(repo, "bad", **bad)
    with pytest.raises(ValidationError, match="VALIDATED"):
        deploy(repo, "bad")
    assert repo.get_current_deployment("s") == current
    with pytest.raises(sqlite3.IntegrityError, match="VALIDATED"):
        raw_deploy(repo, model_version="bad", model_role="new-role")


@pytest.mark.parametrize("bad", [{"site_id": "missing"}, {"model_version": "missing"},
    {"source_type": "DEMO", "is_demo": 1}, {"is_demo": 1}, {"record_status": "UNVALIDATED"},
    {"record_status": "INVALID"}, {"model_role": " "}, {"effective_at": "2099-01-01T00:00:00.000000+00:00"}])
def test_raw_deployment_guard_and_metadata(repo, bad):
    model(repo)
    with pytest.raises(sqlite3.IntegrityError):
        raw_deploy(repo, **bad)


def test_raw_unique_history_guards_and_model_invalidation(repo):
    model(repo)
    raw_deploy(repo)
    with pytest.raises(sqlite3.IntegrityError):
        raw_deploy(repo, deployment_id="duplicate")
    for assignment in ("record_status='UNVALIDATED'", "record_status='INVALID'", "is_demo=1", "status='rejected'", "source_type='DEMO',is_demo=1"):
        with pytest.raises(sqlite3.IntegrityError, match="deployed"):
            with repo.transaction():
                repo.connection.execute(f"UPDATE model_versions SET {assignment} WHERE model_version='m1'")
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute("DELETE FROM model_versions WHERE model_version='m1'")
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute("UPDATE model_deployments SET reason='rewrite'")
    retired = repo.retire_deployment("raw", actor="operator", reason="withdraw", retired_at="2026-02-01T00:00:00Z")
    assert retired["retired_by"] == "operator"
    for sql in ("DELETE FROM model_deployments", "UPDATE model_deployments SET status='current',retired_at=NULL",
                "INSERT OR REPLACE INTO model_deployments SELECT * FROM model_deployments"):
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction():
                repo.connection.execute(sql)
    with pytest.raises(sqlite3.IntegrityError, match="overlaps"):
        raw_deploy(repo, deployment_id="backdate")


def test_deployment_rollback_restores_prior_current(repo):
    model(repo)
    model(repo, "m2")
    first = deploy(repo)
    with pytest.raises(RuntimeError):
        with repo.transaction():
            deploy(repo, "m2")
            raise RuntimeError("abort")
    assert repo.get_current_deployment("s") == first
    assert len(repo.list_model_deployments()) == 1


def test_feature_contract_full_snapshot_and_missing_features(repo):
    repo.register_feature_schema("demand-v1", {"population": "number", "weekday": "integer"})
    p = snapshot_prediction(repo)
    actual(repo)
    assert p["snapshot_validation_json"]["valid"] is True
    result = get_training_dataset(repo)
    assert result["accepted_count"] == 1 and result["rejected_count"] == 0
    assert result["records"][0]["input_snapshot_json"] == {"population": 200, "weekday": 4}
    newer = snapshot_prediction(repo, input_snapshot_json={"population": 200}, created_at="2026-01-02T11:00:00Z")
    result = get_training_dataset(repo)
    assert result["records"] == []  # No silent fallback to an older complete snapshot.
    rejection = result["rejected_records"][0]
    assert rejection["prediction_id"] == newer["prediction_id"]
    assert rejection["validation_result"]["missing_required_features"] == ["weekday"]
    assert get_training_dataset(repo, selection_policy="explicit", prediction_ids={p["prediction_id"]})["accepted_count"] == 1


@pytest.mark.parametrize("changes,expected", [
    ({"feature_schema_version": None}, "feature_schema_version"),
    ({"feature_schema_version": "unknown"}, "unknown"),
    ({"observed_at": None}, "observed_at"),
    ({"observed_at": "2026-01-02T11:00:00Z"}, "after"),
    ({"source_lineage_id": None}, "source_lineage_id"),
    ({"input_snapshot_json": []}, "object"),
])
def test_incomplete_metadata_reports_rejection(repo, changes, expected):
    repo.register_feature_schema("demand-v1", {"population": "number", "weekday": "integer"})
    snapshot_prediction(repo, **changes)
    actual(repo)
    result = get_training_dataset(repo)
    assert result["accepted_count"] == 0
    assert expected in " ".join(result["rejected_records"][0]["validation_result"]["metadata_errors"])


def test_feature_type_errors_and_forged_validation_not_trusted(repo):
    repo.register_feature_schema("demand-v1", {"population": "number", "weekday": "integer"})
    p = snapshot_prediction(repo, input_snapshot_json={"population": True, "weekday": "4"}, snapshot_validation_json={"valid": True})
    assert not p["snapshot_validation_json"]["valid"]
    actual(repo)
    with repo.transaction():
        repo.connection.execute("UPDATE predictions SET snapshot_validation_json=?", ('{"valid":true}',))
    result = get_training_dataset(repo)
    assert result["accepted_count"] == 0
    assert len(result["rejected_records"][0]["validation_result"]["type_errors"]) == 2


def test_schema_version_immutable_and_new_version_allowed(repo):
    repo.register_feature_schema("demand-v1", {"population": "number"})
    for statement in ("UPDATE feature_schemas SET required_features_json='{}'", "DELETE FROM feature_schemas",
                      "INSERT OR REPLACE INTO feature_schemas SELECT * FROM feature_schemas"):
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction():
                repo.connection.execute(statement)
    with pytest.raises(sqlite3.IntegrityError):
        repo.register_feature_schema("demand-v1", {"new": "string"})
    repo.register_feature_schema("demand-v2", {"new": "string"})
    assert len(repo.list_feature_schemas()) == 2


def test_legacy_snapshot_still_in_learning_but_reported_in_training(repo):
    snapshot_prediction(repo, feature_schema_version=None, observed_at=None, source_lineage_id=None)
    actual(repo)
    assert len(get_learning_dataset(repo)) == 1
    assert get_training_dataset(repo)["rejected_count"] == 1


def test_actual_correction_audit_api_raw_sql_immutable(repo):
    original = actual(repo)
    updated = repo.update_actual_result("s", "2026-01-02", actual_diners=96,
        actor="reviewer", correction_source="USER_UPLOAD", reason="Corrected attendance")
    events = repo.get_actual_corrections("s", "2026-01-02")
    assert len(events) == 1
    assert events[0]["old_values_json"] == original
    assert events[0]["new_values_json"] == updated
    assert events[0]["actor"] == "reviewer" and events[0]["source_type"] == "USER_UPLOAD"
    assert events[0]["reason"] == "Corrected attendance" and events[0]["corrected_at"].endswith("+00:00")
    with repo.transaction():
        repo.connection.execute("UPDATE actual_results SET actual_diners=97 WHERE result_id=?", (original["result_id"],))
    events = repo.get_actual_corrections("s", "2026-01-02")
    assert events[1]["old_values_json"] == updated
    assert events[1]["new_values_json"]["actual_diners"] == 97
    assert events[1]["actor"] == "UNKNOWN_RAW_SQL"
    for statement in ("UPDATE actual_corrections SET reason='rewrite'", "DELETE FROM actual_corrections",
        "INSERT OR REPLACE INTO actual_corrections SELECT * FROM actual_corrections",
        "DELETE FROM actual_results", "INSERT OR REPLACE INTO actual_results SELECT * FROM actual_results",
        "UPDATE actual_results SET result_id='changed'"):
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction():
                repo.connection.execute(statement)
    assert len(repo.get_actual_corrections("s", "2026-01-02")) == 2


def test_actual_correction_legacy_rollback_and_context_cleanup(repo):
    original = actual(repo)
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.update_actual_result("s", "2026-01-02", actual_diners=96)
            raise RuntimeError("rollback")
    assert repo.get_actual_result("s", "2026-01-02") == original
    assert repo.get_actual_corrections("s", "2026-01-02") == []
    assert repo.connection.execute("SELECT COUNT(*) FROM actual_correction_context").fetchone()[0] == 0
    repo.update_actual_result("s", "2026-01-02", actual_diners=96)
    assert repo.get_actual_corrections("s", "2026-01-02")[0]["actor"] == "LEGACY_API"
    with pytest.raises(ValidationError):
        repo.update_actual_result("s", "2026-01-02", actual_diners=-1, actor="x", reason="bad")
    assert len(repo.get_actual_corrections("s", "2026-01-02")) == 1


def test_named_dashboard_uses_site_role_cutoff_not_legacy_global(repo):
    repo.create_site(site_id="b", site_name="B")
    repo.save_model_version(model_version="global", model_type="x", status="current", trained_at="2026-01-03T00:00:00Z")
    model(repo, trained_at="2026-01-01T00:00:00Z")
    model(repo, "m2", trained_at="2026-01-03T00:00:00Z")
    deploy(repo)
    deploy(repo, "m2", site="b")
    actual(repo)
    actual(repo, site_id="b")
    assert get_dashboard_readiness(repo, "s", 1)["ready"] is True
    assert get_dashboard_readiness(repo, "b", 1)["ready"] is False
    assert get_retraining_readiness(repo, "s", 1)["ready"] is False  # Compatibility: global current cutoff.
    assert get_dashboard_readiness(repo, "b", 1, model_role="unassigned")["ready"] is True
    assert get_dashboard_readiness(repo, "b", 1, since="2026-01-01T00:00:00Z")["ready"] is True
    assert get_dashboard_kpis(repo, "s") == get_site_kpis(repo, "s")


def test_concurrent_deployments_are_serialized_and_history_preserved(tmp_path):
    path = tmp_path / "concurrent.db"
    with Repository(path) as r:
        r.create_site(site_id="s", site_name="Test")
        model(r)
        model(r, "m2")
    barrier = Barrier(2)
    def worker(version):
        with Repository(path) as r:
            barrier.wait(timeout=10)
            return deploy(r, version)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ("m1", "m2")))
    with Repository(path) as r:
        history = r.list_model_deployments("s")
        assert len(history) == 2
        assert [d["status"] for d in history].count("current") == 1
        assert {d["deployment_id"] for d in history} == {d["deployment_id"] for d in results}


def test_concurrent_actual_corrections_form_a_complete_chain(tmp_path):
    path = tmp_path / "audit-concurrent.db"
    with Repository(path) as r:
        r.create_site(site_id="s", site_name="Test")
        original = actual(r)
    barrier = Barrier(2)
    def worker(value):
        with Repository(path) as r:
            barrier.wait(timeout=10)
            return r.update_actual_result("s", "2026-01-02", actual_diners=value, actor=str(value), reason="correction")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, (96, 97)))
    with Repository(path) as r:
        events = r.get_actual_corrections("s", "2026-01-02")
        assert len(events) == 2
        assert events[0]["old_values_json"] == original
        assert events[1]["old_values_json"] == events[0]["new_values_json"]
        assert r.get_actual_result("s", "2026-01-02") == events[1]["new_values_json"]


def test_failed_deployment_insert_rolls_back_prior_retirement(repo, monkeypatch):
    import lastplate_db.deployments as deployment_module
    model(repo)
    model(repo, "m2")
    first = deploy(repo)
    monkeypatch.setattr(deployment_module, "uuid4", lambda: first["deployment_id"])
    with pytest.raises(sqlite3.IntegrityError):
        deploy(repo, "m2")
    assert repo.get_current_deployment("s") == first
    assert len(repo.list_model_deployments()) == 1


def test_failed_audit_insert_rolls_back_actual_update_and_context(repo):
    original = actual(repo)
    repo.connection.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON actual_corrections BEGIN SELECT RAISE(ABORT,'audit storage failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match="audit storage"):
        repo.update_actual_result("s", "2026-01-02", actual_diners=999, actor="reviewer", reason="fix")
    assert repo.get_actual_result("s", "2026-01-02") == original
    assert repo.get_actual_corrections("s", "2026-01-02") == []
    assert repo.connection.execute("SELECT COUNT(*) FROM actual_correction_context").fetchone()[0] == 0


def test_deployment_existence_guards_work_even_with_foreign_keys_off(repo):
    model(repo)
    repo.connection.execute("PRAGMA foreign_keys=OFF")
    try:
        for changes in ({"site_id": "missing"}, {"model_version": "missing"}):
            with pytest.raises(sqlite3.IntegrityError):
                raw_deploy(repo, **changes)
    finally:
        repo.connection.execute("PRAGMA foreign_keys=ON")


def test_training_extraction_safe_filters_are_not_overridden_by_valid_snapshot(repo):
    repo.register_feature_schema("demand-v1", {"population": "number"})
    snapshot_prediction(repo, source_type="DEMO")
    actual(repo)
    assert get_training_dataset(repo)["candidate_count"] == 0
    assert get_dashboard_kpis(repo, "s")["prediction_mae"] is None
