# LastPlate ML v0.2

기존 모델·성능표를 보존하고 서버 저장·시점 계약·장애 복구를 보강한 독립 Python 모듈입니다. [수정·실행 결과](reports/v2/revision_report.md), [입력 계약](docs/input_contract.md), [복구 절차](docs/recovery.md)를 먼저 확인하세요. 원본 ZIP은 preservation에 있습니다.

**수정본 73개 테스트 통과.** 원본 31개는 별도 보존 코드로 재실행했습니다. 새 rolling 결과는 `experiments/rolling_v2_verified/`이고 기존 성능과 같은 test라고 섞지 않습니다. 기존 83.99명은 날씨 없는 B 결과입니다. 기존 main 모델·포인터는 유지했습니다.

## 설치와 실행

Python 3.12에서 검증했습니다. 이 체크아웃을 기준으로 실행합니다. 데이터/모델은 일반 wheel 패키지에 자동 포함되지 않으므로 체크아웃 디렉터리를 보관하세요.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-service-lock.txt
python -m pip install --no-deps -e .
python -m pytest -q
python scripts/run_original_regression.py --output reports/v2/original-rerun.txt
```

원래 `requirements-lock.txt`도 변경하지 않고 보존했습니다. 확장 lock은 실제 검증한 Streamlit/LangGraph까지 포함합니다.

## 서버 API (v1과 의도적으로 호환되지 않는 부분)

```python
from pathlib import Path
from ml.time_contract import ServiceConfig
from tools.demand import predict_demand, record_actual_result

