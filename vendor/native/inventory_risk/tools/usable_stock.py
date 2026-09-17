"""Native service-date stock eligibility; quantity stays in the caller's unit.

Same-day expiry is usable, matching the Inventory allocator's existing policy.
This helper does not allocate lots, apply restrictions, or include planned orders.
"""
from datetime import date


def usable_stock(quantity, expiry_date, service_date):
    expiry = date.fromisoformat(expiry_date) if isinstance(expiry_date, str) else expiry_date
    service = date.fromisoformat(service_date) if isinstance(service_date, str) else service_date
    return quantity if expiry >= service else 0
