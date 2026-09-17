# 리뷰 수정 완료 보고 — v0.2.0

## 기준 자료와 변경 경계

기준은 이 작업 폴더의 원본 `lastplate-inventory-risk.zip`, 원본 코드/28개 테스트, 첨부 리뷰 요청문, 이번 사용자 메시지의 9개 수정 항목입니다. 별도의 리뷰 실행 결과 파일은 확인되지 않아 기존 코드를 직접 실행하고 결함별 회귀 증빙을 새로 생성했습니다. 기준 ZIP의 SHA256은 `examples/revision_manifest.json`에 기록했습니다.

Inventory & Risk는 자문 전용입니다. 최종 메뉴·발주 결정, 운영 데이터 자동 반영, 수요 예측 실행은 추가하지 않았습니다. DEMO 데이터와 DEMO 메뉴별 영양 기준을 유지하고, 실제 API endpoint/응답을 가정하지 않았습니다.

## 수정 파일

| 구분 | 파일 | 변경 |
|---|---|---|
| Alert | `schemas/alert.py`, `tools/alerts.py`, `config.py` | 필수 type/severity/message/evidence, 이름 정규화, 중앙 severity 정책 |
| 입력·오류 | `schemas/event.py`, `schemas/request.py`, `schemas/errors.py`, `tools/events.py` | 엄격한 정수, 불명확 인원, 다중 날짜 확인, 잘못된 날짜 정형 오류 |
| 보고서 | `schemas/risk_report.py` | v2 계약, 기간/forecast/snapshot/clarification/recheck/execution/errors, 별도 우선 사용 후보 |
| 재고 | `tools/inventory.py` | 날짜/메뉴별 FEFO 감사 기록, 부족·기한 impact, 승인 필요 우선 사용 후보 |
| 가격 | `tools/pricing.py` | weekly/monthly 방향 분리, triggered_rules, 월별 상승 영향 연결 |
| Agent | `agents/inventory_risk.py`, `tools/identity.py` | 원인 ID 전파, 공급 중복 제거, 오류/확인 상태와 보고서 생성 |
| 그래프 | `graph/inventory_risk_workflow.py` | 실제 conditional routing, 선택 실행·생략 trace·오류 단락·재호출 상태 초기화 |
| 데이터 경계 | `adapters/local.py` 및 6개 `*_adapter.py` | 빈 파일/누락 컬럼/손상/형식 오류의 file/row/field 통일 |
| 통합 예시 | `examples/forecast_wrapper.py`, `examples/streamlit_app.py` | 예측 결과를 복제된 식단 snapshot에 주입; 입력·오류·DEMO 출처·확인 상태 UI |
| 배포·안내 | `pyproject.toml`, `requirements-tested.txt`, `README.md`, `VALIDATION.md` | v0.2.0, optional UI 의존성, v2 계약/실행/이관 안내 |

전체 수정·추가 경로는 `examples/revision_manifest.json`을 확인하세요. 원본 테스트와 DEMO 파일은 변경하지 않았습니다.

## 회귀 테스트

기존 28개를 그대로 유지하고 105개를 추가했습니다.

| 결함 | 격리 검증 |
|---|---|
| Alert 계약/이름/severity | 필수 4개 필드 각각 누락 거부, 별칭 5개, 모든 발행 Alert 검증, config severity 변경 |
| 재고 연결 누락 | 가격 변동=0·공급 이벤트=[]·충분한 기본 재고 fixture에서 부족만 주입하여 영향/후보 확인 |
| 임박 재고 구조화 | 동일 isolation fixture에서 D-1 8kg만 주입 → 별도 8,000g 우선 사용 후보; 만료/금지 재료 제외 |
| 인원·날짜 파싱 | 모호한 인원 full/event 양쪽 차단, 다중·충돌 날짜, invalid date, bool/실수/문자열 인원 거부 |
| 월별 상승 누락 | 주간 -4.7619%·월별 +100%, monthly_increase만 발동해 영향/후보 생성; 하락만 있을 때 미생성 |
| 그래프 선택 실행 | 실제 stream 노드 확인, 실행되면 실패하는 spy로 생략 검증, 무영향/무후보/error/재호출 분기 계약 |
| 중복/추적 | 공급 중복 3개 관측을 1개로 통합, 반복 실행 결과 동일, 후보의 부족+공급 원인 ID 병합 |
| 데이터 품질 | CSV 5종의 빈 파일/헤더만/누락 컬럼/손상 및 필드 오류; Excel 2종의 6가지 오류와 정확한 위치 |
| wrapper/UI | 예측 주입 시 원본 불변, 누락/중복 끼니·bool/음수 거부, DEMO 대체 없음, 실제 Streamlit AppTest 3개 |

