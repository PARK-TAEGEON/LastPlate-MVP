import json
from pathlib import Path
from ml.time_contract import ServiceConfig
from ml.errors import DemandError
from tools.demand import predict_demand,record_actual_result

def load_config(path):
    path=Path(path)
    if not path.is_absolute():
        raise ValueError('Config path must be explicit and absolute')
    raw=json.loads(path.read_text(encoding='utf-8'))
    raw.pop('gate_policy',None)
    return ServiceConfig(**raw)

def predict_node(state,config):
    try:
        result=predict_demand(state['input_data'],request_id=state['request_id'],config=config,
                              availability=state.get('availability'),weather_record_id=state.get('weather_record_id'))
        return {'result':result,'error':None}
    except DemandError as exc:
        return {'result':None,'error':{'code':exc.code,'message':str(exc),'retryable':exc.retryable}}
    except (ValueError,TypeError,KeyError) as exc:
        return {'result':None,'error':{'code':'validation_error','message':str(exc),'retryable':False}}

def actual_node(state,config,authenticated_actor):
    """Actor is supplied by server authentication, not read from user state."""
    try:
        result=record_actual_result(state['prediction_id'],state['actual_diners'],request_id=state['request_id'],
                                    config=config,actor=authenticated_actor,measured_at=state['measured_at'],
                                    expected_revision=state.get('expected_revision'),correction_reason=state.get('correction_reason'),
                                    prepared_servings=state.get('prepared_servings'),leftover_servings=state.get('leftover_servings'))
        return {'result':result,'error':None}
    except DemandError as exc:
        return {'result':None,'error':{'code':exc.code,'message':str(exc),'retryable':exc.retryable}}
    except (ValueError,TypeError,KeyError) as exc:
        return {'result':None,'error':{'code':'validation_error','message':str(exc),'retryable':False}}
