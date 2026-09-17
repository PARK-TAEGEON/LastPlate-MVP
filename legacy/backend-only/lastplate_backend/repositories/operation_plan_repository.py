"""SQLite persistence for immutable operation-plan snapshots."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from datetime import datetime, timezone


class RevisionConflict(ValueError):
    """A client attempted to modify an outdated or non-reviewable snapshot."""


class OperationPlanRepository:
    """Store input/output snapshots so UI can show a before/after event history."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        # sqlite3's connection context manager commits/rolls back but does not
        # close the Windows file handle.  ``closing`` is important for tests and
        # for allowing a later process to move or back up the database file.
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operation_plans (
                    id TEXT PRIMARY KEY,
                    parent_plan_id TEXT NULL,
                    site_id TEXT NOT NULL,
                    meal_date TEXT NOT NULL,
                    meal_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    FOREIGN KEY(parent_plan_id) REFERENCES operation_plans(id)
                );
                CREATE INDEX IF NOT EXISTS idx_operation_plans_parent
                    ON operation_plans(parent_plan_id);
                CREATE INDEX IF NOT EXISTS idx_operation_plans_site_created
                    ON operation_plans(site_id, created_at DESC);
                """
            )
            # Keep the MVP database forward-compatible when a developer starts
            # an older local DB before pulling this code revision.
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(operation_plans)").fetchall()
            }
            if "meal_date" not in columns:
                connection.execute(
                    "ALTER TABLE operation_plans ADD COLUMN meal_date TEXT NOT NULL DEFAULT ''"
                )
            if "meal_type" not in columns:
                connection.execute(
                    "ALTER TABLE operation_plans ADD COLUMN meal_type TEXT NOT NULL DEFAULT 'lunch'"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_operation_plans_calendar_slot
                ON operation_plans(site_id, meal_date, meal_type, created_at DESC)
                """
            )
            connection.commit()

    def save(
        self,
        *,
        plan_id: str,
        parent_plan_id: str | None,
        site_id: str,
        meal_date: str,
        meal_type: str,
        created_at: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if parent_plan_id is not None:
                self._require_leaf(connection, parent_plan_id)
            connection.execute(
                """
                INSERT INTO operation_plans (
                    id, parent_plan_id, site_id, meal_date, meal_type, created_at, request_json, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    parent_plan_id,
                    site_id,
                    meal_date,
                    meal_type,
                    created_at,
                    json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            connection.commit()

    @staticmethod
    def _require_leaf(connection, plan_id):
        row = connection.execute("SELECT * FROM operation_plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            raise RevisionConflict("운영안을 찾을 수 없습니다.")
        if connection.execute("SELECT 1 FROM operation_plans WHERE parent_plan_id = ?", (plan_id,)).fetchone():
            raise RevisionConflict("이미 변경된 운영안입니다. 최신 운영안을 불러온 뒤 다시 시도하세요.")
        return row

    def review(self, plan_id):
        self.initialize()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM operation_plans WHERE id = ?", (plan_id,)).fetchone():
                return None
            row = self._require_leaf(connection, plan_id)
            response = json.loads(row['response_json'])
            if not response.get('review_allowed'):
                raise RevisionConflict("용량·납기·안전여유·운영 기준 경고를 해결한 후 검토 완료하세요.")
            if response.get('review_status') != 'reviewed_demo':
                response['review_status'] = 'reviewed_demo'
                response['reviewed_at'] = datetime.now(timezone.utc).isoformat()
                connection.execute("UPDATE operation_plans SET response_json = ? WHERE id = ?",
                                   (json.dumps(response, ensure_ascii=False), plan_id))
            connection.commit()
        return self.get(plan_id)

    def get(self, plan_id: str) -> dict[str, Any] | None:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, parent_plan_id, site_id, meal_date, meal_type, created_at, request_json, response_json
                FROM operation_plans
                WHERE id = ?
                """,
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "parent_plan_id": row["parent_plan_id"],
            "site_id": row["site_id"],
            "meal_date": row["meal_date"],
            "meal_type": row["meal_type"],
            "created_at": row["created_at"],
            "request": json.loads(row["request_json"]),
            "response": json.loads(row["response_json"]),
        }

    def get_latest(self, *, site_id: str, meal_date: str, meal_type: str) -> dict[str, Any] | None:
        """Return the most recent immutable revision for one calendar slot."""
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, parent_plan_id, site_id, meal_date, meal_type, created_at, request_json, response_json
                FROM operation_plans
                WHERE site_id = ? AND meal_date = ? AND meal_type = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (site_id, meal_date, meal_type),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "parent_plan_id": row["parent_plan_id"],
            "site_id": row["site_id"],
            "meal_date": row["meal_date"],
            "meal_type": row["meal_type"],
            "created_at": row["created_at"],
            "request": json.loads(row["request_json"]),
            "response": json.loads(row["response_json"]),
        }
