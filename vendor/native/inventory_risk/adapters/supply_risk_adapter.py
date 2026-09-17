from datetime import date
from typing import Protocol
from schemas.event import Event
from .local import DEMO_DIR, csv_rows, validate_row, fail

class SupplyRiskAdapter(Protocol):
    source: str
    def get_events(self, as_of: date, horizon_end: date) -> list[Event]: ...

class DemoSupplyRiskAdapter:
    source = "DEMO/SIMULATION:demo_risk_events.csv"
    def __init__(self, path=DEMO_DIR / "demo_risk_events.csv"):
        self.rows=[]
        for r in csv_rows(path,("date","end_date","event_type","ingredient","severity","description","source_type")):
            event=validate_row(Event,r)
            if event.event_type != "supply_risk":
                fail(r,"event_type","Expected supply_risk")
            self.rows.append(event)
    def get_events(self, as_of, horizon_end):
        return [r for r in self.rows if r.date <= horizon_end and (r.end_date or r.date) >= as_of]
