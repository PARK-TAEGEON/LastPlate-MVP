"""Backend settings are independent from the agent service's model/store settings."""
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    database_path: Path
    cors_origins: list[str]
    agent_base_url: str | None
    agent_timeout_seconds: float


@lru_cache
def get_settings() -> Settings:
    backend_root = Path(__file__).resolve().parents[2]
    database = os.getenv('LASTPLATE_BACKEND_DATABASE_PATH') or os.getenv('LASTPLATE_DATABASE_PATH')
    url = os.getenv('LASTPLATE_AGENT_BASE_URL', '').strip().rstrip('/') or None
    if url:
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('LASTPLATE_AGENT_BASE_URL must be an HTTP(S) base URL without credentials, query or fragment')
    timeout = float(os.getenv('LASTPLATE_AGENT_TIMEOUT_SECONDS', '600'))
    if not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise ValueError('LASTPLATE_AGENT_TIMEOUT_SECONDS must be between 1 and 3600')
    return Settings(
        app_name='LastPlate Backend', app_version='0.2.0',
        database_path=Path(database) if database else backend_root / 'data' / 'backend.sqlite3',
        cors_origins=[x.strip() for x in os.getenv('LASTPLATE_CORS_ORIGINS',
            'http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173').split(',') if x.strip()],
        agent_base_url=url, agent_timeout_seconds=timeout,
    )
