from fastapi import APIRouter, HTTPException
from app.schemas import ForecastInput
from app.services.forecast_service import ForecastRequest, predict_forecast, model_metadata

router = APIRouter(prefix="/api/v1/forecasts", tags=["forecast"])


@router.get("/model")
def get_model():
    return {"mode": "demo_inference", "operational_eligible": False,
            "metadata": model_metadata(), "weather_used": False,
            "interval_method": "point_only"}


@router.post("/predict", response_model=ForecastInput)
def predict(payload: ForecastRequest):
    try:
        return predict_forecast(payload)
    except (OSError, ImportError, ValueError) as exc:
        raise HTTPException(503, detail="ML 모델을 불러오지 못했습니다. 모델 파일과 설치 환경을 확인하세요.") from exc
