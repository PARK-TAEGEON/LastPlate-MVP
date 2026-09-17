import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.settings import Settings

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(tmp_path/'month.db'))) as value:yield value

URL='/api/ui/months/2026-09'
SITE='DEMO-LH'
def response(r):
    assert r.status_code==200,r.text
    return r.json()
def setup(client):
    month=response(client.get(URL,params={'site_id':SITE}));c=month['context']
    body=dict(site_id=SITE,expected_revision=0,days=[{k:d[k] for k in ('date','menus','change')} for d in month['days'][18:21]],**{k:c[k] for k in ('attendance','inventory','planned_orders')})
    return response(client.put(URL,json=body)),body
def generate(client,day):
    return response(client.post(URL+'/days/'+day['date']+'/generate',json={'site_id':SITE,'expected_revision':day['revision']}))

def test_month_upload_and_conflicts(client):
    month,body=setup(client)
    assert len(month['days'])==3
    assert all(set(d['menus'])=={'rice','soup','main','side'} for d in month['days'])
    assert len({r['current_stock'] for r in month['context']['inventory']})>10
    assert client.put(URL,json=body).status_code==409
    body['expected_revision']=month['revision'];body['days'][0]['menus']['rice']='없는메뉴'
    assert client.put(URL,json=body).status_code==422
    body['days'][0]['menus']['rice']='백미밥';body['days'][0]['date']='2026-10-01'
    assert client.put(URL,json=body).status_code==422
    r=client.get(URL+'/template');assert r.status_code==200 and 'date,rice,soup,main,side' in r.text
    r=client.post('/api/ui/upload/monthly-menu',data={'site_id':SITE,'target_date':'2026-09-19'},files={'file':('month.csv',r.content,'text/csv')})
    assert r.status_code==200,r.text
    assert r.json()['row_count']==30

@pytest.mark.e2e
def test_month_generation_edit_review_and_actual_link(client):
    month,_=setup(client);d=month['days'][0]
    result=generate(client,d);p=result['plan'];assert p['saved'] and p['calculation_complete'] and len(p['menus'])==4
    assert p['final_servings'] is None
    assert generate(client,d)['plan']['id']==p['id']
    change=dict(reason='단체 방문과 출장',increase=83,decrease=17,note='알 수 없는 기타 사유')
    body=dict(site_id=SITE,expected_revision=d['revision'],menus=d['menus'],change=change)
    month=response(client.put(URL+'/days/'+d['date'],json=body));d=month['days'][0]
    assert client.put(URL+'/days/'+d['date'],json=body).status_code==409
    result=generate(client,d);updated=result['plan'];d=result['month']['days'][0]
    assert updated['model_diners']==p['model_diners']
    assert updated['operating_diners']==p['operating_diners']+66
    assert d['note_review']['needs_review']
    rb=dict(site_id=SITE,expected_revision=d['revision'],plan_id=updated['id'],kind='note',candidate_index=0,decision='accept')
    assert client.post(URL+'/days/'+d['date']+'/review',json=rb).status_code==422
    rb['decision']='reject';review=response(client.post(URL+'/days/'+d['date']+'/review',json=rb));assert not review['needs_recalculation']
    assert client.post(URL+'/days/'+d['date']+'/review',json=rb).status_code==409
    assert response(client.get('/api/ui/plans/'+p['id']))['operating_diners']==p['operating_diners']
    # The current recipe inventory produces native recommendations; a valid slot can be accepted as a new draft.
    applicable=[(i,c) for i,c in enumerate(updated['candidates']) if any(c['original_menu']==name and c['menu'] in result['month']['catalog'][slot] for slot,name in d['menus'].items())]
    if applicable:
        i,c=applicable[0];rb.update(kind='menu',candidate_index=i,decision='accept')
        accepted=response(client.post(URL+'/days/'+d['date']+'/review',json=rb));assert accepted['needs_recalculation']
        newday=accepted['month']['days'][0];assert c['menu'] in newday['menus'].values()
        assert generate(client,newday)['plan']['id']!=updated['id']

@pytest.mark.e2e
def test_parsed_other_reason_acceptance(client):
    month,_=setup(client);d=month['days'][0]
    body=dict(site_id=SITE,expected_revision=d['revision'],menus=d['menus'],change=dict(reason='',increase=0,decrease=0,note='두부 사용 금지'))
    month=response(client.put(URL+'/days/'+d['date'],json=body));result=generate(client,month['days'][0]);d=result['month']['days'][0]
    assert not d['note_review']['needs_review'],d['note_review']
    rb=dict(site_id=SITE,expected_revision=d['revision'],plan_id=result['plan']['id'],kind='note',decision='accept')
    accepted=response(client.post(URL+'/days/'+d['date']+'/review',json=rb));rerun=generate(client,accepted['month']['days'][0])
    assert rerun['plan']['blocked']

