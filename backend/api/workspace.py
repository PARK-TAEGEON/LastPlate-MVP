"""Business UI facade: server-owned sites, safe views and context-bound operations."""
import json, sqlite3, logging
from copy import deepcopy
from datetime import date,timedelta
from fastapi import APIRouter,Request,HTTPException,UploadFile,File,Form,Query
from backend.api.routes import database
from backend.contracts import PlanRequest,WorkspacePlan,WorkspaceReplan,ActualRequest,ActualCorrection,EventPreview
from backend.application.profiles import demo_profile
from backend.application.service import plan
from backend.application.presentation import plan_view,actual_view,event_view
from backend.adapters.events import interpret
from backend.adapters.persistence import Persistence,Conflict,now
from backend.adapters.uploads import parse,MAX_BYTES

router=APIRouter(prefix='/api/ui')
SITES={'DEMO-LH':('lh-like','본사 구내식당'), 'DEMO-SMALL':('small-site','별관 구내식당'),
       'DEMO-RISK':('risk-demo','연수원 구내식당')}

def apply_settings(db,site_id,data):
    row=db.repo.connection.execute('SELECT settings_json FROM api_site_settings WHERE site_id=?',(site_id,)).fetchone()
    if not row:return data
    config=json.loads(row[0]);data['attendance']['registered_population']=config['registered_population']
    data['meal_capacity']=config['meal_capacity'];data['operation_policy']['safety_margin_pct']=config['safety_margin_pct']
    data['operation_policy']['constraints']={**data['operation_policy'].get('constraints',{}),
        'minimum_protein':config['minimum_protein'],'calorie_range':[config['calorie_min'],config['calorie_max']],
        'sodium_max':config['sodium_max'],'allergy_restriction':config['allergy_restriction']}
    return data

