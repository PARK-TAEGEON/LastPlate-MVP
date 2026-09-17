"""Server API: explicit configuration, durable IDs, no request-time training."""
import json
import math
import threading
import uuid
import pandas as pd
from ml import time_contract as clock
from ml.time_contract import ServiceConfig,aware_timestamp,target_date
from ml.config import STAFF,WEATHER
from ml.prepare_data import normalize,read_csv
from ml.feature_engineering import features_for_bundle
from ml.evaluate import predictions,monitoring
from ml.model_registry import ModelRegistry
from ml.service_store import ServiceStore,canonical,digest
from ml.weather_contract import weather_for_prediction
from ml.errors import (DemandError,TimeContractError,AvailabilityError,WeatherContractError,
                       NotFound,IdempotencyConflict,RevisionConflict)

_cache={}
_cache_lock=threading.RLock()

def cached_model(path):
    registry=ModelRegistry(path)
    version=registry.current_version()
    with _cache_lock:
        key=str(path)
        if key not in _cache or _cache[key][0]!=version:
            bundle,metadata=registry.load(version)
            _cache[key]=(version,bundle,metadata)
        return _cache[key][1:]

def request_key(value):
    if not isinstance(value,str) or not value.strip() or len(value)>200:
        raise DemandError('request_id must be a nonempty string of <=200 characters')
    return value

def predict_demand(input_data, *, request_id, config:ServiceConfig, availability=None,weather_record_id=None):
    if not isinstance(config,ServiceConfig) or not isinstance(input_data,dict):
        raise DemandError('Explicit ServiceConfig and an input object are required')
    if any(k in input_data for k in ('created_at','predicted_at','prediction_id','model_version','now')):
        raise DemandError('Clients cannot set prediction identity, version, or server time')
    if set(input_data)&set(WEATHER):
        raise WeatherContractError('Use a server weather_record_id, not raw weather values')
    key=request_key(request_id)
    fingerprint=digest(dict(input_data=input_data,availability=availability,weather_record_id=weather_record_id,contract=config.contract()))
    with ServiceStore(config).connection(write=True) as db:
        existing=db.execute('SELECT request_hash,payload FROM predictions WHERE request_key=?',(key,)).fetchone()
        if existing:
            if existing['request_hash']!=fingerprint:
                raise IdempotencyConflict('Same request_id was used for different inputs')
            return json.loads(existing['payload'])
        now=clock.utc_now()
        target=input_data.get('date',input_data.get('일자'))
        target_date(target)
        deadline=config.deadline(target)
        if config.mode=='operation' and now>deadline:
            raise TimeContractError('Operational prediction is after the configured deadline')
        bundle,metadata=cached_model(config.model_dir)
        staff=STAFF if bundle.get('include_overtime',True) else [c for c in STAFF if c!='overtime']
        d=normalize(pd.DataFrame([input_data]),require_target=False,require_overtime='overtime' in staff)
        receipts=availability or {}
        for field in staff:
            receipt=receipts.get(field)
            if receipt is None:
                if config.mode=='operation':
                    raise AvailabilityError(f'Missing real acquisition evidence for {field}')
                continue
            if not isinstance(receipt,dict) or not isinstance(receipt.get('source'),str) or not receipt['source'].strip():
                raise AvailabilityError(f'Missing acquisition source for {field}')
            acquired=aware_timestamp(receipt.get('available_at'))
            if acquired>now or acquired>deadline:
                raise AvailabilityError(f'{field} was not available before prediction/deadline')
        weather=None
        if bundle['group']=='D':
            policy=bundle.get('weather_contract','previous_day_observed')
            features=bundle.get('weather_features',WEATHER)
            weather=weather_for_prediction(db,weather_record_id,config,target,now,policy,features)
            for field in features:
                d[field]=weather['values'][field]
        elif weather_record_id is not None:
            raise WeatherContractError('This model does not use weather')
        pred=int(predictions(bundle['model'],features_for_bundle(bundle,d))[0])
        snapshot={c:float(d.iloc[0][c]) for c in staff}
        snapshot.update(date=target,weekday=d.weekday.iloc[0],menu=d.menu.iloc[0])
        if weather:
            snapshot.update({c:weather['values'][c] for c in bundle.get('weather_features',WEATHER)})
        result=dict(prediction_id=uuid.uuid4().hex,prediction=pred,model_version=metadata['model_version'],
                    created_at=now.isoformat(),target_date=target,deadline_at=deadline.isoformat(),
                    timezone=config.timezone,mode=config.mode,input_data=snapshot,
                    availability=receipts,weather=weather,policy=config.contract(),
                    operational_eligible=config.mode=='operation',
                    availability_status='validated_declared_receipts' if config.mode=='operation' else 'historical_unknown')
        db.execute('INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?)',
                   (result['prediction_id'],key,fingerprint,target,result['created_at'],result['deadline_at'],config.mode,result['model_version'],canonical(result)))
        return result

