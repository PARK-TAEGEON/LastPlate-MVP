"""Monthly scheduling and human review around the existing per-service Agents."""
import csv,io,json,threading
from copy import deepcopy
from datetime import date
from typing import Literal
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import Response
from pydantic import Field,model_validator
from backend.contracts import Contract,Attendance,PlanRequest
from backend.api.routes import database
from backend.api.workspace import baseline,editable,completed,present_run,retry
from backend.application.meal_catalog import CATALOG,SLOTS,demo_days,month_days
from backend.application.service import plan
from backend.application.presentation import event_view
from backend.adapters.events import interpret
from backend.adapters.persistence import Conflict,now

router=APIRouter(prefix='/api/ui/months')
locks={}
locks_guard=threading.Lock()

class Change(Contract):
    reason:str=Field(default='',max_length=200)
    increase:int=Field(default=0,ge=0,le=100000,strict=True)
    decrease:int=Field(default=0,ge=0,le=100000,strict=True)
    note:str=Field(default='',max_length=1000)
    @model_validator(mode='after')
    def check_reason(self):
        if (self.increase or self.decrease) and not self.reason.strip():raise ValueError('인원 변경 사유를 입력하세요.')
        return self

class Day(Contract):
    date:date
    menus:dict[str,str]
    change:Change=Field(default_factory=Change)

class MonthSave(Contract):
    site_id:str=Field(min_length=1,max_length=100)
    expected_revision:int=Field(ge=0)
    attendance:Attendance
    inventory:list[dict]=Field(max_length=5000)
    planned_orders:list[dict]=Field(default_factory=list,max_length=5000)
    days:list[Day]=Field(min_length=1,max_length=31)
    inventory_uploaded:bool=False

class DaySave(Contract):
    site_id:str
    expected_revision:int=Field(ge=1)
    menus:dict[str,str]
    change:Change

class Generate(Contract):
    site_id:str
    expected_revision:int=Field(ge=1)

class Review(Generate):
    plan_id:str
    kind:Literal['menu','note']
    candidate_index:int=Field(default=0,ge=0)
    decision:Literal['accept','reject']
    reason:str=Field(default='',max_length=500)

def ensure(db):
    db.repo.connection.execute('CREATE TABLE IF NOT EXISTS api_month_schedules (site_id TEXT NOT NULL, month TEXT NOT NULL, revision INTEGER NOT NULL, data_json TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(site_id,month))')
    db.repo.connection.commit()

def validate_month(month):
    try:
        if len(month)!=7:raise ValueError()
        return month_days(month)
    except ValueError:raise HTTPException(422,'운영 월을 확인하세요.')

def read(db,site,month,required=False):
    validate_month(month)
    row=db.repo.connection.execute('SELECT * FROM api_month_schedules WHERE site_id=? AND month=?',(site,month)).fetchone()
    if row:return json.loads(row['data_json'])
    if required:raise HTTPException(409,'월간 식단을 먼저 저장하세요.')
    today=date.today()
    reference=today if str(today).startswith(month) else date.fromisoformat(month+'-01')
    base=baseline(db,site,reference)
    return dict(site_id=site,month=month,revision=0,base=base,days=[dict(**d,revision=1,plan_id=None,generated_revision=None,reviews=[],note_review=None,note_action='pending') for d in demo_days(month)])

def write(db,data):
    data['revision']+=1
    db.repo.connection.execute('INSERT INTO api_month_schedules VALUES (?,?,?,?,?) ON CONFLICT(site_id,month) DO UPDATE SET revision=excluded.revision,data_json=excluded.data_json,updated_at=excluded.updated_at',
        (data['site_id'],data['month'],data['revision'],json.dumps(data,ensure_ascii=False,allow_nan=False),now()))

def day_in(data,target):
    result=next((d for d in data['days'] if d['date']==target),None)
    if not result:raise HTTPException(404,'식단이 등록되지 않은 날짜입니다.')
    return result

def check_menus(menus,base):
    if set(menus)!=set(SLOTS):raise HTTPException(422,'밥·국·메인반찬·사이드반찬을 각각 입력하세요.')
    registered={r['menu_name'] for r in base['recipes']}
    for slot,name in menus.items():
        if name not in registered or name not in CATALOG[slot]:raise HTTPException(422,f'{SLOTS[slot]}: {name}의 등록 레시피를 확인하세요. 메뉴 선택 목록에서 선택해 주세요.')

