from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    step: int
    source: str
    rule: str
    finding: str
    evidence: dict = Field(default_factory=dict)
    decision: str | None = None