config = ServiceConfig(
    storage_dir=Path("C:/LastPlate/runtime"),
    model_dir=Path("C:/LastPlate/models"),
    timezone="Asia/Seoul", cutoff_time="10:00", actual_ready_time="14:00",
    mode="operation",
)
# 아래 변수는 서비스의 실제 입력/인사 수집기가 제공해야 합니다.
# prediction = predict_demand(service_inputs, request_id=stable_request_id,
#                             availability=hr_acquisition_evidence, config=config)
# result = record_actual_result(prediction["prediction_id"], measured_actual,
#                               request_id=stable_actual_request_id, config=config,
#                               measured_at=actual_measurement_timestamp,
#                               actor=authenticated_operator)
```

날짜는 input_data의 date에 명시합니다. 인원 변수는 employees/vacation/business_trip/work_from_home 및 모델이 요구할 때 overtime, 메뉴는 menu입니다. 선택 요일은 날짜와 일치해야 합니다. 모르는 확보 시각을 만들어 넣으면 안 됩니다. 실제 서비스에서 source와 available_at는 인증된 서버 수집기가 제공해야 합니다.

`predict_demand`는 저장이 완료된 prediction_id/입력 snapshot/모델 버전/서버 생성 시각을 반환합니다. request_id를 재시도 동안 유지하세요. 다른 입력에는 새로운 ID가 필요합니다. 실제값 API는 전체 예측 객체가 아닌 prediction_id를 받아 서버에서 조회합니다. 수정은 새 request_id, expected_revision, correction_reason이 필요하고 이전 값이 보존됩니다. actor는 서비스의 인증 계층에서 공급해야 합니다.

operation/replay/demo는 물리적으로 다른 SQLite DB입니다. 과거 자료를 시험하려면 서버 설정을 replay로 정하세요. 과거 재생의 created_at는 지금의 실제 서버 시각이며, 옛 예측 시각인 것처럼 만들지 않습니다. 새 API는 기존 CSV에 쓰지 않으며 기존 운영 CSV는 빈 상태입니다. 저장소 경로는 상대경로를 허용하지 않습니다.

오류는 time_contract_error, input_not_available, weather_contract_error, idempotency_conflict, revision_conflict, not_found, storage_error 등으로 구분합니다. 어댑터는 retryable을 반환하며 저장소 오류 재시도 때 같은 ID를 사용합니다. 입력 오류에 자동으로 다른 ID를 발급하지 않습니다.

## 날씨

원래 D는 전날 관측 모델입니다. 관리자 수집기는 `ml.weather_contract.register_weather`로 kind=`previous_day_observed`, observed_date, source, available_at, values를 등록하고 ID를 얻습니다. ingested_at는 서버가 기록합니다. 예측에는 raw 기온값이 아니라 weather_record_id를 넘깁니다.

당일 예보는 별도 kind=`same_day_forecast`, target_date, issued_at가 필요합니다. `tools.forecast.predict_forecast_demand`는 별도로 학습된 예보 계약 모델이 없으면 거절합니다. 이번에는 실제 예보 모델을 학습하지 않았습니다. 강수 null은 0으로 채우지 않습니다.

## Streamlit / LangGraph

`examples/service.example.json`을 자신의 절대 저장 경로로 수정합니다. 예제 10:00/14:00은 LH 업무의 확정 시각이 아닙니다. 공개 운영에는 인증과 신뢰할 수 있는 인사/날씨 수집 계층이 추가로 필요합니다.

```powershell
$env:LASTPLATE_CONFIG="C:/LastPlate/service.json"
python -m streamlit run examples/streamlit_app.py
```

Streamlit 예제는 폼 제출·오류·멱등 재시도를 보여줍니다. 모델 캐시는 current 모델 버전이 바뀌면 갱신됩니다. LangGraph 예제:

```python
from adapters.service import load_config
from adapters.langgraph_adapter import build_prediction_graph
graph = build_prediction_graph(load_config("C:/LastPlate/service.json"))
# response = graph.invoke({"request_id": stable_request_id,
#                          "input_data": service_inputs,
#                          "availability": hr_acquisition_evidence})
```

두 어댑터 모두 재학습을 호출하지 않습니다. 실제 LangGraph와 Streamlit AppTest는 실행했고 공개 서버 배포는 하지 않았습니다.

## 배치 및 복구

```powershell
python -m ml.retrain --config C:/LastPlate/service.json --base-path C:/LastPlate/data/processed/lunch.csv --report-dir C:/LastPlate/retraining-reports --trigger count
python -m ml.retrain --config C:/LastPlate/service.json --base-path C:/LastPlate/data/processed/lunch.csv --report-dir C:/LastPlate/retraining-reports --recover-only
```

D 모델은 추가로 `--weather-daily`에 역사 일자료 절대경로가 필요합니다. 기본 신규 60건/gate 30건, 개선폭 max(5명,2%)를 엄격히 초과할 때만 승격합니다. 평가 구간은 시도 시작 때 영속 예약하고 실패/탈락에도 재사용하지 않습니다. 상세 상태와 I/O 복구 절차는 docs/recovery.md에 있습니다.

기존 model/version/features를 고정한 batch 비교이므로 메뉴 규칙/인원 계약을 바꾸는 연구 후보를 자동 승격시키지는 않습니다. 새 feature 정책의 배포 전환은 별도 미래 구간의 검증이 필요합니다. OS 스케줄러는 등록하지 않았습니다. 전체 자료 재학습본의 독립 정확도는 다음 운영 결과로 검증해야 합니다.

## 연구 재현

```powershell
python -m ml.rolling_validation --output experiments/my-new-rolling-run
```

기존 실험 폴더를 덮어쓰지 않습니다. 최종 기록의 source_snapshot은 그 실행 당시의 정확한 ML/서비스 코드입니다. 신뢰성만 추가 보강한 이후 서비스 코드와 hash가 다를 수 있어 따로 보관합니다. XGBoost missing=NaN 같은 파라미터 sentinel은 audit JSON에 문자열 NaN으로 기록하며 결측 관측값을 조작한 것이 아닙니다.

새 메뉴 규칙은 v2, 과거 저장 모델은 v1 규칙을 계속 사용합니다. 기존 원본 CLI/문서는 preservation/README-v1.md와 원본 ZIP을 참고하세요. 전체 메뉴 키워드 존재를 메인 메뉴 라벨로 해석하지 않습니다. gain/permutation은 인과효과가 아닙니다.
