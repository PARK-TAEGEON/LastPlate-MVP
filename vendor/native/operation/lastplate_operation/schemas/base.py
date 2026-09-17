from decimal import Decimal
from typing import Annotated
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Expected a finite JSON number, not bool/string")
    value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError("Number must be finite")
    if not 0 <= value <= 10**9:
        raise ValueError("Number must be between 0 and 1000000000")
    digits = list(value.as_tuple().digits)
    exponent = value.as_tuple().exponent
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if value and (len(digits) > 15 or exponent < -6):
        raise ValueError("At most 15 significant digits and 6 decimal places are supported")
    if Decimal(str(float(value))) != value:
        raise ValueError("Number cannot round-trip through the JSON numeric snapshot")
    return value


class NumericSchema:
    """Expose JSON numbers only; Decimal's default schema also allows strings."""

    def __get_pydantic_json_schema__(self, schema, handler):
        result = handler(schema)
        if "anyOf" in result:
            number = next(item for item in result.pop("anyOf") if item.get("type") == "number")
            result.update(number)
        for key, target in (("ge", "minimum"), ("le", "maximum"), ("gt", "exclusiveMinimum"), ("lt", "exclusiveMaximum")):
            if key in result:
                result[target] = float(result.pop(key))
        result.setdefault("minimum", 0)
        result.setdefault("maximum", 10**9)
        result["multipleOf"] = 0.000001
        result["x-max-significant-digits"] = 15
        return result


Number = Annotated[Decimal, BeforeValidator(numeric), NumericSchema(), PlainSerializer(float, return_type=float, when_used="json")]
Name = Annotated[str, Field(strict=True, min_length=1)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True, allow_inf_nan=False)
