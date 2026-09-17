"""Deterministic operation-planning engine for group meals.

This module deliberately has no database, HTTP, or ML-model dependency.  The
backend supplies one validated snapshot of forecast, events, recipes, batches,
and inventory; this module returns one JSON-serializable recommendation.

Important business assumptions
------------------------------
* A menu represents one dish.  By default every diner receives one serving of
  every dish.  ``servings_per_guest`` can describe a different serving ratio.
* ``inventory_kg`` is stock usable by batches that have not started yet.  Stock
  already consumed or irrevocably assigned to a locked batch must be excluded.
* This calculation is a recommendation, not a purchase-order reservation.
  The backend persists an immutable result; a later approval workflow can make
  the inventory transaction separately.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import ceil, isfinite
from typing import Any, Mapping, Sequence


class DecisionValidationError(ValueError):
    """Raised when a caller bypasses API validation with invalid domain data."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionValidationError(f"{label}: expected an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DecisionValidationError(f"{label}: expected a list")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    # ``bool`` is an int subclass, but it is never a useful meal quantity.
    if type(value) is not int or value < minimum:
        raise DecisionValidationError(f"{label}: expected an integer >= {minimum}")
    return value


def _signed_integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise DecisionValidationError(f"{label}: expected an integer")
    return value


def _number(value: Any, label: str, minimum: float = 0.0) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise DecisionValidationError(f"{label}: expected a finite number >= {minimum}")
    result = float(value)
    if not isfinite(result) or result < minimum:
        raise DecisionValidationError(f"{label}: expected a finite number >= {minimum}")
    return result


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise DecisionValidationError("current_time: expected datetime or ISO-format string")
    try:
        # Python < 3.11 did not accept a trailing Z, so normalize it here.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionValidationError(f"current_time: invalid ISO datetime: {value!r}") from exc


def _kg_to_g(value: Any, label: str) -> int:
    """Convert kg to exact integer grams and reject sub-gram stock values."""
    try:
        grams = Decimal(str(value)) * 1000
    except (InvalidOperation, ValueError) as exc:
        raise DecisionValidationError(f"{label}: invalid kg quantity") from exc
    if not grams.is_finite() or grams < 0 or grams != grams.to_integral_value():
        raise DecisionValidationError(
            f"{label}: kg must be nonnegative with at most three decimal places"
        )
    return int(grams)


def adjust_prediction(
    prediction: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, float], int, list[str]]:
    """Apply each confirmed incremental event once by its event ID.

    ``included_event_ids`` prevents a double count when an ML forecast already
    used a known event as a feature.  The backend must send the latest version
    of every event relevant to the requested meal.
    """
    prediction = _mapping(prediction, "prediction")
    values = {
        key: _number(prediction.get(key), f"prediction.{key}")
        for key in ("lower", "mid", "upper")
    }
    if not values["lower"] <= values["mid"] <= values["upper"]:
        raise DecisionValidationError("prediction: lower <= mid <= upper is required")

    included_raw = prediction.get("included_event_ids", [])
    included_items = _sequence(included_raw, "included_event_ids")
    if any(not isinstance(event_id, str) or not event_id.strip() for event_id in included_items):
        raise DecisionValidationError("included_event_ids: expected nonempty string IDs")
    included = set(included_items)

    seen: dict[str, tuple[str, int]] = {}
    applied: list[str] = []
    delta = 0
    for raw_event in _sequence(events, "events"):
        event = _mapping(raw_event, "event")
        event_id = event.get("id")
        status = event.get("status")
        event_delta = event.get("delta")
        if not isinstance(event_id, str) or not event_id.strip():
            raise DecisionValidationError("event.id: expected a nonempty string")
        if status not in ("confirmed", "pending", "cancelled"):
            raise DecisionValidationError("event.status: expected confirmed, pending, or cancelled")
        _signed_integer(event_delta, "event.delta")

        signature = (status, event_delta)
        if event_id in seen:
            if seen[event_id] != signature:
                raise DecisionValidationError(f"event {event_id!r} has conflicting versions")
            continue
        seen[event_id] = signature

        if status == "confirmed" and event_id not in included:
            delta += event_delta
            applied.append(event_id)

    return (
        {key: max(0.0, value + delta) for key, value in values.items()},
        delta,
        applied,
    )


