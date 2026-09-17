import inspect
import sqlite3

import pytest

import lastplate_db
from lastplate_db import Repository, ValidationError, get_site_kpis, get_retraining_readiness


def actual(repo, day=1, **changes):
    return repo.save_actual_result({"site_id": "s", "target_date": f"2026-01-{day:02}",
        "actual_diners": 95, "prepared_servings": 100, "unserved_leftover_kg": 2,
        "plate_waste_kg": 3, "shortage": False, "created_at": f"2026-01-{day:02}T12:00:00Z",
        "source_type": "USER_UPLOAD", "record_status": "VALIDATED", **changes})


def prediction(repo, day=1, **changes):
    return repo.save_prediction({"site_id": "s", "target_date": f"2026-01-{day:02}",
        "predicted_diners": 100, "created_at": f"2026-01-{day:02}T10:00:00Z",
        "source_type": "MODEL", "record_status": "VALIDATED", **changes})


EXCLUDED = [dict(source_type="DEMO"), dict(is_demo=True),
            dict(record_status="UNVALIDATED"), dict(record_status="INVALID")]


@pytest.mark.parametrize("bad", EXCLUDED)
def test_one_real_plus_excluded_actual_cannot_unlock_readiness_or_change_safe_kpi(repo, bad):
    prediction(repo)
    actual(repo)
    baseline = get_site_kpis(repo, "s")
    assert baseline == dict(prediction_mae=5.0, average_leftover_kg=2.0,
        average_plate_waste_kg=3.0, shortage_rate=0.0, average_overprep_servings=5.0)
    prediction(repo, day=2, predicted_diners=300)
    actual(repo, day=2, actual_diners=1, prepared_servings=500,
           unserved_leftover_kg=200, plate_waste_kg=300, shortage=True, **bad)
    ready = get_retraining_readiness(repo, "s", 2)
    assert ready == dict(site_id="s", new_actual_records=1, eligible_new_actual_records=1,
                         all_new_actual_records=2, required_records=2, ready=False)
    assert get_site_kpis(repo, "s") == baseline
    legacy = get_retraining_readiness(repo, "s", 2, legacy_all_rows=True)
    assert legacy["ready"] is True and legacy["new_actual_records"] == 2
    assert legacy["eligible_new_actual_records"] == 1 and legacy["all_new_actual_records"] == 2
    kpi = get_site_kpis(repo, "s", eligible_only=False)
    assert kpi["prediction_mae"] == 152
    assert kpi["average_leftover_kg"] == 101
    assert kpi["shortage_rate"] == 0.5


def test_readiness_counts_actuals_without_prediction_and_site_isolation(repo):
    actual(repo)
    repo.create_site(site_id="other", site_name="Other")
    actual(repo, site_id="other")
    assert get_retraining_readiness(repo, "s", 1)["ready"] is True
    assert get_retraining_readiness(repo, "s", 2)["all_new_actual_records"] == 1
    kpi = get_site_kpis(repo, "s")
    assert kpi["prediction_mae"] is None and kpi["average_leftover_kg"] == 2


def test_safe_readiness_cutoff_strict_boundary_and_updates(repo):
    repo.save_model_version(model_version="v", model_type="x", status="current",
                           trained_at="2026-01-02T21:00:00+09:00")
    actual(repo, day=1)
    actual(repo, day=2)
    actual(repo, day=3)
    actual(repo, day=4, record_status="INVALID")
    ready = get_retraining_readiness(repo, "s", 2)
    assert ready["eligible_new_actual_records"] == 1 and ready["all_new_actual_records"] == 2
    assert ready["ready"] is False
    repo.update_actual_result("s", "2026-01-01", actual_diners=94)
    assert get_retraining_readiness(repo, "s", 2) == ready
    explicit = get_retraining_readiness(repo, "s", 3, since="2026-01-01T00:00:00Z")
    assert explicit["eligible_new_actual_records"] == 3 and explicit["all_new_actual_records"] == 4
    assert explicit["ready"] is True


