import sqlite3
from pathlib import Path

import pytest

from lastplate_db import Repository, MigrationError, migrate, get_retraining_readiness, get_site_kpis
from lastplate_db.connection import connect


def old_database(path, version=2):
    with sqlite3.connect(path) as c:
        c.executescript((Path(__file__).parent / f"fixtures/v{version}.sql").read_text(encoding="utf-8"))
        c.execute("INSERT INTO sites(site_id,site_name,created_at) VALUES ('s','Legacy','2026-01-01T00:00:00.000000+00:00')")


def old_inventory(c, inventory_id, source, source_type="UNKNOWN"):
    c.execute('''INSERT INTO inventory_snapshots
        (inventory_id,site_id,snapshot_date,ingredient_name,quantity,unit,created_at,source,source_type,is_demo)
        VALUES (?,'s','2026-01-01','Rice',1,'kg','2026-01-01T00:00:00.000000+00:00',?,?,?)''',
        (inventory_id, source, source_type, int(source_type == "DEMO")))


def test_v2_migration_preserves_safe_data_backfills_reserved_source_and_installs_guards(tmp_path):
    path = tmp_path / "v2.db"
    old_database(path)
    with sqlite3.connect(path) as c:
        old_inventory(c, "demo", "DEMO")
        old_inventory(c, "api", " public_api ")
        old_inventory(c, "label", "Warehouse A")
        c.execute("INSERT INTO model_versions(model_version,model_type,status,created_at) VALUES ('old','x','current','2026-01-01T00:00:00.000000+00:00')")
        c.execute("INSERT INTO actual_results(result_id,site_id,target_date,actual_diners,created_at) VALUES ('a','s','2026-01-01',95,'2026-01-01T12:00:00.000000+00:00')")
    with Repository(path) as r:
        assert r.connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert r.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not r.connection.execute("PRAGMA foreign_key_check").fetchall()
        assert r.get_current_model()["model_version"] == "old"
        items = {i["inventory_id"]: i for i in r.get_inventory_by_site("s")}
        assert items["demo"]["source_type"] == "DEMO" and items["demo"]["is_demo"] == 1
        assert items["api"]["source_type"] == "PUBLIC_API" and items["api"]["source"] == " public_api "
        assert items["label"]["source_type"] == "UNKNOWN"
        assert all(i["record_status"] == "UNVALIDATED" for i in items.values())
        assert get_retraining_readiness(r, "s", 1)["ready"] is False
        assert get_retraining_readiness(r, "s", 1, legacy_all_rows=True)["ready"] is True
        assert all(v is None for v in get_site_kpis(r, "s").values())
        assert get_site_kpis(r, "s", eligible_only=False)["shortage_rate"] == 0
        triggers = r.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'guard_%'").fetchall()
        assert len(triggers) == 4
        with pytest.raises(sqlite3.IntegrityError, match="current model"):
            with r.transaction():
                r.connection.execute("UPDATE model_versions SET record_status='INVALID'")
        with pytest.raises(sqlite3.IntegrityError, match="contradiction"):
            with r.transaction():
                r.connection.execute("UPDATE inventory_snapshots SET source_type='MODEL' WHERE inventory_id='api'")
    with Repository(path) as r:
        assert r.connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert len(r.get_inventory_by_site("s")) == 3


@pytest.mark.parametrize("source,is_demo,status", [("DEMO", 1, "VALIDATED"), ("MODEL", 1, "VALIDATED"), ("MODEL", 0, "INVALID")])
def test_unsafe_v2_current_migration_fails_atomically_and_can_retry(tmp_path, source, is_demo, status):
    path = tmp_path / "bad-current.db"
    old_database(path)
    with sqlite3.connect(path) as c:
        c.execute('''INSERT INTO model_versions(model_version,model_type,status,created_at,source_type,is_demo,record_status)
            VALUES ('bad','x','current','2026-01-01T00:00:00Z',?,?,?)''', (source, is_demo, status))
        old_inventory(c, "untouched", "DEMO")
    c = connect(path)
    try:
        with pytest.raises(MigrationError, match="Unsafe current model.*bad"):
            migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("SELECT status FROM model_versions").fetchone()[0] == "current"
        assert c.execute("SELECT source_type FROM inventory_snapshots").fetchone()[0] == "UNKNOWN"
        assert not c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'guard_%'").fetchall()
        with c:
            c.execute("UPDATE model_versions SET status='archived'")
        migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 5
    finally:
        c.close()


def test_inventory_conflict_migration_rolls_back_earlier_backfill(tmp_path):
    path = tmp_path / "conflict.db"
    old_database(path)
    with sqlite3.connect(path) as c:
        old_inventory(c, "would-backfill", "DEMO")
        old_inventory(c, "conflict", "DEMO", "MODEL")
    c = connect(path)
    try:
        with pytest.raises(MigrationError, match="Conflicting inventory source.*conflict"):
            migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
        row = c.execute("SELECT source_type,is_demo FROM inventory_snapshots WHERE inventory_id='would-backfill'").fetchone()
        assert tuple(row) == ("UNKNOWN", 0)
        assert not c.in_transaction
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        c.close()


def test_v1_direct_to_v3_migrates_demo_inventory_without_approving_it(tmp_path):
    path = tmp_path / "v1.db"
    old_database(path, version=1)
    with sqlite3.connect(path) as c:
        c.execute('''INSERT INTO inventory_snapshots(inventory_id,site_id,snapshot_date,ingredient_name,quantity,unit,created_at,source)
            VALUES ('i','s','2026-01-01','Rice',1,'kg','2026-01-01T00:00:00Z','DEMO')''')
    with Repository(path) as r:
        row = r.get_inventory_by_site("s")[0]
        assert row["source_type"] == "DEMO" and row["is_demo"] == 1
        assert row["record_status"] == "UNVALIDATED"
        assert r.connection.execute("PRAGMA user_version").fetchone()[0] == 5
