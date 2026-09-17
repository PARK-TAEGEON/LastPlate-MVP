from decimal import Decimal, ROUND_CEILING


def calculate_servings(demand, policy):
    base = demand.prediction
    basis = "prediction"
    if policy.shortage_policy == "conservative" and demand.prediction_interval:
        base = demand.prediction_interval.upper
        basis = "prediction_interval.upper"
    padded = base * (1 + policy.safety_margin_pct / Decimal(100))
    count = max(policy.minimum_servings, int(padded.to_integral_value(rounding=ROUND_CEILING)))
    return base, count, {"step": "serving_calculator",
        "formula": "max(minimum_servings, ceil(base * (1 + safety_margin_pct / 100)))",
        "inputs": {"basis": basis, "prediction": float(demand.prediction), "base": float(base),
                   "safety_margin_pct": float(policy.safety_margin_pct), "minimum_servings": policy.minimum_servings},
        "result": count}