@pytest.mark.parametrize("bad", EXCLUDED)
def test_kpi_latest_eligible_pre_actual_prediction(repo, bad):
    prediction(repo, predicted_diners=80, created_at="2026-01-01T09:00:00Z")
    prediction(repo, predicted_diners=100, created_at="2026-01-01T10:00:00Z")
    prediction(repo, predicted_diners=500, created_at="2026-01-01T11:00:00Z", **bad)
    prediction(repo, predicted_diners=700, created_at="2026-01-01T12:00:00Z")
    prediction(repo, predicted_diners=900, created_at="2026-01-01T13:00:00Z")
    actual(repo)
    assert get_site_kpis(repo, "s")["prediction_mae"] == 5
    assert get_site_kpis(repo, "s", eligible_only=False)["prediction_mae"] == 805


def test_safe_mae_uses_one_prediction_per_actual_not_plan_fanout(repo):
    for value in (70, 80, 100):
        p = prediction(repo, predicted_diners=value)
        for count in (100, 110):
            repo.save_operation_plan(site_id="s", target_date="2026-01-01",
                prediction_id=p["prediction_id"], recommended_servings=count)
    actual(repo)
    actual(repo, day=2, prepared_servings=None, plate_waste_kg=None)
    assert get_site_kpis(repo, "s")["prediction_mae"] == 5
    assert get_site_kpis(repo, "s")["average_overprep_servings"] == 5
    assert get_site_kpis(repo, "s")["average_plate_waste_kg"] == 3


def test_demo_only_safe_results(repo):
    from lastplate_db.seed import seed_demo
    site = seed_demo(repo)
    assert all(value is None for value in get_site_kpis(repo, site["site_id"]).values())
    ready = get_retraining_readiness(repo, site["site_id"], 1)
    assert ready["new_actual_records"] == ready["eligible_new_actual_records"] == 0
    assert ready["all_new_actual_records"] == 1 and ready["ready"] is False


@pytest.mark.parametrize("bad", [None, 0, 1, "true", [], {}])
def test_explicit_flags_require_real_boolean(repo, bad):
    with pytest.raises(ValidationError):
        get_site_kpis(repo, "s", eligible_only=bad)
    with pytest.raises(ValidationError):
        get_retraining_readiness(repo, "s", legacy_all_rows=bad)


def test_empty_safe_and_legacy_counts(repo):
    for mode in (False, True):
        result = get_retraining_readiness(repo, "absent", legacy_all_rows=mode)
        assert result["all_new_actual_records"] == result["eligible_new_actual_records"] == result["new_actual_records"] == 0
        assert result["ready"] is False
        assert all(value is None for value in get_site_kpis(repo, "absent", eligible_only=mode).values())


BAD_MODELS = [dict(source_type="DEMO", is_demo=True, record_status="VALIDATED"),
              dict(source_type="MODEL", is_demo=True, record_status="VALIDATED"),
              dict(source_type="MODEL", is_demo=False, record_status="INVALID")]


@pytest.mark.parametrize("bad", BAD_MODELS)
def test_unsafe_current_direct_save_and_switch_preserve_existing_current(repo, bad):
    current = repo.save_model_version(model_version="good", model_type="x", status="current")
    with pytest.raises(ValidationError, match="current model"):
        repo.save_model_version(model_version="bad-direct", model_type="x", status="current", **bad)
    candidate = repo.save_model_version(model_version="bad", model_type="x", status="candidate", **bad)
    with pytest.raises(ValidationError, match="current model"):
        repo.set_current_model("bad")
    assert repo.get_current_model() == current
    assert next(m for m in repo.list_model_versions() if m["model_version"] == "bad") == candidate


@pytest.mark.parametrize("bad", BAD_MODELS)
def test_sql_guards_current_insert_and_switch(repo, bad):
    values = (bad["source_type"], int(bad["is_demo"]), bad["record_status"])
    with pytest.raises(sqlite3.IntegrityError, match="current model"):
        with repo.transaction():
            repo.connection.execute('''INSERT INTO model_versions
                (model_version,model_type,status,created_at,source_type,is_demo,record_status)
                VALUES ('bad-direct','x','current','2026-01-01T00:00:00Z',?,?,?)''', values)
    current = repo.save_model_version(model_version="good", model_type="x", status="current")
    repo.save_model_version(model_version="bad", model_type="x", status="candidate", **bad)
    with pytest.raises(sqlite3.IntegrityError, match="current model"):
        with repo.transaction():
            repo.connection.execute("UPDATE model_versions SET status='archived' WHERE model_version='good'")
            repo.connection.execute("UPDATE model_versions SET status='current' WHERE model_version='bad'")
    assert repo.get_current_model() == current


