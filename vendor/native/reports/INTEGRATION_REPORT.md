> Historical v0.1.0 report. v0.1.1 source of truth: [P0/P1 fix report](P0P1_FIX_REPORT.md).

# LastPlate 통합 MVP v0.1.0 — 검증 보고서

이 패키지는 첨부된 네 모듈의 원본 코드를 유지하고 통합 계층을 추가했습니다. 실제 모델 추론과 네 Agent 호출은 실행했습니다. DEMO 입력을 사용하는 로컬 backend 시연이며 현장 운영·신규 사업장 성능 검증은 아닙니다.

## A. ZIP 원본 테스트

| 모듈 | 독립 baseline | 통합 후 regression |
|---|---:|---:|
| Demand ML v2 | 73 PASS | 73 PASS |
| Operation v0.2.1 | 180 PASS | 180 PASS |
| Inventory & Risk v0.2.3 | 240 PASS | 240 PASS |
| Decision v0.1.3 | 163 PASS + 51 subtests | 163 PASS + 51 subtests |

총 656개 기존 테스트입니다. 기존 실패는 관찰하지 않았습니다. 처음 실행 환경에는 의존성이 없어 workspace 전용 venv에 설치했습니다. 원본 ZIP에 기록된 과거 성공 수를 복사하지 않고 이번 환경에서 재실행했습니다. baseline/regression JSON, TXT, JUnit XML을 함께 제공합니다. 실행 환경은 Python 3.12.14이며 requirements-tested.txt에 실제 설치 버전을 기록했습니다.

## B. 실제 entry point 및 구성

| 모듈 | Public callable | 입력/출력 | config·데이터·의존성 |
|---|---|---|---|
| Demand | tools.demand.predict_demand | attendance + date/menu → 저장된 예측 receipt | ml.time_contract.ServiceConfig, models/current.json, 학습 CSV; LightGBM/sklearn/pandas/joblib/filelock/SQLite |
| Operation | lastplate_operation.generate_operation_plan | DemandResult/레시피 행/재고/발주/정책 → OperationOutput | OperationPolicy, examples JSON; Pydantic/LangGraph |
| Inventory | agents.inventory_risk.analyze_inventory_and_risk | AnalysisRequest + AdapterBundle + event → RiskReport schema 2.0 | RiskConfig, CSV/XLSX DEMO providers; Pydantic/LangGraph/openpyxl |
| Decision | lastplate_decision.make_final_recommendation | 3개 upstream + provenance + events → DecisionOutput 0.1.3 | DecisionPolicy, examples/fixtures; Pydantic/LangGraph |

각 원본의 전체 파일 목록은 module-file-trees.json, 원본 설명·테스트·모델·데이터는 각 모듈 폴더에 보존했습니다. ML의 Streamlit/LangGraph service tests도 실행됐습니다. 원본 아카이브 내부의 더 오래된 nested legacy ZIP 전체를 별도 확장하는 것은 이번 regression 대상이 아닙니다.

## C. 스키마 차이

상세 SCHEMA_MAPPING.md를 참조하세요. 주요 차이는 prediction 명칭, ML에 없는 OOD/구간, Operation의 종합 constraints와 Decision의 항목별 constraints, 서로 다른 provenance, Inventory의 단일 lot 발주 필드, legacy 최상위 패키지명 충돌입니다.

Decision은 ML이 demo/replay이면 운영 근거로 받아들이지 않습니다. Operation이 계산한 수량은 보존하지만 최종 recommended_servings는 null로 보류할 수 있습니다. 이 동작을 없애지 않았습니다.

## D. 추가 Adapter

- demand_adapter.py: metadata/hash/학습 기간 기반 OOD 검사, raw receipt 및 MODEL source 보존.
- operation_adapter.py: 레시피 행 평탄화, attendance/적용범위 mapping, 서비스일 기준 사용 불가 재고를 stock=0으로 전달, capacity를 원본 Operation 정책에 연결.
- inventory_risk_adapter.py: 입력 snapshot을 기존 provider protocol로 제공, 동일 조리량 주입, planned order 단일 기준, source metadata 유지.
- decision_adapter.py: 원본 ML/Inventory adapter 재사용, Operation constraints/order mapping, superseded 현재 근거 제외, 실행 revision 연결. 권고 판정은 원본 Decision 함수가 수행.

