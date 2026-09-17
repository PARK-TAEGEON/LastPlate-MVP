"""Application orchestration derived from v0.1.2; native agents are unchanged.
Only the transport imports and explicit attendance scenario are adapted.
"""
from copy import deepcopy
import json,time,hashlib
from integration.contracts import PipelineInput,PipelineConfig,PipelineResult
from integration.errors import StageError
from integration.bridge import invoke
from integration.adapters.operation_adapter import build_operation

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def run_lastplate_pipeline(input_data, *, config=None, hooks=None, attendance_delta=0):
    """One lunch service per request; weekly context is explicitly scoped to that service.

    Config is server-owned. Hooks are advisory, may run again on retry, and must upsert
    by input_revision. No order, menu or stock mutation is performed here.
    """
    result=PipelineResult(pipeline_status='PARTIAL').model_dump()
    start=time.perf_counter()
    try:
        cfg=config if isinstance(config,PipelineConfig) else PipelineConfig.model_validate(config or {})
    except Exception as e:
        result.update(pipeline_status='FAILED',errors=[dict(stage='config',code='SERVER_CONFIG_INVALID',message=str(e),kind='server',http_status=500)])
        return result
    try:
        p=PipelineInput.model_validate(deepcopy(input_data)).model_dump(mode='json')
        json.dumps(p,allow_nan=False)
        p['input_revision']=fingerprint(p)
        result['input_revision']=p['input_revision']
    except Exception as e:
        result.update(pipeline_status='FAILED',errors=[dict(stage='input',code='INPUT_VALIDATION_ERROR',message=str(e),kind='input',http_status=422)])
        return result
    # The public end-to-end contract is mass-only even when an individual Agent supports ml/ea.
    def mass_units(value,path):
        if isinstance(value,dict):
            if 'unit' in value: yield (path,value['unit'])
            for key,item in value.items(): yield from mass_units(item,path+'.'+key)
        elif isinstance(value,list):
            for i,item in enumerate(value): yield from mass_units(item,f'{path}[{i}]')
    units=[row for key in ('inventory','planned_orders','recipes','prices','monthly_prices','operation_policy') for row in mass_units(p[key],key)]
    unsupported=[{'field':field,'unit':unit} for field,unit in units if unit not in ('g','kg')]
    if unsupported:
        result['errors']=[dict(stage='input',code='UNIT_ERROR',kind='input',http_status=422,message='Pipeline supports mass units g/kg only',details=unsupported)]
        return result
    def call(stage,value):
        t=time.perf_counter()
        try:
            raw=invoke(stage,value,cfg.timeout_seconds)
            result[stage]=raw
            hook=(hooks or {}).get('on_'+stage+'_complete')
            if hook:
                try: hook(deepcopy(raw),p['input_revision'])
                except Exception as e: result['errors'].append(dict(stage=stage,code='PERSIST_HOOK_FAILED',message=str(e),kind='server',http_status=500))
            return raw
        except StageError as e:
            result['errors'].append(e.as_dict())
        except Exception as e:
            result['errors'].append(dict(stage=stage,code=stage.upper()+'_FAILED',message=str(e),kind='server',http_status=500))
        finally: result['timings'][stage]=round(time.perf_counter()-t,4)
    selected=[m['menu_name'] for m in p['weekly_menu'] if (m['date'],m['meal_type'])==(p['target_date'],p['meal_type'])]
    attendance=deepcopy(p['attendance'])
    if 'registered_population' in attendance:
        if 'employees' in attendance and attendance['employees']!=attendance['registered_population']:
            result['errors'].append(dict(stage='demand',code='INPUT_VALIDATION_ERROR',message='Population aliases conflict',kind='input',http_status=422))
        attendance['employees']=attendance.pop('registered_population')
    attendance.update(date=p['target_date'],menu=' '.join(selected))
    d=None if result['errors'] else call('demand',dict(input=attendance,request_id=p['site_id']+':'+p['request_id'],
        availability=p['availability'],config=cfg.model_dump(mode='json')))
    o=r=None
    if d:
        result['warnings'].extend(d['warnings'])
        try:
            operation_input=build_operation(p,d)
            # Explicit event scenario, kept separate from the immutable ML output.
            # Operation still owns buffers, rounding, recipes, stock and order arithmetic.
            if attendance_delta:
                scenario=operation_input['demand_result']
                scenario['prediction']=max(0,d['predicted_diners']+attendance_delta)
                if scenario.get('prediction_interval'):
                    scenario['prediction_interval']={k:max(0,v+attendance_delta) for k,v in scenario['prediction_interval'].items()}
                operation_input['_demand_envelope']['event_scenario']={
                    'raw_model_prediction':d['predicted_diners'],
                    'attendance_delta':attendance_delta,'scenario_diners':scenario['prediction'],
                    'source':'explicit_user_event','requires_confirmation':True}
                result['warnings'].append(dict(code='EVENT_SCENARIO_APPLIED',stage='operation',
                    message='원본 ML 예측을 보존하고 명시적 인원 변동을 운영 시나리오에 반영했습니다. 운영자 확인이 필요합니다.'))
            o=call('operation',operation_input)
        except Exception as e:
            result['errors'].append(dict(stage='operation',code='OPERATION_INPUT_ERROR',message=str(e)))
    if o:
        # Status is authoritative: new/unknown or absent alerts must never hide invalid input.
        if o.get('status')=='invalid_input':
            alerts=deepcopy(o.get('alerts',[]))
            first=alerts[0] if alerts else {}
            result['errors'].append(dict(stage='operation',code=first.get('type') or 'OPERATION_INVALID_INPUT',
                message=first.get('message') or 'Operation rejected the input',kind='input',http_status=422,
                native_status='invalid_input',evidence=deepcopy(first.get('evidence',{})),alerts=alerts))
        for alert in ([] if o.get('status')=='invalid_input' else o.get('alerts',[])):
            kind=alert['type']
            if kind in ('MISSING_RECIPE','MISSING_INVENTORY','UNIT_ERROR','UNIT_MISMATCH','UNSUPPORTED_UNIT','INVALID_INPUT','NUMERIC_ERROR'):
                result['errors'].append(dict(stage='operation',code='RECIPE_MISSING' if kind=='MISSING_RECIPE' else 'INVENTORY_DATA_MISSING' if kind=='MISSING_INVENTORY' else 'UNIT_ERROR' if 'UNIT' in kind else 'INPUT_VALIDATION_ERROR',message=alert['message'],kind='input',http_status=422))
        if (o.get('capacity_excess') or 0)>0:
            result['warnings'].append(dict(code='CAPACITY_EXCEEDED',stage='operation',raw_prediction=d['predicted_diners'],capacity=p['meal_capacity'],message='Raw demand preserved; capacity review required'))
        if o.get('recommended_servings') is not None and o['status']!='invalid_input':
            r=call('inventory_risk',dict(payload=p,recommended_servings=o['recommended_servings'],ingredient_requirements=o['ingredient_requirements'],operation_revision=fingerprint(o)))
            if r and r['status'] in ('error','partial','needs_clarification'):
                result['errors'].append(dict(stage='inventory_risk',code='RISK_DATA_MISSING' if r['status']=='error' else 'DECISION_NEEDS_CONFIRMATION',message=r['status'],details=r.get('errors',[]),
                    http_status=422 if any(e.get('code') in ('input_validation_error','data_quality_error') for e in r.get('errors',[])) else 200,kind='input' if r['status']=='error' else 'confirmation'))
    scope=dict(target_date=p['target_date'],meal_type=p['meal_type'],coverage='full',menus_complete=True,
        menus=[dict(menu=name,ingredients=[i['ingredient'] for recipe in p['recipes'] if recipe['menu_name']==name for i in recipe['ingredients']],
            ingredients_complete=any(recipe['menu_name']==name for recipe in p['recipes'])) for name in selected])
    call('decision',dict(payload=p,demand=d,operation=o,inventory_risk=r,scope=scope))
    result['pipeline_status']='COMPLETE' if all(result[k] is not None for k in ('demand','operation','inventory_risk','decision')) and not result['errors'] else 'PARTIAL'
    result['timings']['total']=round(time.perf_counter()-start,4)
    return PipelineResult.model_validate(result).model_dump(mode='json')
