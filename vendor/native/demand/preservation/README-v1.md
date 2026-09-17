# LastPlate 식수인원 예측 ML 모듈

웹서비스와 독립된 Python 모듈입니다. 첨부 LH 실데이터 1,205건으로 중식계 모델을 실제 학습했습니다. 웹 UI, LLM, 온라인 학습은 포함하지 않습니다.

이번 검증에서는 **LightGBM C**가 선택되었습니다. validation MAE **84.69명**, 선택 후 별도 test MAE **89.75명**입니다. 배포 모델은 선택이 끝난 뒤 전체 1,205건으로 다시 학습했습니다. 이 배포 재학습본 자체에 독립 test 점수가 있는 것은 아닙니다. 모든 수치는 저장된 예측 결과에서 계산했습니다.


## 추가 날씨 실험 업데이트

추가 제공한 진주 시간자료 5개 파일을 결합해 **공통 1,196건으로 A/B/C/D 비교를 완료**했습니다. 전날 기온 3종+습도를 사용한 D는 XGBoost에서 MAE 92.80→87.34명으로 개선됐고, LightGBM에서는 85.93→87.15명으로 악화됐습니다. 강수량 공백은 채우지 않고 이번 feature에서 제외했습니다.

최신 상세 결과는 [날씨 추가 분석](reports/weather_extension.md)에 있습니다. `experiments/weather/`는 연구용 실험·모델 폴더이며, 기존 최상위 배포 모델은 유지했습니다. 아래 최초 분석의 “D 미실행”은 최초 날씨 파일 1개만 받았던 시점의 기록입니다.

추가 실험 재현 명령(프로젝트 폴더에서 실행):

```powershell
python -m ml.prepare_data --source data/raw/lh_original.zip --root rerun-weather
python -m ml.weather --root rerun-weather --sources data/raw/weather_extension/OBS_ASOS_TIM_20260917145120.csv data/raw/weather_extension/OBS_ASOS_TIM_20260917145015.csv data/raw/weather_extension/OBS_ASOS_TIM_20260917144300.csv data/raw/weather_extension/OBS_ASOS_TIM_20260917143912.csv data/raw/weather_extension/OBS_ASOS_TIM_20160201~20170127.csv
python -m ml.train --root rerun-weather --weather-daily rerun-weather/data/processed/weather_daily.csv --weather-features temp_mean temp_max temp_min humidity --common-weather-rows
```

`--weather-features`를 생략하면 기존처럼 날씨 6개를 요구합니다. `--common-weather-rows`는 선택한 변수들의 완전 관측 공통행을 A/B/C/D 모두에 적용하면서 기존 시간 경계를 유지합니다. D의 선택한 feature는 저장 모델에 포함되어 추론과 batch 재학습에 동일 적용됩니다. 따라서 네 변수 D는 강수량/비 여부를 요구하지 않습니다. 당일 예보로 자동 변환하지 않습니다.

## 빠른 시작

Python 3.11 이상을 사용합니다. 이번 실행 환경은 Python 3.12이며 정확한 패키지 버전은 `requirements-lock.txt`에 있습니다. 압축을 해제한 프로젝트 디렉터리에서 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m pytest -q
```

모델은 이미 `models/releases/<version>/demand_model.pkl`에 저장되어 있습니다. `models/current.json`이 현재 모델을 가리킵니다. `models/releases/<version>/metadata.json`에 학습 기간, 평가 기간, MAE/RMSE/MAPE, feature, 파라미터, 버전, 패키지 버전, 해시가 있습니다. 모델과 metadata를 한 쌍으로 전환하기 위해 최상위 pkl 두 개를 개별 덮어쓰기하지 않고 원자적 포인터를 사용합니다. 직접 모델 파일을 복사할 때는 해당 release 폴더 전체를 복사합니다.

## 서비스 연결

```python
from tools.demand import predict_demand, record_actual_result, get_monitoring

# 입력 형식을 보여 주는 예시이며 실제 운영 관측값이 아닙니다.
# 요일을 생략하면 날짜에서 계산합니다. 입력할 경우 날짜와 일치해야 합니다.
prediction = predict_demand({
    "date": "2026-09-21",
    "employees": 2800,
    "vacation": 100,
    "business_trip": 200,
    "work_from_home": 100,
    "overtime": 300,
    "menu": "제육볶음 된장국 두부조림",
})
print(prediction["prediction"], prediction["model_version"])

