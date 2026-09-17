"""Small dependency-free runtime configuration layer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    database_path: Path
    cors_origins: list[str]


@lru_cache
def get_settings() -> Settings:
    backend_root = Path(__file__).resolve().parents[2]
    default_db = backend_root / "data" / "lastplate.db"
    configured_db = os.getenv("LASTPLATE_DATABASE_PATH")
    configured_origins = os.getenv("LASTPLATE_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    return Settings(
        app_name="LastPlate Operation API",
        app_version="0.1.0",
        database_path=Path(configured_db) if configured_db else default_db,
        cors_origins=origins,
    )
