"""Optional real upstream verification. No Operation Agent implementation is supplied.

Each legacy upstream runs in its own process so its agents/config/tools modules
cannot shadow Decision or the other upstream. ML writes only its requested demo store.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

INVENTORY = '''
import json,sys
from agents.inventory_risk import analyze_inventory_and_risk
value=json.loads(sys.stdin.read())
print(json.dumps(analyze_inventory_and_risk(value['request'],value.get('event')),ensure_ascii=False))
'''
ML = '''
import json,sys
from pathlib import Path
from ml.time_contract import ServiceConfig
from tools.demand import predict_demand
value=json.loads(sys.stdin.read())
cfg=ServiceConfig(Path(value['storage']).resolve(),Path('models').resolve(),'Asia/Seoul','10:00','14:00',mode='demo')
result=predict_demand(value['input'],request_id=value['request_id'],config=cfg)
print(json.dumps(result,ensure_ascii=False))
'''


def invoke(root, script, value):
    process=subprocess.run([sys.executable,'-c',script],cwd=root,
        input=json.dumps(value),text=True,encoding='utf-8',capture_output=True,timeout=120)
    if process.returncode:
        raise RuntimeError(process.stderr)
    return json.loads(process.stdout), process.stderr


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--inventory-root',type=Path,required=True)
    parser.add_argument('--ml-root',type=Path,required=True)
    parser.add_argument('--storage',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    manifest={'scope':'Real Inventory DEMO + real saved ML model DEMO calls. No real Operation. Not full operational E2E.',
              'sources':{},'calls':[]}
    for label,root,rel in [('inventory',args.inventory_root,'agents/inventory_risk.py'),('ml',args.ml_root,'tools/demand.py')]:
        manifest['sources'][label]={'file':rel,'sha256':hashlib.sha256((root/rel).read_bytes()).hexdigest()}
    cases=[('inventory_full',{'request':{'as_of':'2026-09-17','horizon_start':'2026-09-18','horizon_end':'2026-09-24','input_snapshot_id':'captured-fixture-input'}}),
           ('inventory_event',{'request':{'as_of':'2026-09-17','mode':'event','horizon_start':'2026-09-18','horizon_end':'2026-09-24','input_snapshot_id':'captured-fixture-input'},
                               'event':{'event_type':'expiry_event','event_id':'live-expiry','ingredient':'두부','date':'2026-09-18','description':'두부 사용기한 점검'}}),
           ('inventory_clarification',{'request':{'as_of':'2026-09-17','mode':'event'},
                                     'event':{'event_type':'attendance_event','needs_clarification':True,'description':'숫자 미확인'}})]
    for name,value in cases:
        result,err=invoke(args.inventory_root,INVENTORY,value)
        (args.output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        manifest['calls'].append({'case':name,'status':result['status'],'stderr':err,'fixture_sha256':hashlib.sha256((args.output/(name+'.json')).read_bytes()).hexdigest()})
    result,err=invoke(args.ml_root,ML,{'storage':str(args.storage.resolve()),'request_id':'decision-v012-contract-capture',
        'input':{'date':'2021-01-26','employees':2983,'vacation':69,'business_trip':183,'work_from_home':362,'overtime':551,
                 'menu':'쌀밥 들깨미역국 교촌간장치킨 옥수수콘치즈구이'}})
    (args.output/'ml_v2_demo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest['calls'].append({'case':'ml_v2_demo','prediction':result['prediction'],'mode':result['mode'],
        'operational_eligible':result['operational_eligible'],'stderr':err,
        'fixture_sha256':hashlib.sha256((args.output/'ml_v2_demo.json').read_bytes()).hexdigest()})
    (args.output/'capture_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from lastplate_decision.adapters import adapt_ml_v2, adapt_inventory_v020
    from lastplate_decision import make_final_recommendation
    inventory=json.loads((args.output/'inventory_full.json').read_text(encoding='utf-8'))
    final=make_final_recommendation(adapt_ml_v2(result),{},adapt_inventory_v020(inventory),input_revision='captured-fixture-input')
    assert final['status'] != 'ok' and final['recommended_servings'] is None
    verification=args.output.parent.parent/'verification'
    verification.mkdir(exist_ok=True)
    (verification/'live_adapter_decision.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest['integration']={'real_inventory':True,'real_saved_ml_model':True,'real_operation':False,
        'decision_status':final['status'],'recommended_servings':final['recommended_servings'],
        'full_operational_e2e':'NOT RUN: no real Operation implementation and shared provenance'}
    (verification/'REAL_UPSTREAM_LOG.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
