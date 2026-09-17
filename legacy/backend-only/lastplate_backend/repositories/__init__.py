"""Persistence adapters.  SQLite is intentionally enough for the MVP."""

from .operation_plan_repository import OperationPlanRepository

__all__ = ["OperationPlanRepository"]