## E. Pipeline 구조

Input validation → 실제 저장 ML → Demand adapter → 실제 Operation → 입력 snapshot 기반 실제 Inventory/Risk → Decision evidence adapter → 실제 Decision.

각 단계는 별도 Python process로 실행하므로 tools/adapters/config 충돌을 피합니다. 프로세스 생성 비용은 있으나 로컬 시연 시간 안에 완료됩니다. Decision adapter의 operation evidence revision은 원본 Operation 계산값과 이후 Risk 결과를 함께 소비한 값입니다. Operation core가 미래 결과를 사용했다는 가짜 provenance를 만들지 않습니다.

한 번에 날짜/사업장/점심 한 끼만 처리합니다. weekly_menu 전체의 주간 공유재고 최적화가 아닙니다. full pipeline을 우선 구현했고 incremental rerun은 구현하지 않았습니다. 인원 이벤트는 무시하지 않고 재예측 요청으로 보류하며, attendance 원자료를 수정하여 새 요청으로 재실행해야 합니다.

## F. 기존 코드 수정

기존 모듈 소스 수정 없음. 원본 manifest와 비교한 변경/누락: {"demand": [], "operation": [], "inventory_risk": [], "decision": []}.

새 integration/app/tests/scripts 및 최상위 문서만 추가했습니다. 테스트가 만든 __pycache__/.pytest_cache는 배포 ZIP에서 제외합니다. 모델을 다시 학습하거나 기존 모델 포인터를 바꾸지 않았습니다.

## G. 통합 테스트

최종 JUnit: 20 tests, 0 failures, 0 errors, 0 skipped. 상세 integration-tests.txt / integration.xml.

| 요구 시나리오 | 이번 검증 및 실제 의미 |
|---|---|
| 1 정상 수요·재고 | 실제 모델+네 단계 완료, 재고 부족 0. DEMO는 정상이어도 NEEDS_CONFIRMATION으로 유지 |
| 2 식수 증가/발주 증가 | 실제 Operation에 명시적 제어 입력을 제공하여 조리량·발주량 증가 검증. 학습 모델의 전 구간 단조증가를 주장하지 않음 |
| 3 재고 부족 | Operation 구매 필요량 + Risk shortage + native Decision BLOCK. 원본 hard-shortage 정책을 ADJUST로 완화하지 않음 |
| 4 유통기한 임박 | 실제 alert, priority-use 및 Decision inventory action 확인 |
| 5 가격 급등 | 실제 대체 후보, 후보별 영양 결과, Decision 후보 평가 확인 |
| 6 영양 FAIL | 실제 Operation FAIL → Decision BLOCK |
| 7 OOD | structured warning 및 최종 data_quality_notes/LOW 유지 |
| 8 레시피 누락 | PARTIAL + RECIPE_MISSING + Decision 보류 |
| 9 지원하지 않는 단위 | PARTIAL + UNIT_ERROR |
| 10 superseded | 원본 audit 보존, 해제된 제한은 현재 restriction FAIL에 영향 없음 |
| 11 retry | 같은 prediction_id 및 recommendation_revision, 원본 입력 변경 없음 |
| 12 JSON | 최종 strict JSON 직렬화 확인 |
| 13/14/15 3000/600/5000 | 실제 모델 호출 및 IN_RANGE/OOD/OOD 확인 |
| 16 capacity | raw ML 값 유지, Operation 조리량 유지, 별도 초과 경고·최종 보류 |