def view(data):
    context=editable(data['base'])
    context['weekly_menu']=[dict(date=d['date'],meal_type='lunch',menu_name=name) for d in data['days'] for name in d['menus'].values()]
    return {k:data[k] for k in ('site_id','month','revision','days')}|{'context':context,'catalog':CATALOG}

@router.get('/{month}/template')
def template(month:str):
    validate_month(month);output=io.StringIO();writer=csv.writer(output);writer.writerow(['date','rice','soup','main','side'])
    for d in demo_days(month):writer.writerow([d['date'],*[d['menus'][slot] for slot in SLOTS]])
    return Response('\ufeff'+output.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="lastplate-{month}-menu.csv"'})

@router.get('/{month}')
def get_month(month:str,site_id:str,request:Request):
    with database(request) as db:
        ensure(db);data=read(db,site_id,month)
        result=view(data)
        for d in result['days']:
            if d['plan_id']:
                saved=db.get_run(d['plan_id'])
                if saved:
                    p=present_run(db,d['plan_id']);d['summary']={k:p[k] for k in ('model_diners','operating_diners','review_servings','blocked','calculation','saved')}
        return result

@router.put('/{month}')
def save_month(month:str,payload:MonthSave,request:Request):
    allowed=validate_month(month)
    if len({d.date for d in payload.days})!=len(payload.days) or any(str(d.date) not in allowed for d in payload.days):raise HTTPException(422,'선택한 월의 날짜를 중복 없이 입력하세요.')
    with database(request) as db:
        ensure(db)
        with db.repo.transaction():
            data=read(db,payload.site_id,month)
            if data['revision']!=payload.expected_revision:raise Conflict('월간 식단이 변경됐습니다. 새로고침 후 다시 반영하세요.')
            if payload.attendance.registered_population!=data['base']['attendance']['registered_population']:raise Conflict('등록 인원은 사업장 설정에서 관리합니다.')
            base=deepcopy(data['base']);base.update(attendance=payload.attendance.model_dump(),inventory=payload.inventory,planned_orders=payload.planned_orders)
            if payload.inventory_uploaded:base['sources']['inventory']='USER_UPLOAD:monthly inventory'
            base['sources']['weekly_menu']='USER_UPLOAD:monthly meal schedule'
            PlanRequest.model_validate(base)
            # Validate nested inventory through the same native contract used for planning.
            from backend.application.service import native_input
            native_input(PlanRequest.model_validate(base),'monthly-validation',{'events':[]})
            base_changed=any(base[k]!=data['base'][k] for k in ('attendance','inventory','planned_orders'))
            previous={d['date']:d for d in data['days']};days=[]
            for value in payload.days:
                check_menus(value.menus,base);d=value.model_dump(mode='json');old=previous.get(d['date'])
                changed=not old or base_changed or any(d[k]!=old[k] for k in ('menus','change'))
                if old:
                    row={**old,**d,'revision':old['revision']+(1 if changed else 0)}
                    if old['change']!=d['change']:row.update(note_review=None,note_action='pending')
                else:row={**d,'revision':1,'plan_id':None,'generated_revision':None,'reviews':[],'note_review':None,'note_action':'pending'}
                days.append(row)
            data.update(base=base,days=sorted(days,key=lambda d:d['date']));write(db,data)
        return view(data)

@router.put('/{month}/days/{target}')
def save_day(month:str,target:date,payload:DaySave,request:Request):
    with database(request) as db:
        ensure(db)
        with db.repo.transaction():
            data=read(db,payload.site_id,month,True);d=day_in(data,str(target));check_menus(payload.menus,data['base'])
            if d['revision']!=payload.expected_revision:raise Conflict('이 날짜의 입력이 변경됐습니다. 새로고침 후 다시 반영하세요.')
            change=payload.change.model_dump()
            if d['menus']!=payload.menus or d['change']!=change:
                if d['change']!=change:d.update(note_action='pending',note_review=None)
                d.update(menus=payload.menus,change=change,revision=d['revision']+1)
            write(db,data)
        return view(data)

def day_request(data,d):
    p=deepcopy(data['base']);target=date.fromisoformat(d['date']);p.update(target_date=d['date'],as_of=str(target.fromordinal(target.toordinal()-1)))
    p['weekly_menu']=[dict(date=d['date'],meal_type='lunch',menu_name=name) for name in d['menus'].values()]
    change=d['change'];p['events']=[]
    if change['increase'] or change['decrease']:
        p['events'].append(dict(event_type='attendance_event',date=d['date'],attendance_delta=change['increase']-change['decrease'],reason=change['reason'],description=change['reason']))
    if change['note'] and d['note_action']=='accept':p['events'].append(d['date']+' '+change['note'])
    return PlanRequest.model_validate(p)

@router.post('/{month}/days/{target}/generate')
def generate(month:str,target:date,payload:Generate,request:Request):
    with locks_guard:lock=locks.setdefault((payload.site_id,month,str(target)),threading.Lock())
    if not lock.acquire(blocking=False):raise Conflict('이 날짜를 계산하고 있습니다. 잠시 후 결과를 확인하세요.')
    try:
        with database(request) as db:
            ensure(db);data=read(db,payload.site_id,month,True);d=day_in(data,str(target))
            if d['revision']!=payload.expected_revision:raise Conflict('입력 내용이 변경됐습니다. 월간 식단을 새로고침하세요.')
            if d['plan_id'] and d['generated_revision']==d['revision']:
                return {'month':view(data),'plan':present_run(db,d['plan_id']),'reused':True}
        resolved=day_request(data,d)
        result=None
        pending_id=d.get('pending_plan_id') if d.get('pending_revision')==d['revision'] else None
        if pending_id:
            with database(request) as db:
                if db.get_run(pending_id):result=present_run(db,pending_id)
            if result is None and pending_id in request.app.state.pending_runs:result=retry(pending_id,request)
        note_review=None
        if d['change']['note']:
            candidate=resolved.model_copy(update={'events':[d['date']+' '+d['change']['note']]})
            note_review=event_view(interpret(candidate),d['date'])
        if result is None:result=completed(request,resolved,plan(resolved,request.app.state.settings,d['plan_id']))
        with database(request) as db:
            ensure(db)
            with db.repo.transaction():
                current=read(db,payload.site_id,month,True);day=day_in(current,str(target))
                if day['revision']!=payload.expected_revision:raise Conflict('계산 중 입력이 변경됐습니다. 이전 계산은 보존했으며 수정된 입력으로 다시 계산하세요.')
                day['note_review']=note_review
                if result['saved']:
                    day.update(plan_id=result['id'],generated_revision=day['revision'],summary={k:result[k] for k in ('model_diners','operating_diners','review_servings','blocked','calculation','saved')})
                    day.pop('pending_plan_id',None);day.pop('pending_revision',None)
                else:day.update(pending_plan_id=result['id'],pending_revision=day['revision'])
                write(db,current)
            return {'month':view(current),'plan':result,'reused':False}
    finally:lock.release()

@router.post('/{month}/days/{target}/review')
def review(month:str,target:date,payload:Review,request:Request):
    with database(request) as db:
        ensure(db)
        with db.repo.transaction():
            data=read(db,payload.site_id,month,True);d=day_in(data,str(target))
            if d['revision']!=payload.expected_revision or d['plan_id']!=payload.plan_id or d['generated_revision']!=d['revision']:raise Conflict('최신 입력으로 계산한 계획에서 권고를 검토하세요.')
            if any(r['plan_id']==payload.plan_id and r['kind']==payload.kind and r['candidate_index']==payload.candidate_index for r in d['reviews']):raise Conflict('이미 선택한 권고입니다. 기록을 새로고침하세요.')
            summary='기타 사유 반영'
            if payload.kind=='menu':
                p=present_run(db,payload.plan_id)
                if payload.candidate_index>=len(p['candidates']):raise HTTPException(422,'현재 계획의 권고를 선택하세요.')
                c=p['candidates'][payload.candidate_index];summary=c['original_menu']+' → '+c['menu']
                slot=next((s for s,n in d['menus'].items() if n==c['original_menu']),None)
                if not slot or c['menu'] not in CATALOG[slot]:raise HTTPException(422,'해당 구성에 적용할 수 없는 메뉴입니다.')
                if payload.decision=='accept':
                    d['menus'][slot]=c['menu'];check_menus(d['menus'],data['base']);d['revision']+=1
            else:
                if not d['change']['note']:raise HTTPException(422,'검토할 기타 사유가 없습니다.')
                if payload.decision=='accept' and (not d.get('note_review') or d['note_review']['needs_review'] or not d['note_review']['rows']):raise HTTPException(422,'Agent가 해석할 수 있는 식재료·변경 내용을 구체적으로 입력하세요.')
                d['note_action']=payload.decision
                if payload.decision=='accept':d['revision']+=1
            d['reviews'].append(dict(plan_id=payload.plan_id,kind=payload.kind,candidate_index=payload.candidate_index,decision=payload.decision,reason=payload.reason,summary=summary,created_at=now()))
            d['reviews']=d['reviews'][-100:];write(db,data)
        return {'month':view(data),'needs_recalculation':payload.decision=='accept'}
