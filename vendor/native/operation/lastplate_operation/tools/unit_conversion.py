from decimal import Decimal

UNITS = {"g": ("g", Decimal(1)), "kg": ("g", Decimal(1000)),
         "ml": ("ml", Decimal(1)), "l": ("ml", Decimal(1000)),
         "ea": ("ea", Decimal(1))}


class UnitError(ValueError):
    pass


def normalize(amount, unit):
    if unit not in UNITS:
        raise UnitError(f"Unsupported unit: {unit}")
    canonical, factor = UNITS[unit]
    return amount * factor, canonical


def assert_same_unit(first, second, ingredient):
    if first != second:
        raise UnitError(f"{ingredient}: incompatible dimensions {first} / {second}")
