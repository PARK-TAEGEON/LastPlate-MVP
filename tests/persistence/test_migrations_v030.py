import sqlite3
from pathlib import Path

import pytest

from lastplate_db import Repository, MigrationError, migrate
from lastplate_db.connection import connect


def v4(path):
    with sqlite3.connect(path) as c:
        c.executescript((Path(__file__).parent/"fixtures/v4.sql").read_text(encoding="utf-8"))
        c.execute("INSERT INTO sites(site_id,site_name,created_at) VALUES ('s','Site','2026-01-01T00:00:00.000000+00:00')")
        c.execute("INSERT INTO model_versions(model_version,model_type,record_status,created_at) VALUES ('m','x','VALIDATED','2026-01-01T00:00:00.000000+00:00')")
        c.execute("INSERT INTO feature_schemas VALUES ('old','{\"x\":\"number\"}',NULL,'2026-01-01T00:00:00.000000+00:00')")
        c.execute('''INSERT INTO model_deployments(deployment_id,site_id,model_version,model_role,status,effective_at,created_at,actor,reason,source_type,is_demo,record_status)
            VALUES ('d','s','m','demand','current','2026-01-01T00:00:00.000000+00:00','2026-01-01T00:00:00.000000+00:00','offline','release','MANUAL',0,'VALIDATED')''')


def test_v4_v5_preserves_old_contracts_and_deployments(tmp_path):
    path = tmp_path/"v4.db"
    v4(path)
    with Repository(path) as r:
        assert r.connection.execute("PRAGMA user_version").fetchone()[0] == 5
        schema = r.get_feature_schema("old")
        assert schema["required_features_json"] == {"x":"number"}
        assert schema["rule_language_version"] is None and schema["rules_json"] is None
        d = r.get_current_deployment("s")
        assert d["deployment_id"] == "d" and d["actor"] == "offline"
        assert d["training_run_id"] is None and d["training_data_cutoff"] is None
        assert r.list_training_runs() == []
        assert not r.connection.execute("PRAGMA foreign_key_check").fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            with r.transaction():
                r.connection.execute("UPDATE feature_schemas SET description='rewrite'")
    with Repository(path) as r:
        assert r.get_current_deployment("s")["training_run_id"] is None


def test_v4_v5_late_fk_failure_rolls_back_new_columns_and_objects(tmp_path):
    path = tmp_path/"orphan.db"
    v4(path)
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO predictions(prediction_id,site_id,target_date,predicted_diners,created_at) VALUES ('p','absent','2026-01-01',1,'2026-01-01T00:00:00Z')")
    c = connect(path)
    try:
        with pytest.raises(MigrationError,match="Foreign key"):
            migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert "rules_json" not in {row[1] for row in c.execute("PRAGMA table_info(feature_schemas)")}
        assert "training_run_id" not in {row[1] for row in c.execute("PRAGMA table_info(model_deployments)")}
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='training_runs'").fetchall()
        with c:
            c.execute("UPDATE predictions SET site_id='s'")
        migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 5
    finally:
        c.close()


def test_v5_reserved_name_collision_is_rejected(tmp_path):
    path = tmp_path/"collision.db"
    v4(path)
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE training_runs(custom TEXT)")
    with pytest.raises(MigrationError,match="Reserved v5"):
        Repository(path)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
