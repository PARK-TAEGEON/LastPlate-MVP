"""Canonical adapter contracts. Mass: g/kg, money: KRW, sodium: mg."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class IngredientAmount(Model):
    ingredient: str
    amount_per_serving: float = Field(gt=0)
    unit: Literal["g", "kg"]

class Recipe(Model):
    recipe_id: str
    menu_name: str
    category: str
    ingredients: list[IngredientAmount] = Field(min_length=1)

class Menu(Model):
    date: date
    meal_type: str
    menu_name: str
    expected_max_diners: int = Field(ge=0)
    ingredients: list[IngredientAmount] = Field(min_length=1)

class InventoryLot(Model):
    ingredient: str
    current_stock: float = Field(ge=0)
    unit: Literal["g", "kg"]
    expiry_date: date
    unit_price: float = Field(ge=0)
    minimum_stock: float = Field(ge=0)
    planned_order: float = Field(ge=0)
    storage_type: str
    last_used_date: date | None = None

class Nutrition(Model):
    ingredient: str
    serving_basis: float = Field(gt=0, description="grams")
    kcal: float = Field(ge=0)
    protein: float = Field(ge=0)
    carbohydrate: float = Field(ge=0)
    fat: float = Field(ge=0)
    sodium: float = Field(ge=0)
    allergens: list[str] | None = None

class PriceTrend(Model):
    date: date
    ingredient: str
    current_price: float = Field(gt=0)
    price_1w_ago: float = Field(gt=0)
    price_2w_ago: float = Field(gt=0)
    price_3w_ago: float = Field(gt=0)
    price_4w_ago: float = Field(gt=0)
    unit: Literal["g", "kg"]

class MonthlyPrice(Model):
    year_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    ingredient: str
    average_price: float = Field(gt=0)
    unit: Literal["g", "kg"]
