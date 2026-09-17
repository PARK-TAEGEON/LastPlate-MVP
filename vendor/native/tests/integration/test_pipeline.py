"""Real module E2E cases; synthetic records are explicitly DEMO, not field evidence."""
import json,sys,copy,sqlite3
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from integration import run_lastplate_pipeline,PipelineConfig
from integration.bridge import invoke
from integration.adapters.operation_adapter import build_operation

@pytest.fixture
def payload():
    p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf-8'))
    p['request_id']='test-clean'
    p['supply_events']=[]
    for lot in p['inventory']:
        lot.update(current_stock=1000000,unit='g',expiry_date='2026-10-01',minimum_stock=0,planned_order=0,last_used_date='2026-09-17')
    for row in p['prices']:
        for key in ('current_price','price_1w_ago','price_2w_ago','price_3w_ago','price_4w_ago'): row[key]=1000
    for row in p['monthly_prices']: row['average_price']=1000
    return p

@pytest.fixture
def run(tmp_path):
    config=PipelineConfig(storage_dir=tmp_path/'store')
    return lambda p:run_lastplate_pipeline(p,config=config)

def assert_complete(r):
    assert r['pipeline_status']=='COMPLETE',r['errors']
    assert r['decision']['requires_human_approval'] is True
    assert r['operation']['recommended_servings']==r['decision']['operation_recommended_servings']
    assert r['decision']['recommended_servings'] in (None,r['operation']['recommended_servings'])
    json.dumps(r,allow_nan=False)

def test_case01_normal_demo_is_calculated_but_not_operationally_approved(payload,run):
    r=run(payload);assert_complete(r)
    assert r['demand']['applicability']=='IN_RANGE'
    assert r['decision']['decision_type']=='NEEDS_CONFIRMATION'
    assert all(x['shortage_at_service_g']==0 for x in r['inventory_risk']['inventory_status'])

def test_case02_serving_increase_and_procurement_from_original_operation(payload,run):
    r=run(payload); assert_complete(r)
    p={**payload,'input_revision':r['input_revision']}
    base=build_operation(p,r['demand'])
    for lot in base['inventory_data']: lot['stock']=0
    base['demand_result']['prediction']=487
    base['demand_result']['prediction_interval']={'lower':469,'upper':507}
    a=invoke('operation',base)
    assert a['recommended_servings']==523
    base['demand_result']['prediction']=700
    base['demand_result']['prediction_interval']={'lower':650,'upper':750}
    b=invoke('operation',base)
    assert b['recommended_servings']>a['recommended_servings']
    assert b['ingredient_requirements'][0]['purchase_need']>a['ingredient_requirements'][0]['purchase_need']

def test_case03_shortage(payload,run):
    for row in payload['inventory']: row['current_stock']=0
    r=run(payload);assert_complete(r)
    assert any(a['type']=='ingredient_shortage' for a in r['inventory_risk']['alerts'])
    assert any(x['purchase_need']>0 for x in r['operation']['ingredient_requirements'])
    assert r['decision']['decision_type']=='BLOCK' # native hard shortage policy

def test_case04_expiry(payload,run):
    for row in payload['inventory']: row['expiry_date']='2026-09-18'
    r=run(payload);assert_complete(r)
    assert any(a['type']=='expiry_risk' for a in r['inventory_risk']['alerts'])
    assert r['decision']['inventory_actions']

def test_case05_price_and_nutrition_candidate(payload,run):
    for row in payload['prices']:
        if row['ingredient']=='두부': row['current_price']=10000
    r=run(payload);assert_complete(r)
    assert r['inventory_risk']['price_risks']
    assert r['inventory_risk']['substitute_candidates']
    assert r['inventory_risk']['nutrition_results']
    assert r['decision']['candidate_evaluations']

def test_case06_nutrition_fail(payload,run):
    payload['operation_policy']['nutrition_per_serving']['protein']=1
    r=run(payload);assert_complete(r)
    assert r['operation']['constraints']['status']=='FAIL'
    assert r['decision']['decision_type']=='BLOCK'

@pytest.mark.parametrize('population,expected',[(3000,'IN_RANGE'),(600,'OUT_OF_DISTRIBUTION'),(5000,'OUT_OF_DISTRIBUTION')])
def test_cases07_13_14_15_ood(payload,run,population,expected):
    payload['attendance'].update(registered_population=population,vacation=30,business_trip=50,work_from_home=10,overtime=50)
    r=run(payload);assert_complete(r)
    assert r['demand']['applicability']==expected
    if expected=='OUT_OF_DISTRIBUTION':
        assert any(a['type']=='DEMAND_OOD' for a in r['operation']['alerts'])
        assert any('outside training range' in x for x in r['decision']['data_quality_notes'])
        assert r['decision']['confidence']=='LOW'

