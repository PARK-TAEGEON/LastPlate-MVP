from .unit_conversion import normalize, assert_same_unit


def check_constraints(policy, recipe_totals):
    checks = []
    rules, nutrition = policy.constraints, policy.nutrition_per_serving

    def add(name, actual, lower=None, upper=None):
        status = "UNKNOWN" if actual is None else (
            "FAIL" if (lower is not None and actual < lower) or (upper is not None and actual > upper) else "PASS")
        checks.append({"constraint": name, "status": status,
            "actual": float(actual) if actual is not None else None,
            "minimum": float(lower) if lower is not None else None,
            "maximum": float(upper) if upper is not None else None})

    for ingredient, minimum in rules.minimum_serving_amount.items():
        amount, unit = normalize(minimum.amount, minimum.unit)
        actual, actual_unit = recipe_totals.get(ingredient, (None, unit))
        assert_same_unit(unit, actual_unit, ingredient)
        add("minimum_serving_amount:" + ingredient, actual, lower=amount)
    for name, attribute, lower, upper in [
        ("minimum_protein", "protein", rules.minimum_protein, None),
        ("calorie_range", "calories", rules.calorie_range[0] if rules.calorie_range else None,
         rules.calorie_range[1] if rules.calorie_range else None),
        ("sodium_max", "sodium", None, rules.sodium_max),
    ]:
        if lower is not None or upper is not None:
            add(name, getattr(nutrition, attribute) if nutrition else None, lower, upper)
    if rules.allergy_restriction:
        allergens = nutrition.allergens if nutrition else None
        found = sorted(set(rules.allergy_restriction) & set(allergens or []))
        checks.append({"constraint": "allergy_restriction", "status":
            "UNKNOWN" if allergens is None else "FAIL" if found else "PASS", "matched": found})
    states = {c["status"] for c in checks}
    status = "FAIL" if "FAIL" in states else "UNKNOWN" if "UNKNOWN" in states else "PASS" if checks else "NOT_CONFIGURED"
    return {"status": status, "checks": checks}