추가로 잘못된 입력, Demand 실패, 누락된 source, attendance event 재검증 요청, hook 장애, FastAPI 입력 validation을 검증했습니다. 마지막 source-label 보완 후 영향받는 두 테스트를 별도 재실행해 통과했습니다(api-source-followup.xml): UNKNOWN source를 REAL로 승격하지 않으며 실제 POST /api/plan의 정상 요청이 네 Agent를 거쳐 200/COMPLETE를 반환하고 잘못된 nested 입력은 422로 거절합니다. 모든 정상 입력이 KEEP/ADJUST가 되어야 한다고 가정하면 DEMO와 실제 운영 근거를 혼동하게 되므로 기존 확인 정책을 유지했습니다.

숫자 검증: 별도 제어 사례에서 upper_bound 507 → 원본 Operation 523식. 실제 ML은 구간을 반환하지 않으므로 이 구간을 실모델 산출물로 표시하지 않습니다. 최종 Decision은 수량을 재계산하지 않으며 보류할 때 null, 별도 operation_recommended_servings에는 원래 수량을 유지합니다.

## H. Regression

통합 후 기존 656개 전부 재통과했습니다. 실행 방법: python scripts/run_regression.py. 각 모듈은 별도 cwd/프로세스로 검사합니다. 원본 테스트 파일을 수정하지 않았습니다.

## I. 실패·부분 성공 처리

입력 계약 실패는 FAILED, 중간 단계 오류는 PARTIAL, 성공적으로 수행된 단계는 보존합니다. Decision은 빈 upstream을 원본 정책으로 처리해 보류합니다. worker timeout/잘못된 응답/모듈 예외는 구조화합니다. persistence hook 실패도 이미 산출한 결과를 버리지 않습니다.

BLOCK이나 NEEDS_CONFIRMATION은 Python 실행 실패가 아니므로 pipeline_status=COMPLETE와 함께 나올 수 있습니다. INVALID_INPUT, RECIPE_MISSING, UNIT_ERROR, INVENTORY_DATA_MISSING, MODEL_INPUT_OUT_OF_RANGE, CAPACITY_EXCEEDED 등이 독립적으로 표시됩니다.

## J. OOD 결과

선택된 모델의 실제 deployment fit 기간: 2016-02-01~2021-01-26, 1,205행. CSV SHA-256이 metadata.data_sha256과 일치하고 행 수도 일치해야 범위를 사용합니다. 불일치하면 UNKNOWN/LOW로 보류합니다.

| feature | min | max |
|---|---:|---:|
| employees / registered_population | 2601 | 3305 |
| vacation | 23 | 1224 |
| business_trip | 41 | 378 |
| work_from_home | 0 | 533 |
| overtime | 0 | 1044 |

small_site 예제: 정원 600, 실제 모델 예측 856.0, capacity 550. 예측을 550으로 clip하지 않았습니다. 재고 위험도 함께 있는 예제이므로 최종 BLOCK이며, 재고 정상인 독립 capacity 테스트에서는 NEEDS_CONFIRMATION입니다. 과거 924명과 동일 입력이 제공된 것은 아니므로 924라는 숫자 자체의 재현으로 주장하지 않습니다.

IN_RANGE는 주변 feature별 범위 검사만 통과했다는 의미입니다. 결합분포 OOD, 신규 사업장 일반화, 확률적 confidence는 검증하지 않았습니다. LH 데이터에 participation_rate 열은 있지만 배포 모델은 절대 식수 예측 모델입니다. 참여율/정규화 모델이나 site calibration은 이번에 구현하지 않았습니다.

## K. Source 추적

수요는 MODEL, 원본 receipt에는 demo/replay/operation이 별도로 남습니다. 예제 레시피·재고·영양·가격·공급은 DEMO 표기를 유지합니다. 대체 후보 영양 검사에 사용하는 원본 RiskConfig의 DEMO dish-level threshold와 Operation의 입력 whole-meal threshold 출처를 구분합니다. 실제 외부 API 호출은 없습니다. USER_UPLOAD/PUBLIC_API 표시는 호출자가 제공한 출처 선언이며 서버가 외부 출처를 인증했다는 뜻은 아닙니다.

## L. Public entry point

