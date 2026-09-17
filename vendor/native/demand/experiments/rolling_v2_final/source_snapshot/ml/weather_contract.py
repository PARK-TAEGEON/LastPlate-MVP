"""Ingestion is an authenticated server/admin operation, not a client input."""
from datetime import timedelta
import json
import math
from . import time_contract as clock
from .time_contract import aware_timestamp,target_date
from .service_store import ServiceStore,canonical,digest
from .errors import WeatherContractError,NotFound
from .config import WEATHER

def register_weather(config, payload):
    p=dict(payload)
    if p.get('source') not in config.trusted_weather_sources:
        raise WeatherContractError('Unregistered weather source')
    kind=p.get('kind')
    if kind not in ('previous_day_observed','same_day_forecast'):
        raise WeatherContractError('Unsupported weather contract')
    available=aware_timestamp(p.get('available_at'))
    now=clock.utc_now()
    if available>now:
        raise WeatherContractError('Weather availability cannot be in the future')
    values=p.get('values',{})
    if not isinstance(values,dict) or not values or not set(values).issubset(WEATHER):
        raise WeatherContractError('Invalid weather values')
    for k,v in values.items():
        if v is None:
            continue
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
            raise WeatherContractError('Weather values must be finite numbers or null')
        if k=='humidity' and not 0<=v<=100 or k=='rain' and v not in (0,1) or k=='precipitation' and v<0:
            raise WeatherContractError('Weather value outside its physical contract')
    if all(values.get(k) is not None for k in ('temp_min','temp_mean','temp_max')):
        if not values['temp_min']<=values['temp_mean']<=values['temp_max']:
            raise WeatherContractError('Temperature extrema are inconsistent')
    if kind=='previous_day_observed':
        end=config.local_instant(target_date(p.get('observed_date'))+timedelta(days=1),'00:00')
        if available<end or 'issued_at' in p:
            raise WeatherContractError('Observed day availability or forecast field is invalid')
    else:
        target_date(p.get('target_date'))
        if aware_timestamp(p.get('issued_at'))>available:
            raise WeatherContractError('Forecast issuance must not follow availability')
    p['available_at']=available.isoformat()
    p['ingested_at']=now.isoformat()
    record_id=digest({k:v for k,v in p.items() if k!='ingested_at'})
    with ServiceStore(config).connection(write=True) as db:
        db.execute('INSERT OR IGNORE INTO weather VALUES (?,?,?)',(record_id,kind,canonical(p)))
    return record_id

def weather_for_prediction(db, record_id, config, target, prediction_time, required_kind, features):
    row=db.execute('SELECT payload FROM weather WHERE id=?',(record_id,)).fetchone()
    if row is None:
        raise NotFound('Unknown server weather record')
    p=json.loads(row['payload'])
    if p['kind']!=required_kind or p['source'] not in config.trusted_weather_sources:
        raise WeatherContractError('Weather kind/source does not match the trained contract')
    if aware_timestamp(p['available_at'])>prediction_time or aware_timestamp(p['ingested_at'])>prediction_time:
        raise WeatherContractError('Weather was not available on this server at prediction time')
    if required_kind=='previous_day_observed':
        if target_date(p['observed_date'])!=target_date(target)-timedelta(days=1):
            raise WeatherContractError('D requires the previous calendar day')
    elif required_kind=='same_day_forecast':
        if p['target_date']!=target or aware_timestamp(p['issued_at'])>prediction_time:
            raise WeatherContractError('Forecast date or issue time is invalid')
    else:
        raise WeatherContractError('Unsupported model weather contract')
    if any(p['values'].get(k) is None for k in features):
        raise WeatherContractError('Required weather is missing; no automatic zero/imputation')
    return p
