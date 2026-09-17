from typing import Literal, Annotated
from decimal import Decimal
from pydantic import Field, StrictInt, StrictBool, model_validator
from ..schemas.base import Model, Name, Number
from ..schemas.provenance import EvidenceBundle

Quantum = Annotated[Number, Field(ge=Decimal("0.001"), le=1000000)]
LossPercent = Annotated[Number, Field(le=99)]


class Amount(Model):
    amount: Number
    unit: Name


class ConstraintPolicy(Model):
    minimum_serving_amount: dict[str, Amount] = Field(default_factory=dict)
    minimum_protein: Number | None = None  # g per diner, complete meal
    calorie_range: tuple[Number, Number] | None = None  # kcal per diner
    sodium_max: Number | None = None  # mg per diner
    allergy_restriction: list[Name] | None = None

    @model_validator(mode="after")
    def ordered_range(self):
        if self.calorie_range and self.calorie_range[0] > self.calorie_range[1]:
            raise ValueError("calorie_range must be ordered")
        return self


class Nutrition(Model):
    protein: Number | None = None
    calories: Number | None = None
    sodium: Number | None = None
    allergens: list[Name] | None = None  # [] explicitly certifies none in supplied meal


class OperationPolicy(Model):
    execution_mode: Literal["simulation", "operation"] = "simulation"
    policy_acknowledged: StrictBool = False
    capacity_servings: StrictInt | None = Field(default=None, ge=0, le=1000000)
    maximum_input_servings: StrictInt = Field(default=100000, ge=1, le=1000000)
    provenance: EvidenceBundle = Field(default_factory=EvidenceBundle)
    rounding_policy: Literal["legacy_combined", "purchase_only", "cooking_and_purchase"] = "legacy_combined"
    cooking_quantum: dict[Literal["g", "ml", "ea"], Quantum] | None = None
    purchase_quantum: dict[Literal["g", "ml", "ea"], Quantum] | None = None
    fractional_ea_inventory: StrictBool = False
    safety_margin_pct: Number = Field(default=3, le=100)
    trim_loss_pct: dict[str, LossPercent] = Field(default_factory=dict)
    minimum_servings: StrictInt = Field(default=0, ge=0, le=1000000)
    shortage_policy: Literal["conservative", "expected"] = "conservative"
    order_tolerance_pct: Number = Field(default=5, le=100)
    quantity_quantum: dict[Literal["g", "ml", "ea"], Quantum] = Field(
        default_factory=lambda: {"g": 1, "ml": 1, "ea": 1}, json_schema_extra={"deprecated": True},
        description="legacy_combined only; new policies use cooking_quantum / purchase_quantum")
    planned_servings: StrictInt | None = Field(default=None, ge=0, le=1000000)
    required_menus: list[Name] = Field(default_factory=list)
    constraints: ConstraintPolicy = Field(default_factory=ConstraintPolicy)
    nutrition_per_serving: Nutrition | None = None
    data_mode: Literal["DEMO", "REAL", "UNSPECIFIED"] = "UNSPECIFIED"

    @model_validator(mode="after")
    def valid_maps(self):
        if any(v > 99 for v in self.trim_loss_pct.values()):
            raise ValueError("trim_loss_pct must be within 0..99 for this MVP")
        for name in ("quantity_quantum", "cooking_quantum", "purchase_quantum"):
            values = getattr(self, name)
            if values is None:
                continue
            if set(values) != {"g", "ml", "ea"}:
                raise ValueError(f"{name} requires g, ml, ea")
            if any(not Decimal("0.001") <= v <= 1000000 for v in values.values()):
                raise ValueError(f"{name}: quantum must be within 0.001..1000000")
            if name != "cooking_quantum" and values["ea"] != values["ea"].to_integral_value():
                raise ValueError(f"{name}: ea purchase quantum must be a whole item")
        if self.rounding_policy == "legacy_combined":
            if self.cooking_quantum is not None or self.purchase_quantum is not None:
                raise ValueError("legacy_combined uses quantity_quantum only")
        else:
            if self.purchase_quantum is None:
                raise ValueError("Explicit purchase_quantum required for split rounding")
            if self.quantity_quantum != {"g": 1, "ml": 1, "ea": 1}:
                raise ValueError("Non-default deprecated quantity_quantum conflicts with split rounding")
            if self.rounding_policy == "purchase_only" and self.cooking_quantum is not None:
                raise ValueError("purchase_only does not use cooking_quantum")
            if self.rounding_policy == "cooking_and_purchase" and self.cooking_quantum is None:
                raise ValueError("cooking_and_purchase requires cooking_quantum")
        return self