def test_case08_recipe_missing(payload,run):
    payload['recipes']=[]
    r=run(payload)
    assert r['pipeline_status']=='PARTIAL'
    assert any(x['code']=='RECIPE_MISSING' for x in r['errors'])
    assert r['decision']['decision_type']=='NEEDS_CONFIRMATION'

def test_case09_unsupported_unit(payload,run):
    for recipe in payload['recipes']:
        if recipe['menu_name']=='두부조림': recipe['ingredients'][0]['unit']='bucket'
    r=run(payload)
    assert r['pipeline_status']=='PARTIAL'
    assert any(x['code']=='UNIT_ERROR' for x in r['errors']),r['errors']

def test_case10_superseded_is_audit_only(payload,run):
    payload['event']='내일 두부 금지. 두부 금지 해제.'
    r=run(payload);assert_complete(r)
    assert any(e.get('superseded') for e in r['inventory_risk']['detected_events'])
    assert not any(a['type']=='menu_conflict' for a in r['inventory_risk']['alerts'])
    assert 'restriction' not in r['decision']['serving_action']['failed_constraints']

def test_case11_retry_no_duplicate_or_input_mutation(payload,run):
    before=copy.deepcopy(payload)
    a=run(payload);b=run(payload)
    assert_complete(a);assert_complete(b)
    assert payload==before
    assert a['demand']['prediction_id']==b['demand']['prediction_id']
    assert a['decision']['recommendation_revision']==b['decision']['recommendation_revision']

def test_cases12_16_capacity_json_raw_preserved(payload,run):
    payload['meal_capacity']=550
    payload['attendance'].update(registered_population=520,vacation=30,business_trip=50,work_from_home=10,overtime=50)
    r=run(payload);assert_complete(r)
    assert r['demand']['predicted_diners']>550
    assert r['demand']['predicted_diners']==r['demand']['source_payload']['prediction']
    assert r['operation']['predicted_diners']==r['demand']['predicted_diners']
    assert any(w['code']=='CAPACITY_EXCEEDED' for w in r['warnings'])
    assert r['decision']['decision_type']=='NEEDS_CONFIRMATION'

def test_invalid_input_structured(run):
    assert run({})['pipeline_status']=='FAILED'

def test_demand_failure_preserves_decision(payload,run):
    payload['attendance']['vacation']=-10
    r=run(payload)
    assert r['pipeline_status']=='PARTIAL'
    assert r['errors'] and r['decision']['decision_type']=='NEEDS_CONFIRMATION'

def test_sources_no_default_fallback(payload,run):
    raw=json.loads((ROOT/'reports/demo-lh.json').read_text(encoding='utf-8'))['demand']
    p={**payload,'input_revision':'source-unit-test','sources':{k:'UNKNOWN' for k in payload['sources']}}
    assert build_operation(p,raw)['config']['data_mode']=='UNSPECIFIED'
    payload['sources'].pop('nutrition')
    r=run(payload)
    assert r['pipeline_status']=='FAILED'

def test_attendance_event_is_not_silently_applied(payload,run):
    payload['event']='내일 손님 35명 추가'
    r=run(payload);assert_complete(r)
    assert r['decision']['decision_type']=='NEEDS_CONFIRMATION'
    assert any(x['agent']=='demand_forecast' for x in r['decision']['recommended_rechecks'])

def test_hooks_are_advisory_and_failure_is_partial(payload,tmp_path):
    def broken(*args): raise OSError('test persistence failure')
    r=run_lastplate_pipeline(payload,config=PipelineConfig(storage_dir=tmp_path),hooks={'on_decision_complete':broken})
    assert r['decision'] and r['pipeline_status']=='PARTIAL'
    assert any(x['code']=='PERSIST_HOOK_FAILED' for x in r['errors'])

def test_api_validation(payload,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv('LASTPLATE_STORAGE',str(tmp_path/'api-store'))
    monkeypatch.setenv('LASTPLATE_MODE','demo')
    with TestClient(app) as client:
        assert client.post('/api/plan',json={}).status_code==422
        malformed=copy.deepcopy(payload)
        malformed['weekly_menu']=[{}]
        assert client.post('/api/plan',json=malformed).status_code==422
        response=client.post('/api/plan',json=payload)
        assert response.status_code==200
        assert_complete(response.json())
