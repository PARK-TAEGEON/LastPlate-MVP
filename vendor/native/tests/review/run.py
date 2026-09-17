import subprocess,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/p1-v012/previous-invariants'
for name in ('probe_review','followup_review','final_checks'):
    proc=subprocess.run([sys.executable,str(ROOT/'tests/review'/(name+'.py'))],capture_output=True,text=True,encoding='utf8',env={**os.environ,'PYTHONUTF8':'1'})
    (OUT/(name+'.txt')).write_text(proc.stdout+'\n'+proc.stderr,encoding='utf8')
    print(name,proc.returncode,flush=True)
    if proc.returncode:sys.exit(proc.returncode)
proc=subprocess.run([sys.executable,'-m','pytest','-q','tests/review/test_review_findings.py','--junitxml='+str(OUT/'review-invariants.xml')],cwd=ROOT,capture_output=True,text=True,encoding='utf8',env={**os.environ,'PYTHONUTF8':'1'})
(OUT/'review-invariants.txt').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf8')
print(proc.stdout);sys.exit(proc.returncode)
