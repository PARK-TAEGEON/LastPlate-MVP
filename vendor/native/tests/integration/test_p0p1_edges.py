import copy,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from integration.risk_evidence import project_active
from integration import run_lastplate_pipeline,PipelineConfig

def test_projection_graph_mixed_and_candidate_only_edges():
    r=dict(status='ok',detected_events=[dict(event_id='old',superseded=True,event_type='supply_risk'),dict(event_id='live',event_type='supply_risk')],
        substitute_candidates=[dict(candidate_id='dead',cause_event_ids=['old']),dict(candidate_id='keep',cause_event_ids=['old','live'])],
        alerts=[dict(candidate_id='dead',type='nutrition_violation'),dict(candidate_id='keep',cause_event_ids=['old','live'])],
        nutrition_results=[dict(candidate_id='dead',status='FAIL')],cost_impacts=[dict(candidate_id='dead')],
        constraints=[dict(candidate_id='dead',status='FAIL')],recommended_rechecks=[dict(agent='operation',cause_event_ids=['old'])])
    before=copy.deepcopy(r);active=project_active(r)
    assert r==before
    assert [x['candidate_id'] for x in active['substitute_candidates']]==['keep']
    assert active['substitute_candidates'][0]['cause_event_ids']==['live']
    for key in ('nutrition_results','cost_impacts','constraints'): assert not active[key]
    assert not any(isinstance(x,dict) for x in active['recommended_rechecks'])
    assert active['current_plan_checks']==dict(shortage='UNKNOWN',expiry='UNKNOWN',restriction='UNKNOWN',supply='UNKNOWN')

@pytest.mark.parametrize('unit',['ml','ea'])
def test_unsupported_units_before_any_model_write(unit,tmp_path):
    p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf8'))
    p['planned_orders']=[dict(ingredient='두부',planned_order=1,unit=unit)]
    r=run_lastplate_pipeline(p,config=PipelineConfig(storage_dir=tmp_path))
    assert r['demand'] is None and r['errors'][0]['http_status']==422
    assert not list(tmp_path.rglob('*.sqlite3'))

def test_http_server_failure_retains_successful_stage(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    import integration.orchestrator as orchestrator
    from integration.errors import StageError
    original=orchestrator.invoke
    def failing(stage,payload,timeout):
        if stage=='inventory_risk':raise StageError(stage,'TEST_WORKER_FAILURE','injected server failure',500)
        return original(stage,payload,timeout)
    monkeypatch.setattr(orchestrator,'invoke',failing)
    monkeypatch.setenv('LASTPLATE_STORAGE',str(tmp_path))
    monkeypatch.setenv('LASTPLATE_MODE','demo')
    p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf8'))
    with TestClient(app) as client:response=client.post('/api/plan',json=p)
    r=response.json()
    assert response.status_code==500 and r['demand'] and r['operation'] and r['decision']
    assert r['errors'][0]['kind']=='server'
    evidence=ROOT/'reports/p0p1/after/server-failure.json'
    evidence.write_text(json.dumps({'http_status':response.status_code,'body':r},ensure_ascii=False,indent=2),encoding='utf8')

def test_invalid_server_config_is_not_input_error():
    p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf8'))
    r=run_lastplate_pipeline(p,config={'mode':'bad-server-mode'})
    assert r['errors'][0]['http_status']==500 and r['errors'][0]['kind']=='server'

def test_native_multi_menu_raw_total_and_expiry():
    import subprocess
    code='''
import json
from datetime import date
from schemas.models import Menu,Recipe,InventoryLot
from tools.inventory import allocate
from tools.recipe import menu_key
menus=[Menu(date='2026-09-18',meal_type='lunch',menu_name=n,expected_max_diners=10,ingredients=[dict(ingredient='tofu',amount_per_serving=a,unit='g')]) for n,a in [('A',80),('B',20)]]
recipes={menu_key(m):Recipe(recipe_id=m.menu_name,menu_name=m.menu_name,category='test',ingredients=m.ingredients) for m in menus}
lots=[InventoryLot(ingredient='tofu',current_stock=5000,unit='g',expiry_date='2026-09-17',unit_price=1,minimum_stock=0,planned_order=0,storage_type='cold'),InventoryLot(ingredient='tofu',current_stock=1500,unit='g',expiry_date='2026-09-19',unit_price=1,minimum_stock=0,planned_order=0,storage_type='cold')]
needed,missing,remaining,audit=allocate(lots,menus,recipes,with_audit=True,required_totals={'tofu':2000})
assert needed['tofu']==2000 and missing['tofu']==500
assert [x['required_g'] for x in audit]==[1600,400]
assert all(a['lot_index']==1 for x in audit for a in x['allocations'])
assert [r.ingredients[0].amount_per_serving for r in recipes.values()]==[80,20]
print(json.dumps({'needed':needed,'missing':missing,'audit':audit}))
'''
    proc=subprocess.run([sys.executable,'-c',code],cwd=ROOT/'inventory_risk',capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    (ROOT/'reports/p0p1/after/multi-menu-allocation.json').write_text(proc.stdout,encoding='utf8')
