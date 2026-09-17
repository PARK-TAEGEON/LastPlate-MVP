import os
from dataclasses import dataclass
from pathlib import Path
from backend.bootstrap import ROOT


@dataclass(frozen=True)
class Settings:
    database: Path
    mode: str = 'demo'
    stage_timeout: float = 120
    debug_enabled: bool = False
    debug_token: str = ''

    @classmethod
    def from_env(cls):
        return cls(Path(os.environ.get('LASTPLATE_DB_PATH', ROOT/'data/lastplate.db')).resolve(),
                   os.environ.get('LASTPLATE_MODE', 'demo'),
                   float(os.environ.get('LASTPLATE_STAGE_TIMEOUT', '120')),
                   os.environ.get('LASTPLATE_DEBUG','').lower()=='true',
                   os.environ.get('LASTPLATE_DEBUG_TOKEN',''))
