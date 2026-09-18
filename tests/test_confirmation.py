import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.settings import Settings

URL='/api/ui/months/2026-09'
DAY=URL+'/days/2026-09-19'
SITE='DEMO-LH'

def ok(response):
    assert response.status_code==200,response.text
    return response.json()

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(tmp_path/'confirmation.db'))) as client:
        month=ok(client.get(URL,params={'site_id':SITE}));c=month['context'];d=month['days'][18]
        for row in c['inventory']:row['current_stock']=1000
        ok(client.put(URL,json=dict(site_id=SITE,expected_revision=0,days=[{k:d[k] for k in ('date','menus','change')}],
                                    **{k:c[k] for k in ('attendance','inventory','planned_orders')})))
        yield client

def day(client):return ok(client.get(URL,params={'site_id':SITE}))['days'][0]
def change(client,diners):
    d=day(client)
    return ok(client.put(DAY,json=dict(site_id=SITE,expected_revision=d['revision'],menus=d['menus'],change=d['change'],diners=diners)))['days'][0]
def generate(client):
    return ok(client.post(DAY+'/generate',json=dict(site_id=SITE,expected_revision=day(client)['revision'])))['plan']
def confirmation(client,p,**kwargs):
    return client.post(DAY+'/confirm',json=dict(site_id=SITE,expected_revision=day(client)['revision'],plan_id=p['id'],warnings_reviewed=True,**kwargs))

@pytest.mark.e2e
def test_confirmation_recalculates_persists_and_invalidates(client):
    p=generate(client)
    assert confirmation(client,p).status_code==409  # explicit operator count required
    change(client,900);p=generate(client)
    assert p['operating_diners']==900 and p['model_diners']!=900
    assert p['review_servings']>=900 and p['final_servings'] is None
    confirmed=ok(confirmation(client,p))['plan']
    assert confirmed['final_servings']==p['review_servings']
    assert confirmed['confirmed_diners']==900 and confirmed['outcome']=='시연 조리량 확정'
    assert ok(confirmation(client,p))['plan']['confirmed_at']==confirmed['confirmed_at']
    assert ok(client.get('/api/ui/plans/'+p['id']))['final_servings']==confirmed['final_servings']
    assert day(client)['summary']['confirmed_at']==confirmed['confirmed_at']
    change(client,1000)
    assert ok(client.get('/api/ui/plans/'+p['id']))['final_servings'] is None
    assert confirmation(client,p).status_code==409
    newer=generate(client)
    assert newer['operating_diners']==1000 and newer['model_diners']==p['model_diners']
    assert newer['review_servings']>p['review_servings']
    assert newer['final_servings'] is None
    old_material={r['ingredient']:r['required_kg'] for r in p['materials']}
    assert any(r['required_kg']>old_material[r['ingredient']] for r in newer['materials'])

@pytest.mark.e2e
def test_demo_providers_apply_clear_and_preserve_inventory(client):
    before=ok(client.get(URL,params={'site_id':SITE}));original=before['context']['inventory']
    providers=ok(client.get(DAY+'/data-examples',params={'site_id':SITE}))
    assert len(providers['providers'])==4
    assert all(1<=len(p['rows'])<=2 and p['mode']=='demo' for p in providers['providers'])
    p=generate(client)
    selected=['recipe','nutrition','price','supply']
    updated=ok(client.post(DAY+'/data-examples',json=dict(site_id=SITE,expected_revision=day(client)['revision'],providers=selected)))
    assert updated['context']['inventory']==original
    newer=generate(client)
    assert newer['calculation_complete'] and newer['saved']
    assert len(newer['data_examples'])==4 and newer['price_changes'] and newer['supply_risks']
    assert newer['model_diners']==p['model_diners']
    assert newer['materials']!=p['materials']
    ok(client.post(DAY+'/data-examples',json=dict(site_id=SITE,expected_revision=day(client)['revision'],providers=[])))
    restored=generate(client)
    assert not restored['data_examples'] and restored['materials']==p['materials']
    assert not restored['price_changes'] and not restored['supply_risks']

@pytest.mark.e2e
def test_capacity_and_partial_cannot_be_confirmed(client):
    change(client,100000);p=generate(client)
    assert confirmation(client,p).status_code==409

def test_invalid_count_and_missing_review_rejected(client):
    d=day(client);body=dict(site_id=SITE,expected_revision=d['revision'],menus=d['menus'],change=d['change'])
    for value in [-1,1.5,True]:assert client.put(DAY,json={**body,'diners':value}).status_code==422
    assert client.post(DAY+'/confirm',json=dict(site_id=SITE,expected_revision=d['revision'],plan_id='unknown',warnings_reviewed=False)).status_code==422
