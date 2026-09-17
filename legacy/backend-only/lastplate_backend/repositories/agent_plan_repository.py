"""Append-only records of native agent responses in a backend-owned table."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class AgentPlanRepository:
    def __init__(self, database_path):
        self.database_path = Path(database_path)

    def connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        return connection

    def initialize(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS agent_plan_snapshots (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    site_id TEXT NOT NULL, target_date TEXT NOT NULL, request_id TEXT NOT NULL,
                    upstream_url TEXT NOT NULL, upstream_http_status INTEGER NOT NULL,
                    request_json TEXT NOT NULL, result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_slot
                    ON agent_plan_snapshots(site_id, target_date, created_at DESC);
            ''')
            connection.commit()

    def save(self, payload, status, result, upstream_url):
        record_id = str(uuid4())
        with closing(self.connect()) as connection:
            connection.execute('INSERT INTO agent_plan_snapshots VALUES (?,?,?,?,?,?,?,?,?)', (
                record_id, datetime.now(timezone.utc).isoformat(), payload['site_id'],
                payload['target_date'], payload['request_id'], upstream_url, status,
                json.dumps(payload, ensure_ascii=False, allow_nan=False),
                json.dumps(result, ensure_ascii=False, allow_nan=False)))
            connection.commit()
        return record_id

    @staticmethod
    def unpack(row):
        if row is None:
            return None
        result = dict(row)
        result['request'] = json.loads(result.pop('request_json'))
        result['result'] = json.loads(result.pop('result_json'))
        return result

    def get(self, record_id):
        with closing(self.connect()) as connection:
            row = connection.execute('SELECT * FROM agent_plan_snapshots WHERE id=?', (record_id,)).fetchone()
        return self.unpack(row)

    def latest(self, site_id, target_date):
        with closing(self.connect()) as connection:
            row = connection.execute('''SELECT * FROM agent_plan_snapshots
                WHERE site_id=? AND target_date=? ORDER BY created_at DESC, rowid DESC LIMIT 1''',
                (site_id, target_date)).fetchone()
        return self.unpack(row)
