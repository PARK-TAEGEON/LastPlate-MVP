from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from .unit_conversion import normalize, assert_same_unit


def ceil_quantity(value, quantum):
    return (value / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum


def aggregate(rows, field):
    totals = {}
    for row in rows:
        amount, unit = normalize(getattr(row, field), row.unit)
        if row.ingredient in totals:
            previous, previous_unit = totals[row.ingredient]
            assert_same_unit(previous_unit, unit, row.ingredient)
            amount += previous
        totals[row.ingredient] = (amount, unit)
    return totals


def purchase_details(required, stock, loss, cooking_quantum, purchase_quantum, tolerance):
    # Rational division retains repeating raw requirements exactly until purchase rounding.
    raw = Fraction(required) / (1 - Fraction(loss) / 100)
    cooking = raw if cooking_quantum is None else Fraction(ceil_fraction(raw, cooking_quantum))
    need = ceil_fraction(max(Fraction(0), cooking - Fraction(stock)), purchase_quantum)
    upper = ceil_fraction(Fraction(need) * (1 + Fraction(tolerance) / 100), purchase_quantum)
    return raw, cooking, need, upper


def ceil_fraction(value, quantum):
    return (value / Fraction(quantum)).__ceil__() * quantum


def review_order(planned, lower, upper):
    if planned < lower:
        return "UNDER", lower - planned
    if planned > upper:
        return "OVER", planned - upper
    return "OK", Decimal(0)
