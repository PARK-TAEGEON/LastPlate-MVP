from datetime import date
from typing import Literal
from pydantic import Field, model_validator, field_validator
from .models import Model

class AnalysisRequest(Model):
    as_of: date
    horizon_start: date | None = None
    horizon_end: date | None = None
    mode: Literal["full", "event"] = "full"
    forecast_version: str | None = None
    input_snapshot_id: str | None = None
    prohibited_allergens: list[str] = Field(default_factory=list)

    @field_validator("as_of","horizon_start","horizon_end",mode="before")
    @classmethod
    def explicit_dates(cls,value):
        if value is not None and not isinstance(value,(str,date)):
            raise ValueError("Use an ISO date string or date object")
        return value

    @model_validator(mode="after")
    def period_valid(self):
        from datetime import timedelta
        self.horizon_start = self.horizon_start or self.as_of
        self.horizon_end = self.horizon_end or self.horizon_start + timedelta(days=7)
        if not self.as_of <= self.horizon_start <= self.horizon_end:
            raise ValueError("Require as_of <= horizon_start <= horizon_end")
        return self