def baseline(db,site_id,target,base_id=None):
    if base_id:
        row=db.get_run(base_id)
        if not row or (row['site_id'],row['target_date'])!=(site_id,str(target)):
            raise Conflict('선택한 계획의 사업장·날짜를 확인하세요.')
        data=deepcopy(row['request'])
        if site_id in SITES:data['site_name']=SITES[site_id][1]
        return data
    if site_id in SITES:
        profile,name=SITES[site_id]
        result=demo_profile(profile,target)['request']
        result.update(site_id=site_id,site_name=name,planned_orders=[])
        return apply_settings(db,site_id,result)
    row=db.repo.connection.execute('SELECT request_json FROM api_runs WHERE site_id=? AND target_date=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(site_id,str(target))).fetchone()
    if not row:raise HTTPException(404,'이 날짜의 등록 자료가 없습니다. 등록된 계획의 날짜를 선택하세요.')
    return apply_settings(db,site_id,json.loads(row[0]))

def editable(data,base_id=None):
    return {**{k:data[k] for k in ('site_id','site_name','target_date','attendance','meal_capacity','weekly_menu','inventory','planned_orders','events','is_demo')},
        'base_request_id':base_id,'as_of':data['as_of'],
        'menu_uploaded':'USER_UPLOAD' in data['sources'].get('weekly_menu',''),
        'inventory_uploaded':'USER_UPLOAD' in data['sources'].get('inventory','')}

def assemble(payload,db):
    data=baseline(db,payload.site_id,payload.target_date,payload.base_request_id)
    values=payload.model_dump(mode='json')
    if values['attendance']['registered_population']!=data['attendance']['registered_population']:
        raise Conflict('등록 인원은 사업장 설정에서 관리합니다.')
    for key in ('attendance','weekly_menu','inventory','planned_orders','events'):data[key]=values[key]
    # Reference day is automatic and relative event dates have a visible preview.
    data['as_of']=str(payload.target_date-timedelta(days=1))
    if payload.menu_uploaded:data['sources']['weekly_menu']='USER_UPLOAD:operator menu'
    if payload.inventory_uploaded:data['sources']['inventory']='USER_UPLOAD:operator inventory'
    for order in data['planned_orders']:
        arrival=order.get('arrival_date')
        if arrival:
            try:date.fromisoformat(arrival)
            except (ValueError,TypeError):raise HTTPException(422,'입고 예정일을 확인하세요.')
    return PlanRequest.model_validate(data)

def metadata(db,identity):
    row=db.get_run(identity)
    if not row:raise HTTPException(404,'저장된 계획을 찾지 못했습니다.')
    version=db.repo.connection.execute('SELECT COUNT(*) FROM api_runs WHERE site_id=? AND target_date=? AND rowid<=(SELECT rowid FROM api_runs WHERE request_id=?)',(row['site_id'],row['target_date'],identity)).fetchone()[0]
    ack=db.repo.connection.execute('SELECT acknowledged_at FROM api_acknowledgements WHERE request_id=?',(identity,)).fetchone()
    previous=db.get_run(row['result'].get('parent_request_id')) if row['result'].get('parent_request_id') else None
    return row,{'created_at':row['created_at'],'version':version,'acknowledged_at':ack[0] if ack else None,'previous':previous['result'] if previous else None}

def present_run(db,identity):
    row,meta=metadata(db,identity)
    confirmation=db.repo.connection.execute('SELECT * FROM api_plan_confirmations WHERE request_id=?',(identity,)).fetchone()
    if confirmation:
        confirmation=dict(confirmation);confirmation['valid']=False
        schedule=db.repo.connection.execute('SELECT data_json FROM api_month_schedules WHERE site_id=? AND month=?',
            (row['site_id'],row['target_date'][:7])).fetchone()
        if schedule:
            d=next((d for d in json.loads(schedule[0])['days'] if d['date']==row['target_date']),None)
            confirmation['valid']=bool(d and d.get('plan_id')==identity and d['revision']==confirmation['day_revision'] and d.get('generated_revision')==d['revision'])
    meta['confirmation']=confirmation
    return plan_view(row['result'],row['request'],**meta)

def completed(request,payload,result):
    if result['persistence_status']!='SUCCESS':
        pending=request.app.state.pending_runs
        pending[result['request_id']]=(payload,result)
        while len(pending)>30:pending.pop(next(iter(pending)))
    try:
        with database(request) as db:
            if db.get_run(result['request_id']):return present_run(db,result['request_id'])
    except (sqlite3.Error,OSError):pass
    return plan_view(result,payload.model_dump(mode='json'),created_at=now())

@router.get('/sites')
def sites(request:Request):
    values={key:{'id':key,'name':name,'is_demo':True} for key,(_,name) in SITES.items()}
    with database(request) as db:
        for row in db.repo._many('SELECT site_id,site_name,is_demo FROM sites'):
            if row['site_id'] not in values:values[row['site_id']]={'id':row['site_id'],'name':row['site_name'],'is_demo':bool(row['is_demo'])}
    return {'sites':list(values.values()),'default_site':'DEMO-LH'}

@router.get('/context')
def context(request:Request,site_id:str,target_date:date,plan_id:str|None=None):
    with database(request) as db:return editable(baseline(db,site_id,target_date,plan_id),plan_id)

@router.get('/plans')
def plans(request:Request,site_id:str,target_date:date):
    with database(request) as db:
        rows=db.repo._many('SELECT request_id,created_at,result_json FROM api_runs WHERE site_id=? AND target_date=? ORDER BY rowid',(site_id,str(target_date)))
        return {'plans':[{'id':r['request_id'],'version':i+1,'created_at':r['created_at'],
            'saved':r['result_json']['persistence_status']=='SUCCESS'} for i,r in reversed(list(enumerate(rows)))]}

@router.get('/plans/{identity}')
def get_plan(identity:str,request:Request):
    with database(request) as db:return present_run(db,identity)

@router.post('/plan')
def create_plan(payload:WorkspacePlan,request:Request):
    with database(request) as db:resolved=assemble(payload,db)
    result=plan(resolved,request.app.state.settings)
    return completed(request,resolved,result)

@router.post('/events/preview')
def preview(payload:EventPreview,request:Request):
    with database(request) as db:data=baseline(db,payload.site_id,payload.target_date,payload.plan_id)
    data['events']=payload.events
    data['as_of']=str(payload.target_date-timedelta(days=1))
    result=interpret(PlanRequest.model_validate(data))
    view=event_view(result,str(payload.target_date))
    view['needs_review']=view['needs_review'] or (bool(payload.events) and not view['rows'])
    return view

@router.post('/replan')
def change_plan(payload:WorkspaceReplan,request:Request):
    with database(request) as db:
        row=db.get_run(payload.existing_context)
        if not row:raise HTTPException(404,'변경할 계획을 다시 선택하세요.')
    data=row['request'];data['events']=payload.events
    data['as_of']=str(date.fromisoformat(data['target_date'])-timedelta(days=1))
    resolved=PlanRequest.model_validate(data)
    parsed=event_view(interpret(resolved),str(resolved.target_date))
    if parsed['needs_review']:raise HTTPException(422,'변경사항의 날짜와 내용을 확인하세요.')
    return completed(request,resolved,plan(resolved,request.app.state.settings,payload.existing_context))

@router.post('/plans/{identity}/acknowledgement')
def acknowledge(identity:str,request:Request):
    with database(request) as db:
        row=db.get_run(identity)
        if not row:raise HTTPException(404,'계획을 찾지 못했습니다.')
        if row['result']['persistence_status']!='SUCCESS':raise Conflict('계획 저장을 먼저 완료하세요.')
        result=db.acknowledge(identity)
        return {'acknowledged_at':result['acknowledged_at'],'message':'권고 내용을 읽었음을 기록했습니다. 계획 확정이나 발주는 실행되지 않습니다.'}

@router.post('/plans/{identity}/retry-save')
def retry(identity:str,request:Request):
    pending=request.app.state.pending_runs
    with database(request) as db:
        saved=db.get_run(identity)
        if saved and saved['result']['persistence_status']=='SUCCESS':return present_run(db,identity)
        item=pending.get(identity)
        if not item and saved:item=(PlanRequest.model_validate(saved['request']),saved['result'])
        if not item:raise HTTPException(404,'임시 계산 결과가 없습니다. 새 계획을 생성하세요.')
        payload,result=item;result=deepcopy(result);ids=result['persistence_ids']
        # All retry writes, including the public run, are atomic. Native Agents are not rerun.
        with db.repo.transaction():
            db.ensure_site(payload)
            if result.get('demand') and not ids.get('prediction_id'):
                ids['prediction_id']=db.demand(payload,result['demand'],identity)['prediction_id']
            if (result.get('operation') or {}).get('recommended_servings') is not None and not ids.get('operation_plan_id'):
                ids['operation_plan_id']=db.operation(payload,ids['prediction_id'],result['operation'])['plan_id']
            if result.get('decision') and not ids.get('decision_id'):
                ids['decision_id']=db.decision(payload,ids.get('prediction_id'),ids.get('operation_plan_id'),result['decision'])['decision_id']
            result['persistence_status']='SUCCESS'
            result['warnings']=[w for w in result['warnings'] if w.get('code')!='PERSISTENCE_FAILED']
            if saved:
                db.repo.connection.execute('UPDATE api_runs SET result_json=? WHERE request_id=?',(json.dumps(result,ensure_ascii=False,allow_nan=False),identity))
            else:db.save_run(payload,result)
        pending.pop(identity,None)
        return present_run(db,identity)

def actual_result(db,site_id,target):
    record=db.repo.get_actual_result(site_id,str(target))
    if not record:return None
    summary=next(r for r in db.history(site_id,1000) if r['target_date']==str(target))
    return actual_view(summary,db.actual_revision(record),db.repo.get_actual_corrections(site_id,str(target)))

@router.get('/actual')
def get_actual(request:Request,site_id:str,target_date:date):
    with database(request) as db:return {'record':actual_result(db,site_id,target_date)}

@router.post('/actual')
def save_actual(payload:ActualRequest,request:Request):
    if not payload.plan_request_id:raise HTTPException(422,'연결할 저장 계획을 선택하세요.')
    with database(request) as db:
        db.actual(payload)
        return {'record':actual_result(db,payload.site_id,payload.target_date)}

@router.post('/actual/correct')
def correct(payload:ActualCorrection,request:Request):
    with database(request) as db:
        db.correct_actual(payload)
        return {'record':actual_result(db,payload.site_id,payload.target_date)}

@router.get('/history')
def history(request:Request,site_id:str,limit:int=Query(30,ge=1,le=1000)):
    with database(request) as db:return {'records':[actual_view(r) for r in db.history(site_id,limit)]}

@router.post('/upload/{kind}')
def upload(kind:str,request:Request,file:UploadFile=File(...),site_id:str=Form(...),target_date:date=Form(...)):
    if kind not in ('menu','inventory','monthly-menu'):raise HTTPException(404,'지원하지 않는 자료입니다.')
    rows=parse(file.file.read(MAX_BYTES+1),file.filename or '',kind)
    if kind=='inventory':
        with database(request) as db:
            payload=PlanRequest.model_validate(baseline(db,site_id,target_date))
            db.ensure_site(payload);db.inventory(site_id,target_date-timedelta(days=1),rows,payload.is_demo)
    return {'rows':rows,'row_count':len(rows),'stored':kind=='inventory'}
