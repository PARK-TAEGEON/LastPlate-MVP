"""Only the integration package is imported here; agents stay in native workers."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'vendor/native'
if str(NATIVE) not in sys.path:
    sys.path.insert(0, str(NATIVE))