@pytest.mark.parametrize("assignments", ["source_type='DEMO',is_demo=1", "is_demo=1", "record_status='INVALID'"])
def test_current_metadata_update_cannot_evade_guard(repo, assignments):
    current = repo.save_model_version(model_version="good", model_type="x", status="current")
    with pytest.raises(sqlite3.IntegrityError, match="current model"):
        with repo.transaction():
            repo.connection.execute(f"UPDATE model_versions SET {assignments} WHERE model_version='good'")
    assert repo.get_current_model() == current


def test_unvalidated_non_demo_model_remains_allowed_for_compatibility(repo):
    repo.save_model_version(model_version="old", model_type="x", status="current")
    candidate = repo.save_model_version(model_version="new", model_type="x")
    assert candidate["record_status"] == "UNVALIDATED"
    assert repo.set_current_model("new")["model_version"] == "new"


def inventory(repo, **changes):
    return repo.save_inventory_snapshot({"site_id": "s", "snapshot_date": "2026-01-01",
        "ingredient_name": "Rice", "quantity": 1, "unit": "kg", **changes})


@pytest.mark.parametrize("source,canonical", [("DEMO", "MODEL"), (" demo ", "MODEL"),
    ("MODEL", "DEMO"), ("PUBLIC_API", "USER_UPLOAD"), ("UNKNOWN", "MODEL")])
def test_inventory_source_contradiction_repository_and_sql(repo, source, canonical):
    with pytest.raises(ValidationError, match="contradiction"):
        inventory(repo, source=source, source_type=canonical)
    with pytest.raises(sqlite3.IntegrityError, match="contradiction"):
        with repo.transaction():
            repo.connection.execute('''INSERT INTO inventory_snapshots
                (inventory_id,site_id,snapshot_date,ingredient_name,quantity,unit,created_at,source,source_type,is_demo)
                VALUES ('raw','s','2026-01-01','Rice',1,'kg','2026-01-01T00:00:00Z',?,?,?)''',
                (source, canonical, int(canonical == "DEMO")))


@pytest.mark.parametrize("code", ["UNKNOWN", "MODEL", "DEMO", "USER_UPLOAD", "PUBLIC_API", "MANUAL", "AGENT"])
def test_inventory_legacy_reserved_source_infers_canonical(repo, code):
    row = inventory(repo, source=" " + code.lower() + " ")
    assert row["source"] == row["source_type"] == code
    assert row["is_demo"] == int(code == "DEMO")
    assert row["record_status"] == "UNVALIDATED"


def test_inventory_source_free_text_label_and_null_still_supported(repo):
    row = inventory(repo, source="warehouse A / feed-v2", source_type="PUBLIC_API")
    assert row["source"] == "warehouse A / feed-v2" and row["source_type"] == "PUBLIC_API"
    assert inventory(repo, source=None)["source_type"] == "UNKNOWN"
    row = inventory(repo, source="warehouse A")
    assert row["source_type"] == "UNKNOWN"


@pytest.mark.parametrize("assignment", ["source='DEMO'", "source_type='MODEL'"])
def test_inventory_update_guard(repo, assignment):
    item = inventory(repo, source="PUBLIC_API", source_type="PUBLIC_API")
    with pytest.raises(sqlite3.IntegrityError, match="contradiction"):
        with repo.transaction():
            repo.connection.execute(f"UPDATE inventory_snapshots SET {assignment}")
    assert repo.get_inventory_by_site("s") == [item]


def test_public_exports_and_safe_defaults():
    assert lastplate_db.__version__ == "0.3.0"
    for name in lastplate_db.__all__:
        assert hasattr(lastplate_db, name)
    assert inspect.signature(get_site_kpis).parameters["eligible_only"].default is True
    assert inspect.signature(get_retraining_readiness).parameters["legacy_all_rows"].default is False
