"""Inference adapter for the supplied LastPlate ML v2, native LightGBM C release.

Preserves its v1 menu rules, feature order and nonnegative round-to-even output.
Demo/replay inference only: no invented HR acquisition receipts, no retraining,
no claim of a calibrated interval. Operation snapshots retain input provenance.
"""
from datetime import date, datetime, timezone
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import threading
from typing import Literal

from pydantic import Field, model_validator
from app.schemas import ForecastInput, StrictModel

BUNDLE = Path(__file__).resolve().parents[2] / "ml_bundle"
STAFF = ["employees", "vacation", "business_trip", "work_from_home", "overtime"]
RULES_V1 = {
    "menu_meat": r"제육|돈육|돼지|쇠고기|소고기|소불고기|돈불고기|닭|치킨|오리|삼겹|갈비|돈까스|돈가스|함박|미트",
    "menu_fish": r"고등어|삼치|갈치|꽁치|명태|동태|황태|대구|연어|가자미|생선|참치|조기|임연수",
    "menu_noodles": r"국수|우동|라면|냉면|쫄면|파스타|스파게티|짜장면|짬뽕|소바|당면",
    "menu_special": r"특식|특별|\(New\)|스테이크|장어|삼계탕",
    "menu_rice_bowl": r"볶음밥|덮밥|비빔밥|오므라이스",
    "menu_soup": r"국|찌개|탕|전골",
}
_predict_lock = threading.Lock()


class ForecastRequest(StrictModel):
    site_id: str = Field(min_length=1, max_length=120)
    meal_date: date
    meal_type: Literal["lunch"] = "lunch"
    employees: int = Field(gt=0, le=100000, strict=True)
    vacation: int = Field(ge=0, strict=True)
    business_trip: int = Field(ge=0, strict=True)
    work_from_home: int = Field(ge=0, strict=True)
    overtime: int = Field(ge=0, strict=True, description="시간외근무 승인 건수; 출근인원에서 빼지 않음")
    menu: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_inputs(self):
        if not self.menu.strip() or not self.site_id.strip():
            raise ValueError("menu and site_id cannot be blank")
        if self.employees - self.vacation - self.business_trip - self.work_from_home <= 0:
            raise ValueError("estimated available population must be positive")
        return self


@lru_cache
def model_metadata():
    return json.loads((BUNDLE / "metadata.json").read_text(encoding="utf-8"))


@lru_cache
def load_model():
    import lightgbm as lgb
    metadata = model_metadata()
    content = (BUNDLE / "demand_model.txt").read_bytes()
    if sha256(content).hexdigest() != metadata["native_sha256"]:
        raise ValueError("Model checksum mismatch")
    model = lgb.Booster(model_str=content.decode("utf-8"))
    if model.feature_name() != metadata["features"]:
        raise ValueError("Model feature order mismatch")
    return model


def build_feature_values(request: ForecastRequest):
    values = {key: getattr(request, key) for key in STAFF}
    values.update({f"weekday_{day}": int(request.meal_date.weekday() == day) for day in range(7)})
    menu = re.sub(r"\([^)]*(?:원산지|국내산|수입산|호주산|미국산)[^)]*\)", "", request.menu)
    values.update({key: int(bool(re.search(rule, menu, re.I))) for key, rule in RULES_V1.items()})
    return [values[key] for key in model_metadata()["features"]]


def predict_forecast(request: ForecastRequest) -> ForecastInput:
    import numpy as np
    values = np.array([build_feature_values(request)], dtype=float)
    with _predict_lock:
        raw = float(load_model().predict(values, num_threads=2)[0])
    if not np.isfinite(raw):
        raise ValueError("Model returned a non-finite prediction")
    prediction = int(np.rint(max(0, raw)))
    population = request.employees - request.vacation - request.business_trip - request.work_from_home
    lower, upper = model_metadata()["estimated_available_training_range"]
    warnings = ["점 예측 모델입니다. P95·예측구간·부족 확률을 제공하지 않습니다.",
                "시연/재생 추론입니다. 인사정보의 실제 확보 시각은 검증하지 않았습니다."]
    if not lower <= population <= upper:
        warnings.append(f"예정 출근인원 {population}명이 학습자료 범위({lower:g}~{upper:g}) 밖입니다.")
    if prediction > population:
        warnings.append("예상 식수가 예정 출근인원보다 큽니다. 사업장·방문객·모델 적용 범위를 확인하세요.")
    return ForecastInput(
        site_id=request.site_id, meal_date=request.meal_date, meal_type=request.meal_type,
        lower=prediction, mid=prediction, upper=prediction,
        model_version=model_metadata()["model_version"], generated_at=datetime.now(timezone.utc),
        interval_method="point_only", source_kind="ml",
        input_summary=request.model_dump(mode="json"), warnings=warnings,
    )
