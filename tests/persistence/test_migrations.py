import sqlite3
from pathlib import Path

import pytest

from lastplate_db import Repository, get_learning_dataset
from lastplate_db.connection import connect
from lastplate_db.migrations import MigrationError, migrate
from lastplate_db.schema import TABLES


def make_v1(path, *, invalid=False):
    with sqlite3.connect(path) as c:
        c.executescript((Path(__file__).parent / "fixtures/v1.sql").read_text(encoding="utf-8"))
        records = {
            "sites": dict(site_id="s", site_name="Legacy", created_at="2026-01-01T00:00:00.000000+00:00"),
            "predictions": dict(prediction_id="p", site_id="s", target_date="2026-01-01", predicted_diners=200 if invalid else 100,
                lower_bound=90, upper_bound=110, input_snapshot_json='{"x": 1}', request_id="old-request", created_at="2026-01-01T01:00:00.000000+00:00"),
            "operation_plans": dict(plan_id="op", prediction_id="p", site_id="s", target_date="2026-01-01",
                recommended_servings=110, created_at="2026-01-01T02:00:00.000000+00:00"),
            "actual_results": dict(result_id="a", site_id="s", target_date="2026-01-01", actual_diners=95,
                created_at="2026-01-01T10:00:00.000000+00:00"),
            "inventory_snapshots": dict(inventory_id="i", site_id="s", snapshot_date="2026-01-01",
                ingredient_name="Rice", quantity=1, unit="kg", created_at="2026-01-01T00:00:00.000000+00:00"),
            "model_versions": dict(model_version="v", model_type="xgb", created_at="2026-01-01T00:00:00.000000+00:00"),
            "decision_logs": dict(decision_id="d", site_id="s", target_date="2026-01-01", created_at="2026-01-01T03:00:00.000000+00:00"),
        }
        for table, row in records.items():
            c.execute(f"INSERT INTO {table}({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
        c.execute("CREATE INDEX custom_prediction_index ON predictions(model_version)")
        c.execute("CREATE TRIGGER custom_prediction_trigger BEFORE UPDATE ON predictions WHEN NEW.predicted_diners=999 BEGIN SELECT RAISE(ABORT,'custom'); END")
    return records


def test_v1_backfill_preserves_all_records_foreign_keys_and_objects(tmp_path):
    path = tmp_path / "v1.db"
    originals = make_v1(path)
    with Repository(path) as r:
        assert r.connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert r.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not r.connection.execute("PRAGMA foreign_key_check").fetchall()
        for table in TABLES:
            row = dict(r.connection.execute(f"SELECT * FROM {table}").fetchone())
            assert (row["source_type"], row["is_demo"], row["record_status"]) == ("UNKNOWN", 0, "UNVALIDATED")
            for name, value in originals[table].items():
                assert row[name] == value
        assert r.get_operation_plan("op")["idempotency_key"] is None
        assert get_learning_dataset(r) == []
        rows = get_learning_dataset(r, include_unvalidated=True)
        assert len(rows) == 1 and rows[0]["plan_id"] == "op"
        assert rows[0]["input_snapshot_json"] == {"x": 1}
        for name in ("custom_prediction_index", "custom_prediction_trigger"):
            assert r.connection.execute("SELECT name FROM sqlite_master WHERE name=?", (name,)).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            with r.transaction():
                r.connection.execute("UPDATE predictions SET predicted_diners=111")
        with pytest.raises(sqlite3.IntegrityError):
            r.save_prediction(site_id="missing", target_date="2026-01-01", predicted_diners=1)
        r.save_operation_plan(site_id="s", prediction_id="p", target_date="2026-01-01", recommended_servings=110, idempotency_key="k")
        with pytest.raises(sqlite3.IntegrityError):
            r.save_operation_plan(site_id="s", prediction_id="p", target_date="2026-01-01", recommended_servings=110, idempotency_key="k")
    with Repository(path) as r:
        assert r.connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert len(r.get_predictions_by_site("s")) == 1


def test_bad_interval_migration_fails_without_mutation(tmp_path):
    path = tmp_path / "bad-v1.db"
    make_v1(path, invalid=True)
    c = connect(path)
    try:
        with pytest.raises(MigrationError, match="Out-of-interval.*p"):
            migrate(c)
        assert not c.in_transaction
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "source_type" not in {row[1] for row in c.execute("PRAGMA table_info(predictions)")}
        assert c.execute("SELECT predicted_diners FROM predictions").fetchone()[0] == 200
        with c:
            c.execute("UPDATE predictions SET predicted_diners=100")
        migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 5
    finally:
        c.close()


def test_late_fk_failure_rolls_back_ddl_and_backfill(tmp_path):
    path = tmp_path / "orphan-v1.db"
    make_v1(path)
    with sqlite3.connect(path) as c:
        c.execute("UPDATE operation_plans SET prediction_id='missing'")
    c = connect(path)
    try:
        with pytest.raises(MigrationError, match="Foreign key"):
            migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert "source_type" not in {row[1] for row in c.execute("PRAGMA table_info(actual_results)")}
        assert c.execute("SELECT prediction_id FROM predictions").fetchone()[0] == "p"
    finally:
        c.close()


def test_migration_refuses_unversioned_nonempty_and_active_transaction(tmp_path):
    c = connect(tmp_path / "unknown.db")
    try:
        c.execute("CREATE TABLE unrelated(id INTEGER)")
        with pytest.raises(MigrationError, match="Unversioned"):
            migrate(c)
        c.execute("BEGIN")
        with pytest.raises(MigrationError, match="active transaction"):
            migrate(c)
        c.rollback()
    finally:
        c.close()


def test_migration_preserves_rowid_tie_order(tmp_path):
    path = tmp_path / "ties.db"
    make_v1(path)
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO predictions(prediction_id,site_id,target_date,predicted_diners,created_at) SELECT 'p2',site_id,target_date,101,created_at FROM predictions")
    with Repository(path) as r:
        assert get_learning_dataset(r, include_unvalidated=True)[0]["prediction_id"] == "p2"
