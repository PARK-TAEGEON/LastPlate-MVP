from dataclasses import dataclass
from .recipe_adapter import RecipeAdapter, DemoRecipeAdapter
from .nutrition_adapter import NutritionAdapter, DemoNutritionAdapter
from .price_trend_adapter import PriceTrendAdapter, DemoPriceTrendAdapter
from .monthly_price_adapter import MonthlyPriceAdapter, DemoMonthlyPriceAdapter
from .inventory_adapter import InventoryAdapter, DemoInventoryAdapter
from .supply_risk_adapter import SupplyRiskAdapter, DemoSupplyRiskAdapter

@dataclass
class AdapterBundle:
    recipe: RecipeAdapter
    nutrition: NutritionAdapter
    price_trend: PriceTrendAdapter
    monthly_price: MonthlyPriceAdapter
    inventory: InventoryAdapter
    supply_risk: SupplyRiskAdapter

    @classmethod
    def demo(cls):
        return cls(DemoRecipeAdapter(), DemoNutritionAdapter(), DemoPriceTrendAdapter(), DemoMonthlyPriceAdapter(), DemoInventoryAdapter(), DemoSupplyRiskAdapter())

    def sources(self):
        return {**{name:getattr(self, name).source for name in self.__dataclass_fields__}, "weekly_menu":self.inventory.menu_source, "constraints":"DEMO configurable dish-level thresholds"}
