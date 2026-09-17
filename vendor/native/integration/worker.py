"""Private fixed dispatcher; no user-supplied Python or import paths."""
import sys,json,contextlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
stage=sys.argv[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/stage))
from integration.errors import StageError

def execute(value):
    if stage=='demand':
        from ml.time_contract import ServiceConfig
        from tools.demand import predict_demand
        from ml.model_registry import ModelRegistry
        from integration.adapters.demand_adapter import adapt_demand
        c=value['config']
        cfg=ServiceConfig(Path(c['storage_dir']).resolve(),ROOT/'demand/models',c['timezone'],c['cutoff_time'],c['actual_ready_time'],mode=c['mode'])
        from ml.prepare_data import normalize
        from tools.demand import cached_model
        import pandas as pd
        bundle,_=cached_model(cfg.model_dir)
        try:
            normalize(pd.DataFrame([value['input']]),require_target=False,require_overtime=bundle.get('include_overtime',True))
        except (ValueError,TypeError,KeyError) as exc:
            raise StageError(stage,'MODEL_INPUT_INVALID',str(exc),422) from exc
        raw=predict_demand(value['input'],request_id=value['request_id'],config=cfg,availability=value.get('availability'))
        _,metadata=ModelRegistry(cfg.model_dir).load(raw['model_version'])
        return adapt_demand(raw,metadata,ROOT/'demand/data/processed/lunch.csv')
    if stage=='operation':
        from lastplate_operation import generate_operation_plan
        envelope=value.pop('_demand_envelope',None)
        result=generate_operation_plan(**value)
        if envelope is not None:result['demand_envelope']=envelope
        return result
    if stage=='inventory_risk':
        from integration.adapters.inventory_risk_adapter import analyze
        return analyze(value)
    if stage=='decision':
        from integration.adapters.decision_adapter import decide
        return decide(value)
    raise ValueError('Unknown stage')

try:
    payload=json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        result=execute(payload)
    answer={'result':result}
except Exception as exc:
    from pydantic import ValidationError
    code=getattr(exc,'code',type(exc).__name__)
    http_status=getattr(exc,'http_status',500)
    if code in ('idempotency_conflict','revision_conflict'):http_status=409
    elif code in ('validation_error','time_contract_error','input_not_available','weather_contract_error'):
        http_status=422
    elif isinstance(exc,ValidationError) and stage=='inventory_risk':http_status=422
    answer={'error':{'code':code,'message':str(exc),'http_status':http_status}}
print(json.dumps(answer,ensure_ascii=False,allow_nan=False))
