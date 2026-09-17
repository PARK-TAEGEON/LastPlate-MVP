import copy,json,os,sys
from pathlib import Path
import pytest
ARTIFACT_ROOT=Path(__file__).resolve().parents[2]
ROOT=Path(os.environ.get('LASTPLATE_TEST_ROOT',str(ARTIFACT_ROOT))).resolve()
sys.path.insert(0,str(ROOT))
from integration import run_lastplate_pipeline,PipelineConfig
from integration.bridge import invoke

def save(name,value):
    folder=ARTIFACT_ROOT/'reports/p0p1'/os.environ.get('EVIDENCE_PHASE','after')
    folder.mkdir(parents=True,exist_ok=True)
    (folder/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

@pytest.fixture
def p():
    p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf-8'))
    p['request_id']='p0p1';p['supply_events']=[]
    p['inventory']=[x for x in p['inventory'] if x['ingredient'] in ('두부','간장')]
    p['inventory']=list({x['ingredient']:x for x in p['inventory']}.values())
    for x in p['inventory']:
        x.update(current_stock=100000 if x['ingredient']=='두부' else 3000,unit='g',expiry_date='2026-10-01',minimum_stock=0,planned_order=0,last_used_date='2026-09-17')
    for row in p['prices']:
        for k in ('current_price','price_1w_ago','price_2w_ago','price_3w_ago','price_4w_ago'):row[k]=1000
    for row in p['monthly_prices']:row['average_price']=1000
    return p

@pytest.fixture
def run(tmp_path):
    return lambda p:run_lastplate_pipeline(p,config=PipelineConfig(storage_dir=tmp_path/'store'))

def cancelled():
    return dict(event_type='supply_risk',event_id='cancelled-supply',ingredient='두부',date='2026-09-18',end_date='2026-09-18',severity='HIGH',superseded=True,description='cancelled observation',source_type='DEMO')

def test_01_cancelled_structured_supply_public(p,run):
    p['event']=cancelled();r=run(p);save('01-cancelled-structured',r)
    assert r['pipeline_status']=='COMPLETE',r['errors']
    assert any(e.get('superseded') for e in r['inventory_risk']['detected_events'])
    assert not r['inventory_risk']['supply_risks']
    assert not any(a['type']=='supply_risk' for a in r['decision']['critical_alerts'])
    assert not any(a['decision']=='REVIEW' and '공급' in a['reason'] for a in r['decision']['menu_actions'])

def test_02_raw_cooking_basis(p,run):
    p['operation_policy']['trim_loss_pct']={'두부':50}
    r=run(p);save('02-raw-basis',r)
    assert r['operation']['recommended_servings']==910
    o=next(x for x in r['operation']['ingredient_requirements'] if x['ingredient']=='두부')
    i=next(x for x in r['inventory_risk']['inventory_status'] if x['ingredient']=='두부')
    assert o['cooking_required']==145600 and o['purchase_need']==45600
    assert i['required_g']==o['cooking_required'] and i['shortage_at_service_g']==45600

def test_03_units_public_boundary(p,run):
    p['planned_orders']=[dict(ingredient='두부',planned_order=2,unit='kg')]
    good=run(p)
    bad=copy.deepcopy(p);bad['request_id']='bad-unit';bad['inventory'][0]['unit']='ml'
    unsupported=run(bad)
    save('03-units',dict(convertible=good,unsupported=unsupported))
    assert good['pipeline_status']=='COMPLETE',good['errors']
    assert next(x for x in good['inventory_risk']['inventory_status'] if x['ingredient']=='두부')['planned_order_g']==2000
    assert unsupported['demand'] is None
    assert any(e['code']=='UNIT_ERROR' and e.get('http_status')==422 for e in unsupported['errors'])

def test_04_http_error_semantics(p,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv('LASTPLATE_STORAGE',str(tmp_path/'api'))
    monkeypatch.setenv('LASTPLATE_MODE','demo')
    cases={}
    with TestClient(app) as c:
        for name,body in [('ok',p),('ml',{**p,'request_id':'invalid-ml','attendance':{**p['attendance'],'vacation':-1}}),
            ('nested',{**p,'request_id':'invalid-nested','nutrition':[{'ingredient':'두부'}]}),
            ('conflict',{**p,'attendance':{**p['attendance'],'overtime':552}})]:
            res=c.post('/api/plan',json=body);cases[name]={'status':res.status_code,'body':res.json()}
    save('04-http',cases)
    assert {k:v['status'] for k,v in cases.items()}=={'ok':200,'ml':422,'nested':422,'conflict':409}
    assert cases['nested']['body']['demand'] and cases['nested']['body']['operation']

def test_05_audit_and_demand_envelope(p,run):
    p['supply_events']=[cancelled()]
    p['attendance'].update(registered_population=600,vacation=30,business_trip=50,work_from_home=10,overtime=50)
    r=run(p);save('05-audit-envelope',r)
    assert any(e.get('superseded') for e in r['inventory_risk']['detected_events'])
    assert not r['inventory_risk']['supply_risks']
    for envelope in (r['operation'].get('demand_envelope'),r['decision'].get('demand_envelope')):
        assert envelope and envelope['confidence']==r['demand']['confidence']
        for k in ('model_type','training_ranges','warnings','model_version','predicted_diners'): assert envelope[k]==r['demand'][k]

def test_06_last_adapter_defense_and_native_gates(p,run):
    base=run(p);r=copy.deepcopy(base['inventory_risk'])
    dead=cancelled();cid='cancelled-candidate'
    r['detected_events'].append(dead)
    linked=dict(ingredient='두부',date=p['target_date'],meal_type='lunch',cause_event_ids=[dead['event_id']],candidate_id=cid)
    r['price_risks']=[{**linked,'severity':'HIGH','message':'cancelled-price'}]
    r['supply_risks']=[{**dead,'inventory_context':{}}]
    r['affected_menus']=[{**linked,'cause_event_id':dead['event_id'],'cause':'supply_risk','menu_name':'두부조림'}]
    r['alerts']=[{**linked,'type':'supply_risk','severity':'HIGH','message':'cancelled alert','evidence':['cancelled']}]
    r['priority_use_candidates']=[{**linked,'quantity_g':1,'expiry_date':p['target_date'],'menu_name':'두부조림'}]
    r['substitute_candidates']=[{**linked,'original_menu':'두부조림','candidate_menu':'계란찜','nutrition_check':'FAIL'}]
    r['nutrition_results']=[{**linked,'status':'FAIL'}];r['cost_impacts']=[{**linked,'delta_total':100}]
    r['recommended_rechecks']=['operation_agent']
    p['input_revision']=base['input_revision']
    scope=base['decision']['adapter_provenance']['operation']['analysis_scope']
    final=invoke('decision',dict(payload=p,demand=base['demand'],operation=base['operation'],inventory_risk=r,scope=scope))
    save('06-adapter-defense',dict(input=r,decision=final))
    assert not any(a['type']=='supply_risk' for a in final['critical_alerts'])
    assert not any(a.get('candidate_id')==cid for a in final['candidate_evaluations'])
    assert not any(q['reason']=='upstream_request:operation' for q in final['recommended_rechecks'])
    assert final['active_evidence_summary']['current_plan_checks']==base['inventory_risk']['current_plan_checks']
    assert final['source_payload']['inventory_risk']['supply_risks'] # audit only
