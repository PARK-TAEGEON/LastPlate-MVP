import io,json,sqlite3,base64
from datetime import date
from types import SimpleNamespace
import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.settings import Settings
from backend.contracts import PlanRequest,ActualRequest
from backend.adapters.persistence import Persistence
from backend.application.profiles import demo_profile
from lastplate_db import Repository,get_dashboard_kpis,get_learning_dataset


@pytest.fixture
def context(tmp_path):
    settings=Settings(tmp_path/'db.sqlite',debug_enabled=True,debug_token='regression-access')
    with TestClient(create_app(settings),headers={'Authorization':'Basic '+base64.b64encode(b'developer:regression-access').decode()}) as client:yield client,settings


def test_inventory_unit_nonfinite_and_negative_are_rejected(context):
    client,settings=context
    p=demo_profile(target_date=date(2026,9,21))['request']
    headers='ingredient,current_stock,unit,expiry_date,unit_price,minimum_stock,planned_order,storage_type'
    for stock,unit in [('10','ea'),('NaN','kg'),('-1','kg')]:
        content=f'{headers}\n두부,{stock},{unit},2026-09-22,1000,0,0,refrigerated'.encode('utf-8')
        r=client.post('/api/upload/inventory',files={'file':('a.csv',content)},data={'context':json.dumps(p)})
        assert r.status_code==422,r.text
    with Repository(settings.database) as repo:assert repo.get_inventory_by_site('DEMO-LH')==[]


def test_xlsx_formula_rejected(context):
    client,_=context
    b=Workbook();s=b.active;s.append(['date','meal_type','menu_name']);s.append(['2026-09-21','lunch','=1+1'])
    output=io.BytesIO();b.save(output);b.close()
    r=client.post('/api/upload/menu',files={'file':('menu.xlsx',output.getvalue())})
    assert r.status_code==422 and r.json()['errors'][0]['code']=='FORMULA_NOT_ALLOWED'


def test_real_source_labels_cannot_override_demo_server_mode(context):
    client,_=context
    p=demo_profile()['request'];p['is_demo']=False;p['site_id']='REAL-SITE'
    p['sources']={k:'USER_UPLOAD:operator' for k in p['sources']}
    r=client.post('/api/plan',json=p)
    assert r.status_code==409 and r.json()['errors'][0]['code']=='RECORD_CONFLICT'


def test_malformed_recipe_with_event_is_input_error_not_500(context):
    client,_=context
    p=demo_profile()['request'];p['recipes']=[{'invalid':'shape'}];p['events']=['내일 손님 80명 추가']
    r=client.post('/api/plan',json=p)
    assert r.status_code==422 and r.json()['errors'][0]['code']=='INPUT_VALIDATION_ERROR'


def test_actual_storage_permission_error_is_explicit(context,monkeypatch):
    client,_=context
    from backend.api import routes
    def denied(*args,**kwargs):raise PermissionError('injected permission error')
    monkeypatch.setattr(routes,'Persistence',denied)
    body=dict(site_id='DEMO-LH',target_date='2026-09-21',actual_diners=100,prepared_servings=110,
              unserved_leftover_kg=1,plate_waste_kg=1,ingredient_waste_kg=0,shortage=False,notes='',is_demo=True)
    response=client.post('/api/actual-results',json=body)
    assert response.status_code==503 and response.json()['errors'][0]['code']=='PERSISTENCE_FAILED'


def test_history_excludes_post_actual_reforecast_and_demo_training(context):
    client,settings=context
    db=Persistence(settings.database)
    try:
        repo=db.repo
        repo.create_site(site_id='real',site_name='Real',source_type='MANUAL',is_demo=False)
        early=repo.save_prediction(site_id='real',target_date='2026-09-21',predicted_diners=100,
            source_type='MODEL',is_demo=False,record_status='VALIDATED',created_at='2026-09-21T01:00:00Z')
        repo.save_operation_plan(site_id='real',prediction_id=early['prediction_id'],target_date='2026-09-21',
            recommended_servings=110,created_at='2026-09-21T01:00:01Z',source_type='AGENT',is_demo=False,record_status='VALIDATED')
        repo.save_actual_result(site_id='real',target_date='2026-09-21',actual_diners=90,prepared_servings=110,
            created_at='2026-09-21T06:00:00Z',source_type='MANUAL',is_demo=False,record_status='VALIDATED')
        repo.save_prediction(site_id='real',target_date='2026-09-21',predicted_diners=90,
            source_type='MODEL',is_demo=False,record_status='VALIDATED',created_at='2026-09-21T07:00:00Z')
        assert db.history('real')[0]['prediction_id']==early['prediction_id']
        assert db.kpis('real')['prediction_mae']==10
        assert len(get_learning_dataset(repo,'real'))==1
        # Explicit demo record is excluded by the existing helper even if labelled VALIDATED.
        repo.save_actual_result(site_id='real',target_date='2026-09-22',actual_diners=200,source_type='DEMO',is_demo=True,record_status='VALIDATED')
        assert db.kpis('real')['retraining_readiness']['eligible_new_actual_records']==1
    finally:db.close()


def test_size_limit_returns_json(context):
    client,_=context
    r=client.post('/api/plan',content=b' '*(6*1024*1024+1),headers={'Content-Type':'application/json'})
    assert r.status_code==413 and r.json()['errors'][0]['code']=='REQUEST_TOO_LARGE'


@pytest.mark.parametrize('relative',[
    'legacy/integrated/backend/app/repositories/operation_plan_repository.py',
    'legacy/backend-only/lastplate_backend/repositories/operation_plan_repository.py'])
def test_legacy_latest_plan_with_identical_timestamps(tmp_path,relative):
    """Reproduces the original real failure without depending on clock resolution."""
    import importlib.util
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('legacy_repository_test',root/relative)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    repo=module.OperationPlanRepository(tmp_path/'legacy.db')
    for identity in ('first','second'):
        repo.save(plan_id=identity,parent_plan_id=None,site_id='site',meal_date='2026-09-21',meal_type='lunch',
            created_at='2026-09-21T00:00:00+00:00',request={},response={})
    assert repo.get_latest(site_id='site',meal_date='2026-09-21',meal_type='lunch')['id']=='second'