@pytest.mark.e2e
def test_failed_month_save_retries_same_calculation(client,monkeypatch):
    import sqlite3
    from backend.adapters.persistence import Persistence
    from backend.api import monthly
    month,_=setup(client);day=month['days'][0];original=Persistence.save_run
    def fail(*args,**kwargs):raise sqlite3.OperationalError('forced test failure')
    monkeypatch.setattr(Persistence,'save_run',fail)
    partial=generate(client,day);assert not partial['plan']['saved']
    assert partial['month']['days'][0]['pending_plan_id']==partial['plan']['id']
    monkeypatch.setattr(Persistence,'save_run',original)
    def forbidden(*args,**kwargs):raise AssertionError('Do not recompute a completed plan')
    monkeypatch.setattr(monthly,'plan',forbidden)
    recovered=generate(client,day)
    assert recovered['plan']['saved'] and recovered['plan']['id']==partial['plan']['id']
    assert recovered['month']['days'][0]['plan_id']==partial['plan']['id']

def test_monthly_xlsx_and_duplicate_dates(client):
    from io import BytesIO
    from openpyxl import Workbook
    wb=Workbook();ws=wb.active;ws.append(['날짜','밥','국','메인반찬','사이드반찬']);ws.append(['2026-09-19','백미밥','된장국','제육볶음','두부조림'])
    stream=BytesIO();wb.save(stream)
    r=client.post('/api/ui/upload/monthly-menu',data={'site_id':SITE,'target_date':'2026-09-19'},files={'file':('month.xlsx',stream.getvalue())})
    assert r.status_code==200,r.text
    assert r.json()['rows'][0]['rice']=='백미밥'
    ws.append(['2026-09-19','백미밥','된장국','제육볶음','두부조림']);stream=BytesIO();wb.save(stream)
    assert client.post('/api/ui/upload/monthly-menu',data={'site_id':SITE,'target_date':'2026-09-19'},files={'file':('month.xlsx',stream.getvalue())}).status_code==422

@pytest.mark.e2e
def test_concurrent_edit_never_attaches_stale_calculation(client,monkeypatch):
    from backend.api import monthly
    month,_=setup(client);day=month['days'][0];original=monthly.plan
    def edit_during_calculation(*args,**kwargs):
        menus={**day['menus'],'rice':'잡곡밥'}
        response(client.put(URL+'/days/'+day['date'],json=dict(site_id=SITE,expected_revision=day['revision'],menus=menus,change=day['change'])))
        return original(*args,**kwargs)
    monkeypatch.setattr(monthly,'plan',edit_during_calculation)
    r=client.post(URL+'/days/'+day['date']+'/generate',json=dict(site_id=SITE,expected_revision=day['revision']))
    assert r.status_code==409,r.text
    current=response(client.get(URL,params={'site_id':SITE}))['days'][0]
    assert current['plan_id'] is None and current['menus']['rice']=='잡곡밥'
    plans=response(client.get('/api/ui/plans',params=dict(site_id=SITE,target_date=day['date'])))
    assert len(plans['plans'])==1

@pytest.mark.e2e
def test_partial_calculation_retries_and_repairs_old_completion_marker(client,monkeypatch):
    import json,sqlite3
    from backend.application import orchestrator
    from integration.errors import StageError
    month,_=setup(client);day=month['days'][0];original=orchestrator.invoke
    def missing_package(stage,*args,**kwargs):
        if stage=='demand':raise StageError(stage,'ModuleNotFoundError',"No module named 'lightgbm'")
        return original(stage,*args,**kwargs)
    monkeypatch.setattr(orchestrator,'invoke',missing_package)
    failed=generate(client,day);p=failed['plan']
    assert p['saved'] and not p['calculation_complete']
    assert p['model_diners'] is None and p['review_servings'] is None
    assert 'requirements.txt' in p['next_action']
    assert '재료 부족 · 유통기한' not in p['next_action']
    assert failed['month']['days'][0]['generated_revision'] is None
    assert 'lightgbm' not in json.dumps(p)  # Raw exception remains in server diagnostics.
    # Emulate a schedule saved by 1.2.0, which incorrectly marked this partial run complete.
    with sqlite3.connect(client.app.state.settings.database) as db:
        row=db.execute('SELECT data_json FROM api_month_schedules WHERE site_id=? AND month=?',(SITE,'2026-09')).fetchone()
        stored=json.loads(row[0]);stored['days'][0]['generated_revision']=day['revision']
        stored['days'][0]['summary'].pop('calculation_complete')
        db.execute('UPDATE api_month_schedules SET data_json=? WHERE site_id=? AND month=?',(json.dumps(stored),SITE,'2026-09'));db.commit()
    assert client.post(URL+'/days/'+day['date']+'/review',json=dict(site_id=SITE,expected_revision=day['revision'],plan_id=p['id'],kind='note',decision='accept')).status_code==409
    loaded=response(client.get(URL,params={'site_id':SITE}))['days'][0]
    assert not loaded['summary']['calculation_complete'] and loaded['generated_revision'] is None
    monkeypatch.setattr(orchestrator,'invoke',original)
    recovered=generate(client,day);new=recovered['plan']
    assert new['saved'] and new['calculation_complete'] and new['id']!=p['id']
    assert not recovered['reused'] and new['model_diners'] is not None
    assert '계산 미완료' not in new['outcome']
    assert generate(client,day)['reused']
    assert not response(client.get('/api/ui/plans/'+p['id']))['calculation_complete']
