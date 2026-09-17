from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from .decision_trace import TraceStep
from .context import RecheckRequest

Decision = Literal["KEEP", "ADJUST", "REVIEW", "BLOCK", "NEEDS_CONFIRMATION"]


class Action(BaseModel):
    action_id: str
    ingredient: str | None = None
    menu: str | None = None
    candidate_id: str | None = None
    decision: Decision
    action: str
    reason: str
    current_plan: float | None = None
    recommended: dict | None = None
    unit: str | None = None
    failed_constraints: list[str] = Field(default_factory=list)
    unknown_constraints: list[str] = Field(default_factory=list)
    selected: bool = False
    scope: dict = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)


class DecisionOutput(BaseModel):
    schema_version: Literal['0.1.3'] = '0.1.3'
    run_id: str | None = None
    recommendation_revision: str
    selected_action_ids: list[str] = Field(default_factory=list)
    rejected_candidate_ids: list[str] = Field(default_factory=list)
    recheck_history: list[RecheckRequest] = Field(default_factory=list)
    upstream_traces: dict[str, list] = Field(default_factory=dict)
    status: Literal["ok", "needs_confirmation", "blocked"]
    critical_alerts: list[dict] = Field(default_factory=list)
    recommended_servings: int | None = None
    serving_action: Action
    procurement_actions: list[Action] = Field(default_factory=list)
    inventory_actions: list[Action] = Field(default_factory=list)
    menu_actions: list[Action] = Field(default_factory=list)
    candidate_evaluations: list[Action] = Field(default_factory=list)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    provenance_notes: list[str] = Field(default_factory=list)
    source_provenance: list[dict] = Field(default_factory=list)
    quality_records: list[dict] = Field(default_factory=list)
    confidence_evidence: list[dict] = Field(default_factory=list)
    confidence_reasons: list[str]
    requires_human_approval: Literal[True] = True
    approval_status: Literal["pending"] = "pending"
    recommended_rechecks: list[RecheckRequest] = Field(default_factory=list)
    decision_trace: list[TraceStep] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recommendation_revision: str | None = None
    choice: Literal["approve", "modify", "reject"]
    operator_id: str = Field(min_length=1)
    comment: str = ""
    revised_input: dict | None = None

    @model_validator(mode="after")
    def revision(self):
        if self.choice == "modify" and self.revised_input is None:
            raise ValueError("modify requires complete revised_input for revalidation")
        if self.choice != "modify" and self.revised_input is not None:
            raise ValueError("revised_input is only valid for modify")
        return self
