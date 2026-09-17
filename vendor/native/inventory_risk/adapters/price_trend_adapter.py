from datetime import date
from typing import Protocol
from schemas.models import PriceTrend
from .local import DEMO_DIR, csv_rows, validate_row

class PriceTrendAdapter(Protocol):
    source: str
    def get_price_trend(self, ingredient: str, as_of: date) -> PriceTrend | None: ...

class DemoPriceTrendAdapter:
    source = "DEMO:demo_price_trend.csv"
    def __init__(self, path=DEMO_DIR / "demo_price_trend.csv"):
        self.rows = [validate_row(PriceTrend,r) for r in csv_rows(path,PriceTrend.model_fields)]
    def get_price_trend(self, ingredient, as_of):
        matches = [r for r in self.rows if r.ingredient == ingredient and r.date <= as_of]
        return max(matches, key=lambda r:r.date) if matches else None
