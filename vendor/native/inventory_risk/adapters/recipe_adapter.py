from typing import Protocol
from schemas.models import Recipe, IngredientAmount
from .local import DEMO_DIR, csv_rows, validate_row, fail

class RecipeAdapter(Protocol):
    source: str
    def get_recipe(self, menu_name: str) -> Recipe | None: ...
    def list_recipes(self) -> list[Recipe]: ...

class DemoRecipeAdapter:
    source = "DEMO:demo_recipe_ingredients.csv"
    def __init__(self, path=DEMO_DIR / "demo_recipe_ingredients.csv"):
        grouped = {}
        for r in csv_rows(path,("recipe_id","menu_name","category","ingredient","amount_per_serving","unit")):
            item = grouped.setdefault(r["menu_name"], dict(recipe_id=r["recipe_id"], menu_name=r["menu_name"], category=r["category"], ingredients=[]))
            if item["recipe_id"]!=r["recipe_id"] or item["category"]!=r["category"]:
                fail(r,"recipe_id","Inconsistent recipe identity/category")
            item["ingredients"].append(validate_row(IngredientAmount,r,{k:r[k] for k in ("ingredient", "amount_per_serving", "unit")}))
        self.recipes = {k:Recipe(**v) for k,v in grouped.items()}
    def get_recipe(self, menu_name):
        return self.recipes.get(menu_name)
    def list_recipes(self):
        return list(self.recipes.values())
