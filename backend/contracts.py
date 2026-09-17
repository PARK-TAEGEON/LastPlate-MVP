from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Attendance(Contract):
    registered_population: int = Field(gt=0, le=100000, strict=True)
    vacation: int = Field(ge=0, strict=True)
    business_trip: int = Field(ge=0, strict=True)
    work_from_home: int = Field(ge=0, strict=True)
    overtime: int = Field(ge=0, strict=True)

    @model_validator(mode='after')
    def population(self):
        if self.registered_population <= self.vacation + self.business_trip + self.work_from_home:
            raise ValueError('휴가·출장·재택 합계는 재직 인원보다 작아야 합니다.')
        return self


class PlanRequest(Contract):
    site_id: str = Field(min_length=1, max_length=100, pattern=r'^[\w가-힣.-]+$')
    site_name: str = Field(min_length=1, max_length=120)
    target_date: date
    as_of: date
    meal_type: Literal['lunch'] = 'lunch'
    meal_capacity: int = Field(gt=0, le=100000, strict=True)
    attendance: Attendance
    weekly_menu: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    recipes: list[dict[str, Any]] = Field(max_length=1000)
    inventory: list[dict[str, Any]] = Field(max_length=5000)
    planned_orders: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    nutrition: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    prices: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    monthly_prices: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    supply_events: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    sources: dict[str, str]
    operation_policy: dict[str, Any] = Field(default_factory=dict)
    events: list[str | dict[str, Any]] = Field(default_factory=list, max_length=30)
    availability: dict[str, Any] | None = None
    is_demo: bool = True

    @model_validator(mode='after')
    def coherence(self):
        if self.as_of > self.target_date:
            raise ValueError('기준일은 운영일보다 늦을 수 없습니다.')
        if any(not v.strip() or len(v) > 500 for v in self.sources.values()):
            raise ValueError('출처를 입력하세요.')
        if not self.is_demo and any('DEMO' in v.upper() or 'SIMULATION' in v.upper() for v in self.sources.values()):
            raise ValueError('DEMO 출처가 포함된 계획은 실제 운영 데이터로 저장할 수 없습니다.')
        if any(isinstance(e, str) and (not e.strip() or len(e) > 2000) for e in self.events):
            raise ValueError('이벤트는 1~2000자여야 합니다.')
        return self


class ReplanRequest(Contract):
    existing_context: str = Field(min_length=1, max_length=100, description='이전 API 응답의 request_id')
    events: list[str | dict[str, Any]] = Field(min_length=1, max_length=30,
        description='현재 유효한 전체 이벤트 목록. 이전 목록을 대체하므로 반복 제출해도 중복 가산하지 않습니다.')


class ActualRequest(Contract):
    site_id: str = Field(min_length=1, max_length=100)
    target_date: date
    actual_diners: int = Field(ge=0, le=100000, strict=True)
    prepared_servings: int = Field(ge=0, le=100000, strict=True)
    unserved_leftover_kg: float | None = Field(default=None, ge=0, le=1000000)
    plate_waste_kg: float | None = Field(default=None, ge=0, le=1000000)
    ingredient_waste_kg: float | None = Field(default=None, ge=0, le=1000000)
    shortage: bool
    notes: str = Field(default='', max_length=4000)
    is_demo: bool | None = None
    plan_request_id: str | None = Field(default=None, max_length=100)


class ActualCorrection(ActualRequest):
    reason: str = Field(min_length=1, max_length=1000)
    expected_revision: str = Field(min_length=1, max_length=100)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip(): raise ValueError('정정 사유를 입력하세요.')
        return value.strip()


class WorkspacePlan(Contract):
    site_id: str = Field(min_length=1, max_length=100)
    target_date: date
    base_request_id: str | None = Field(default=None, max_length=100)
    attendance: Attendance
    weekly_menu: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    inventory: list[dict[str, Any]] = Field(max_length=5000)
    planned_orders: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    events: list[str] = Field(default_factory=list, max_length=30)
    menu_uploaded: bool = False
    inventory_uploaded: bool = False


class EventPreview(Contract):
    site_id: str = Field(min_length=1, max_length=100)
    target_date: date
    plan_id: str | None = Field(default=None, max_length=100)
    events: list[str] = Field(max_length=30)


class WorkspaceReplan(Contract):
    existing_context: str = Field(min_length=1, max_length=100)
    events: list[str] = Field(max_length=30)


class SiteSettings(Contract):
    registered_population: int = Field(gt=0,le=100000,strict=True)
    meal_capacity: int = Field(gt=0,le=100000,strict=True)
    safety_margin_pct: float = Field(ge=0,le=100)
    minimum_protein: float = Field(ge=0,le=10000)
    calorie_min: float = Field(ge=0,le=100000)
    calorie_max: float = Field(ge=0,le=100000)
    sodium_max: float = Field(ge=0,le=1000000)
    allergy_restriction: list[str] = Field(max_length=100)

    @model_validator(mode='after')
    def bounds(self):
        if self.calorie_min>self.calorie_max:raise ValueError('열량 최소값이 최대값보다 큽니다.')
        if any(not s.strip() or len(s)>100 for s in self.allergy_restriction):raise ValueError('알레르기 제한 항목을 확인하세요.')
        return self


class DemandResult(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    prediction_id: str
    target_date: str
    predicted_diners: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    predicted_rate: float | None = None
    available_population: float | None = None
    model_version: str
    model_type: str | None = None
    applicability: str
    confidence: str | None = None
    warnings: list[dict] = Field(default_factory=list)
    source_type: Literal['MODEL'] = 'MODEL'


class OperationResult(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    recommended_servings: int | None
    base_demand: float | None
    safety_margin: float | None
    ingredient_requirements: list[dict]
    order_reviews: list[dict]
    constraints: dict
    alerts: list[dict]
    status: str
    requires_human_approval: Literal[True]


class RiskResult(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    alerts: list[dict]
    inventory_status: list[dict]
    affected_menus: list[dict]
    substitute_candidates: list[dict]
    risk_events: list[dict]
    recommended_rechecks: list[Any]
    requires_confirmation: bool


class DecisionResult(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    decision_type: Literal['KEEP', 'ADJUST', 'REVIEW', 'BLOCK', 'NEEDS_CONFIRMATION']
    recommended_servings: int | None
    procurement_actions: list[dict]
    inventory_actions: list[dict]
    menu_actions: list[dict]
    critical_alerts: list[Any]
    confidence: str
    requires_human_approval: Literal[True]
    decision_trace: list[Any]
    data_quality_notes: list[str]


class PipelineResult(Contract):
    contract_version: Literal['1.0'] = '1.0'
    pipeline_status: Literal['SUCCESS', 'PARTIAL', 'FAILED']
    persistence_status: Literal['SUCCESS', 'PARTIAL', 'FAILED']
    request_id: str
    site_id: str
    target_date: str
    parent_request_id: str | None = None
    demand: DemandResult | None = None
    operation: OperationResult | None = None
    inventory_risk: RiskResult | None = None
    decision: DecisionResult | None = None
    warnings: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    sources: dict[str, str]
    is_demo: bool
    advisory_only: Literal[True] = True
    persistence_ids: dict[str, str] = Field(default_factory=dict)
    event_context: dict = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