from integration import run_lastplate_pipeline, PipelineConfig

result = run_lastplate_pipeline(payload, config=PipelineConfig(...))

일반 JSON dict를 반환합니다. README와 examples/*.json에 전체 입력을 제공합니다. 파일 일부만 추출하지 말고 전체 소스 폴더를 유지하세요.

## M. FastAPI

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

POST /api/plan. 기본 demo. production 모드 전환은 서버 환경변수이며 요청 body가 모델 경로나 storage를 지정하지 못합니다. 인증/운영 데이터 수집기는 후속 작업입니다. UI를 다시 만들지 않았습니다.

## N. SQLite

ML ZIP에 포함된 ServiceStore를 그대로 사용합니다: storage_dir/demo/service.sqlite3 등 모드별 분리. 통합용 새 DB schema는 만들지 않았습니다. 단계별 저장 연결점은 on_demand_complete, on_operation_complete, on_inventory_risk_complete, on_decision_complete입니다. hook은 재시도 시 다시 불릴 수 있으므로 input_revision 기준 upsert가 필요합니다. 주문·재고·메뉴 실행 hook은 없습니다.

## O. 남은 P0 / P1 / P2

- P0 운영 적용 전제: 소형/신규 사업장 일반화 미검증, 실제 인사 수집 근거·인증·기관 영양 기준 미연결. 로컬 자문 MVP에서 이를 검증 완료로 주장하면 안 됩니다. 감지된 입력/제약 문제는 보류 또는 차단합니다.
- P1 기능 범위: attendance event를 원자료에 반영하는 승인된 재예측 흐름, 위험 이벤트 후 Operation 재계산, 후보 선택 후 재배분, 주간 공유 재고·입고시각, 실제 API provider, calibrated interval/confidence. 현재 recommended_rechecks는 실행 완료로 위조하지 않고 남깁니다.
- P1 계약 범위: Inventory는 g/kg만 지원하며 Operation의 ml/ea 전체 범위를 통합 지원하지 않습니다. 발주 입력은 기존 lot과 단위가 일치해야 합니다.
- P2 성능·배포: process pool/cache 최적화, 장기 부하 테스트, package wheel에 모델/원본 데이터 포함, 외부 배포 환경 smoke. FastAPI 정상 요청의 로컬 TestClient 실행은 완료했습니다.

## P. 발표에서 실제 시연 가능한 기능

네 실제 모듈의 연속 호출, 실제 저장 모델 예측, OOD와 수용량 분리, 원본 조리량·발주 계산, 재고/유통기한/가격 위험, 대체 후보 영양 검토, 제한 해제 이벤트 감사, hard constraint 우선 Decision, 승인 대기, 오류 격리, 동일 요청의 ML 멱등 재시도.

샘플 성능(프로세스 시작 포함, 일부 테스트와 병행 실행):

| profile | Demand | Operation | Inventory | Decision | 전체 |
|---|---:|---:|---:|---:|---:|
| LH-like | 4.3837s | 0.5505s | 3.0854s | 0.6593s | 8.6816s |
| Small-site | 4.2934s | 0.5551s | 2.9826s | 0.7507s | 8.5853s |

외부 API 없이 약 6~9초 수준의 로컬 시연을 관찰했습니다. SLA나 운영 부하 검증은 아닙니다.

## Q. 주장하면 안 되는 기능

모든 규모 급식소 적용, 소형 사업장 정확도 검증, 전국 일반화, 실제 가격/영양/공급 API 연동 완료, 기관 영양 기준 인증, 자동 승인·발주·메뉴 변경·재고 차감, 주간 최적화, 참여율 모델, site calibration, 인원 자연어 이벤트의 자동 재학습/재예측 완료를 주장하면 안 됩니다.

권장 발표 표현: “현재 공개된 특정 대형 구내식당 데이터로 학습·검증했으며, 신규 사업장에서는 적용범위를 확인하고 운영 데이터 축적 후 사업장별 보정/재학습하는 구조로 설계했다.”
