import sqlite3
import pytest
from lastplate_db import Repository
from lastplate_db.schema import TABLES


def test_schema(repo):
    names = {r[0] for r in repo.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLES) <= names
    assert repo.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert repo.connection.execute("PRAGMA user_version").fetchone()[0] == 5


def test_foreign_key(repo):
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_prediction(site_id="missing", target_date="2026-01-01", predicted_diners=1)


def test_plan_identity(repo, prediction):
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_operation_plan(site_id="s", prediction_id=prediction["prediction_id"],
                                 target_date="2026-01-02", recommended_servings=1)


def test_missing_prediction(repo):
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_operation_plan(site_id="s", prediction_id="missing", target_date="2026-01-01", recommended_servings=1)


def test_reopen(tmp_path):
    path = tmp_path / "persist.db"
    with Repository(path) as r:
        r.create_site(site_id="persist", site_name="Persistent")
    with Repository(path) as r:
        assert r.get_site("persist")["site_name"] == "Persistent"


def test_env_path(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "env.db"
    monkeypatch.setenv("LASTPLATE_DB_PATH", str(path))
    with Repository() as r:
        assert r.list_sites() == []
    assert path.is_file()


def test_raw_negative_constraint(repo):
    with pytest.raises(sqlite3.IntegrityError):
        with repo.connection:
            repo.connection.execute("UPDATE sites SET meal_capacity=-1 WHERE site_id='s'")


def test_future_schema(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError):
        Repository(path)
