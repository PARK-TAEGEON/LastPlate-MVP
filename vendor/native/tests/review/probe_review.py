import tempfile
import sys,json,copy,tempfile,os,sqlite3,time
from pathlib import Path
BASE=Path(tempfile.mkdtemp(prefix='lastplate-review012-'))
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/p1-v012/previous-invariants'
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT))
from integration import run_lastplate_pipeline,PipelineConfig
from integration.bridge import invoke
from integration.adapters.operation_adapter import build_operation
p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf-8'))
p['supply_events']=[]
for lot in p['inventory']:
    lot.update(current_stock=1000000,unit='g',expiry_date='2026-10-01',minimum_stock=0,planned_order=0,last_used_date='2026-09-17')
for row in p['prices']:
    for key in ('current_price','price_1w_ago','price_2w_ago','price_3w_ago','price_4w_ago'): row[key]=1000
for row in p['monthly_prices']: row['average_price']=1000
cfg=PipelineConfig(storage_dir=BASE/'probe-store-011')
results={}
def run(name,payload):
    payload=copy.deepcopy(payload);payload['request_id']='review-'+name
    r=run_lastplate_pipeline(payload,config=cfg)
    json.dumps(r,allow_nan=False)
    (OUT/(name+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    results[name]={'status':r['pipeline_status'],'errors':r['errors'],'prediction':(r['demand'] or {}).get('predicted_diners'),'applicability':(r['demand'] or {}).get('applicability'),'servings':(r['operation'] or {}).get('recommended_servings'),'decision':(r['decision'] or {}).get('decision_type'),'timings':r['timings']}
    (OUT/'probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(name,json.dumps(results[name],ensure_ascii=False),flush=True)
    return r,payload
normal,np=run('normal',p)
for pop in (3000,600,5000,520):
    q=copy.deepcopy(p);q['attendance'].update(registered_population=pop,vacation=30,business_trip=50,work_from_home=10,overtime=50)
    if pop==520:q['meal_capacity']=550
    run('ood-valid-'+str(pop),q)
mutations={
 'invalid-ml':lambda q:q['attendance'].update(vacation=-10),
 'recipe-missing':lambda q:q.update(recipes=[]),
 'unsupported-unit':lambda q:q['recipes'][0]['ingredients'][0].update(unit='bucket'),
 'inventory-missing':lambda q:q.update(inventory=[]),
 'inventory-failure':lambda q:q['inventory'][0].update(unit_price=-1),
 'malformed-event':lambda q:q.update(event={'event_type':'banana'}),
 'ambiguity':lambda q:q.update(event='내일 두부 사용 금지인가?'),
 'nutrition-missing-no-candidate':lambda q:q.update(nutrition=[]),
 'nutrition-failure':lambda q:(q.update(nutrition=[]),q['prices'][0].update(current_price=10000)),
 'nutrition-hard-fail':lambda q:q['operation_policy']['nutrition_per_serving'].update(protein=1),
 'shortage':lambda q:[x.update(current_stock=0) for x in q['inventory']],
 'expiry':lambda q:[x.update(expiry_date='2026-09-18') for x in q['inventory']],
 'expired':lambda q:[x.update(expiry_date='2026-09-16') for x in q['inventory']],
 'price-rise':lambda q:q['prices'][0].update(current_price=10000),
 'superseded':lambda q:q.update(event='내일 두부 금지. 두부 금지 해제.'),
 'attendance-increase':lambda q:q.update(event='내일 손님 35명 추가'),
 'unknown-sources':lambda q:q.update(sources={k:'UNKNOWN' for k in q['sources']}),
 'real-labels':lambda q:q.update(sources={k:'USER_UPLOAD:review-fixture' for k in q['sources']}),
 'string-bool':lambda q:q.update(supply_events=[{'event_type':'supply_risk','ingredient':'두부','date':'2026-09-18','superseded':'false'}]),
 'nan':lambda q:q['attendance'].update(vacation=float('nan')),
 'order-convertible-unit':lambda q:q.update(planned_orders=[{'ingredient':'두부','planned_order':1,'unit':'kg'}]),
 'loss-mismatch':lambda q:(q['operation_policy'].update(trim_loss_pct={'두부':50}),[x.update(current_stock=100000 if x['ingredient']=='두부' else 1000000) for x in q['inventory']]),
}
for name,fn in mutations.items():
    if name not in {'inventory-failure','nutrition-hard-fail','order-convertible-unit','superseded'}:continue
    q=copy.deepcopy(p);fn(q)
    run(name,q)
# Idempotent replay, mutation, durable count, stable recommendation.
before=copy.deepcopy(np)
again=run_lastplate_pipeline(np,config=cfg)
db=next((BASE/'probe-store-011').rglob('*.sqlite3'),None)
if db:
    with sqlite3.connect(db) as c: n=c.execute('select count(*) from predictions where request_key=?',(np['site_id']+':'+np['request_id'],)).fetchone()[0]
else:n=None
results['retry']={'input_unchanged':np==before,'prediction_id_same':normal['demand']['prediction_id']==again['demand']['prediction_id'],'recommendation_revision_same':normal['decision']['recommendation_revision']==again['decision']['recommendation_revision'],'prediction_rows':n}
# Operation 523 identity test across the real Decision adapter.
pp={**np,'input_revision':normal['input_revision']}
oi=build_operation(pp,normal['demand']);oi['demand_result']['prediction']=487;oi['demand_result']['prediction_interval']={'lower':469,'upper':507}
op=invoke('operation',oi)
dd=copy.deepcopy(normal['demand']);dd['source_payload']['prediction']=487;dd['predicted_diners']=487
scope={'target_date':pp['target_date'],'meal_type':'lunch','coverage':'full','menus_complete':True,'menus':[{'menu':'두부조림','ingredients':['두부','간장'],'ingredients_complete':True}]}
decision_value={'payload':pp,'demand':dd,'operation':op,'inventory_risk':normal['inventory_risk'],'scope':scope}
de=invoke('decision',decision_value)
results['523-identity']={'operation':op['recommended_servings'],'decision_operation':de['operation_recommended_servings'],'decision_final':de['recommended_servings'],'operation_prediction':op['predicted_diners'],'operation_source':op['source']}
# Superseded stale derived risk: adversarial adapter boundary.
stale=copy.deepcopy(decision_value)
stale['inventory_risk']['detected_events'].append({'event_type':'price_event','event_id':'old-price','ingredient':'두부','date':'2026-09-18','severity':'HIGH','superseded':True,'description':'revoked price event'})
stale['inventory_risk']['price_risks'].append({'event_id':'old-price','ingredient':'두부','date':'2026-09-18','severity':'HIGH','superseded':True,'description':'revoked price event'})
sd=invoke('decision',stale)
(OUT/'superseded-stale-decision.json').write_text(json.dumps(sd,ensure_ascii=False,indent=2),encoding='utf-8')
results['superseded-stale']={'base_revision':de['recommendation_revision'],'stale_revision':sd['recommendation_revision'],'base_rechecks':de['recommended_rechecks'],'stale_rechecks':sd['recommended_rechecks'],'base_inventory_actions':de['inventory_actions'],'stale_inventory_actions':sd['inventory_actions'],'stale_trace':[t for t in sd['decision_trace'] if 'revoked' in json.dumps(t)]}
# FastAPI lifecycle and error status checks.
from fastapi.testclient import TestClient
from app.main import app
os.environ['LASTPLATE_STORAGE']=str(BASE/'api-probe-store-011')
with TestClient(app,raise_server_exceptions=False) as client:
    for name,body in [('normal',np),('empty',{}),('invalid-ml',{**np,'request_id':'api-invalid','attendance':{**np['attendance'],'vacation':-1}}),('nested-invalid',{**np,'request_id':'api-nested','supply_events':[{'event_type':'banana'}]})]:
        res=client.post('/api/plan',json=body)
        results['api-'+name]={'http':res.status_code,'body':res.json()}
(OUT/'probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
