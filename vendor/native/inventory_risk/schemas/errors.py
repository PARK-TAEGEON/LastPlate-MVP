"""Public structured errors; no silent DEMO fallback."""
from pydantic import Field, ValidationError
from .models import Model

class ErrorDetail(Model):
    code: str
    message: str
    file: str | None = None
    row: int | None = Field(default=None, ge=1)
    field: str | None = None

class DataQualityError(ValueError):
    def __init__(self, message, *, file=None, row=None, field=None, code="data_quality_error"):
        self.detail = ErrorDetail(code=code, message=message, file=str(file) if file else None, row=row, field=field)
        super().__init__(message)

def input_error(message, field):
    return DataQualityError(message, field=field, code="input_validation_error")

def validation_error(exc: ValidationError, *, file=None, row=None, prefix=""):
    first = exc.errors()[0]
    field = ".".join(str(x) for x in first["loc"]) or "record"
    return DataQualityError(first["msg"], file=file, row=row, field=prefix + field,
                            code="data_quality_error" if file else "input_validation_error")
