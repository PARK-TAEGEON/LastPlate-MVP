from contextlib import contextmanager
from datetime import date
import json
from typing import Literal
from fastapi import APIRouter, Request, Query, UploadFile, File, Form, HTTPException, Depends
from backend.api.access import legacy_access
from fastapi.responses import JSONResponse
from backend.contracts import PlanRequest, ReplanRequest, ActualRequest, PipelineResult
from backend.application.service import plan
from backend.application.profiles import demo_profile
from backend.adapters.persistence import Persistence
from backend.adapters.uploads import parse, MAX_BYTES
from lastplate_db import get_learning_dataset, get_training_dataset

router=APIRouter(prefix='/api',dependencies=[Depends(legacy_access)])


@contextmanager
def database(request):
    persistence=Persistence(request.app.state.settings.database)
    try:yield persistence
    finally:persistence.close()


@router.get('/health')
def health():
    return {'status':'ok'}


@router.get('/demo-profile')
def profile(profile:Literal['lh-like','small-site','risk-demo']='lh-like', target_date:date|None=None):
    return demo_profile(profile,target_date)


def plan_response(result):
    codes=[e.get('http_status',200) for e in result['errors']]
    status=500 if any(c>=500 for c in codes) else 409 if 409 in codes else 422 if 422 in codes else 200
    return JSONResponse(result,status_code=status)


@router.post('/plan',response_model=PipelineResult)
def create_plan(payload:PlanRequest, request:Request):
    return plan_response(plan(payload,request.app.state.settings))


@router.get('/plans/{request_id}',response_model=PipelineResult)
def get_plan(request_id:str,request:Request):
    with database(request) as persistence:
        row=persistence.get_run(request_id)
        if not row:raise HTTPException(404,'계획을 찾지 못했습니다.')
        return row['result']


@router.post('/replan',response_model=PipelineResult)
def replan(payload:ReplanRequest,request:Request):
    with database(request) as persistence:
        row=persistence.get_run(payload.existing_context)
        if not row:raise HTTPException(404,'기존 계획을 찾지 못했습니다. 계획을 먼저 생성하세요.')
    data=row['request']
    data['events']=payload.events
    return plan_response(plan(PlanRequest.model_validate(data),request.app.state.settings,payload.existing_context))


@router.post('/plans/{request_id}/acknowledgement')
def acknowledge(request_id:str,request:Request):
    with database(request) as persistence:
        try:return persistence.acknowledge(request_id)
        except KeyError:raise HTTPException(404,'계획을 찾지 못했습니다.')


@router.post('/actual-results')
def actual(payload:ActualRequest,request:Request):
    with database(request) as persistence:
        row=persistence.actual(payload)
        history=persistence.history(payload.site_id,1000)
        summary=next(r for r in history if r['result_id']==row['result_id'])
        return {'saved':True,'result':row,'summary':summary,'kpis':persistence.kpis(payload.site_id)}


@router.get('/history/{site_id}')
def history(site_id:str,request:Request,limit:int=Query(30,ge=1,le=1000)):
    with database(request) as persistence:
        return {'site_id':site_id,'source_type':'DATABASE','records':persistence.history(site_id,limit)}


@router.get('/kpis/{site_id}')
def kpis(site_id:str,request:Request):
    with database(request) as persistence:return persistence.kpis(site_id)


@router.get('/learning-dataset/{site_id}')
def learning(site_id:str,request:Request):
    with database(request) as persistence:
        return {'site_id':site_id,'source_type':'DATABASE','automatic_retraining':False,
                'dataset':get_training_dataset(persistence.repo,site_id)}


@router.post('/upload/menu')
def upload_menu(file:UploadFile=File(...)):
    rows=parse(file.file.read(MAX_BYTES+1),file.filename or '', 'menu')
    return {'rows':rows,'row_count':len(rows),'source_type':'USER_UPLOAD','warnings':[]}


@router.post('/upload/inventory')
def upload_inventory(request:Request,file:UploadFile=File(...),context:str=Form(...)):
    # Context supplies an explicit site and DEMO label before the first plan exists.
    payload=PlanRequest.model_validate_json(context)
    rows=parse(file.file.read(MAX_BYTES+1),file.filename or '', 'inventory')
    with database(request) as persistence:
        persistence.ensure_site(payload)
        ids=persistence.inventory(payload.site_id,payload.as_of,rows,payload.is_demo)
    return {'rows':rows,'row_count':len(rows),'source_type':'USER_UPLOAD','is_demo':payload.is_demo,
            'persistence_status':'SUCCESS','inventory_ids':ids,'warnings':[]}
