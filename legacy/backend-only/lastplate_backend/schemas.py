"""HTTP request and response contracts shared by backend, ML, and frontend."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Reject misspelled fields instead of silently changing an operation plan."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ForecastInput(StrictModel):
    """Normalized output expected from the Demand Forecast Tool / ML team."""

    site_id: str = Field(min_length=1, max_length=120)
    meal_date: date
    meal_type: str = Field(default="lunch", min_length=1, max_length=40)
    lower: float = Field(ge=0, description="Lower bound of the predicted diner count")
    mid: float = Field(ge=0, description="Point prediction of the diner count")
    upper: float = Field(ge=0, description="Upper bound of the predicted diner count")
    included_event_ids: list[str] = Field(default_factory=list)
    model_version: str | None = Field(default=None, max_length=120)
    generated_at: datetime | None = None
    interval_method: Literal["supplied", "demo_interval", "point_only"] = "supplied"
    source_kind: Literal["manual", "demo", "ml"] = "manual"
    input_summary: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interval(self) -> "ForecastInput":
        if not self.lower <= self.mid <= self.upper:
            raise ValueError("forecast must satisfy lower <= mid <= upper")
        if any(not event_id.strip() for event_id in self.included_event_ids):
            raise ValueError("included_event_ids cannot contain an empty ID")
        if not self.site_id.strip() or not self.meal_type.strip():
            raise ValueError("forecast site_id and meal_type cannot be blank")
        return self


class EventInput(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    status: Literal["confirmed", "pending", "cancelled"]
    delta: int = Field(description="Incremental diner-count change, e.g. +35 or -20")
    event_type: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("id")
    @classmethod
    def event_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id cannot be blank")
        return value


class BatchInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    start: datetime
    planned: int = Field(ge=0)
    capacity: int = Field(ge=0)
    status: Literal["planned", "cooking", "done"] = "planned"
    fixed_qty: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_quantities(self) -> "BatchInput":
        if self.planned > self.capacity:
            raise ValueError("planned cannot exceed capacity")
        if self.fixed_qty is not None and self.fixed_qty > self.capacity:
            raise ValueError("fixed_qty cannot exceed capacity")
        return self


class MenuInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    recipe_g: dict[str, int] = Field(min_length=1, description="Ingredient grams per serving")
    batches: list[BatchInput] = Field(min_length=1)
    servings_per_guest: float = Field(default=1.0, gt=0, le=10)
    minimum_servings: int = Field(default=0, ge=0)
    nutrition_per_portion: dict[str, float] = Field(default_factory=dict)

    @field_validator("recipe_g")
    @classmethod
    def validate_recipe(cls, recipe: dict[str, int]) -> dict[str, int]:
        for ingredient, grams in recipe.items():
            if not ingredient.strip():
                raise ValueError("recipe ingredient cannot be blank")
            if isinstance(grams, bool) or grams <= 0:
                raise ValueError("recipe grams must be a positive integer")
        return recipe

    @field_validator("nutrition_per_portion")
    @classmethod
    def validate_nutrition(cls, nutrition: dict[str, float]) -> dict[str, float]:
        for nutrient, amount in nutrition.items():
            if not nutrient.strip() or amount < 0:
                raise ValueError("nutrition keys must be nonblank and values nonnegative")
        return nutrition


class InventoryLotInput(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    quantity_kg: float = Field(ge=0)
    reserved_kg: float = Field(default=0, ge=0)
    expires_on: date

    @field_validator('quantity_kg', 'reserved_kg')
    @classmethod
    def whole_grams(cls, value):
        if Decimal(str(value)) * 1000 % 1:
            raise ValueError('kg quantities must use at most three decimal places')
        return value

    @model_validator(mode="after")
    def validate_reserved(self) -> "InventoryLotInput":
        if self.reserved_kg > self.quantity_kg:
            raise ValueError("lot reserved_kg must not exceed quantity_kg")
        return self


class InventoryItemInput(StrictModel):
    ingredient: str = Field(min_length=1, max_length=120)
    available_kg: float | None = Field(default=None, ge=0, description="Net usable stock; do not subtract reservations again")
    physical_kg: float | None = Field(default=None, ge=0)
    reserved_kg: float = Field(default=0, ge=0)
    lots: list[InventoryLotInput] = Field(default_factory=list)
    expires_on: date | None = None
    order_unit_kg: float = Field(default=0.001, gt=0, le=1000)
    unit_price_per_kg: float | None = Field(default=None, ge=0)
    expected_delivery_at: datetime | None = None

    @field_validator('available_kg', 'physical_kg', 'reserved_kg', 'order_unit_kg')
    @classmethod
    def whole_grams(cls, value):
        if value is not None and Decimal(str(value)) * 1000 % 1:
            raise ValueError('kg quantities must use at most three decimal places')
        return value

    @model_validator(mode="after")
    def validate_stock_mode(self) -> "InventoryItemInput":
        if sum((self.available_kg is not None, self.physical_kg is not None, bool(self.lots))) != 1:
            raise ValueError("provide exactly one stock source: available_kg, physical_kg, or lots")
        if self.physical_kg is not None and self.reserved_kg > self.physical_kg:
            raise ValueError("reserved_kg must not exceed physical_kg")
        if self.physical_kg is None and self.reserved_kg:
            raise ValueError("reserved_kg requires physical_kg; use lot reservations for lots")
        if self.lots and self.expires_on is not None:
            raise ValueError("use each lot's expires_on when lots are provided")
        if len({lot.id for lot in self.lots}) != len(self.lots):
            raise ValueError("lot IDs must be unique within an ingredient")
        return self

    @field_validator("ingredient")
    @classmethod
    def ingredient_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ingredient cannot be blank")
        return value


class OperationPolicy(StrictModel):
    target_method: Literal["additive", "max_interval_and_buffer"] = "additive"
    demand_basis: Literal["lower", "mid", "upper"] = "upper"
    safety_buffer_people: int = Field(default=0, ge=0)
    safety_buffer_rate: float = Field(default=0.0, ge=0, le=1)
    cooking_unit: int = Field(default=1, ge=1, le=1000, strict=True)
    operating_rules_verified: bool = True


class OperationConstraints(StrictModel):
    minimum_servings_by_menu: dict[str, int] = Field(default_factory=dict)
    minimum_nutrition_per_guest: dict[str, float] = Field(default_factory=dict)

    @field_validator("minimum_servings_by_menu")
    @classmethod
    def validate_serving_minima(cls, values: dict[str, int]) -> dict[str, int]:
        for menu, amount in values.items():
            if not menu.strip() or amount < 0:
                raise ValueError("minimum servings must have nonblank menu names and nonnegative values")
        return values

    @field_validator("minimum_nutrition_per_guest")
    @classmethod
    def validate_nutrition_minima(cls, values: dict[str, float]) -> dict[str, float]:
        for nutrient, amount in values.items():
            if not nutrient.strip() or amount < 0:
                raise ValueError("nutrition minima must have nonblank names and nonnegative values")
        return values


class OperationPlanRequest(StrictModel):
    site_id: str = Field(default="demo-site", min_length=1, max_length=120)
    meal_date: date
    meal_type: str = Field(default="lunch", min_length=1, max_length=40)
    current_time: datetime
    forecast: ForecastInput
    events: list[EventInput] = Field(default_factory=list)
    menus: list[MenuInput] = Field(min_length=1)
    inventory: list[InventoryItemInput] = Field(default_factory=list)
    policy: OperationPolicy = Field(default_factory=OperationPolicy)
    constraints: OperationConstraints = Field(default_factory=OperationConstraints)
    applied_servings: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_unique_names(self) -> "OperationPlanRequest":
        if not self.site_id.strip() or not self.meal_type.strip():
            raise ValueError("site_id and meal_type cannot be blank")
        if self.forecast.site_id != self.site_id:
            raise ValueError("forecast.site_id must match site_id")
        if self.forecast.meal_date != self.meal_date:
            raise ValueError("forecast.meal_date must match meal_date")
        if self.forecast.meal_type != self.meal_type:
            raise ValueError("forecast.meal_type must match meal_type")
        menu_names = [menu.name for menu in self.menus]
        if len(menu_names) != len(set(menu_names)):
            raise ValueError("menu names must be unique")
        ingredient_names = [item.ingredient for item in self.inventory]
        if len(ingredient_names) != len(set(ingredient_names)):
            raise ValueError("inventory ingredient names must be unique")
        event_ids = [event.id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event IDs must be unique; submit only the latest version")
        unknown_minimums = set(self.constraints.minimum_servings_by_menu) - set(menu_names)
        if unknown_minimums:
            raise ValueError(f"minimum_servings_by_menu has unknown menu(s): {sorted(unknown_minimums)}")
        if self.applied_servings is not None and self.applied_servings % self.policy.cooking_unit:
            raise ValueError("applied_servings must be a multiple of policy.cooking_unit")
        times = [batch.start for menu in self.menus for batch in menu.batches]
        times.extend(item.expected_delivery_at for item in self.inventory if item.expected_delivery_at)
        if any((t.utcoffset() is None) != (self.current_time.utcoffset() is None) for t in times):
            raise ValueError("all timestamps must use the same timezone awareness")
        return self


class PurchaseRecommendation(StrictModel):
    ingredient: str
    shortage_kg: float
    order_unit_kg: float
    recommended_order_kg: float
    estimated_cost: float | None = None
    reason: str
    package_count: int = 0
    delivery_status: Literal["on_time", "late", "unconfirmed"] = "unconfirmed"
    expected_delivery_at: datetime | None = None
    required_by: datetime | None = None


class Alert(StrictModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    message: str
    menu: str | None = None
    ingredient: str | None = None


class InventoryAdvisory(StrictModel):
    code: Literal["EXPIRED_STOCK", "USE_FIRST_EXPIRING_STOCK"]
    severity: Literal["warning", "critical"]
    ingredient: str
    expires_on: date
    days_until_expiry: int
    message: str


class OperationPlanResponse(StrictModel):
    id: str
    parent_plan_id: str | None = None
    created_at: datetime
    site_id: str
    meal_date: date
    meal_type: str
    result: dict[str, Any]
    purchase_recommendations: list[PurchaseRecommendation]
    alerts: list[Alert]
    inventory_advisories: list[InventoryAdvisory]
    stock_allocations: list[dict[str, Any]] = Field(default_factory=list)
    projected_after_purchase: dict[str, Any] | None = None
    review_allowed: bool = False
    review_status: Literal["pending", "reviewed_demo"] = "pending"
    reviewed_at: datetime | None = None


class RecalculateWithEventRequest(StrictModel):
    event: EventInput
    current_time: datetime


class AdjustServingsRequest(StrictModel):
    applied_servings: int | None = Field(default=None, ge=0, strict=True)
    current_time: datetime


class HealthResponse(StrictModel):
    status: Literal["ok"]
    service: str
    version: str
