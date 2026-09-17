from datetime import date as Date
from typing import Literal
from pydantic import model_validator, StrictInt, field_validator, Field
from .models import Model

class Event(Model):
    event_type: Literal["ingredient_restriction_event", "ingredient_restriction_release_event", "expiry_event", "attendance_event", "supply_risk", "price_event", "unparsed_event", "inventory_shortage_event", "inventory_expiry_event"]
    action: Literal["release_restriction"] | None = None
    superseded: bool = False
    event_id: str | None = None
    ingredient: str | None = None
    date: Date | None = None
    end_date: Date | None = None
    restriction: Literal["do_not_use"] | None = None
    attendance_delta: StrictInt | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    description: str = ""
    source_type: str = "user"
    needs_clarification: bool = False
    source_text: str | None = None
    matched_sources: list[str] = Field(default_factory=list)
    reason: str | None = None

    @field_validator("date","end_date",mode="before")
    @classmethod
    def explicit_dates(cls,value):
        if value is not None and not isinstance(value,(str,Date)):
            raise ValueError("Use an ISO date string or date object")
        return value

    @model_validator(mode="after")
    def validate_event(self):
        if self.end_date and self.date and self.end_date < self.date:
            raise ValueError("end_date precedes date")
        if self.event_type in {"ingredient_restriction_event", "ingredient_restriction_release_event", "expiry_event", "supply_risk", "price_event"} and not self.ingredient:
            raise ValueError("ingredient is required")
        if self.event_type == "attendance_event" and self.attendance_delta is None and not self.needs_clarification:
            raise ValueError("attendance_delta or clarification is required")
        if self.event_type == "ingredient_restriction_event" and self.restriction != "do_not_use":
            raise ValueError("restriction is required")
        if self.event_type == "ingredient_restriction_release_event":
            if self.restriction is not None:
                raise ValueError("release cannot carry a restriction")
            self.action = "release_restriction"
        elif self.action is not None:
            raise ValueError("release action requires a release event")
        return self

class EventParseResult(Model):
    """ok=complete; partial=unparsed clauses remain; clarification=ambiguous;
    invalid_input=unsupported input type/invalid date. No number is inferred."""
    status: Literal["ok","partial","needs_clarification","invalid_input"]
    parsed_events: list[Event] = Field(default_factory=list)
    unparsed_segments: list[str] = Field(default_factory=list)
    validation_warnings: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    decision_trace: list[str] = Field(default_factory=list)
