import json,sqlite3
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.settings import Settings
from backend.adapters.persistence import Persistence

DAY='2026-09-19'

@pytest.fixture
def ui(tmp_path):
    settings=Settings(tmp_path/'ui.db')
    with TestClient(create_app(settings)) as client:yield client,settings

def inputs(client,site='DEMO-LH'):
    context=client.get('/api/ui/context',params={'site_id':site,'target_date':DAY}).json()
    return {k:context[k] for k in ('site_id','target_date','base_request_id','attendance','weekly_menu','inventory','planned_orders','events','menu_uploaded','inventory_uploaded')}

def generate(client,site='DEMO-LH'):
    response=client.post('/api/ui/plan',json=inputs(client,site))
    assert response.status_code==200,response.text
    assert response.json()['saved'] is True,response.text
    return response.json()

def actual_body(plan):
    return dict(site_id=plan['site_id'],target_date=plan['target_date'],plan_request_id=plan['id'],actual_diners=1180,prepared_servings=1227,
        unserved_leftover_kg=3,plate_waste_kg=2,ingredient_waste_kg=None,shortage=False,notes='UI 검증용 가상 결과')

def test_debug_and_raw_contract_are_not_an_unauthenticated_backdoor(ui,tmp_path):
    client,_=ui
    for path in ('/debug','/debug/app.js','/admin','/admin/app.js','/api/admin/settings/DEMO-LH','/docs','/openapi.json','/api/demo-profile','/api/plans/missing','/api/kpis/DEMO-LH'):
        assert client.get(path).status_code==404,path
    assert client.get('/assets/developer/app.js').status_code==404
    assert client.get('/api/health').json()=={'status':'ok'}
    assert client.get('/api/ui/sites').status_code==200
    with TestClient(create_app(Settings(tmp_path/'debug.db',debug_enabled=True,debug_token='test-access'))) as secured:
        assert secured.get('/debug').status_code==401
        assert secured.get('/debug',auth=('developer','wrong')).status_code==401
        assert secured.get('/debug',auth=('developer','test-access')).status_code==200
        assert secured.get('/api/demo-profile',auth=('developer','test-access')).status_code==200

def test_context_is_server_owned_orders_unspecified_and_population_distinct(ui):
    client,_=ui
    p=inputs(client)
    assert p['planned_orders']==[]
    p['attendance']['registered_population']=600
    assert client.post('/api/ui/plan',json=p).status_code==409
    assert inputs(client,'DEMO-SMALL')['attendance']['registered_population']==600

def test_event_preview_is_scoped_and_unclear_text_does_not_become_zero(ui):
    client,_=ui
    r=client.post('/api/ui/events/preview',json={'site_id':'DEMO-LH','target_date':DAY,'events':['내일 손님 80명 추가']}).json()
    assert r['attendance_delta']==80 and r['rows'][0]['date']==DAY
    unknown=client.post('/api/ui/events/preview',json={'site_id':'DEMO-LH','target_date':DAY,'events':['알 수 없는 문장']}).json()
    assert unknown['needs_review']

@pytest.mark.e2e
def test_ui_plan_allowlist_context_list_acknowledgement_and_ood(ui):
    client,_=ui
    plan=generate(client,'DEMO-SMALL')
    assert plan['ood'] and plan['final_servings'] is None
    assert '미확정' in plan['outcome']
    for name in ('trace','model_version','source_payload','confidence','prediction_id','pipeline_status','persistence_ids'):
        assert name not in json.dumps(plan),name
    records=client.get('/api/ui/plans',params={'site_id':'DEMO-SMALL','target_date':DAY}).json()['plans']
    assert records[0]['id']==plan['id'] and records[0]['version']==1
    assert client.get('/api/ui/context',params={'site_id':'DEMO-LH','target_date':DAY,'plan_id':plan['id']}).status_code==409
    ack=client.post(f"/api/ui/plans/{plan['id']}/acknowledgement").json()
    loaded=client.get(f"/api/ui/plans/{plan['id']}").json()
    assert loaded['acknowledged_at']==ack['acknowledged_at']
    assert loaded['outcome']==plan['outcome'] and loaded['final_servings'] is None

@pytest.mark.e2e
def test_replan_differences_and_actual_exact_link_survive_correction_and_restart(ui):
    client,settings=ui
    first=generate(client)
    second=client.post('/api/ui/replan',json={'existing_context':first['id'],'events':['내일 손님 80명 추가']}).json()
    assert second['model_diners']==first['model_diners']
    assert second['changes']['diners_delta']==80 and second['changes']['servings_delta']==83
    body=actual_body(second)
    response=client.post('/api/ui/actual',json=body)
    assert response.status_code==200,response.text
    record=response.json()['record']
    assert record['model_difference']==20 and record['operating_difference']==-60
    assert record['ingredient_waste_kg'] is None and bool(record['is_demo'])
    assert client.post('/api/ui/actual',json={**body,'site_id':'DEMO-SMALL'}).status_code==409
    assert client.post('/api/ui/actual',json={**body,'is_demo':False}).status_code==409
    changed={**body,'actual_diners':1181,'reason':'집계 누락 1명 반영','expected_revision':record['revision']}
    response=client.post('/api/ui/actual/correct',json=changed)
    assert response.status_code==200,response.text
    fixed=response.json()['record']
    assert fixed['actual_diners']==1181 and fixed['model_difference']==21 and fixed['operating_difference']==-59
    assert fixed['created_at']==record['created_at']
    assert fixed['corrections'][0]['reason']==changed['reason']
    assert client.post('/api/ui/actual/correct',json={**changed,'actual_diners':1182}).status_code==409
    db=Persistence(settings.database)
    try:
        audit=db.repo.get_actual_corrections('DEMO-LH',DAY)[0]
        assert audit['old_values_json']['actual_diners']==1180 and audit['new_values_json']['actual_diners']==1181
    finally:db.close()
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get('/api/ui/actual',params={'site_id':'DEMO-LH','target_date':DAY}).json()['record']==fixed
        assert restarted.get('/api/ui/actual',params={'site_id':'DEMO-LH','target_date':'2026-09-20'}).json()['record'] is None