`pytest` 실행 결과: **133 passed**, 실패 및 skip 없음.
- 원본 테스트: 28
- 리뷰 결함 회귀: 58
- 데이터 품질·통합: 47

## 실행 결과

1. 격리된 계란 재고 부족만으로 계란찜/계란말이 impact와 대체 후보가 생성됩니다. 후보는 부족 이벤트 ID를 보존합니다.
2. 임박 두부 8kg은 기존 두부조림의 FEFO 배분 8,000g 범위에서 `priority_use_candidates`로 반환됩니다. 발주나 메뉴에 적용하지 않습니다.
3. 주간 -4.7619% / 월별 +100% → `weekly_direction=decrease`, `monthly_direction=increase`, `triggered_rules=[monthly_increase]` → 영향/대체 검토로 이어집니다.
4. “내일 사람이 좀 많이 올 것 같아요.” → attendance_event / 2026-09-18 / delta=null / clarification=true. event 모드에서 실제 실행은 parser와 report 두 노드뿐이며 demand_forecast는 blocked_clarification입니다.
5. 유효한 “35명 추가”도 Agent가 예측을 실행하지 않습니다. requested/execute_allowed=true/ executed=false로 별도 도구에 전달할 정보만 반환합니다.
6. 잘못된 날짜·손상 파일은 구조화된 error report가 됩니다. 오류 시 후보와 예측 실행을 진행하지 않고 DEMO로 대체하지 않습니다.
7. Streamlit AppTest에서 DEMO 표시, 정상 보고서, clarification 차단 문구, invalid date 오류 표시를 확인했습니다.
8. 별도 설치한 v0.2.0에서 신규 예시 import, DEMO 7개 포함, 모호한 인원 입력의 조건부 실행을 재확인했습니다.

실제 보고서 예시는 `examples/regression_cases.json`, 개별 테스트 실행 증빙은 `examples/test-results.xml`입니다. 설치와 테스트 통과는 실제 API 검증을 뜻하지 않습니다.

## 남은 미구현·운영 전 필요한 작업

- 실제 4개 공공 API HTTP adapter: 명세·인증키·응답 fixture가 없어 구현/검증하지 않았습니다. endpoint나 응답을 지어내지 않았습니다.
- 실제 수요 예측 도구 연결: 이미 산출된 결과를 주입하는 wrapper만 제공합니다. Agent는 식수를 예측하지 않습니다.
- 기관이 승인한 영양 기준·전체 한 끼의 영양 평가: 현재는 DEMO 단일 메뉴 검증입니다.
- 실제 LastPlate/Decision Agent 저장소와의 배포 통합, 운영 UI 인증·권한·승인 흐름: 제공된 독립 패키지 범위 밖입니다.
- 이벤트 재분석은 이전 보고서 캐시를 부분 갱신하지 않습니다. 새 event-scoped 보고서를 반환하며 생략된 분석의 빈 목록은 무위험을 뜻하지 않습니다.
- 자동 생성 snapshot ID는 관측 입력 fingerprint입니다. 운영 환경의 불변 snapshot ID와 forecast_version은 상위 시스템이 제공해야 합니다.
- 일반 한국어 전체를 이해하는 parser, 서로 다른 공급 출처의 의미상 중복 통합은 제공하지 않습니다. 제한된 문법과 명시적 내용 기반 중복 제거입니다.

최종 메뉴/발주 결정·자동 적용은 미구현 기능을 보완할 대상이 아니라 이 Agent에서 계속 제외할 책임 경계입니다.