def resolve_target(
    adjusted_prediction: Mapping[str, float], policy: Mapping[str, Any] | None
) -> tuple[int, dict[str, float | str]]:
    """Turn a forecast interval into a transparent safe cooking target."""
    policy = _mapping(policy or {}, "policy")
    basis = policy.get("demand_basis", "upper")
    if basis not in ("lower", "mid", "upper"):
        raise DecisionValidationError("policy.demand_basis: expected lower, mid, or upper")
    buffer_people = _integer(policy.get("safety_buffer_people", 0), "policy.safety_buffer_people")
    buffer_rate = _number(policy.get("safety_buffer_rate", 0.0), "policy.safety_buffer_rate")
    if buffer_rate > 1:
        raise DecisionValidationError("policy.safety_buffer_rate: must not exceed 1.0")

    method = policy.get("target_method", "additive")
    if method not in ("additive", "max_interval_and_buffer"):
        raise DecisionValidationError("unknown target_method")
    unit = _integer(policy.get("cooking_unit", 1), "policy.cooking_unit", 1)
    base_demand = adjusted_prediction[basis]
    buffered_mid = adjusted_prediction["mid"] * (1 + buffer_rate) + buffer_people
    raw_target = (max(adjusted_prediction["upper"], buffered_mid)
                  if method == "max_interval_and_buffer"
                  else base_demand * (1 + buffer_rate) + buffer_people)
    return ceil(raw_target / unit) * unit, {
        "target_method": method,
        "buffered_mid": buffered_mid,
        "raw_target": raw_target,
        "cooking_unit": unit,
        "demand_basis": basis,
        "base_demand": base_demand,
        "safety_buffer_people": buffer_people,
        "safety_buffer_rate": buffer_rate,
    }


def _menu_target(
    operation_target: int, menu: Mapping[str, Any], constraints: Mapping[str, Any]
) -> tuple[int, int, float]:
    ratio = _number(menu.get("servings_per_guest", 1.0), "menu.servings_per_guest", 0.000001)
    menu_minimum = _integer(menu.get("minimum_servings", 0), "menu.minimum_servings")
    minimums = _mapping(constraints.get("minimum_servings_by_menu", {}), "minimum_servings_by_menu")
    configured_minimum = _integer(
        minimums.get(menu["name"], 0), f"minimum_servings_by_menu.{menu['name']}"
    )
    minimum = max(menu_minimum, configured_minimum)
    return max(ceil(operation_target * ratio), minimum), minimum, ratio


