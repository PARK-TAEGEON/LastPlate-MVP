from typing import Protocol
from schemas.models import Nutrition
from .local import DEMO_DIR, csv_rows, validate_row

class NutritionAdapter(Protocol):
    source: str
    def get_nutrition(self, ingredient: str) -> Nutrition | None: ...

class DemoNutritionAdapter:
    source = "DEMO:demo_nutrition.csv"
    def __init__(self, path=DEMO_DIR / "demo_nutrition.csv"):
        self.rows = {}
        for r in csv_rows(path,Nutrition.model_fields,nullable=("allergens",)):
            r["allergens"] = r["allergens"].split("|") if r["allergens"] else []
            self.rows[r["ingredient"]] = validate_row(Nutrition,r)
    def get_nutrition(self, ingredient):
        return self.rows.get(ingredient)
