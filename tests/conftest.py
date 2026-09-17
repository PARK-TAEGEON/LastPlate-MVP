"""Make the reused persistence suite's subprocess imports portable after relocation."""
import os
from pathlib import Path

root=str(Path(__file__).resolve().parents[1])
os.environ['PYTHONPATH']=root+(os.pathsep+os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
