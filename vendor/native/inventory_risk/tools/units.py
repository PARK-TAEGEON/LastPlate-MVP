def grams(amount: float, unit: str) -> float:
    if unit not in {"g", "kg"}:
        raise ValueError(f"Unsupported mass unit: {unit}; adapter must normalize it")
    return amount * (1000 if unit == "kg" else 1)

def price_per_kg(amount: float, unit: str) -> float:
    return amount * 1000 / grams(1, unit)
