import sqlite3
from pathlib import Path

import pytest

from lastplate_db import Repository, MigrationError, migrate, get_training_dataset
from lastplate_db.connection import connect


def v3(path):
    with sqlite3.connect(path) as c:
        c.executescript((Path(__file__).parent / "fixtures/v3.sql").read_text(encoding="utf-8"))
        c.execute("INSERT INTO sites(site_id,site_name,created_at) VALUES ('s','Old','2026-01-01T00:00:00.000000+00:00')")
        c.execute("INSERT INTO model_versions(model_version,model_type,status,created_at) VALUES ('global','x','current','2026-01-01T00:00:00.000000+00:00')")
        c.execute('''INSERT INTO predictions(prediction_id,site_id,target_date,predicted_diners,created_at,record_status,input_snapshot_json)
            VALUES ('p','s','2026-01-01',100,'2026-01-01T01:00:00.000000+00:00','VALIDATED','{"population":200}')''')
        c.execute('''INSERT INTO actual_results(result_id,site_id,target_date,actual_diners,created_at,record_status)
            VALUES ('a','s','2026-01-01',95,'2026-01-01T12:00:00.000000+00:00','VALIDATED')''')


def test_v3_v4_preserves_rows_adds_contracts_without_inventing_history(tmp_path):
    path = tmp_path / "v3.db"
    v3(path)
    with Repository(path) as r:
        assert r.connection.execute("PRAGMA user_version").fetchone()[0] == 5
        p = r.get_prediction("p")
        assert p["input_snapshot_json"] == {"population": 200}
        for field in ("feature_schema_version", "observed_at", "source_lineage_id", "snapshot_validation_json"):
            assert p[field] is None
        assert r.get_current_model()["model_version"] == "global"
        assert r.get_current_deployment("s") is None
        assert r.list_feature_schemas() == []
        assert r.list_model_deployments() == []
        assert r.get_actual_corrections("s", "2026-01-01") == []
        assert get_training_dataset(r)["rejected_count"] == 1
        assert not r.connection.execute("PRAGMA foreign_key_check").fetchall()
        r.update_actual_result("s", "2026-01-01", actual_diners=96)
        assert r.get_actual_corrections("s", "2026-01-01")[0]["old_values_json"]["actual_diners"] == 95
    # Capture direct SQL corrections from an independent connection without Python UDFs.
    with sqlite3.connect(path) as c:
        c.execute("UPDATE actual_results SET actual_diners=97 WHERE result_id='a'")
    with Repository(path) as r:
        assert len(r.get_actual_corrections("s", "2026-01-01")) == 2
        assert r.get_actual_corrections("s", "2026-01-01")[-1]["actor"] == "UNKNOWN_RAW_SQL"
        assert r.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v3_migration_late_failure_rolls_back_columns_tables_and_triggers(tmp_path):
    path = tmp_path / "orphan.db"
    v3(path)
    with sqlite3.connect(path) as c:
        c.execute("UPDATE predictions SET site_id='missing'")
    c = connect(path)
    try:
        with pytest.raises(MigrationError, match="Foreign key"):
            migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='model_deployments'").fetchall()
        assert "feature_schema_version" not in {row[1] for row in c.execute("PRAGMA table_info(predictions)")}
        assert c.execute("SELECT actual_diners FROM actual_results").fetchone()[0] == 95
        with c:
            c.execute("UPDATE predictions SET site_id='s'")
        migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 5
    finally:
        c.close()


def test_v3_reserved_name_collision_is_not_silently_adopted(tmp_path):
    path = tmp_path / "collision.db"
    v3(path)
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE feature_schemas(custom TEXT)")
    with pytest.raises(MigrationError, match="Reserved v4"):
        Repository(path)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
        assert "feature_schema_version" not in {row[1] for row in c.execute("PRAGMA table_info(predictions)")}
