import tempfile
import json,sys,copy
from pathlib import Path
BASE=Path(tempfile.mkdtemp(prefix='lastplate-review012-'));ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'reports/p1-v012/previous-invariants'
sys.path.insert(0,str(ROOT))
from integration import run_lastplate_pipeline,PipelineConfig
cfg=PipelineConfig(storage_dir=BASE/'followup-store-011')
original=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf-8'))
clean=copy.deepcopy(original);clean['supply_events']=[]
for lot in clean['inventory']:lot.update(current_stock=1000000,unit='g',expiry_date='2026-10-01',minimum_stock=0,planned_order=0,last_used_date='2026-09-17')
for row in clean['prices']:
    for key in ('current_price','price_1w_ago','price_2w_ago','price_3w_ago','price_4w_ago'):row[key]=1000
for row in clean['monthly_prices']:row['average_price']=1000
cases={}
for pop in (3000,600,5000,520):
    p=copy.deepcopy(clean);p['attendance'].update(registered_population=pop,vacation=30,business_trip=50,work_from_home=10,overtime=50)
    if pop==520:p['meal_capacity']=550
    cases['ood-valid-'+str(pop)]=p
cases['original-lh-demo']=original
cases['original-small-demo']=json.loads((ROOT/'examples/small_site.json').read_text(encoding='utf-8'))
q=copy.deepcopy(clean);q['event']={'event_type':'attendance_event','needs_clarification':True,'date':'2026-09-18','description':'Unknown visitor count'};cases['decision-ambiguity']=q
q=copy.deepcopy(clean);q['supply_events']=[{'event_type':'supply_risk','event_id':'revoked-supply','superseded':True,'ingredient':'두부','date':'2026-09-18','description':'revoked supply risk'}];cases['superseded-supply-audit']=q
q=copy.deepcopy(clean);q['inventory']=[x for x in q['inventory'] if x['ingredient']!='두부']+[dict(clean['inventory'][0],current_stock=100000)];q['operation_policy']['trim_loss_pct']={'두부':50};cases['loss-gap-single-lot']=q
q=copy.deepcopy(clean);q['recipes'][0]['ingredients'][0]['unit']='ml';q['inventory'][0]['unit']='ml';q['inventory'][1]['unit']='ml';cases['unsupported-risk-unit']=q
q=copy.deepcopy(clean);q['nutrition']=[];q['prices'][0]['current_price']=10000;cases['nutrition-provider-missing']=q
results={}
for name,p in cases.items():
    if name not in {'superseded-supply-audit','loss-gap-single-lot','nutrition-provider-missing'}:continue
    p['request_id']='followup-'+name;r=run_lastplate_pipeline(p,config=cfg)
    (OUT/(name+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    d=r['demand'] or {};o=r['operation'] or {};dec=r['decision'] or {}
    results[name]={'status':r['pipeline_status'],'errors':r['errors'],'prediction':d.get('predicted_diners'),'applicability':d.get('applicability'),'confidence':d.get('confidence'),'warnings':d.get('warnings'),'servings':o.get('recommended_servings'),'capacity_excess':o.get('capacity_excess'),'decision':dec.get('decision_type'),'decision_confidence':dec.get('confidence'),'notes':dec.get('data_quality_notes'),'timings':r['timings']}
    (OUT/'followup.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,json.dumps({k:v for k,v in results[name].items() if k not in ('notes','warnings')},ensure_ascii=False),flush=True)
