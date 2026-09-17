# LastPlate public contract 1.0

> 1.1 UI 개편: 아래 원문 통합 API의 구조는 유지하지만 개발자 인증이 필요하다.
> `LASTPLATE_DEBUG=true`와 `LASTPLATE_DEBUG_TOKEN`을 설정하고 HTTP Basic 사용자 이름 `developer`로 접근한다.
> 개발 도구가 꺼져 있으면 원문 API·`/debug`·`/admin`·`/docs`·`/openapi.json`은 404다.
> 일반 업무 UI는 인증된 원문 API 대신 아래 `/api/ui/*`의 업무 표시 모델을 사용한다.

## 1.1 업무 API 추가

| 메서드·경로 | 목적 |
|---|---|
| GET `/api/ui/sites` | 사업장 이름·읽기 전용 시연 구분 |
| GET `/api/ui/context?site_id=&target_date=&plan_id=` | 선택한 날짜·계획의 업무 입력. plan_id 생략 시 최신 사업장 설정과 등록 자료 |
| GET `/api/ui/plans?site_id=&target_date=` | 날짜별 저장 버전 목록 |
| GET `/api/ui/plans/{id}` | 내부 trace를 제외한 계획 업무 표시 모델 |
| POST `/api/ui/plan` | 업무 입력을 원래 PlanRequest로 조립해 계산 |
| POST `/api/ui/events/preview` | 기존 파서로 날짜·변경사항 해석 |
| POST `/api/ui/replan` | 기존 계획의 전체 변경사항 목록 교체. 빈 목록으로 취소 가능 |
| POST `/api/ui/plans/{id}/acknowledgement` | 열람 확인 시각 저장. 승인 아님 |
| POST `/api/ui/plans/{id}/retry-save` | 기존 계산 결과 저장 재시도. 모델 재실행 안 함 |
| GET/POST `/api/ui/actual` | 사업장·날짜 실측 조회/저장. 저장 시 계획 ID 필요 |
| POST `/api/ui/actual/correct` | 사유·현재 revision과 함께 정정. 이전값 감사 이력 보존 |
| GET `/api/ui/history?site_id=` | 선택 사업장의 실측 이력과 정확한 비교 기준 |
| POST `/api/ui/upload/{menu\|inventory}` | 파일·사업장·날짜 입력으로 자료 검증/불러오기 |
| GET/PUT `/api/admin/settings/{site_id}` | 인증된 사업장 설정 조회/저장. 기존 계획 스냅샷 유지 |

ActualRequest의 폐기 무게 3개는 null을 허용한다. `is_demo` 생략 시 서버가 사업장 기록으로 결정하고,
클라이언트가 다른 구분을 보내면 거부한다. 추가된 `plan_request_id`는 새 업무 UI에서 필수다.
정정은 `reason`, `expected_revision`을 추가로 요구한다. 과거 실측의 생성 시각과 연결 계획을 바꾸지 않는다.
예측/운영 기준 차이는 실제 식수에서 각각의 값을 뺀 값이다. 과거 링크가 없는 기록은 저장 전 예측 기준을 보존한다.
업무 표시 모델의 id는 조회/URL용 불투명 키이며 사용자 본문에 표시하지 않는다.

입고 예정일은 일정 메모만 보관한다. 원본 Agent에 검증된 입고로 전달하지 않는다.
계획 저장만 실패한 응답도 계산을 보여주기 위해 200과 `saved=false` 업무 결과를 반환한다.
입력/DB 오류는 4xx/5xx와 사용자용 message를 반환한다. 기술 진단은 개발자 원문·서버 로그에서 확인한다.

API가 유일한 공개 interface다. UI는 Agent import, 조리/발주 계산, 임의 ID 생성을 하지 않는다. OpenAPI는 `/openapi.json`, 설명 화면은 `/docs`다. `docs/openapi.json`은 배포 시 생성한 동일 계약이다.

## 입력

`POST /api/plan`: `site_id`, `site_name`, `target_date`, `as_of`, `meal_capacity`, `attendance`, `weekly_menu`, `recipes`, `inventory`, `planned_orders`, `nutrition`, `prices`, `monthly_prices`, `supply_events`, `sources`, `operation_policy`, `events`, `is_demo`. `availability`는 원래 Demand 입력 확보 증빙을 전달할 때만 사용한다. `request_id`와 모든 저장 ID는 서버에서 만든다. 정확한 필드/타입은 `backend/contracts.py`와 OpenAPI, 실행 예시는 `/api/demo-profile` 응답의 `request`에 있다.

레시피·영양·가격·재고 도메인 계약은 원본 `vendor/native`의 스키마를 보존한다. mass 단위는 g/kg만 허용한다. `operation_policy.safety_margin_pct`는 백분율(3=3%)이며 응답의 `operation.safety_margin`은 비율(0.03)이다. UI는 단위를 변환하거나 수량을 재계산하지 않는다.

## 응답

`pipeline_status`: SUCCESS / PARTIAL / FAILED. 원본 COMPLETE를 SUCCESS로 매핑한다. 계산 성공은 운영 승인과 다르다. SUCCESS여도 Decision이 BLOCK 또는 NEEDS_CONFIRMATION일 수 있다.

`persistence_status`: SUCCESS / PARTIAL / FAILED. 저장 실패는 계산 상태를 변경하지 않는다. `persistence_ids`에는 실제 저장 성공한 ID만 있다.