def plan_menu(
    target: int,
    minimum_servings: int,
    servings_per_guest: float,
    menu: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Plan a dish while preserving batches that can no longer be changed.

    Increases use earlier mutable batches first.  Decreases use later mutable
    batches first.  This greedy order is intentional and easy to explain in a
    UI; it is not a global cost-optimization algorithm.
    """
    name = menu.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DecisionValidationError("menu.name: expected a nonempty string")
    raw_recipe = _mapping(menu.get("recipe_g"), f"{name}.recipe_g")
    recipe = dict(raw_recipe)
    if not recipe:
        raise DecisionValidationError(f"{name}.recipe_g: must not be empty")
    for ingredient, grams in recipe.items():
        if not isinstance(ingredient, str) or not ingredient.strip():
            raise DecisionValidationError("recipe_g: ingredient names must be nonempty strings")
        _integer(grams, f"recipe_g.{ingredient}", 1)

    raw_nutrition = _mapping(menu.get("nutrition_per_portion", {}), f"{name}.nutrition_per_portion")
    nutrition = {
        nutrient: _number(amount, f"nutrition_per_portion.{nutrient}")
        for nutrient, amount in raw_nutrition.items()
    }
    if any(not isinstance(nutrient, str) or not nutrient.strip() for nutrient in nutrition):
        raise DecisionValidationError("nutrition_per_portion: nutrient names must be nonempty strings")

    timed: list[tuple[datetime, Mapping[str, Any], bool]] = []
    batch_names: set[str] = set()
    for raw_batch in _sequence(menu.get("batches", []), f"{name}.batches"):
        batch = _mapping(raw_batch, f"{name}.batch")
        batch_name = batch.get("name")
        if not isinstance(batch_name, str) or not batch_name.strip() or batch_name in batch_names:
            raise DecisionValidationError(f"{name}.batches: names must be nonempty and unique")
        batch_names.add(batch_name)
        start = _time(batch.get("start"))
        if (start.utcoffset() is None) != (now.utcoffset() is None):
            raise DecisionValidationError("Do not mix timezone-aware and naive timestamps")
        planned = _integer(batch.get("planned"), "batch.planned")
        capacity = _integer(batch.get("capacity"), "batch.capacity")
        if planned > capacity:
            raise DecisionValidationError("batch.planned: must not exceed capacity")
        status = batch.get("status", "planned")
        if status not in ("planned", "cooking", "done"):
            raise DecisionValidationError("batch.status: expected planned, cooking, or done")
        # Scheduled start at/before now is a conservative lock if no live state
        # is available.  A future revision can use a per-site change cutoff.
        locked = status in ("cooking", "done") or start <= now
        if "fixed_qty" in batch:
            fixed_qty = _integer(batch["fixed_qty"], "batch.fixed_qty")
            if not locked:
                raise DecisionValidationError("batch.fixed_qty is valid only for a locked batch")
            if fixed_qty > capacity:
                raise DecisionValidationError("batch.fixed_qty: must not exceed capacity")
        timed.append((start, batch, locked))
    timed.sort(key=lambda item: item[0])

    fixed: list[dict[str, Any]] = []
    future: list[dict[str, Any]] = []
    for start, batch, locked in timed:
        if locked:
            fixed.append(
                {
                    "name": batch["name"],
                    "qty": batch.get("fixed_qty", batch["planned"]),
                    "quantity_is_assumed": "fixed_qty" not in batch,
                }
            )
        else:
            future.append(
                {
                    "name": batch["name"],
                    "start": start.isoformat(),
                    "planned": batch["planned"],
                    "capacity": batch["capacity"],
                    "desired_qty": batch["planned"],
                    "qty": 0,
                }
            )

    locked_qty = sum(batch["qty"] for batch in fixed)
    needed = max(0, target - locked_qty)
    difference = needed - sum(batch["desired_qty"] for batch in future)
    if difference < 0:
        reduce_by = -difference
        for batch in reversed(future):
            cut = min(reduce_by, batch["desired_qty"])
            batch["desired_qty"] -= cut
            reduce_by -= cut
    else:
        for batch in future:
            add = min(difference, batch["capacity"] - batch["desired_qty"])
            batch["desired_qty"] += add
            difference -= add

    possible = locked_qty + sum(batch["desired_qty"] for batch in future)
    return {
        "menu": name,
        "target": target,
        "minimum_servings": minimum_servings,
        "servings_per_guest": servings_per_guest,
        "locked": locked_qty,
        "fixed_batches": fixed,
        "future": future,
        "recipe_g": recipe,
        "nutrition_per_portion": nutrition,
        "equipment_shortage": max(0, target - possible),
    }


def _take_stock(wanted: int, recipe: Mapping[str, int], stock: dict[str, int]) -> int:
    """Allocate whole portions from a request-local inventory copy."""
    if wanted <= 0:
        return 0
    possible = min(stock.get(ingredient, 0) // grams for ingredient, grams in recipe.items())
    qty = min(wanted, possible)
    for ingredient, grams in recipe.items():
        stock[ingredient] = stock.get(ingredient, 0) - qty * grams
    return qty


def allocate_inventory(
    plans: list[dict[str, Any]], inventory_kg: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Allocate one shared inventory pool without double-counting stock.

    The first pass retains existing planned portions where possible.  The second
    pass allocates requested increases.  This makes the policy reproducible and
    protects pre-existing plans before using stock for a scenario change.
    """
    inventory_kg = _mapping(inventory_kg, "inventory_kg")
    initial: dict[str, int] = {}
    for ingredient, kg in inventory_kg.items():
        if not isinstance(ingredient, str) or not ingredient.strip():
            raise DecisionValidationError("inventory: ingredient names must be nonempty strings")
        initial[ingredient] = _kg_to_g(kg, f"inventory.{ingredient}")
    stock = initial.copy()

    for phase in ("keep_original", "increase"):
        for plan in plans:
            for batch in plan["future"]:
                goal = (
                    min(batch["planned"], batch["desired_qty"])
                    if phase == "keep_original"
                    else batch["desired_qty"]
                )
                wanted = goal - batch["qty"]
                batch["qty"] += _take_stock(wanted, plan["recipe_g"], stock)

    needed_target: dict[str, int] = {}
    needed_equipment_plan: dict[str, int] = {}
    for plan in plans:
        recipe = plan["recipe_g"]
        desired = sum(batch["desired_qty"] for batch in plan["future"])
        actual = sum(batch["qty"] for batch in plan["future"])
        plan["final"] = plan["locked"] + actual
        plan["over"] = max(0, plan["final"] - plan["target"])
        plan["shortage"] = max(0, plan["target"] - plan["final"])
        plan["inventory_shortage_servings"] = max(0, desired - actual)
        plan["inventory_blocked"] = actual < desired
        for batch in plan["future"]:
            batch["change"] = batch["qty"] - batch["planned"]
        for ingredient, grams in recipe.items():
            future_target_servings = max(0, plan["target"] - plan["locked"])
            needed_target[ingredient] = needed_target.get(ingredient, 0) + future_target_servings * grams
            needed_equipment_plan[ingredient] = (
                needed_equipment_plan.get(ingredient, 0) + desired * grams
            )

    result: list[dict[str, Any]] = []
    for ingredient in sorted(set(initial) | set(needed_target)):
        available = initial.get(ingredient, 0)
        remaining = stock.get(ingredient, 0)
        target_need = needed_target.get(ingredient, 0)
        equipment_need = needed_equipment_plan.get(ingredient, 0)
        result.append(
            {
                "ingredient": ingredient,
                "available_kg": available / 1000,
                "allocated_kg": (available - remaining) / 1000,
                "remaining_kg": remaining / 1000,
                "needed_for_target_kg": target_need / 1000,
                "needed_for_equipment_plan_kg": equipment_need / 1000,
                "additional_kg_for_target": max(0, target_need - available) / 1000,
                "additional_kg_for_equipment_plan": max(0, equipment_need - available) / 1000,
                "missing_from_input": ingredient not in initial and target_need > 0,
            }
        )
    return result


def evaluate_constraints(
    plans: Sequence[Mapping[str, Any]],
    operation_target: int,
    constraints: Mapping[str, Any],
) -> dict[str, Any]:
    """Check explicit serving and nutrition minima without inventing a menu."""
    violations: list[dict[str, Any]] = []
    nutrition_per_guest: dict[str, float] = {}
    for plan in plans:
        if plan["final"] < plan["minimum_servings"]:
            violations.append(
                {
                    "code": "MINIMUM_SERVINGS_NOT_MET",
                    "menu": plan["menu"],
                    "required": plan["minimum_servings"],
                    "actual": plan["final"],
                }
            )
        if operation_target > 0:
            for nutrient, per_portion in plan["nutrition_per_portion"].items():
                nutrition_per_guest[nutrient] = nutrition_per_guest.get(nutrient, 0.0) + (
                    per_portion * plan["final"] / operation_target
                )

    minimum_nutrition = _mapping(
        constraints.get("minimum_nutrition_per_guest", {}), "minimum_nutrition_per_guest"
    )
    validated_minimums = {
        nutrient: _number(amount, f"minimum_nutrition_per_guest.{nutrient}")
        for nutrient, amount in minimum_nutrition.items()
    }
    if any(not isinstance(nutrient, str) or not nutrient.strip() for nutrient in validated_minimums):
        raise DecisionValidationError("minimum_nutrition_per_guest: nutrient names must be nonempty strings")
    for nutrient, minimum in validated_minimums.items():
        actual = nutrition_per_guest.get(nutrient, 0.0)
        if actual + 1e-9 < minimum:
            violations.append(
                {
                    "code": "NUTRITION_BELOW_MINIMUM",
                    "nutrient": nutrient,
                    "required_per_guest": minimum,
                    "actual_per_guest": actual,
                }
            )

    return {
        "nutrition_per_guest": nutrition_per_guest,
        "minimum_nutrition_per_guest": validated_minimums,
        "violations": violations,
    }


def calculate_decision(
    prediction: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    menus: Sequence[Mapping[str, Any]],
    current_time: datetime | str,
    inventory_kg: Mapping[str, Any],
    policy: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
    applied_servings: int | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable operation recommendation.

    The same input always produces the same output.  No I/O, ML call, database
    update, or permanent inventory reservation is performed here.
    """
    now = _time(current_time)
    constraints = _mapping(constraints or {}, "constraints")
    adjusted_prediction, event_delta, applied_event_ids = adjust_prediction(prediction, events)
    operation_target, policy_result = resolve_target(adjusted_prediction, policy)
    recommended_target = operation_target
    if applied_servings is not None:
        operation_target = _integer(applied_servings, "applied_servings")
        if operation_target % policy_result["cooking_unit"]:
            raise DecisionValidationError("applied_servings must be a multiple of cooking_unit")

    raw_menus = _sequence(menus, "menus")
    menu_names: set[str] = set()
    plans: list[dict[str, Any]] = []
    for raw_menu in raw_menus:
        menu = _mapping(raw_menu, "menu")
        name = menu.get("name")
        if not isinstance(name, str) or not name.strip():
            raise DecisionValidationError("menu.name: expected a nonempty string")
        if name in menu_names:
            raise DecisionValidationError("menus: menu names must be unique")
        menu_names.add(name)
        target, minimum, ratio = _menu_target(operation_target, menu, constraints)
        plans.append(plan_menu(target, minimum, ratio, menu, now))

    inventory_result = allocate_inventory(plans, inventory_kg)
    constraint_result = evaluate_constraints(plans, operation_target, constraints)
    warnings: list[str] = []
    if operation_target < recommended_target:
        warnings.append("BELOW_RECOMMENDED_TARGET")
    if any(plan["over"] for plan in plans):
        warnings.append("LOCKED_BATCH_SURPLUS")
    baseline_lower = _number(_mapping(prediction, "prediction").get("lower"), "prediction.lower")
    if baseline_lower + event_delta < 0:
        warnings.append("NEGATIVE_DEMAND_CLIPPED_TO_ZERO")
    if any(row["missing_from_input"] for row in inventory_result):
        warnings.append("MISSING_INGREDIENT_TREATED_AS_ZERO")
    if any(batch["quantity_is_assumed"] for plan in plans for batch in plan["fixed_batches"]):
        warnings.append("SOME_LOCKED_QUANTITIES_ASSUMED_FROM_PLAN")
    if any(plan["equipment_shortage"] > 0 for plan in plans):
        warnings.append("EQUIPMENT_CAPACITY_SHORTAGE")
    if any(plan["inventory_blocked"] for plan in plans):
        warnings.append("INVENTORY_SHORTAGE")
    if constraint_result["violations"]:
        warnings.append("CONSTRAINT_VIOLATION")

    for plan in plans:
        point_target = ceil(adjusted_prediction["mid"] * plan["servings_per_guest"])
        plan["point_prediction_gap"] = max(0, point_target - plan["final"])

    baseline = _mapping(prediction, "prediction")
    return {
        "current_time": now.isoformat(),
        "baseline_prediction": {
            key: baseline[key] for key in ("mid", "lower", "upper")
        },
        "prediction": adjusted_prediction,
        "event_delta": event_delta,
        "applied_event_ids": applied_event_ids,
        "target": operation_target,
        "recommended_target": recommended_target,
        "policy": policy_result,
        "menus": plans,
        "inventory": inventory_result,
        "constraints": constraint_result,
        "warnings": warnings,
        "allocation_policy": "existing_plan_first_then_increases_in_menu_order",
        "assumptions": [
            "Inventory excludes stock already consumed or reserved for locked batches.",
            "A menu is one dish; servings_per_guest defaults to one serving per diner.",
            "The result is a recommendation and does not reserve inventory or submit an order.",
        ],
    }
