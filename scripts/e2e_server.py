"""Test-only server runner with a stdin shutdown channel and identity probe."""
import os,sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
import sqlite3
from backend.main import create_app
from backend.adapters.persistence import Persistence

app=create_app()
@app.get('/__e2e_identity')
def identity():return {'pid':os.getpid(),'token':os.environ['LASTPLATE_E2E_TOKEN']}

# Fault injection exists only in this test runner, never in run.py / production app.
_save_run=Persistence.save_run
_fail_next=False
def maybe_fail(self,*args,**kwargs):
    global _fail_next
    if _fail_next:
        _fail_next=False
        raise sqlite3.OperationalError('E2E forced save failure')
    return _save_run(self,*args,**kwargs)
Persistence.save_run=maybe_fail
@app.post('/__e2e_fail_next_save')
def fail_next():
    global _fail_next
    _fail_next=True
    return {'armed':True}

server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=int(sys.argv[1]),log_level='info'))
def shutdown_reader():
    sys.stdin.readline()
    server.should_exit=True
threading.Thread(target=shutdown_reader,daemon=True).start()
server.run()
