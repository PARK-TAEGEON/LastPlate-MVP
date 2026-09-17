import os
import sqlite3
from pathlib import Path


def connect(path=None):
    """Explicit path > LASTPLATE_DB_PATH > cwd/data/lastplate.db."""
    path = os.fspath(path if path is not None else os.environ.get("LASTPLATE_DB_PATH", "data/lastplate.db"))
    if path != ":memory:":
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        path = str(Path(path).expanduser())
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