@pytest.mark.e2e
def test_risk_view_keeps_blocked_stock_and_unusable_candidates(ui):
    client,_=ui
    plan=generate(client,'DEMO-RISK')
    assert plan['blocked']
    tofu=next(r for r in plan['materials'] if r['ingredient']=='두부')
    assert tofu['required_kg']==23.9 and tofu['stock_kg']==38 and tofu['additional_kg']==0
    assert tofu['planned_kg'] is None and tofu['order_review']=='미입력 · 확인 필요'
    assert all(not c['eligible'] for c in plan['candidates'])
    assert any('영양' in ' '.join(c['reasons']) for c in plan['candidates'])
    assert any('유통기한' in i['title'] for i in plan['issues'])
    assert len(plan['issues'])==len(set((i['title'],i['target']) for i in plan['issues']))
    assert any(m['menu']=='된장국' for m in plan['affected_menus'])
    assert plan['price_changes'] and plan['supply_risks']

@pytest.mark.e2e
def test_order_arrival_is_a_note_and_events_can_be_removed(ui):
    client,_=ui
    p=inputs(client)
    p['planned_orders']=[{'ingredient':'두부','planned_order':5,'unit':'kg','arrival_date':'2026-09-19'}]
    p['events']=['내일 손님 80명 추가']
    response=client.post('/api/ui/plan',json=p)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['operating_diners']==1240 and result['review_servings']==1278
    tofu=next(r for r in result['materials'] if r['ingredient']=='두부')
    assert tofu['arrival_date']=='2026-09-19' and tofu['arrival']=='입고 확인 필요'
    cleared=client.post('/api/ui/replan',json={'existing_context':result['id'],'events':[]})
    assert cleared.status_code==200,cleared.text
    assert cleared.json()['operating_diners']==1160
    assert cleared.json()['changes']['diners_delta']==-80

@pytest.mark.e2e
def test_site_settings_are_protected_persistent_and_do_not_rewrite_saved_plan(ui):
    client,settings=ui
    existing=generate(client)
    config=Settings(settings.database,debug_enabled=True,debug_token='test-admin')
    auth=('developer','test-admin')
    endpoint='/api/admin/settings/DEMO-LH?target_date='+DAY
    with TestClient(create_app(config)) as admin:
        response=admin.get(endpoint,auth=auth)
        assert response.status_code==200,response.text
        body=response.json()['settings']
        assert body['registered_population']==3000
        assert response.json()['recipes'] and response.json()['prices']
        body.update(registered_population=3200,meal_capacity=2300,safety_margin_pct=5)
        assert admin.put(endpoint,json=body).status_code==401
        result=admin.put(endpoint,json=body,auth=auth)
        assert result.status_code==200,result.text
        assert admin.put(endpoint,json={**body,'calorie_min':9999,'calorie_max':500},auth=auth).status_code==422
    with TestClient(create_app(config)) as restarted:
        fresh=inputs(restarted)
        assert fresh['attendance']['registered_population']==3200
        stored=restarted.get('/api/ui/context',params={'site_id':'DEMO-LH','target_date':DAY,'plan_id':existing['id']}).json()
        assert stored['attendance']['registered_population']==3000
        assert restarted.get('/api/ui/plans/'+existing['id']).json()['margin_pct']==3

@pytest.mark.e2e
def test_failed_run_save_retry_does_not_recompute_or_duplicate(ui,monkeypatch):
    client,settings=ui
    original=Persistence.save_run
    def broken(*args,**kwargs):raise sqlite3.OperationalError('forced run save failure')
    monkeypatch.setattr(Persistence,'save_run',broken)
    response=client.post('/api/ui/plan',json=inputs(client))
    assert response.status_code==200
    partial=response.json();assert not partial['saved'] and partial['review_servings'] is not None
    monkeypatch.setattr(Persistence,'save_run',original)
    from backend.api import workspace
    def recompute_forbidden(*args,**kwargs):raise AssertionError('must not recompute')
    monkeypatch.setattr(workspace,'plan',recompute_forbidden)
    retried=client.post(f"/api/ui/plans/{partial['id']}/retry-save")
    assert retried.status_code==200,retried.text
    assert retried.json()['saved'] and retried.json()['model_diners']==partial['model_diners']
    assert client.post(f"/api/ui/plans/{partial['id']}/retry-save").json()==retried.json()
    with sqlite3.connect(settings.database) as db:
        assert db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0]==1

def test_upload_error_and_business_only_reply(ui):
    client,_=ui
    content=f'date,meal_type,menu_name\n{DAY},lunch,두부조림\n'.encode('utf-8')
    r=client.post('/api/ui/upload/menu',files={'file':('menu.csv',content)},data={'site_id':'DEMO-LH','target_date':DAY})
    assert r.status_code==200
    assert r.json()['row_count']==1 and 'source_type' not in r.json()
    invalid=client.post('/api/ui/upload/menu',files={'file':('menu.csv',b'wrong\n1')},data={'site_id':'DEMO-LH','target_date':DAY})
    assert invalid.status_code==422
