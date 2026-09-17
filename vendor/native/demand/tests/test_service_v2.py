"""Synthetic clocks/values stay in tmp_path; never in delivered operation stores."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor
from ml.config import STAFF,ROOT
from ml.feature_engineering import build_features,menu_features
from ml.model_registry import ModelRegistry
from ml.time_contract import ServiceConfig
from ml import time_contract as clock
from ml.service_store import ServiceStore,canonical
from ml.weather_contract import register_weather
from ml.errors import (DemandError,TimeContractError,AvailabilityError,IdempotencyConflict,
                       RevisionConflict,WeatherContractError,NotFound)
from tools.demand import predict_demand,record_actual_result,get_monitoring
from tools.forecast import predict_forecast_demand
from adapters.service import predict_node

FIELDS=['temp_mean','temp_max','temp_min','humidity']

def dummy(group='B',value=900,include_overtime=True):
    d=pd.DataFrame([dict(date=pd.Timestamp('2026-09-21'),employees=2800,vacation=100,
                         business_trip=100,work_from_home=100,overtime=20,menu='불고기 국수',
                         temp_mean=20,temp_max=25,temp_min=15,humidity=70)])
    x=build_features(d,group,FIELDS,'v2',include_overtime)
    bundle=dict(model=DummyRegressor(strategy='constant',constant=value).fit(x,[900]),kind='lightgbm',
                group=group,features=list(x),feature_rules_version='v2',include_overtime=include_overtime)
    if group=='D':
        bundle['weather_features']=FIELDS
        bundle['weather_contract']='previous_day_observed'
    return bundle

@pytest.fixture
def service(tmp_path,monkeypatch):
    now=[datetime(2026,9,21,0,0,tzinfo=timezone.utc)]
    monkeypatch.setattr(clock,'utc_now',lambda:now[0])
    cfg=ServiceConfig(tmp_path/'storage',tmp_path/'models','Asia/Seoul','10:00','14:00')
    r=ModelRegistry(cfg.model_dir)
    r.promote(dummy(),dict(trained_through='2021-01-26'))
    inputs=dict(date='2026-09-21',employees=2800,vacation=100,business_trip=100,work_from_home=100,overtime=20,menu='불고기 국수')
    availability={f:dict(available_at='2026-09-21T08:00:00+09:00',source='test_fixture') for f in STAFF}
    return cfg,inputs,availability,now

def predict(service,key='p'):
    c,x,a,n=service
    return predict_demand(x,config=c,request_id=key,availability=a)

def actual(service,p,key='a',**kw):
    c,x,a,n=service;n[0]=datetime(2026,9,21,6,tzinfo=timezone.utc)
    return record_actual_result(p['prediction_id'],910,config=c,request_id=key,measured_at='2026-09-21T14:00:00+09:00',actor='test_operator',**kw)

def test_durable_retry_after_deadline_and_model_change(service):
    c,x,a,n=service;p=predict(service)
    r=ModelRegistry(c.model_dir);r.promote(dummy(value=1000),{},expected_current=p['model_version'])
    n[0]+=timedelta(hours=2)
    assert predict(service)==p
    with ServiceStore(c).connection() as db:
        assert db.execute('SELECT count(*) FROM predictions').fetchone()[0]==1

def test_model_cache_refreshes_on_new_request(service):
    c,x,a,n=service;p=predict(service)
    r=ModelRegistry(c.model_dir);r.promote(dummy(value=1000),{},expected_current=p['model_version'])
    new=predict(service,'p2')
    assert new['prediction']==1000 and new['model_version']!=p['model_version']

def test_concurrent_prediction_retry(service):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:predict(service),range(4)))
    assert len({p['prediction_id'] for p in results})==1

def test_changed_request_conflicts(service):
    predict(service);service[1]['employees']+=1
    with pytest.raises(IdempotencyConflict):predict(service)

@pytest.mark.parametrize('value',['bad','2026-09-21T08:00:00','2026-09-21T10:30:00+09:00'])
def test_bad_input_acquisition_times(service,value):
    service[2]['overtime']['available_at']=value
    with pytest.raises((TimeContractError,AvailabilityError)):predict(service)

def test_unknown_overtime_availability_fails(service):
    del service[2]['overtime']
    with pytest.raises(AvailabilityError):predict(service)

def test_no_overtime_model_does_not_require_overtime(service):
    c,x,a,n=service;r=ModelRegistry(c.model_dir)
    r.promote(dummy(include_overtime=False),{},expected_current=r.current_version())
    del x['overtime'];del a['overtime']
    p=predict(service)
    assert 'overtime' not in p['input_data']

def test_deadline_boundary_and_late_predictions(service):
    c,x,a,n=service;n[0]=c.deadline(x['date'])
    predict(service)
    n[0]+=timedelta(microseconds=1)
    with pytest.raises(TimeContractError):predict(service,'late')

@pytest.mark.parametrize('field',['created_at','predicted_at','model_version','now'])
def test_client_cannot_set_identity_or_clock(service,field):
    service[1][field]='forged'
    with pytest.raises(DemandError):predict(service)

def test_server_id_actuals_and_correction_history(service):
    p=predict(service);a=actual(service,p)
    assert actual(service,p)==a
    c,x,av,n=service
    b=record_actual_result(p['prediction_id'],920,config=c,request_id='correction',measured_at='2026-09-21T14:00:00+09:00',
                           actor='test_operator',expected_revision=1,correction_reason='counter reconciled')
    assert b['revision']==2 and b['predicted_diners']==900
    assert actual(service,p)==a # Original request's exact response remains stable.
    with ServiceStore(c).connection() as db:
        assert db.execute('SELECT count(*) FROM actual_events').fetchone()[0]==2
        previous=json.loads(db.execute('SELECT previous_payload FROM actual_events WHERE revision=2').fetchone()[0])
        assert previous['actual_diners']==910
    assert get_monitoring(config=c)['overall_mae']==20

def test_client_prediction_object_and_unknown_id_rejected(service):
    p=predict(service);c,x,a,n=service;n[0]+=timedelta(hours=6)
    for obj,error in [(p,DemandError),('unknown-id',NotFound)]:
        with pytest.raises(error):
            record_actual_result(obj,5,config=c,request_id='a',measured_at='2026-09-21T14:00:00+09:00',actor='test')

def test_correction_revision_and_reason_required(service):
    p=predict(service);actual(service,p)
    with pytest.raises(RevisionConflict):actual(service,p,'new')
    with pytest.raises(RevisionConflict):actual(service,p,'new',expected_revision=1)

def test_actual_request_payload_change_conflict(service):
    p=predict(service);actual(service,p)
    with pytest.raises(IdempotencyConflict):actual(service,p,expected_revision=1,correction_reason='changed')

def test_future_actual_and_early_meal_rejected(service):
    c,x,a,n=service;p=predict(service)
    with pytest.raises(TimeContractError):
        record_actual_result(p['prediction_id'],900,config=c,request_id='a',measured_at='2026-09-22T14:00:00+09:00',actor='test')
    n[0]+=timedelta(hours=3)
    with pytest.raises(TimeContractError):
        record_actual_result(p['prediction_id'],900,config=c,request_id='b',measured_at='2026-09-21T11:00:00+09:00',actor='test')

def test_late_stored_prediction_defense(service):
    p=predict(service);c,x,a,n=service
    p['created_at']='2026-09-21T02:00:00+00:00'
    with ServiceStore(c).connection(write=True) as db:
        db.execute('UPDATE predictions SET payload=? WHERE id=?',(canonical(p),p['prediction_id']))
    with pytest.raises(TimeContractError):actual(service,p)

def test_replay_is_physically_separate_and_has_no_faked_historical_time(service):
    c,x,a,n=service;replay=replace(c,mode='replay');x=dict(x,date='2021-01-26')
    p=predict_demand(x,config=replay,request_id='historical')
    assert p['created_at'].startswith('2026-') and not p['operational_eligible']
    assert p['availability_status']=='historical_unknown'
    record_actual_result(p['prediction_id'],900,config=replay,request_id='a',measured_at='2021-01-26T14:00:00+09:00',actor='test')
    assert get_monitoring(config=c)['count']==0
    assert get_monitoring(config=replay)['count']==1

def weather(service,**changes):
    c,x,a,n=service
    payload=dict(kind='previous_day_observed',observed_date='2026-09-20',available_at='2026-09-21T01:00:00+09:00',
                 source='KMA_ASOS',values=dict(temp_mean=20,temp_max=25,temp_min=15,humidity=70,precipitation=None))
    payload.update(changes)
    return register_weather(c,payload)

def use_d(service):
    c,x,a,n=service;r=ModelRegistry(c.model_dir)
    r.promote(dummy('D'),{},expected_current=r.current_version())

def test_observed_weather_contract_and_null_rain(service):
    use_d(service);wid=weather(service);c,x,a,n=service
    p=predict_demand(x,config=c,request_id='p',availability=a,weather_record_id=wid)
    assert p['weather']['values']['precipitation'] is None
    assert p['input_data']['temp_mean']==20

@pytest.mark.parametrize('changes',[{'source':'unknown'},{'available_at':'2026-09-22T00:00:00Z'},
                                    {'available_at':'2026-09-20T20:00:00+09:00'}])
def test_bad_weather_source_and_availability(service,changes):
    with pytest.raises(WeatherContractError):weather(service,**changes)

def test_wrong_observation_day(service):
    use_d(service);wid=weather(service,observed_date='2026-09-19');c,x,a,n=service
    with pytest.raises(WeatherContractError):predict_demand(x,config=c,request_id='p',availability=a,weather_record_id=wid)

def test_forecast_cannot_enter_observation_model(service):
    use_d(service);c,x,a,n=service
    wid=register_weather(c,dict(kind='same_day_forecast',target_date=x['date'],source='KMA_ASOS',
                               issued_at='2026-09-21T06:00:00+09:00',available_at='2026-09-21T06:10:00+09:00',
                               values=dict(temp_mean=20,temp_max=25,temp_min=15,humidity=70)))
    with pytest.raises(WeatherContractError):predict_demand(x,config=c,request_id='p',availability=a,weather_record_id=wid)
    with pytest.raises(WeatherContractError):predict_forecast_demand(x,config=c,request_id='p',availability=a,weather_record_id=wid)

def test_forecast_issue_time_and_explicit_route(service):
    c,x,a,n=service;r=ModelRegistry(c.model_dir);bundle=dummy('D');bundle['weather_contract']='same_day_forecast'
    r.promote(bundle,{},expected_current=r.current_version()) # Synthetic test model, not an actual trained forecast model.
    payload=dict(kind='same_day_forecast',target_date=x['date'],source='KMA_ASOS',issued_at='2026-09-21T10:00:00+09:00',
                 available_at='2026-09-21T08:00:00+09:00',values=dict(temp_mean=20,temp_max=25,temp_min=15,humidity=70))
    with pytest.raises(WeatherContractError):register_weather(c,payload)
    payload['issued_at']='2026-09-21T07:00:00+09:00';wid=register_weather(c,payload)
    result=predict_forecast_demand(x,config=c,request_id='f',availability=a,weather_record_id=wid)
    assert result['weather']['kind']=='same_day_forecast'

def test_menu_version_fixes():
    assert menu_features('불고기','v1')['menu_meat']==0
    assert menu_features('불고기','v2')['menu_meat']==1
    assert menu_features('잔치국수','v2')['menu_soup']==0
    assert menu_features('국수 된장국','v2')['menu_soup']==1

def test_adapter_error_is_typed(service):
    c,x,a,n=service
    result=predict_node({'request_id':'bad','input_data':{}},c)
    assert result['error']['code']=='time_contract_error'
    assert result['error']['retryable'] is False

def test_real_legacy_model_prediction_unchanged(service):
    c,x,a,n=service
    old=json.loads((ROOT/'reports/inference_smoke.json').read_text(encoding='utf-8'))['result']
    p=predict_demand(old['input_data'],config=replace(c,mode='replay',model_dir=ROOT/'models'),request_id='legacy')
    assert p['prediction']==old['prediction'] and p['model_version']==old['model_version']

def test_forged_returned_object_does_not_change_server_record(service):
    p=predict(service);p['prediction']=99999;p['created_at']='1900-01-01T00:00:00Z'
    result=actual(service,p)
    assert result['predicted_diners']==900

def test_invalid_availability_and_extra_input_fields(service):
    c,x,a,n=service
    with pytest.raises(AvailabilityError):predict_demand(x,config=c,request_id='bad',availability=[])
    with pytest.raises(DemandError):predict_demand(dict(x,actual_diners=999),config=c,request_id='bad',availability=a)

def test_xgboost_parameter_sentinel_is_auditable_json():
    from ml.provenance import model_parameters
    from ml.train import make_model
    params=model_parameters(make_model('xgboost'))
    assert params['missing']=='NaN'
    json.dumps(params,allow_nan=False)

def test_retry_survives_server_policy_change(service):
    c,x,a,n=service;p=predict(service)
    updated=replace(c,cutoff_time='11:00')
    assert predict_demand(x,config=updated,request_id='p',availability=a)==p
