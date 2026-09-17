"""Parse JSON before binary floats can erase excessive input precision."""
from decimal import Decimal
import json


def load_operation_json(text):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")

    result = json.loads(text, parse_float=Decimal, parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError("Operation input must be a JSON object")
    return result
