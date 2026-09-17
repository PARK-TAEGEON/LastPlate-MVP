"""REST endpoints consumed by the frontend and ML integration layer."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.engine import DecisionValidationError
from pydantic import ValidationError
from app.repositories.operation_plan_repository import RevisionConflict
from app.schemas import (
    ForecastInput,
    HealthResponse,
    OperationPlanRequest,
    OperationPlanResponse,
    RecalculateWithEventRequest,
    AdjustServingsRequest,
)
from app.services import OperationPlanService


router = APIRouter(prefix="/api/v1")


def get_operation_service(request: Request) -> OperationPlanService:
    return request.app.state.operation_plan_service


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.post("/forecasts/validate", response_model=ForecastInput, tags=["forecast"])
def validate_forecast(forecast: ForecastInput) -> ForecastInput:
    """Validate the normalized output sent by the ML team's forecast adapter.

    The actual model remains owned by the ML team.  The operation-plan endpoint
    accepts this exact object in its ``forecast`` field, so frontend code never
    has to call an XGBoost/LightGBM model directly.
    """
    return forecast


@router.post(
    "/operation-plans",
    response_model=OperationPlanResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["operation"],
)
def create_operation_plan(
    payload: OperationPlanRequest,
    service: OperationPlanService = Depends(get_operation_service),
) -> OperationPlanResponse:
    try:
        return service.create(payload)
    except (DecisionValidationError, ValidationError) as exc:
        # This is primarily a safety net for direct API users.  Normal malformed
        # JSON is rejected by Pydantic before this code is reached.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/operation-plans/latest",
    response_model=OperationPlanResponse,
    tags=["operation"],
)
def get_latest_operation_plan(
    site_id: str = Query(min_length=1),
    meal_date: date = Query(),
    meal_type: str = Query(default="lunch", min_length=1),
    service: OperationPlanService = Depends(get_operation_service),
) -> OperationPlanResponse:
    """Restore the newest saved plan for a UI calendar slot after refresh."""
    plan = service.get_latest(site_id=site_id, meal_date=meal_date, meal_type=meal_type)
    if plan is None:
        raise HTTPException(status_code=404, detail="Operation plan not found")
    return plan


@router.get(
    "/operation-plans/{plan_id}",
    response_model=OperationPlanResponse,
    tags=["operation"],
)
def get_operation_plan(
    plan_id: str, service: OperationPlanService = Depends(get_operation_service)
) -> OperationPlanResponse:
    plan = service.get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Operation plan not found")
    return plan


@router.post(
    "/operation-plans/{plan_id}/events",
    response_model=OperationPlanResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["operation"],
)
def recalculate_with_event(
    plan_id: str,
    payload: RecalculateWithEventRequest,
    service: OperationPlanService = Depends(get_operation_service),
) -> OperationPlanResponse:
    """Save a new immutable revision after an event such as 'field trip +35'."""
    try:
        plan = service.recalculate_with_event(plan_id, payload)
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DecisionValidationError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Operation plan not found")
    return plan


@router.get('/operation-plans/{plan_id}/input', response_model=OperationPlanRequest, tags=['operation'])
def get_input(plan_id: str, service: OperationPlanService = Depends(get_operation_service)):
    saved = service.repository.get(plan_id)
    if saved is None:
        raise HTTPException(404, detail='Operation plan not found')
    return saved['request']


@router.post('/operation-plans/{plan_id}/adjust', response_model=OperationPlanResponse, status_code=201, tags=['operation'])
def adjust(plan_id: str, payload: AdjustServingsRequest, service: OperationPlanService = Depends(get_operation_service)):
    try:
        plan = service.adjust(plan_id, payload)
    except RevisionConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (DecisionValidationError, ValidationError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(404, detail='Operation plan not found')
    return plan


@router.post('/operation-plans/{plan_id}/review', response_model=OperationPlanResponse, tags=['operation'])
def review(plan_id: str, service: OperationPlanService = Depends(get_operation_service)):
    try:
        plan = service.review(plan_id)
    except RevisionConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(404, detail='Operation plan not found')
    return plan
