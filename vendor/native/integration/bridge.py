"""Process isolation prevents legacy tools/adapters/config module collisions."""
import json, subprocess, sys, os
from .contracts import ROOT
from .errors import StageError

def invoke(stage, payload, timeout=120):
    try:
        p=subprocess.run([sys.executable,str(ROOT/'integration/worker.py'),stage],
            cwd=ROOT/stage,input=json.dumps(payload,ensure_ascii=False,allow_nan=False),
            capture_output=True,text=True,encoding='utf-8',timeout=timeout,
            env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
    except subprocess.TimeoutExpired as e:
        raise StageError(stage,'STAGE_TIMEOUT',f'{stage} exceeded {timeout}s') from e
    if p.returncode:
        raise StageError(stage,'WORKER_FAILED',p.stderr[-2000:])
    try:
        response=json.loads(p.stdout)
    except ValueError as e:
        raise StageError(stage,'INVALID_WORKER_RESPONSE',p.stdout[-500:]) from e
    if response.get('error'):
        e=response['error']
        raise StageError(stage,e['code'],e['message'],e.get('http_status',500))
    return response['result']
