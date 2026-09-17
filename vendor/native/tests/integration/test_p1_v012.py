"""P1 public-boundary regression; JSON evidence comes from actual executions."""
import copy,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from integration import run_lastplate_pipeline,PipelineConfig
from integration.bridge import invoke
from integration.adapters.operation_adapter import build_operation

def save(name,value):
    folder=ROOT/'reports/p1-v012';folder.mkdir(exist_ok=True)
    (folder/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

@pytest.fixture
def payload():
    return json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf8'))

def test_native_limit_http_422_preserves_demand_and_decision(payload,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv('LASTPLATE_STORAGE',str(tmp_path));monkeypatch.setenv('LASTPLATE_MODE','demo')
    payload['operation_policy']['maximum_input_servings']=100
    res=TestClient(app).post('/api/plan',json=payload);r=res.json()
    save('limit-after',dict(http_status=res.status_code,body=r))
    assert res.status_code==422 and r['pipeline_status']=='PARTIAL'
    assert r['demand']['predicted_diners']==883
    assert r['operation']['status']=='invalid_input'
    error=next(e for e in r['errors'] if e['stage']=='operation')
    assert error['code']=='INPUT_DEMAND_OUT_OF_RANGE' and error['http_status']==422
    assert error['evidence']=={'maximum_input_servings':100,'received_max':883}
    assert error['alerts']==r['operation']['alerts']
    assert r['decision']['decision_type']=='NEEDS_CONFIRMATION'
    assert r['decision']['requires_human_approval'] is True
    assert r['inventory_risk'] is None

@pytest.mark.parametrize('alerts',[
    [],[dict(type='FUTURE_INPUT_ALERT',severity='HIGH',message='future rejection',evidence={'limit':1})]])
def test_all_invalid_input_statuses_are_errors(payload,tmp_path,monkeypatch,alerts):
    import integration.orchestrator as orchestration
    original=orchestration.invoke
    def worker(stage,value,timeout):
        result=original(stage,value,timeout)
        if stage=='operation': result.update(status='invalid_input',alerts=copy.deepcopy(alerts))
        return result
    monkeypatch.setattr(orchestration,'invoke',worker)
    r=run_lastplate_pipeline(payload,config=PipelineConfig(storage_dir=tmp_path))
    save('unknown-alert' if alerts else 'absent-alert',r)
    error=next(e for e in r['errors'] if e['stage']=='operation')
    assert error['http_status']==422 and error['native_status']=='invalid_input'
    assert error['code']==('FUTURE_INPUT_ALERT' if alerts else 'OPERATION_INVALID_INPUT')
    assert error['alerts']==alerts
    assert r['demand'] and r['decision'] and r['inventory_risk'] is None

def test_usable_stock_native_policy_is_shared(payload,tmp_path):
    from integration.native_stock import usable_stock
    # Mixed lots, inclusive expiry, unchanged units. Native allocation is also exercised below.
    r=run_lastplate_pipeline(payload,config=PipelineConfig(storage_dir=tmp_path))
    payload['input_revision']=r['input_revision']
    lot=payload['inventory'][0]
    payload['inventory']=[{**lot,'current_stock':q,'unit':unit,'expiry_date':expiry} for q,unit,expiry in
        [(1000,'g','2026-09-17'),(2,'kg','2026-09-18'),(3000,'g','2026-09-19')]]
    rows=build_operation(payload,r['demand'])['inventory_data']
    assert [x['stock'] for x in rows]==[0,2,3000]
    assert [x['unit'] for x in rows]==['g','kg','g']
    assert usable_stock(2,'2026-09-18','2026-09-18')==2
    save('usable-stock',rows)

def test_invalid_expiry_is_rejected_before_model(payload,tmp_path):
    from app.main import result_status
    payload['inventory'][0]['expiry_date']='not-a-date'
    r=run_lastplate_pipeline(payload,config=PipelineConfig(storage_dir=tmp_path))
    save('invalid-expiry',r)
    assert result_status(r)==422 and r['demand'] is None
    assert r['errors'][0]['kind']=='input'
    assert not list(tmp_path.rglob('*.sqlite3'))

def test_raw_candidate_has_explicit_pending_gate(payload,tmp_path):
    payload['operation_policy']['trim_loss_pct']={'두부':50}
    base=run_lastplate_pipeline(payload,config=PipelineConfig(storage_dir=tmp_path))
    assert base['inventory_risk'],base['errors']
    risk=copy.deepcopy(base['inventory_risk'])
    # Upstream raw/cooking flag, independent of other demo/missing-proof holds.
    risk['substitute_candidates']=[dict(candidate_id='raw-candidate',original_menu='두부조림',candidate_menu='계란찜',
        date=payload['target_date'],meal_type='lunch',nutrition_check='PASS',inventory_available=True,
        operation_quantity_recheck_required=True,quantity_basis='native edible estimate',cause_event_ids=[])]
    payload['input_revision']=base['input_revision']
    scope=base['decision']['adapter_provenance']['operation']['analysis_scope']
    final=invoke('decision',dict(payload=payload,demand=base['demand'],operation=base['operation'],inventory_risk=risk,scope=scope))
    save('candidate-gate',dict(input=risk,decision=final))
    gate=next(g for g in final['confirmation_gates'] if g['candidate_id']=='raw-candidate')
    assert gate['status']=='pending' and gate['automatic_execution'] is False
    assert any(q['request_id']==gate['request_id'] and q['status']=='pending' and q['agent']=='operation' for q in final['recommended_rechecks'])
    assert final['requires_human_approval'] is True
    assert not any(a['selected'] for a in final['menu_actions'] if a.get('candidate_id')=='raw-candidate')
    evaluations=[a for a in final['candidate_evaluations'] if a.get('candidate_id')=='raw-candidate']
    assert evaluations and all(a['decision'] in ('NEEDS_CONFIRMATION','BLOCK') for a in evaluations)
    # Isolate the gate from DEMO and missing constraints with native all-PASS test evidence.
    import subprocess
    request=next(q for q in final['recommended_rechecks'] if q['request_id']==gate['request_id'])
    code='''
import json,sys
from examples.fixtures import baseline,PASS
from lastplate_decision import make_final_recommendation as decide
p=baseline()
p['inventory_risk_result']['substitute_candidates']=[dict(candidate_id='raw-candidate',kind='menu_substitution',menu='두부조림',candidate_menu='계란찜',constraints=PASS)]
before=decide(**p)
q=json.load(sys.stdin);q['input_revision']=p['input_revision']
p['inventory_risk_result']['recommended_rechecks']=[q]
after=decide(**p)
assert before['candidate_evaluations'][0]['decision']=='REVIEW'
assert after['candidate_evaluations'][0]['decision']=='NEEDS_CONFIRMATION'
assert after['candidate_evaluations'][0]['selected'] is False
assert all('raw-candidate' not in a['candidates'] for a in after['menu_actions'])
print(json.dumps(dict(before=before,after=after),ensure_ascii=False))
'''
    proc=subprocess.run([sys.executable,'-c',code],cwd=ROOT/'decision',input=json.dumps(request),capture_output=True,text=True,encoding='utf8',env={**__import__('os').environ,'PYTHONUTF8':'1'})
    assert proc.returncode==0,proc.stderr
    save('all-pass-candidate-gate',json.loads(proc.stdout))
    # A cancelled candidate may remain in audit, but must not generate a pending gate.
    risk['detected_events'].append(dict(event_id='cancelled-raw',event_type='supply_risk',superseded=True))
    risk['substitute_candidates'][0]['cause_event_ids']=['cancelled-raw']
    cancelled=invoke('decision',dict(payload=payload,demand=base['demand'],operation=base['operation'],inventory_risk=risk,scope=scope))
    assert cancelled['confirmation_gates']==[]
    assert not any('operation_quantity_recheck_required:' in q['reason'] for q in cancelled['recommended_rechecks'])
    save('cancelled-candidate-gate',cancelled)

def test_business_confirmation_remains_http_200(payload,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv('LASTPLATE_STORAGE',str(tmp_path));monkeypatch.setenv('LASTPLATE_MODE','demo')
    payload['supply_events']=[]
    for lot in payload['inventory']:
        lot.update(current_stock=1000000,unit='g',expiry_date='2026-10-01',minimum_stock=0,planned_order=0,last_used_date='2026-09-17')
    for row in payload['prices']:
        for key in ('current_price','price_1w_ago','price_2w_ago','price_3w_ago','price_4w_ago'): row[key]=1000
    for row in payload['monthly_prices']: row['average_price']=1000
    res=TestClient(app).post('/api/plan',json=payload);r=res.json()
    save('business-confirmation',dict(http_status=res.status_code,body=r))
    assert res.status_code==200 and r['decision']['decision_type']=='NEEDS_CONFIRMATION'
    assert r['decision']['requires_human_approval'] is True
