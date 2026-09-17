from datetime import date
from typing import Protocol
from schemas.models import MonthlyPrice
from .local import DEMO_DIR, csv_rows, validate_row

class MonthlyPriceAdapter(Protocol):
    source: str
    def get_monthly_history(self, ingredient: str, as_of: date) -> list[MonthlyPrice]: ...

class DemoMonthlyPriceAdapter:
    source = "DEMO:demo_monthly_price.csv"
    def __init__(self, path=DEMO_DIR / "demo_monthly_price.csv"):
        self.rows = [validate_row(MonthlyPrice,r) for r in csv_rows(path,MonthlyPrice.model_fields)]
    def get_monthly_history(self, ingredient, as_of):
        return [r for r in self.rows if r.ingredient == ingredient and r.year_month < as_of.strftime("%Y-%m")]
