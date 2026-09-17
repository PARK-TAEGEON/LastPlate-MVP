import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from lastplate_db import Repository, ValidationError, get_learning_dataset
from lastplate_db.seed import seed_demo


DATE = "2026-01-01"


def stamp(hour):
    return f"2026-01-01T{hour:02}:00:00+00:00"


def prediction(repo, *, hour=1, **changes):
    return repo.save_prediction({"site_id": "s", "target_date": DATE, "predicted_diners": 100,
        "created_at": stamp(hour), "source_type": "MODEL", "record_status": "VALIDATED", **changes})


def actual(repo, *, hour=10, **changes):
    return repo.save_actual_result({"site_id": "s", "target_date": DATE, "actual_diners": 95,
        "created_at": stamp(hour), "source_type": "USER_UPLOAD", "record_status": "VALIDATED", **changes})


def plan(repo, p, *, hour=2, **changes):
    return repo.save_operation_plan({"site_id": p["site_id"], "target_date": p["target_date"],
        "prediction_id": p["prediction_id"], "recommended_servings": 110, "created_at": stamp(hour),
        "source_type": "AGENT", "record_status": "VALIDATED", **changes})


def test_cp949_demo_clean_and_second_run(tmp_path):
    project = Path(__file__).resolve().parents[1]
    path = tmp_path / "cp949.db"
    env = {**os.environ, "PYTHONIOENCODING": "cp949:strict", "PYTHONUTF8": "0"}
    # Child stdout is a pipe; PYTHONIOENCODING therefore forces actual CP949 encoding.
    for expected in (1, 2):
        result = subprocess.run([sys.executable, "-m", "lastplate_db.demo", "--db", str(path)],
            cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        assert result.returncode == 0, result.stderr.decode("cp949", errors="replace")
        output = result.stdout.decode("cp949", errors="strict")
        assert "DEMO - synthetic values" in output
        assert '"predicted_diners": 487.0' in output
        assert '"source_type": "DEMO"' in output
        assert "UnicodeEncodeError" not in result.stderr.decode("cp949", errors="replace")
        with Repository(path) as db:
            assert len(db.list_sites()) == expected
            assert get_learning_dataset(db) == []
            assert len(get_learning_dataset(db, include_demo=True)) == expected
            for table in ("sites", "predictions", "operation_plans", "actual_results", "decision_logs", "inventory_snapshots", "model_versions"):
                assert db.connection.execute(f"SELECT COUNT(*) FROM {table} WHERE source_type!='DEMO' OR is_demo!=1").fetchone()[0] == 0


@pytest.mark.parametrize("lower,value,upper", [(90, 89, 110), (90, 111, 110), (110, 100, 90)])
def test_interval_rejected_by_repository_and_sql(repo, lower, value, upper):
    with pytest.raises(ValidationError, match="lower_bound"):
        prediction(repo, lower_bound=lower, predicted_diners=value, upper_bound=upper)
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute('''INSERT INTO predictions
                (prediction_id,site_id,target_date,predicted_diners,lower_bound,upper_bound,created_at)
                VALUES ('raw','s',?,?,?,?,?)''', (DATE, value, lower, upper, stamp(1)))


@pytest.mark.parametrize("lower,value,upper", [(90, 90, 110), (90, 110, 110), (100, 100, 100), (None, 120, 110), (110, 100, None)])
def test_interval_boundary_and_optional_bounds(repo, lower, value, upper):
    assert prediction(repo, lower_bound=lower, predicted_diners=value, upper_bound=upper)["predicted_diners"] == value


def test_interval_raw_update_is_checked(repo):
    p = prediction(repo, lower_bound=90, upper_bound=110)
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute("UPDATE predictions SET predicted_diners=111 WHERE prediction_id=?", (p["prediction_id"],))
    assert repo.get_prediction(p["prediction_id"])["predicted_diners"] == 100


@pytest.mark.parametrize("side", ["prediction", "actual", "plan"])
@pytest.mark.parametrize("marker", [{"source_type": "DEMO"}, {"source_type": "MODEL", "is_demo": True}])
def test_demo_filter_on_each_join_side(repo, side, marker):
    p = prediction(repo, **(marker if side == "prediction" else {}))
    plan(repo, p, **(marker if side == "plan" else {}))
    actual(repo, **(marker if side == "actual" else {}))
    rows = get_learning_dataset(repo)
    if side == "plan":
        assert len(rows) == 1 and rows[0]["plan_id"] is None
    else:
        assert rows == []
    assert len(get_learning_dataset(repo, include_demo=True)) == 1


@pytest.mark.parametrize("side", ["prediction", "actual", "plan"])
@pytest.mark.parametrize("status", ["UNVALIDATED", "INVALID"])
def test_status_filter_on_each_join_side(repo, side, status):
    marker = {"record_status": status}
    p = prediction(repo, **(marker if side == "prediction" else {}))
    plan(repo, p, **(marker if side == "plan" else {}))
    actual(repo, **(marker if side == "actual" else {}))
    rows = get_learning_dataset(repo)
    if side == "plan":
        assert rows[0]["plan_id"] is None
    else:
        assert rows == []
    rows = get_learning_dataset(repo, include_demo=True, include_unvalidated=True)
    if status == "UNVALIDATED":
        assert len(rows) == 1 and rows[0]["plan_id"] is not None
    elif side == "plan":
        assert rows[0]["plan_id"] is None
    else:
        assert rows == []


def test_demo_and_unvalidated_options_are_independent(repo):
    prediction(repo, source_type="DEMO", record_status="UNVALIDATED")
    actual(repo)
    assert get_learning_dataset(repo, include_demo=True) == []
    assert get_learning_dataset(repo, include_unvalidated=True) == []
    assert len(get_learning_dataset(repo, include_demo=True, include_unvalidated=True)) == 1


def test_feature_complete_dataset(repo):
    p = prediction(repo, input_snapshot_json={"menu": ["쌀", "🥣"]}, available_population=200,
        predicted_rate=0.5, model_type="xgb", model_version="v", applicability="in_range", confidence="high",
        lower_bound=90, upper_bound=110)
    op = plan(repo, p)
    actual(repo)
    row = get_learning_dataset(repo)[0]
    for name in ("input_snapshot_json", "available_population", "predicted_rate", "model_type", "model_version",
                 "applicability", "confidence", "source_type", "is_demo", "record_status"):
        assert row[name] == p[name]
    assert row["actual_source_type"] == "USER_UPLOAD"
    assert row["actual_record_status"] == "VALIDATED"
    assert row["plan_source_type"] == op["source_type"]
    assert row["plan_record_status"] == "VALIDATED"


def test_post_actual_leakage_and_explicit_policy(repo):
    before = prediction(repo, hour=9)
    equal = prediction(repo, hour=10)
    after = prediction(repo, hour=11)
    actual(repo, hour=10)
    assert [r["prediction_id"] for r in get_learning_dataset(repo)] == [before["prediction_id"]]
    ids = {p["prediction_id"] for p in (before, equal, after)}
    assert [r["prediction_id"] for r in get_learning_dataset(repo, selection_policy="explicit", prediction_ids=ids)] == [before["prediction_id"]]
    assert get_learning_dataset(repo, selection_policy="explicit", prediction_ids={after["prediction_id"]}) == []


def test_three_predictions_two_plans_no_fanout(repo):
    predictions = [prediction(repo, hour=h) for h in (1, 2, 3)]
    latest_plans = []
    for p in predictions:
        plan(repo, p, hour=4)
        latest_plans.append(plan(repo, p, hour=5))
    actual(repo)
    rows = get_learning_dataset(repo)
    assert len(rows) == 1
    assert rows[0]["prediction_id"] == predictions[-1]["prediction_id"]
    assert rows[0]["plan_id"] == latest_plans[-1]["plan_id"]
    explicit = get_learning_dataset(repo, selection_policy="explicit", prediction_ids=[p["prediction_id"] for p in predictions])
    assert len(explicit) == 3
    assert {r["plan_id"] for r in explicit} == {p["plan_id"] for p in latest_plans}


def test_filtered_newer_predictions_and_plans_do_not_mask_history(repo):
    good = prediction(repo)
    prediction(repo, hour=2, source_type="DEMO")
    prediction(repo, hour=3, record_status="INVALID")
    prediction(repo, hour=4, record_status="UNVALIDATED")
    old_plan = plan(repo, good, hour=5)
    plan(repo, good, hour=6, source_type="DEMO")
    plan(repo, good, hour=7, record_status="UNVALIDATED")
    plan(repo, good, hour=10)
    plan(repo, good, hour=11)
    actual(repo)
    row = get_learning_dataset(repo)[0]
    assert row["prediction_id"] == good["prediction_id"]
    assert row["plan_id"] == old_plan["plan_id"]


def test_deterministic_ties_and_explicit_dedup(repo):
    prediction(repo)
    newest = prediction(repo)
    plan(repo, newest)
    latest_plan = plan(repo, newest)
    actual(repo)
    assert get_learning_dataset(repo)[0]["plan_id"] == latest_plan["plan_id"]
    rows = get_learning_dataset(repo, selection_policy="explicit", prediction_ids=[newest["prediction_id"]] * 2)
    assert len(rows) == 1
    assert get_learning_dataset(repo, selection_policy="explicit", prediction_ids=[]) == []
    assert get_learning_dataset(repo, selection_policy="explicit", prediction_ids=["' OR 1=1 --"]) == []


@pytest.mark.parametrize("options", [{"selection_policy": "all"}, {"selection_policy": "explicit"},
    {"prediction_ids": ["a"]}, {"selection_policy": "explicit", "prediction_ids": "a"},
    {"selection_policy": "explicit", "prediction_ids": [None]}, {"include_demo": "yes"},
    {"include_unvalidated": 1}])
def test_bad_selection_options(repo, options):
    with pytest.raises(ValidationError):
        get_learning_dataset(repo, **options)


def test_plan_retry_is_deterministic_conflict_and_new_key_is_history(repo):
    p = prediction(repo)
    first = plan(repo, p, idempotency_key="request-1")
    for changes in ({}, {"recommended_servings": 150}):
        with pytest.raises(sqlite3.IntegrityError):
            plan(repo, p, idempotency_key="request-1", **changes)
    second = plan(repo, p, hour=3, idempotency_key="revision-2")
    assert repo.get_operation_plan(first["plan_id"])["recommended_servings"] == 110
    assert repo.get_operation_plan_by_prediction(p["prediction_id"]) == second
    assert repo.connection.execute("SELECT COUNT(*) FROM operation_plans").fetchone()[0] == 2
    other = prediction(repo)
    plan(repo, other, idempotency_key="request-1")  # Key is scoped to prediction.
    plan(repo, other)
    plan(repo, other)  # Legacy NULL keys append history.


@pytest.mark.parametrize("method,payload", [
    ("save_prediction", {"site_id": "s", "target_date": DATE, "predicted_diners": 100}),
    ("save_actual_result", {"site_id": "s", "target_date": DATE, "actual_diners": 90}),
    ("save_decision", {"site_id": "s", "target_date": DATE}),
    ("create_site", {"site_name": "Another"}),
])
@pytest.mark.parametrize("bad", [{"source_type": "typo"}, {"source_type": "model"},
    {"source_type": None}, {"record_status": "bad"}, {"is_demo": 2}, {"source_type": "DEMO", "is_demo": False}])
def test_source_validation(repo, method, payload, bad):
    with pytest.raises(ValidationError):
        getattr(repo, method)({**payload, **bad})


def test_plan_source_and_database_source_constraints(repo):
    p = prediction(repo)
    with pytest.raises(ValidationError):
        plan(repo, p, source_type="typo")
    for assignment in ("source_type='typo'", "record_status='bad'", "is_demo=2", "source_type='DEMO',is_demo=0"):
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction():
                repo.connection.execute(f"UPDATE predictions SET {assignment}")


def test_legacy_calls_default_to_unvalidated(repo):
    p = repo.save_prediction(site_id="s", target_date=DATE, predicted_diners=100, created_at=stamp(1))
    actual(repo)
    assert (p["source_type"], p["is_demo"], p["record_status"]) == ("UNKNOWN", 0, "UNVALIDATED")
    assert get_learning_dataset(repo) == []
    assert len(get_learning_dataset(repo, include_unvalidated=True)) == 1


def test_update_site_preserves_created_and_open_site_type_policy(repo):
    old = repo.get_site("s")
    new = repo.update_site("s", {"site_name": "Updated", "site_type": "research_campus", "meal_capacity": 5})
    assert new["site_name"] == "Updated"
    assert new["site_type"] == "research_campus"
    assert new["created_at"] == old["created_at"]
    assert datetime.fromisoformat(new["updated_at"]) >= datetime.fromisoformat(old["created_at"])
    assert repo.update_site("s", site_type=None)["site_type"] is None
    with pytest.raises(ValidationError):
        repo.update_site("s", site_type="   ")
    with pytest.raises(ValidationError):
        repo.update_site("s", created_at=stamp(1))
    with pytest.raises(ValidationError):
        repo.update_site("missing", site_name="No")


@pytest.mark.parametrize("failure", ["validation", "foreign_key"])
def test_public_transaction_rolls_back_site_prediction_plan(repo, failure):
    with pytest.raises((ValidationError, sqlite3.IntegrityError)):
        with repo.transaction():
            repo.create_site(site_id="new", site_name="New")
            p = prediction(repo, site_id="new")
            plan(repo, p, **({"recommended_servings": -1} if failure == "validation" else {"target_date": "2026-01-02"}))
    assert repo.get_site("new") is None
    assert repo.get_predictions_by_site("new") == []
    assert repo.connection.execute("SELECT COUNT(*) FROM operation_plans").fetchone()[0] == 0


def test_nested_savepoint_and_transaction_commit(repo):
    with repo.transaction():
        repo.create_site(site_id="good", site_name="Good")
        with pytest.raises(ValidationError):
            with repo.transaction():
                repo.create_site(site_id="inner", site_name="Inner")
                raise ValidationError("rollback inner")
        repo.update_site("good", meal_capacity=50)
    assert repo.get_site("good")["meal_capacity"] == 50
    assert repo.get_site("inner") is None
    assert not repo.connection.in_transaction


def test_updates_and_model_switch_join_parent_transaction(repo):
    original = actual(repo)
    repo.save_model_version(model_version="v1", model_type="x", status="current")
    repo.save_model_version(model_version="v2", model_type="x", status="candidate")
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.update_site("s", site_name="Changed")
            repo.update_actual_result("s", DATE, actual_diners=1)
            repo.set_current_model("v2")
            raise RuntimeError("rollback all")
    assert repo.get_site("s")["site_name"] == "Test"
    assert repo.get_actual_result("s", DATE) == original
    assert repo.get_current_model()["model_version"] == "v1"


def test_seed_collision_rolls_back_all_rows(repo):
    repo.save_model_version(model_version="demo-v1", model_type="real")
    with pytest.raises(ValidationError):
        seed_demo(repo)
    assert len(repo.list_sites()) == 1
    assert repo.connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_public_compound_commit_visible_only_after_exit(tmp_path):
    path = tmp_path / "transaction.db"
    with Repository(path) as writer, Repository(path) as reader:
        with writer.transaction():
            writer.create_site(site_id="s", site_name="New")
            p = prediction(writer)
            op = plan(writer, p)
            assert reader.get_site("s") is None
            assert reader.get_prediction(p["prediction_id"]) is None
        assert reader.get_site("s") is not None
        assert reader.get_operation_plan(op["plan_id"]) == op


def test_selection_partition_and_explicit_site_scope(repo):
    p1 = prediction(repo)
    prediction(repo, hour=2)
    actual(repo)
    repo.create_site(site_id="other", site_name="Other")
    other = prediction(repo, site_id="other")
    actual(repo, site_id="other")
    next_day = prediction(repo, target_date="2026-01-02")
    actual(repo, target_date="2026-01-02")
    assert len(get_learning_dataset(repo)) == 3
    assert len(get_learning_dataset(repo, "s")) == 2
    selected = get_learning_dataset(repo, "s", selection_policy="explicit",
        prediction_ids={p1["prediction_id"], other["prediction_id"], next_day["prediction_id"]})
    assert {row["prediction_id"] for row in selected} == {p1["prediction_id"], next_day["prediction_id"]}


def test_adapter_accepts_provenance_and_plan_retry_key(repo):
    from lastplate_db import persist_demand_result, persist_operation_result, persist_actual_result
    p = persist_demand_result(repo, "s", dict(target_date=DATE, predicted_diners=100,
        source_type="PUBLIC_API", record_status="VALIDATED", created_at=stamp(1)))
    payload = dict(target_date=DATE, recommended_servings=110, source_type="AGENT",
        record_status="VALIDATED", idempotency_key="adapter-retry", created_at=stamp(2))
    persist_operation_result(repo, "s", p["prediction_id"], payload)
    with pytest.raises(sqlite3.IntegrityError):
        persist_operation_result(repo, "s", p["prediction_id"], payload)
    persist_actual_result(repo, "s", dict(target_date=DATE, actual_diners=90,
        source_type="USER_UPLOAD", record_status="VALIDATED", created_at=stamp(10)))
    assert get_learning_dataset(repo)[0]["source_type"] == "PUBLIC_API"
