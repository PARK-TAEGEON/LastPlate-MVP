"""Separate processes keep the original Agent test namespaces isolated."""
from pathlib import Path
import argparse, subprocess, sys, json, os, shutil
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SUITES={
    'legacy-backend':(ROOT/'legacy/backend-only',[]),
    'legacy-ui-integration':(ROOT/'legacy/integrated/backend',[]),
    'demand':(ROOT/'vendor/native/demand',[]),
    'operation':(ROOT/'vendor/native/operation',[]),
    'inventory-risk':(ROOT/'vendor/native/inventory_risk',[]),
    'decision':(ROOT/'vendor/native/decision',[]),
    'native-integration':(ROOT/'vendor/native',[]),
    'persistence':(ROOT,['tests/persistence']),
    'public-api':(ROOT,['tests/test_public_api.py']),
    'boundaries':(ROOT,['tests/test_integration_boundaries.py']),
    'workspace-ux':(ROOT,['tests/test_workspace_ux.py']),
}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=SUITES,action='append')
    args=parser.parse_args()
    folder=ROOT/'reports/regression';folder.mkdir(parents=True,exist_ok=True)
    results=[]
    for name in args.suite or SUITES:
        cwd,paths=SUITES[name];xml=folder/f'{name}.xml'
        native_reports=ROOT/'vendor/native/reports'
        originals={p:p.read_bytes() for p in native_reports.rglob('*') if p.is_file()}
        with (folder/f'{name}.txt').open('w',encoding='utf-8') as log:
            process=subprocess.run([sys.executable,'-m','pytest',*paths,'-q',f'--junitxml={xml}'],
                cwd=cwd,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONUTF8':'1'})
        # Some original integration tests rewrite their checked-in evidence reports.
        # Retain the new evidence separately and restore the supplied archival files.
        for file,content in originals.items():
            if file.read_bytes()!=content:
                destination=ROOT/'reports/native-regression-generated'/file.relative_to(native_reports)
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(file,destination)
                file.write_bytes(content)
        stats={}
        if xml.exists():
            suite=ET.parse(xml).getroot().find('testsuite')
            stats={k:suite.attrib[k] for k in ('tests','failures','errors','skipped','time')}
        result={'suite':name,'returncode':process.returncode,**stats}
        results.append(result);print(json.dumps(result),flush=True)
    previous=json.loads((folder/'summary.json').read_text(encoding='utf-8')) if (folder/'summary.json').exists() else []
    merged={x['suite']:x for x in previous}
    merged.update({x['suite']:x for x in results})
    (folder/'summary.json').write_text(json.dumps(list(merged.values()),indent=2),encoding='utf-8')
    sys.exit(any(x['returncode'] for x in results))