`demand`: prediction_id, target_date, predicted_diners, lower_bound, upper_bound, predicted_rate, available_population, model_version, model_type, applicability, confidence, warnings, source_type. 원본 `source_payload`와 training_ranges를 함께 유지한다. 점 예측 모델이므로 구간과 비율은 null이며 가짜 신뢰구간을 만들지 않는다. available_population은 인사 입력의 재직−휴가−출장−재택으로 API adapter가 계산하며 raw ML 예측을 제한하지 않는다.

`operation`: recommended_servings, base_demand, safety_margin, ingredient_requirements, order_reviews, constraints(원본 object), alerts, status, requires_human_approval. 식재료 수량의 raw/edible/cooking/purchase 의미와 단위, 원본 trace를 보존한다.

`inventory_risk`: alerts, inventory_status, affected_menus, substitute_candidates, risk_events, recommended_rechecks(원본은 문자열 또는 객체), requires_confirmation 및 원본 증빙.

`decision`: decision_type, recommended_servings(null 가능), procurement_actions, inventory_actions, menu_actions, critical_alerts, confidence, requires_human_approval, decision_trace, data_quality_notes. 최종 추천은 원본 Decision만 결정한다. operation 권장량으로 Decision의 null을 채우지 않는다.

`sources`, `is_demo`, `advisory_only`, `warnings`, `errors`, `event_context`, `timings`를 항상 표시/전달한다. 알려지지 않은 Agent 증빙 필드는 버리지 않는다.

## 이벤트

`POST /api/replan`: `{ "existing_context": "앞선 request_id", "events": ["내일 손님 80명 추가"] }`.

events는 현재 전체 목록으로 이전 목록을 대체한다. 같은 이벤트를 다시 제출해도 이전 시나리오에 중복 가산하지 않는다. 날짜 해석 기준은 `as_of`. 원본 Risk parser가 해석하고, 대상일에 유효하며 superseded/needs_clarification이 아닌 인원 변동만 별도 운영 시나리오에 반영한다. ML 예측은 매번 원본 모델 입력에서 계산하고 그대로 반환한다. 조리/발주 재계산은 기존 Operation이 담당한다. MVP는 전체 pipeline을 재실행한다. 모호하거나 일부 해석되지 않은 문장은 PARTIAL/확인 요구로 남을 수 있다. 원본 Decision의 재검증 게이트를 임의 해제하지 않는다.

## 저장과 이력

`POST /api/actual-results`: site_id, target_date, actual_diners, prepared_servings, unserved_leftover_kg, plate_waste_kg, ingredient_waste_kg, shortage, notes, is_demo. 저장 후 DB에서 다시 읽은 result, 서버에서 계산한 summary(절대 예측오차/초과조리량), kpis를 반환한다. 동일한 재전송은 같은 결과, 변경된 중복은 409이며 덮어쓰지 않는다.

`GET /api/history/{site_id}`: 실적 입력 전에 생성된 마지막 예측과 조리계획을 연결한다. 실적 이후 예측으로 오차를 다시 쓰지 않는다. limit 기본 30, 최대 1000.

`GET /api/kpis/{site_id}`: 기존 DB helper의 안전한 집계. 데이터 부족 시 null. DEMO 및 UNVALIDATED 제외. all_new_actual_records와 eligible_new_actual_records를 분리한다. 실제 입력도 검증 전에는 UNVALIDATED이며 자동 재학습하지 않는다.

`GET /api/learning-dataset/{site_id}`: 원본 DB의 feature/snapshot 검증을 거친 데이터셋. 검증되지 않은 기록과 DEMO가 자동 유입되지 않는다.

## 업로드

`POST /api/upload/menu`: multipart file, CSV/XLSX. 열: date, meal_type, menu_name.

`POST /api/upload/inventory`: multipart file + context(PlanRequest JSON). 필수 열: ingredient, current_stock, unit, expiry_date, unit_price, minimum_stock, planned_order, storage_type. 선택: last_used_date. context로 사업장을 확인하고 원본 Repository에 inventory_snapshots를 즉시 저장한다. USER_UPLOAD는 진위 검증을 의미하지 않으며 DEMO 사업장의 업로드는 is_demo=true로 유지한다.

빈 파일, 열 불일치, 중복행, 날짜/음수/NaN, 지원되지 않는 단위, 수식, 손상 파일, 크기(5MB)/행수(5000)를 검사한다. 오류는 code/message/details 형식이다. 문법 오류 422, 충돌 409, DB 저장 실패 503, 내부 오류 500. 부분 Agent 결과가 있으면 오류 응답에도 보존한다.

## 확인

`POST /api/plans/{request_id}/acknowledgement`: 권고를 읽었다는 기록만 남긴다. approved=false, automatic_execution=false. 원본 Decision 승인 상태는 바뀌지 않는다. 발주/메뉴 변경 endpoint는 없다.

## Endpoint 목록

| Method | Path |
|---|---|
|GET|/api/health|
|GET|/api/demo-profile|
|POST|/api/plan|
|POST|/api/replan|
|GET|/api/plans/{request_id}|
|POST|/api/plans/{request_id}/acknowledgement|
|POST|/api/actual-results|
|GET|/api/history/{site_id}|
|GET|/api/kpis/{site_id}|
|GET|/api/learning-dataset/{site_id}|
|POST|/api/upload/menu|
|POST|/api/upload/inventory|
