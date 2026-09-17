import copy, csv, io, json, sqlite3, base64
from datetime import date
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.settings import Settings
from backend.adapters.persistence import Persistence
from backend.application.profiles import demo_profile
from lastplate_db import Repository


@pytest.fixture
def settings(tmp_path):return Settings(tmp_path/'lastplate.db',debug_enabled=True,debug_token='regression-access')

@pytest.fixture
def client(settings):
    with TestClient(create_app(settings),headers={'Authorization':'Basic '+base64.b64encode(b'developer:regression-access').decode()}) as value:yield value

@pytest.fixture
def payload():return demo_profile(target_date=date(2026,9,21))['request']

def execute(client,payload):
    response=client.post('/api/plan',json=payload)
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.e2e
def test_case01_normal_pipeline_contract_ids_and_original_model(client,payload,settings):
    r=execute(client,payload)
    assert r['pipeline_status']=='SUCCESS'
    assert r['persistence_status']=='SUCCESS'
    assert r['demand']['predicted_diners']==r['demand']['source_payload']['prediction']
    assert r['demand']['lower_bound'] is None and r['demand']['upper_bound'] is None
    assert r['decision']['requires_human_approval'] is True
    assert r['decision']['recommended_servings'] in (None,r['operation']['recommended_servings'])
    assert r['operation']['recommended_servings']==r['decision']['operation_recommended_servings']
    with Repository(settings.database) as repo:
        pred=repo.get_prediction(r['persistence_ids']['prediction_id'])
        op=repo.get_operation_plan(r['persistence_ids']['operation_plan_id'])
        dec=repo.get_decision(r['persistence_ids']['decision_id'])
        assert pred['input_snapshot_json']['request']['attendance']==payload['attendance']
        assert pred['applicability']=='IN_RANGE'
        assert pred['model_version']==r['demand']['model_version']
        assert op['prediction_id']==pred['prediction_id']
        assert dec['recommendation_json']['prediction_id']==pred['prediction_id']
        assert dec['recommendation_json']['operation_plan_id']==op['plan_id']
    assert client.get('/api/plans/'+r['request_id']).json()==r


@pytest.mark.e2e
@pytest.mark.parametrize('population',[600,5000])
def test_cases02_03_ood_and_no_capacity_clip(client,payload,population):
    payload['attendance']['registered_population']=population
    payload['meal_capacity']=500
    r=execute(client,payload)
    assert r['demand']['applicability']=='OUT_OF_DISTRIBUTION'
    assert r['demand']['predicted_diners']==r['demand']['source_payload']['prediction']
    assert r['demand']['predicted_diners']>500
    assert any(w['code']=='MODEL_INPUT_OUT_OF_RANGE' for w in r['demand']['warnings'])
    assert r['decision']['confidence']=='LOW'


@pytest.mark.e2e
def test_case04_event_recomputes_without_overwriting_ml_or_double_counting(client,payload):
    a=execute(client,payload)
    event=['내일 손님 80명 추가']
    b=client.post('/api/replan',json={'existing_context':a['request_id'],'events':event}).json()
    c=client.post('/api/replan',json={'existing_context':b['request_id'],'events':event}).json()
    assert b['demand']['predicted_diners']==a['demand']['predicted_diners']==c['demand']['predicted_diners']
    assert b['operation']['base_demand']==a['operation']['base_demand']+80
    assert b['operation']['recommended_servings']>a['operation']['recommended_servings']
    assert c['operation']['recommended_servings']==b['operation']['recommended_servings']
    assert b['parent_request_id']==a['request_id']
    assert b['decision']['requires_human_approval']


@pytest.mark.e2e
def test_case05_shortage_uses_native_risk(client,payload):
    for row in payload['inventory']:row['current_stock']=0
    r=execute(client,payload)
    assert any(a['type']=='ingredient_shortage' for a in r['inventory_risk']['alerts'])
    assert r['decision']['decision_type']=='BLOCK'


