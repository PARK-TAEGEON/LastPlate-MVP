"""Shared validation and JSON utilities; records use ordinary dictionaries."""
import json
import math
from datetime import date, datetime, timezone


class ValidationError(ValueError):
    """Input does not satisfy the persistence contract."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def to_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Invalid JSON value: {exc}") from exc


def from_json(value):
    if value is None:
        return None
    try:
        result = json.loads(value, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        to_json(result)  # Reject overflow such as 1e999, including nested values.
        return result
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Malformed or non-finite JSON: {exc}") from exc


def validate_date(value):
    if not isinstance(value, str):
        raise ValidationError("Date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValidationError("Date must be YYYY-MM-DD")
    return value


def normalize_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError("Timestamp must be timezone-aware ISO 8601") from exc


def number(value, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("Expected a number, not a boolean or string")
    if integer and not isinstance(value, int):
        raise ValidationError("Expected an integer")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0:
        raise ValidationError("Numbers must be finite and nonnegative")
    if integer and value > 9223372036854775807:
        raise ValidationError("Integer exceeds SQLite range")
    return value
