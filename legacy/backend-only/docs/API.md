# 백엔드 API 인수인계

실행 후 `/docs`에서 요청/응답 스키마와 실행 예제를 확인할 수 있습니다. OpenAPI는 `/openapi.json`입니다.
이 백엔드는 JSON API만 제공합니다. UI와 모델은 포함되지 않습니다.

## 새 에이전트 연결 경로

| 메서드·경로 | 기능 |
| --- | --- |
| GET `/api/v1/health` | 백엔드 상태. ML 서버 상태를 검사하지 않음 |
| GET `/api/v1/integration` | 연결 설정 여부·계약 버전 확인 |
| POST `/api/v1/agent-plans` | v0.1.2 요청 전달, 원본 결과 저장·반환 |
| GET `/api/v1/agent-plans/{record_id}` | 저장한 요청·결과·상태 코드 조회 |
| GET `/api/v1/agent-plans/latest?site_id=...&target_date=2026-09-18` | 대상 사업장·날짜의 가장 최근 **저장된 시도**. 실패/부분 결과일 수도 있음 |

POST 입력은 팀원의 `/api/plan`과 같은 최상위 필드입니다.
팀원 폴더의 `examples/lh_like.json` 또는 `examples/small_site.json`을 그대로 사용하되 새 요청에는 고유 request_id를 주세요.
예제 파일 자체는 ML/팀원 자료 분리 원칙에 따라 이 배포본에 복사하지 않았습니다.

| 필드 | 형식·의미 |
| --- | --- |
| request_id | 1~100자 문자열. 입력 변경 시 새 ID |
| site_id | 사업장 ID. `site_id:request_id` 합계 200자 이하 |
| target_date, as_of | `YYYY-MM-DD`. as_of ≤ target_date. 시각 문자열이 아님 |
| meal_type | 현재 `lunch`만 지원. 생략 시 팀원 서버 기본값 사용 |
| meal_capacity | 0 이상의 정수 |
| attendance | registered_population 또는 employees, vacation/business_trip/work_from_home/overtime 등 native 인사 입력 |
| availability | 선택: 입력 확보시각 등 native metadata 객체 또는 null |
| weekly_menu | date/meal_type/menu_name을 포함한 목록. 현재 대상 점심이 있어야 함 |
| recipes | menu_name, ingredients 등 native 레시피 목록 |
| inventory | ingredient/current_stock/unit/expiry_date 등 native 재고 목록 |
| planned_orders, nutrition, prices, monthly_prices, supply_events | 각각 native 객체 목록 |
| sources | recipe/inventory/nutrition/price_trend/monthly_price/supply_risk/weekly_menu/constraints 출처 문자열 |
| operation_policy | native Operation 정책 객체 |
| event | 선택: 문자열, 구조화된 이벤트 객체 또는 null |

백엔드는 바깥 형식·날짜·유한 수치만 검증하고, 레시피/재고/증빙/이벤트의 세부 규칙은 원래 에이전트에 맡깁니다.
수량 변환, 인원 이벤트 자동 차감, 하위 에이전트 재실행, 누락 증빙 보완을 임의로 하지 않습니다.
v0.1.2 전체 파이프라인의 수량 단위는 g/kg만 허용됩니다. ml/ea가 들어오면 native 오류를 그대로 돌려줍니다.

### POST 응답과 이력

응답 본문은 팀원의 PipelineResult JSON입니다.
`pipeline_status`, `demand`, `operation`, `inventory_risk`, `decision`, `errors`, `warnings`,
`timings`, `input_revision`, `advisory_only` 및 추가 필드를 그대로 보존합니다.
성공한 단계와 실패한 단계가 섞인 부분 결과도 버리지 않습니다.

저장 성공 시 응답 헤더:

- `X-LastPlate-Record-Id`: 백엔드 이력 ID
- `Location`: `/api/v1/agent-plans/{record_id}`
- `X-LastPlate-Storage: saved`
- `X-LastPlate-Upstream-Status`: 팀원 서버의 HTTP 코드

GET 이력 응답은 POST와 달리 `{id, created_at, site_id, target_date, request_id, upstream_url,
upstream_http_status, request, result}`입니다. 계산 내용은 `result`에 있습니다.
동일 request_id를 재시도해도 백엔드는 native 서버에 전달하며, 호출별 이력을 따로 저장합니다.
ML 측의 중복 요청/충돌 처리를 백엔드가 대체하지 않습니다.

### UI에서 반드시 구분할 상태

| 상태 | 처리 |
| --- | --- |
| HTTP 200 + COMPLETE | 파이프라인 계산 완료. 승인 완료 아님 |
| decision.decision_type = BLOCK / NEEDS_CONFIRMATION | 차단/확인 필요로 표시. 자동 조리·발주 금지 |
| decision.recommended_servings = null | 최종 확정값 없음. 0 또는 Operation 값으로 덮어쓰지 않음 |
| operation.recommended_servings > capacity_servings | 원래 권장량과 capacity_excess를 함께 표시. 용량에 맞춰 몰래 자르지 않음 |
| demand.applicability = OUT_OF_DISTRIBUTION | 학습 적용 범위 밖 경고 표시. 예측을 검증된 정답으로 취급하지 않음 |
| lower_bound / upper_bound = null | 예측구간 없음. P95·확률을 임의 생성하지 않음 |
| requires_human_approval / approval_status / confirmation_gates / recommended_rechecks | 검토 필요·대기 상태를 그대로 표시. 재검증 완료나 승인으로 바꾸지 않음 |

