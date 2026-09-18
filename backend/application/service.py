from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import logging

from backend.bootstrap import ROOT
from integration.contracts import PipelineInput, PipelineConfig
from backend.contracts import PlanRequest, PipelineResult
from backend.adapters import results
from backend.adapters.events import interpret
from backend.adapters.persistence import Persistence, Conflict
from backend.application.orchestrator import run_lastplate_pipeline

log=logging.getLogger(__name__)


def native_input(request, request_id, event_context):
    p=request.model_dump(mode='json',exclude={'site_name','events','is_demo','operating_diners_override'})
    # Arrival dates are UI schedule notes, not verified stock/receipts in native contracts.
    p['planned_orders']=[{k:v for k,v in order.items() if k!='arrival_date'} for order in p['planned_orders']]
    p['request_id']=request_id
    if all(isinstance(e,str) for e in request.events):
        p['event']='. '.join(request.events) or None
    else:
        p['event']=None
        p['supply_events']+=event_context['events']
    return PipelineInput.model_validate(p).model_dump(mode='json')


def plan(request, settings, parent_request_id=None):
    if settings.mode=='demo' and not request.is_demo:
        raise Conflict('서버가 DEMO 모드입니다. 이 모드의 계획을 실제 운영 데이터로 표시할 수 없습니다.')
    request_id=uuid4().hex
    native_input(request,request_id,{'events':[]})  # Validate nested native shapes before parser access.
    context=interpret(request)
    p=native_input(request,request_id,context)
    persistence=None
    ids, persistence_warnings = {}, []

    def warn(stage):
        persistence_warnings.append(dict(code='PERSISTENCE_FAILED',stage=stage,
            message='운영 계획은 계산되었지만 일부 저장에 실패했습니다. 저장 상태를 확인하세요.'))

    try:
        persistence=Persistence(settings.database)
        persistence.ensure_site(request)
    except Conflict:
        if persistence: persistence.close()
        raise
    except Exception:
        log.exception('Could not open persistence')
        if persistence: persistence.close()
        persistence=None
        warn('connection')

    def persist(stage, native, revision):
        if not persistence:
            return
        try:
            if stage=='demand':
                row=persistence.demand(request,results.demand(native,request),request_id)
                ids['prediction_id']=row['prediction_id']
            elif stage=='operation' and native.get('recommended_servings') is not None:
                if 'prediction_id' not in ids:
                    raise ValueError('Prediction was not persisted')
                row=persistence.operation(request,ids['prediction_id'],results.operation(native))
                ids['operation_plan_id']=row['plan_id']
            elif stage=='decision':
                row=persistence.decision(request,ids.get('prediction_id'),ids.get('operation_plan_id'),native)
                ids['decision_id']=row['decision_id']
        except Exception:
            log.exception('Persistence failed at %s',stage)
            warn(stage)  # Never throw into native pipeline: original hooks otherwise mark it PARTIAL.

    hooks={f'on_{stage}_complete':(lambda raw,revision,s=stage:persist(s,raw,revision))
           for stage in ('demand','operation','decision')}
    try:
        # Native Demand has a private receipt DB with an incompatible schema. Keep that
        # request-local; the supplied lastplate_db is the sole durable application store.
        with TemporaryDirectory(prefix='lastplate-native-') as scratch:
            raw=run_lastplate_pipeline(p,config=PipelineConfig(storage_dir=Path(scratch),
                mode=settings.mode,timeout_seconds=settings.stage_timeout),hooks=hooks,
                attendance_delta=context['attendance_delta'], operating_diners=request.operating_diners_override)
        errors=[results.message(e) for e in raw['errors']]
        for diagnostic in context['diagnostics']:
            if diagnostic.get('errors'):
                errors.append(dict(code='EVENT_PARSE_ERROR',stage='events',http_status=422,
                    message='이벤트 형식 또는 날짜를 확인하세요.',details=diagnostic['errors']))
        stages={key:raw.get(key) for key in ('demand','operation','inventory_risk','decision')}
        if stages['demand']: stages['demand']=results.demand(stages['demand'],request)
        if stages['operation']: stages['operation']=results.operation(stages['operation'])
        status='SUCCESS' if raw['pipeline_status']=='COMPLETE' and not errors else 'PARTIAL'
        for error in errors:
            log.error('Plan calculation failed at %s (%s): %s',error.get('stage'),error.get('code'),error.get('original_message') or error.get('message'))
        if not any(stages.values()): status='FAILED'
        response=dict(pipeline_status=status,persistence_status='SUCCESS',request_id=request_id,
            site_id=request.site_id,target_date=str(request.target_date),parent_request_id=parent_request_id,
            **stages,warnings=[results.message(w) for w in raw['warnings']],errors=errors,
            sources={**request.sources,'demand':'MODEL','risk_constraints':'DEMO:original RiskConfig dish-level thresholds'},
            is_demo=request.is_demo,persistence_ids=ids,event_context={**context,
                'policy':'전체 이벤트 목록 대체; raw ML 값 보존; 명시적 인원 증감만 운영 시나리오에 반영',
                'recomputed':['demand','operation','inventory_risk','decision']},timings=raw['timings'])
        response['warnings']+=persistence_warnings
        if persistence_warnings: response['persistence_status']='PARTIAL' if ids else 'FAILED'
        response=PipelineResult.model_validate(response).model_dump(mode='json')
        if persistence:
            try:
                persistence.save_run(request,response)
            except Exception:
                log.exception('Could not save API run')
                response['persistence_status']='PARTIAL' if ids else 'FAILED'
                response['warnings'].append(dict(code='PERSISTENCE_FAILED',stage='api_run',
                    message='계산 결과는 반환되었지만 재계획용 이력을 저장하지 못했습니다.'))
        return response
    finally:
        if persistence: persistence.close()
