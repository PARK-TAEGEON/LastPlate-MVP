"""Run upstream suites independently, preserving legacy import boundaries."""
import subprocess,sys,os,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
results=[]
for name in ('demand','operation','inventory_risk','decision'):
    start=time.perf_counter()
    process=subprocess.run([sys.executable,'-m','pytest','-q','tests'],cwd=ROOT/name,
        capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'})
    (ROOT/'reports'/('regression-'+name+'.txt')).write_text(process.stdout+'\n'+process.stderr,encoding='utf-8')
    results.append(dict(module=name,exit_code=process.returncode,seconds=round(time.perf_counter()-start,3)))
print(json.dumps(results,indent=2))
sys.exit(1 if any(r['exit_code'] for r in results) else 0)