`raw_required`, `raw_required_exact`, `cooking_required`, `purchase_need`, `unit` 등 수량의 의미를 구분하세요.
특히 원재료 손실률과 구매 단위 처리는 팀원 Operation v2.0의 계산을 그대로 사용합니다.
trace_refs, evidence, allocation_audit, source_payload 등 근거 데이터도 조회할 수 있습니다.

### 오류 코드

- 409/422/500: 팀원 서버가 반환한 상태·본문 그대로. 부분 결과를 표시하고 errors를 함께 보여 주세요.
- 422 `INPUT_VALIDATION_ERROR`: 백엔드 경계 입력 오류. PipelineResult 모양의 FAILED 응답입니다.
- 503 `AGENT_SERVICE_NOT_CONFIGURED` / `AGENT_SERVICE_UNAVAILABLE`: 주소 미설정/연결 불가.
- 504 `AGENT_SERVICE_TIMEOUT`: 처리 완료 여부 불명. 자동 재요청하지 말고 동일 입력·동일 request_id로 명시적 재시도하세요.
- 502 `AGENT_HTTP_PROTOCOL_ERROR` / `AGENT_RESPONSE_INVALID`: 예상치 못한 상태 코드 또는 응답 형식. 리다이렉트는 따라가지 않습니다.
- 저장 실패 특례: HTTP 503 + `X-LastPlate-Storage: failed`, `X-LastPlate-Error: BACKEND_STORAGE_FAILED`.
  이때 본문에는 받은 원래 결과가 그대로 남습니다. `X-LastPlate-Upstream-Status`로 원래 HTTP를 확인하고,
  UI에 **결과는 수신했지만 이력 저장 실패**를 표시하세요. 이력 ID는 없습니다.
- 이력 GET 404: 저장된 결과 없음. URL 미설정·연결 실패 같은 upstream 응답 전 오류는 이력에 저장하지 않습니다.

모든 HTTP 응답에서 본문을 읽으세요. `response.ok`만 보고 오류 본문을 버리면 PARTIAL 증빙이 사라집니다.

```javascript
const response = await fetch(`${BACKEND_URL}/api/v1/agent-plans`, {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify(input)
});
const result = await response.json();
const recordId = response.headers.get("X-LastPlate-Record-Id");
const storage = response.headers.get("X-LastPlate-Storage");
// 화면에는 response.status, result.errors, decision 상태, storage를 함께 표시합니다.
// result가 있다는 이유만으로 승인/발주 완료로 처리하지 않습니다.
```

## 기존 조리 엔진 경로 — 별도 시뮬레이션으로 유지

| 메서드·경로 | 기능 |
| --- | --- |
| GET `/api/v1/demo/input?scenario=normal` | normal/capacity_limit/delivery_delay/no_doc 시연 입력 |
| POST `/api/v1/forecasts/validate` | 기존 ForecastInput 형식 검증. 모델 실행 아님 |
| POST `/api/v1/operation-plans` | 예측·확정 이벤트·배치·재고로 운영안 생성, 201 |
| GET `/api/v1/operation-plans/latest?site_id=...&meal_date=2026-09-18&meal_type=lunch` | 기존 운영안 최신 이력 |
| GET `/api/v1/operation-plans/{id}` | 저장된 운영안 |
| GET `/api/v1/operation-plans/{id}/input` | 계산에 사용한 입력 |
| POST `/api/v1/operation-plans/{id}/events` | 인원 이벤트 반영/취소, 새 revision, 201 |
| POST `/api/v1/operation-plans/{id}/adjust` | 수동 조리량 조정/복원, 새 revision, 201 |
| POST `/api/v1/operation-plans/{id}/review` | 시연 검토 상태 저장. 실제 승인·발주 아님 |

입력은 `examples/operation-plan-request.json` 또는 demo/input을 참고하세요.
기존 날짜 키는 meal_date, 판단 시각은 current_time, 레시피는 recipe_g, 재고는 kg 방식입니다.
이미 조리를 시작한 배치 잠금, 확정 이벤트만 반영, 취소 시 복원, 중복 이벤트 검증, 공용 재고 중복 사용 방지,
기한순 배정, 최소량·영양 경고, 동시 revision 충돌 처리를 유지합니다.

이벤트 요청 예: `{"current_time":"2026-09-18T09:10:00+09:00","event":{"id":"trip","status":"confirmed","delta":-35}}`.
반환된 새 id로 다음 변동을 요청하세요. 이미 다음 revision이 생긴 과거 id 수정은 409입니다.
ML 기준에 이미 들어간 이벤트를 또 더하지 마세요. 기존 forecast.included_event_ids로 중복 반영을 제한합니다.

기존 경로의 review/adjust/events는 새 `/agent-plans` 결과에 적용할 수 없습니다.
예전 `/forecasts/predict`, `/forecasts/model`, `/assets` 및 HTML UI 경로는 이 배포본에 없습니다.