def count(value,name,optional=False):
    if value is None and optional:
        return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or int(value)!=value:
        raise DemandError(f'{name} must be a finite nonnegative integer')
    return int(value)

def record_actual_result(prediction_id, actual_diners, *, request_id, config:ServiceConfig,
                         measured_at, actor, prepared_servings=None,leftover_servings=None,
                         expected_revision=None, correction_reason=None):
    if not isinstance(prediction_id,str):
        raise DemandError('Supply stored prediction_id, never a client prediction object')
    if not isinstance(actor,str) or not actor.strip():
        raise DemandError('An authenticated server actor is required')
    actual=count(actual_diners,'actual_diners')
    prepared=count(prepared_servings,'prepared_servings',True)
    leftover=count(leftover_servings,'leftover_servings',True)
    if prepared is not None and leftover is not None and leftover>prepared:
        raise DemandError('leftover_servings cannot exceed prepared_servings')
    measured=aware_timestamp(measured_at)
    key=request_key(request_id)
    fingerprint=digest(dict(prediction_id=prediction_id,actual=actual,prepared=prepared,leftover=leftover,
                           measured_at=measured.isoformat(),actor=actor,expected_revision=expected_revision,correction_reason=correction_reason))
    with ServiceStore(config).connection(write=True) as db:
        retry=db.execute('SELECT request_hash,payload FROM actual_events WHERE request_key=?',(key,)).fetchone()
        if retry:
            if retry['request_hash']!=fingerprint:
                raise IdempotencyConflict('Same actual request_id was used for a different operation')
            return json.loads(retry['payload'])
        now=clock.utc_now()
        record=db.execute('SELECT payload FROM predictions WHERE id=?',(prediction_id,)).fetchone()
        if record is None:
            raise NotFound('Prediction ID does not exist in this server mode/store')
        prediction=json.loads(record['payload'])
        target=prediction['target_date']
        stored=prediction['policy']
        policy=ServiceConfig(config.storage_dir,config.model_dir,stored['timezone'],stored['cutoff_time'],stored['actual_ready_time'],stored['mode'],stored['deadline_days_before'])
        if measured>now:
            raise TimeContractError('Future actual measurement is invalid')
        if config.mode=='operation':
            if not prediction['operational_eligible'] or aware_timestamp(prediction['created_at'])>aware_timestamp(prediction['deadline_at']):
                raise TimeContractError('Late/non-operational prediction is ineligible')
            if now<policy.actual_ready(target) or measured<policy.actual_ready(target):
                raise TimeContractError('Actual is before target meal completion or in the future')
        previous=db.execute('SELECT revision,payload FROM actuals WHERE prediction_id=?',(prediction_id,)).fetchone()
        if previous:
            if type(expected_revision) is not int or expected_revision!=previous['revision']:
                raise RevisionConflict('Correction requires the current expected_revision')
            if not isinstance(correction_reason,str) or not correction_reason.strip():
                raise RevisionConflict('Correction reason is required')
            revision=previous['revision']+1
        else:
            if expected_revision is not None:
                raise RevisionConflict('Initial result must not specify expected_revision')
            if db.execute('SELECT 1 FROM actuals WHERE target_date=?',(target,)).fetchone():
                raise RevisionConflict('Meal/date already has an actual; correct its original prediction ID')
            revision=1
        result=dict(prediction_id=prediction_id,date=target,model_version=prediction['model_version'],
                    predicted_diners=prediction['prediction'],actual_diners=actual,prediction_error=actual-prediction['prediction'],revision=revision,
                    measured_at=measured.isoformat(),recorded_at=now.isoformat(),actor=actor,prepared_servings=prepared,
                    leftover_servings=leftover,mode=config.mode,correction_reason=correction_reason)
        db.execute('INSERT INTO actuals VALUES (?,?,?,?) ON CONFLICT(prediction_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',
                   (prediction_id,target,revision,canonical(result)))
        db.execute('INSERT INTO actual_events VALUES (?,?,?,?,?,?,?,?,?)',
                   (key,fingerprint,prediction_id,revision,canonical(result),previous['payload'] if previous else None,result['recorded_at'],actor,correction_reason or 'initial'))
        return result

def history(config):
    with ServiceStore(config).connection() as db:
        rows=db.execute('SELECT a.payload actual,p.payload prediction FROM actuals a JOIN predictions p ON p.id=a.prediction_id ORDER BY a.target_date').fetchall()
    return [(json.loads(r['prediction']),json.loads(r['actual'])) for r in rows]

def get_monitoring(*,config):
    return monitoring(pd.DataFrame([a for _,a in history(config)]))

def read_history(path):
    """Read-only legacy CSV inspection. New operations never write this file."""
    return read_csv(path)
