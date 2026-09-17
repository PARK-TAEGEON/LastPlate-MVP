import contextlib
import hashlib
import json
import sqlite3
from filelock import FileLock
from .errors import StorageError

def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS predictions (
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 target_date TEXT NOT NULL, created_at TEXT NOT NULL, deadline_at TEXT NOT NULL,
 mode TEXT NOT NULL, model_version TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actuals (
 prediction_id TEXT PRIMARY KEY REFERENCES predictions(id), target_date TEXT NOT NULL UNIQUE,
 revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actual_events (
 request_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, prediction_id TEXT NOT NULL,
 revision INTEGER NOT NULL, payload TEXT NOT NULL, previous_payload TEXT,
 recorded_at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS weather (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL);
'''

class ServiceStore:
    def __init__(self,config):
        self.path=config.database
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with FileLock(str(self.path)+'.init.lock'):
            with self.connection() as db:
                if db.execute('PRAGMA journal_mode').fetchone()[0]!='wal':
                    db.execute('PRAGMA journal_mode=WAL')
                db.executescript(SCHEMA)

    @contextlib.contextmanager
    def connection(self,write=False):
        db=None
        try:
            db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except sqlite3.Error as exc:
            if db is not None and db.in_transaction:
                db.rollback()
            raise StorageError(f'SQLite operation failed: {type(exc).__name__}') from exc
        except BaseException:
            if db is not None and db.in_transaction:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()