@pytest.mark.e2e
def test_case06_expiry(client,payload):
    for row in payload['inventory']:row['expiry_date']=payload['target_date']
    r=execute(client,payload)
    assert any(a['type']=='expiry_risk' for a in r['inventory_risk']['alerts'])


@pytest.mark.e2e
def test_case07_price_risk_candidates(client,payload):
    for row in payload['prices']:
        if row['ingredient']=='두부':row['current_price']=10000
    r=execute(client,payload)
    assert r['inventory_risk']['price_risks']
    assert r['inventory_risk']['substitute_candidates']
    assert r['decision']['candidate_evaluations']


@pytest.mark.e2e
def test_case08_nutrition_fail(client,payload):
    payload['operation_policy']['nutrition_per_serving']['protein']=1
    r=execute(client,payload)
    assert r['operation']['constraints']['status']=='FAIL'
    assert r['decision']['decision_type'] in ('REVIEW','BLOCK')


@pytest.mark.e2e
def test_case09_recipe_missing_partial(client,payload):
    payload['recipes']=[]
    response=client.post('/api/plan',json=payload)
    assert response.status_code==422
    r=response.json()
    assert r['pipeline_status']=='PARTIAL'
    assert r['demand'] and r['decision']['decision_type']=='NEEDS_CONFIRMATION'
    assert any(e['code']=='RECIPE_MISSING' for e in r['errors'])


def test_case10_unsupported_unit_structured(client,payload):
    payload['inventory'][0]['unit']='bucket'
    response=client.post('/api/plan',json=payload)
    assert response.status_code==422
    assert response.json()['errors'][0]['code']=='UNIT_ERROR'


@pytest.mark.e2e
def test_case11_superseded_event_is_audit_only(client,payload):
    payload['events']=['내일 두부 금지. 두부 금지 해제.']
    r=execute(client,payload)
    assert any(e.get('superseded') for e in r['inventory_risk']['detected_events'])
    assert 'restriction' not in r['decision']['serving_action']['failed_constraints']


def actual_input(payload):
    return dict(site_id=payload['site_id'],target_date=payload['target_date'],actual_diners=1180,
        prepared_servings=1300,unserved_leftover_kg=18.4,plate_waste_kg=31.2,
        ingredient_waste_kg=3.1,shortage=False,notes='운영자 측정',is_demo=True)


@pytest.mark.e2e
def test_cases12_13_14_actual_restart_history_kpis_and_json(client,payload,settings):
    r=execute(client,payload)
    response=client.post('/api/actual-results',json=actual_input(payload))
    assert response.status_code==200,response.text
    saved=response.json()
    assert saved['saved']
    assert saved['summary']['prediction_error']==abs(r['demand']['predicted_diners']-1180)
    assert saved['summary']['overprep_servings']==120
    assert saved['kpis']['retraining_readiness']['all_new_actual_records']==1
    assert saved['kpis']['retraining_readiness']['eligible_new_actual_records']==0
    assert saved['kpis']['prediction_mae'] is None
    with Repository(settings.database) as repo:
        assert repo.get_actual_result(payload['site_id'],payload['target_date'])['actual_diners']==1180
    with TestClient(create_app(settings),headers={'Authorization':'Basic '+base64.b64encode(b'developer:regression-access').decode()}) as restarted:
        history=restarted.get('/api/history/'+payload['site_id']).json()['records']
        assert history[0]['result_id']==saved['result']['result_id']
        assert history[0]['prediction_id']==r['demand']['prediction_id']
        assert restarted.get('/api/plans/'+r['request_id']).json()['demand']==r['demand']
        assert restarted.get('/api/learning-dataset/'+payload['site_id']).json()['dataset']['accepted_count']==0
    assert client.post('/api/actual-results',json=actual_input(payload)).json()['result']['result_id']==saved['result']['result_id']
    changed=actual_input(payload);changed['actual_diners']=1200
    assert client.post('/api/actual-results',json=changed).status_code==409
    json.dumps(r,allow_nan=False);json.dumps(saved,allow_nan=False)


