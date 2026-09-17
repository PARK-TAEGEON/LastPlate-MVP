"""Future UI integration endpoints, separate from the preserved local engine."""
from datetime import date
import sqlite3
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from lastplate_backend.agent_contracts import AgentPlanRequest, AgentPipelineResult, failed_result
from lastplate_backend.services.agent_client import AgentServiceError

router = APIRouter(prefix='/api/v1', tags=['agent-service'])


@router.get('/integration')
def integration_status(request: Request):
    settings = request.app.state.settings
    return dict(backend_version=settings.app_version, peer_contract='lastplate-integrated-v0.1.2',
                agent_service_configured=bool(settings.agent_base_url),
                backend_endpoint='/api/v1/agent-plans', upstream_endpoint='/api/plan',
                local_engine_endpoint='/api/v1/operation-plans',
                model_bundled=False, frontend_bundled=False)


@router.post('/agent-plans', response_model=AgentPipelineResult,
             responses={code: {'model':AgentPipelineResult} for code in (409,422,500,502,503,504)})
def calculate_with_agents(payload: AgentPlanRequest, request: Request):
    # Forward explicitly supplied fields; do not introduce nulls/defaults into the request.
    original = payload.model_dump(mode='json', exclude_unset=True)
    try:
        status, result = request.app.state.agent_client.plan(original)
    except AgentServiceError as exc:
        return JSONResponse(status_code=exc.status, content=failed_result(exc.code, str(exc), exc.status))
    try:
        record_id = request.app.state.agent_repository.save(
            original, status, result, request.app.state.settings.agent_base_url)
    except sqlite3.Error:
        # Preserve the successful/partial upstream body even when our own history
        # storage fails. Report the backend failure out-of-band, not as an agent decision.
        return JSONResponse(status_code=503, content=result, headers={
            'X-LastPlate-Storage':'failed', 'X-LastPlate-Error':'BACKEND_STORAGE_FAILED',
            'X-LastPlate-Upstream-Status':str(status)})
    return JSONResponse(status_code=status, content=result, headers={
        'X-LastPlate-Record-Id':record_id, 'X-LastPlate-Storage':'saved',
        'X-LastPlate-Upstream-Status':str(status), 'Location':f'/api/v1/agent-plans/{record_id}'})


@router.get('/agent-plans/latest')
def latest_agent_plan(request: Request, site_id: str = Query(min_length=1), target_date: date = Query()):
    result = request.app.state.agent_repository.latest(site_id, target_date.isoformat())
    if result is None:
        raise HTTPException(404, detail='Agent plan not found')
    return result


@router.get('/agent-plans/{record_id}')
def get_agent_plan(record_id: str, request: Request):
    result = request.app.state.agent_repository.get(record_id)
    if result is None:
        raise HTTPException(404, detail='Agent plan not found')
    return result
