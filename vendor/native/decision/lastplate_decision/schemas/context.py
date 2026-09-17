"""Versioned scope, provenance and recheck contracts. Missing is never PASS."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class MenuScope(Contract):
    menu: str = Field(min_length=1)
    ingredients: list[str] = Field(default_factory=list)
    ingredients_complete: bool = False


class AnalysisScope(Contract):
    target_date: str | None = None
    meal_type: str | None = None
    menus: list[MenuScope] = Field(default_factory=list)
    menus_complete: bool = False
    coverage: Literal['full', 'event', 'unknown'] = 'unknown'

    @field_validator('target_date')
    @classmethod
    def valid_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError('Use YYYY-MM-DD')
        return value


class Provenance(Contract):
    dependency_basis: Literal["independent", "demand_scaled"] = "independent"
    target_date: str | None = None
    prediction_id: str | None = None
    input_revision: str | None = None
    result_revision: str | None = None
    analysis_scope: AnalysisScope = Field(default_factory=AnalysisScope)
    consumed_results: dict[str, str] = Field(default_factory=dict)
    metadata_source: str | None = None

    _valid_date = field_validator('target_date')(AnalysisScope.valid_date.__func__)


class RecheckRequest(Contract):
    analysis_mode: Literal["full"] | None = None
    request_id: str
    agent: str
    reason: str
    input_revision: str | None = None
    source_agent: str = 'decision'
    source_result_revision: str | None = None
    baseline_result_revision: str | None = None
    result_revision: str | None = None
    status: Literal['pending', 'completed', 'failed', 'stale'] = 'pending'
    attempts: int = 0
    required_dependencies: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class ScopeSelector(Contract):
    target_date: str | None = None
    end_date: str | None = None
    meal_type: str | None = None
    menu: str | None = None
    ingredient: str | None = None
    candidate_id: str | None = None
    applies_to_all: bool = False

    _valid_dates = field_validator('target_date', 'end_date')(AnalysisScope.valid_date.__func__)
