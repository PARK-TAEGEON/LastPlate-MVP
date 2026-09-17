"""All local table failures use file/physical-row/field structured errors."""
import csv
from datetime import datetime
from pathlib import Path
from openpyxl import load_workbook
from pydantic import ValidationError
from schemas.errors import DataQualityError, validation_error

DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "demo"

class Row(dict):
    def __init__(self, values, file, number):
        super().__init__(values)
        self.file, self.number = str(file), number

def fail(row, field, message):
    raise DataQualityError(message, file=row.file, row=row.number, field=field)

def validate_row(model, row, values=None):
    try:
        return model.model_validate(dict(row) if values is None else values)
    except ValidationError as exc:
        error=validation_error(exc, file=row.file, row=row.number)
        if error.detail.field=="amount_per_serving" and "serving_amount" in row:
            error.detail.field="serving_amount"
        raise error from exc

def table_rows(path, raw, required, nullable=()):
    if not raw:
        raise DataQualityError("Empty file", file=path, row=1, field="header")
    header = raw[0][1]
    if any(not isinstance(h,str) or not h.strip() for h in header) or len(set(header)) != len(header):
        raise DataQualityError("Invalid or duplicate column header", file=path, row=1, field="header")
    for name in required:
        if name not in header:
            raise DataQualityError("Missing required column", file=path, row=1, field=name)
    rows=[]
    for number, values in raw[1:]:
        if not any(v is not None and v != "" for v in values):
            continue
        if len(values) != len(header):
            raise DataQualityError("Column count mismatch", file=path, row=number, field="record")
        row=Row(dict(zip(header,values)),path,number)
        for field in required:
            if field not in nullable and (row[field] is None or str(row[field]).strip()==""):
                fail(row,field,"Required value is empty")
        rows.append(row)
    if not rows:
        raise DataQualityError("No data rows",file=path,row=2,field="record")
    return rows

def csv_rows(path, required=(), nullable=()):
    reader=None
    try:
        with Path(path).open(encoding="utf-8-sig",newline="") as stream:
            reader=csv.reader(stream,strict=True)
            raw=[]
            for values in reader:
                raw.append((reader.line_num,values))
        return table_rows(path,raw,required,nullable)
    except DataQualityError:
        raise
    except (OSError,UnicodeError,csv.Error) as exc:
        raise DataQualityError(str(exc),file=path,row=max(1,reader.line_num) if reader else 1,field="file") from exc

def excel_rows(path, required=(), nullable=()):
    book=None
    try:
        book=load_workbook(path,read_only=True,data_only=True)
        if "DEMO" not in book.sheetnames:
            raise DataQualityError("Missing DEMO sheet",file=path,row=1,field="sheet")
        raw=[(index,[v.date() if isinstance(v,datetime) else v for v in row]) for index,row in enumerate(book["DEMO"].values,1)]
        return table_rows(path,raw,required,nullable)
    except DataQualityError:
        raise
    except Exception as exc:
        raise DataQualityError(str(exc),file=path,row=1,field="file") from exc
    finally:
        if book is not None:
            book.close()