@pytest.mark.e2e
def test_persistence_failure_preserves_success_and_actual_fails(client,payload,monkeypatch):
    def broken(*args,**kwargs):raise sqlite3.OperationalError('injected write failure')
    monkeypatch.setattr(Persistence,'demand',broken)
    r=execute(client,payload)
    assert r['pipeline_status']=='SUCCESS'
    assert r['persistence_status'] in ('PARTIAL','FAILED')
    assert any(w['code']=='PERSISTENCE_FAILED' for w in r['warnings'])
    monkeypatch.setattr(Persistence,'actual',broken)
    response=client.post('/api/actual-results',json=actual_input(payload))
    assert response.status_code==503
    assert response.json()['errors'][0]['code']=='PERSISTENCE_FAILED'


@pytest.mark.e2e
def test_acknowledgement_is_not_approval(client,payload,settings):
    r=execute(client,payload)
    ack=client.post('/api/plans/'+r['request_id']+'/acknowledgement').json()
    assert ack['acknowledged'] and not ack['approved'] and not ack['automatic_execution']
    with Repository(settings.database) as repo:
        assert repo.get_decision(r['persistence_ids']['decision_id'])['approved']==0


def test_upload_csv_xlsx_and_inventory_snapshot(client,payload,settings):
    from openpyxl import Workbook
    content=f"date,meal_type,menu_name\n{payload['target_date']},lunch,두부조림\n".encode('utf-8-sig')
    assert client.post('/api/upload/menu',files={'file':('menu.csv',content)}).status_code==200
    rows=payload['inventory'][:1]
    book=Workbook();sheet=book.active;sheet.append(list(rows[0]));sheet.append(list(rows[0].values()))
    binary=io.BytesIO();book.save(binary);book.close()
    response=client.post('/api/upload/inventory',files={'file':('inventory.xlsx',binary.getvalue())},data={'context':json.dumps(payload)})
    assert response.status_code==200,response.text
    with Repository(settings.database) as repo:
        stored=repo.get_inventory_by_site(payload['site_id'])
        assert len(stored)==1 and stored[0]['source_type']=='USER_UPLOAD' and stored[0]['is_demo']==1


@pytest.mark.parametrize('name,data,code',[
    ('a.csv',b'','EMPTY_FILE'),('a.csv',b'no,columns\na,b','INVALID_COLUMNS'),
    ('a.xlsx',b'broken archive','MALFORMED_FILE'),('a.exe',b'any','FILE_TYPE_ERROR'),
    ('a.csv',b'date,meal_type,menu_name\n2026-09-21,lunch,x\n2026-09-21,lunch,x','DUPLICATE_ROW'),
    ('a.csv',b'date,meal_type,menu_name\nnot-date,lunch,x','ROW_VALIDATION_ERROR'),
])
def test_upload_errors_are_understandable(client,name,data,code):
    response=client.post('/api/upload/menu',files={'file':(name,data)})
    assert response.status_code==422
    assert response.json()['errors'][0]['code']==code


def test_health_empty_kpis_and_strict_requests(client,payload):
    assert client.get('/api/health').json()=={'status':'ok'}
    assert client.get('/api/kpis/unknown').json()['prediction_mae'] is None
    payload['request_id']='invented-by-client'
    assert client.post('/api/plan',json=payload).status_code==422
    del payload['request_id'];payload['attendance']['vacation']=5000
    assert client.post('/api/plan',json=payload).status_code==422


def test_demo_cannot_be_relabelled_real(client,payload):
    payload['is_demo']=False
    assert client.post('/api/plan',json=payload).status_code==422


def test_frontend_static_and_no_agent_imports(client):
    assert client.get('/').status_code==200
    assert client.get('/assets/app.js').status_code==200
    assert client.get('/openapi.json').json()['info']['version']=='1.0.0'