# 실제 급식 종료 후 측정된 값을 전달합니다. 아래 변수는 서비스가 제공합니다.
# record_actual_result(
#     prediction, actual_diners=measured_actual,
#     prepared_servings=measured_prepared, leftover_servings=measured_leftover,
#     weather=observed_weather, event_variables=observed_events,
# )
print(get_monitoring())
```

`prediction`에는 정수 예측, model_version, prediction_id, predicted_at, input_data가 있습니다. 전체 객체를 서비스 저장소에 보관한 뒤 실적 입력 때 그대로 전달하세요. 결과 입력 시 당시 버전으로 재계산하여 입력 snapshot과 예측이 일치하는지도 검사합니다. lower/upper는 만들지 않습니다. `model_dir`, `history_path`를 지정하면 별도 운영 저장소를 사용할 수 있습니다.

한국어 원본 컬럼명도 지원합니다. 날짜는 시각 없는 현지 날짜이며 인원 입력은 유한한 0 이상의 수, 정원과 추정 가용 인원은 양수여야 합니다. 메뉴는 비어 있으면 안 됩니다. 시간외근무(`overtime`)도 필수입니다. 요청문 입력 예시에는 이 값이 없으므로 보완해야 합니다. `2026-09-20`은 일요일이므로 ‘월’을 함께 보내면 오류를 반환합니다.

**입력 시점 제한:** 휴가·출장·재택·시간외근무 승인 건수는 예측 시점에 이미 확인된 값이어야 합니다. 원자료에 각 값의 확정 시각이 없어 운영 시점 가용성까지 검증한 성능은 아닙니다. 시간외근무가 점심 이후 확정되는 업무라면 사전값을 별도 수집하거나 해당 변수를 제외하고 다시 비교해야 합니다.

학습 자료는 2021년 1월까지의 한 기관 데이터입니다. 2026년 운영이나 정원 580명인 다른 기관에서 같은 정확도를 보장하지 않습니다. 소규모 기관으로 단순 비례 환산하거나 정원을 예측 상한으로 강제하지 않았습니다. 초기 실제 운영 결과를 축적해 기관별로 검증해야 합니다.

## 데이터와 분석

- 원본: `data/raw/lh_original.zip`, `data/raw/weather_hourly.csv` (첨부 파일 복사본).
- 정제: `data/processed/lunch.csv`, `weather_daily.csv`.
- 분석 보고서: `reports/analysis.md`, 스키마: `reports/schema.md`.
- 원자료 품질: `data_profile.json`, `weather_profile.json`, `source_manifest.json`.
- 비교 결과: `ablation.csv`, `validation_predictions.csv`, `test_predictions.csv`, `training_summary.json`.
- 중요도: `feature_importance.csv` (A/B/C 원학습 gain), `deployed_feature_importance.csv` (전체 자료 재학습 gain).
- 기술통계: `weekday_patterns.csv`, `menu_patterns.csv`, `participation_sensitivity.csv`.

가용 인원은 `정원 - 휴가 - 출장 - 재택`으로 추정합니다. 원자료에 개인 ID와 인원 집합 정의가 없으므로 중복 차감 가능성을 배제할 수 없습니다. 참여율은 설명용 분석에만 쓰고 A/B/C의 입력으로 사용하지 않습니다. 시간외근무는 가용 인원에서 차감하지 않습니다. 비교용으로 재택을 차감하지 않은 분모의 참여율도 저장합니다.

요일은 날짜에서 산출합니다. 원자료의 `2018-06-01: 월 → 금` 1건만 명시적으로 교정합니다. 중식 관련 결측치는 없습니다. 석식메뉴에는 공백 문자열 4건이 있습니다. ZIP의 `test.csv`는 0바이트여서 사용하지 않습니다. 표본 submission은 학습·평가 라벨로 쓰지 않습니다.

메뉴는 사전 정의한 6개 키워드 지표를 사용합니다. 육류·생선·면·특식·볶음밥/덮밥류·국/찌개류이며 중복 분류가 가능합니다. 비빔밥/오므라이스도 밥류 규칙에 포함됩니다. ‘특식’은 `(New)`, 스테이크 등으로 만든 휴리스틱이며 실제 선호도 점수가 아닙니다. 키워드는 `ml/config.py`에 공개되어 있습니다. 고정 규칙의 오탐·누락, 주재료와 부재료 구분 부족을 감안하세요.

## 재현

기존 저장 모델을 유지하며 재현하려면 새 디렉터리를 지정합니다.

```powershell
python -m ml.prepare_data --source data/raw/lh_original.zip --root rerun
python -m ml.weather --source data/raw/weather_hourly.csv --root rerun
python -m ml.analyze_features --root rerun
python -m ml.train --root rerun --weather-daily rerun/data/processed/weather_daily.csv
```

`ml.train`은 이미 current 모델이 있는 디렉터리에 덮어쓰기하지 않습니다. 과거 843건/다음 181건/마지막 181건의 시간 분할을 모든 모델에 동일 적용합니다. 파라미터는 사전 고정하며 early stopping이나 test 기반 튜닝은 하지 않습니다. 검증 최저 MAE로 모델을 선택한 뒤 train+validation으로 재학습해 마지막 test를 한 번 평가합니다. 예측은 서비스와 평가 모두 음수 방지와 같은 정수 반올림을 적용합니다. MAPE는 실제값 0을 제외하고 제외 건수를 별도 기록합니다.

이번 비교는 단일 시간 holdout baseline입니다. 다중 모델 비교에 따른 선택 편향과 기간별 변동이 있으므로 작은 메뉴 개선을 확정적 효과로 해석하지 않습니다. gain 중요도는 상관된 변수 사이에 분배될 수 있고 인과효과가 아닙니다. 요일·메뉴 기술통계는 전체 기간을 설명할 뿐 모델의 target encoding이나 선택 기준으로 쓰지 않았습니다.

SHAP은 선택 기능입니다.

```powershell
python -m pip install -e ".[explain]"
python -m ml.analyze_features --shap
```

`reports/shap.csv`를 생성합니다. 이번 전달본에서는 SHAP을 설치·실행하지 않았습니다. 배포 모델 학습 표본의 설명용 출력이며 독립 성능 검증이 아닙니다.

## 운영 기록과 모니터링

`data/operational_history.csv`는 **헤더만 있는 빈 파일**입니다. 테스트용 데이터를 실제 이력에 넣지 않았습니다. 중식·한 기관·하루 1행을 전제로 날짜와 prediction_id 중복을 거절합니다. 정정, 다기관, 중식/석식 동시 운영은 별도 식별키와 정정 이력 설계가 필요합니다.

실제 식수, 당시 예측, 버전, 원래 입력 전체, 메뉴, 추정 가용 인원, 관측 날씨/행사 JSON, 준비/잔여 식수와 기록 시각을 저장합니다. `prediction_error = actual - predicted`이므로 양수는 과소예측입니다. 나중에 입력한 관측 날씨/행사는 학습 입력으로 자동 전환하지 않습니다. 원본 예측 시점에 알고 있던 `input_json`만 재학습에 사용합니다.

CSV 쓰기는 파일 잠금과 원자적 교체를 사용합니다. 모델 등록도 잠금과 단일 포인터 교체를 사용합니다. 로컬 파일시스템의 단일 저장소를 위한 구조입니다. 분산 다중 서버에서 쓰려면 DB 트랜잭션과 원격 모델 저장소로 바꾸세요. joblib 모델은 신뢰하는 로컬 산출물만 로드합니다. 해시 검사는 손상 탐지용이며 악의적인 파일의 서명을 대신하지 않습니다.

모니터링은 전체/최근 30건/최근 60건 MAE와 실제 사용 건수를 반환합니다. 최근 30건과 그 이전 이력을 비교하며 양쪽에 30건 이상 있을 때 이전 MAE의 1.25배를 초과하면 `retraining_needed=True`입니다. 최신 구간을 비교 기준에 다시 포함하지 않습니다. 여러 버전이 섞인 운영 전체 지표이므로 버전별 진단도 후속 확장할 수 있습니다.

## 배치 재학습

```powershell
# 마지막 시도 이후 신규 30건 이상일 때
python -m ml.retrain --trigger count
# 7일 또는 30일 경과 여부를 확인하는 외부 스케줄러용 명령
python -m ml.retrain --trigger weekly
python -m ml.retrain --trigger monthly
# 수동 실행도 새로운 평가 데이터 조건을 생략하지 않음
python -m ml.retrain --trigger manual --holdout-size 10 --min-improvement 0
```

명령은 실행 시 조건을 검사합니다. OS 스케줄러에 실제 등록하지는 않았습니다. `monthly`는 30일 간격이며 달력상의 매월 같은 날짜 방식은 외부 스케줄러가 담당합니다. 첫 주기 계산은 모델 생성 시각 기준입니다. 경과 시간은 모델 교체 여부와 무관하게 마지막 평가 시도를 기준으로 갱신됩니다.

1. 원래 학습 데이터와 누적 운영 입력·실적을 결합합니다. 원자료와 날짜가 겹치는 운영 자료는 명시적 정리를 요구합니다.
2. 기존 모델의 `trained_through` 이후이면서 직전 평가 시도 이후인 새 결과를 확보합니다. 기본 count 조건은 신규 30건입니다. 모든 방식에서 기본 holdout 10건 + 추가 학습 5건 이상의 새 자료가 필요합니다.
3. 최신 10건을 두 모델이 보지 않은 동일 gate로 남깁니다. 그 이전 데이터로 challenger를 학습합니다. 비교 전 모델 계열과 feature 집합을 기존 모델과 동일하게 고정합니다.
4. 저장된 기존 모델과 challenger를 같은 gate에서 비교합니다. `candidate_MAE < incumbent_MAE - min_improvement`일 때만 교체합니다. 동점은 유지합니다.
5. 통과하면 모든 확보 자료로 다시 학습해 새 release를 만들고 이전 모델을 archive에 보관합니다. 탈락하면 기존 포인터를 유지합니다. 두 경우 모두 비교 점수·기간·행별 예측을 `reports/retraining/`에 저장합니다.

직전 평가에 쓴 자료로 반복 승인 결정을 내리지 않습니다. 수동 재시도도 새 gate가 필요합니다. 학습 중 기존 모델이 바뀌면 낙관적 버전 검증이 교체를 거절합니다. 최종 전체 자료 재학습본 자체의 독립 성능은 다음 운영 결과로 확인해야 합니다. 아주 작은 개선을 승격시키지 않으려면 `--min-improvement`를 명 단위로 설정하세요. 새 feature/모델 계열 탐색은 별도의 시간 검증으로 먼저 결정해야 합니다.

## 날씨와 기타 확장

첨부 날씨는 진주(192)의 시간 자료 1,728건, 2021-01-27 01:00~2021-04-09 00:00입니다. 중식 라벨은 2021-01-26에 끝나므로 날짜 교집합이 0건입니다. **Model D는 실행하지 않았으며 날씨 효과는 아직 확인할 수 없습니다.** 강수 공백을 0으로 치환하지 않았습니다.

관측 날씨 확장 절차:

1. 원래 식수 기간과 겹치는 동일 위치의 실제 일별 자료를 확보합니다. 원자료의 지점과 식당 위치가 적합한지도 확인합니다. 전날 feature를 쓰려면 최초 식수일의 전날부터 필요합니다.
2. `date,temp_mean,temp_max,temp_min,precipitation,humidity,rain` 컬럼의 CSV로 만듭니다. 섭씨, mm, 상대습도 %, rain=0/1을 사용합니다. 실제 결측은 그대로 두고 강수 공백의 의미는 제공기관 정의로 확인한 뒤에만 처리합니다. 시간자료 어댑터의 min/max는 시간 관측값의 극값으로 공식 일 최저/최고와 다를 수 있습니다.
3. `merge_observed_weather`는 전날 **달력 날짜**의 관측 자료를 연결합니다. 0일 lag는 막습니다. 동일 날짜·여러 지점 중복은 거절하므로 먼저 한 지점을 선택해야 합니다. 시간자료 집계는 하루 24개 시각과 각 변수의 관측 완전성을 확인합니다.
4. 동일 A/B/C/D 비교행에 전체 날씨가 있으면 `ml.train --weather-daily ... --root 새_학습_폴더`가 D를 추가합니다. 부분 겹침이면 현 구현은 D를 건너뜁니다. 부분 기간 실험을 원하면 사전에 공통 기간을 정하고 A/B/C/D 전체를 그 동일 기간·동일 시간 split에서 다시 비교해야 합니다.
5. 당일 기상 예보로 바꾸려면 발행시각(`issued_at`), 예측 대상 날짜, 예측 실행시각을 저장하고 `issued_at <= prediction_time`인 예보만 선택하는 어댑터를 추가해야 합니다. 현 구현은 전날 관측 어댑터이며, 최종 당일 평균·최고기온을 과거 점심 예측에 붙이지 않습니다.

공휴일·회사 행사·실측 메뉴 선호도는 현 학습 feature가 아닙니다. 이들은 출처와 예측 전 확인 시각이 있는 별도 날짜 테이블 및 명시적 feature group으로 확장하세요. 동일 메뉴 참여율은 당일을 제외한 과거 확정 실적만으로 expanding/shift 방식으로 계산하고, validation에서도 해당 시점 이전 정보만 쓰도록 구현해야 합니다. 현재는 이런 값을 생성하지 않았습니다.

잔차 기반 conformal/quantile 구간은 별도의 시간 calibration 구간을 확보한 후 추가해야 합니다. 현 잔차 CSV는 검토용이며 즉시 유효한 신뢰구간으로 해석하지 않습니다.

## 코드 구조와 검증

`ml/prepare_data.py`, `feature_engineering.py`, `analyze_features.py`, `weather.py`, `train.py`, `evaluate.py`, `retrain.py`, `model_registry.py`, `config.py`가 ML 기능을 담당하고 `tools/demand.py`가 서비스 인터페이스입니다. 테스트는 `tests/test_demand.py`에 있습니다. 코드 리뷰 결과와 남은 한계는 `reports/code_review.md`에 정리했습니다.

사용 API 참고: [LightGBM LGBMRegressor](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRegressor.html), [XGBoost Python API](https://xgboost.readthedocs.io/en/release_3.1.0/python/python_api.html). 정확한 재현 환경은 URL 문서 버전보다 저장된 lock/metadata를 우선합니다.
