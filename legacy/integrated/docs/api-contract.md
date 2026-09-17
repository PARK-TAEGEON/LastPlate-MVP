# LastPlate API 계약 — UI/ML 통합판

같은 FastAPI가 / 에 HTML, /assets 에 JS/CSS, /api/v1 에 JSON API를 제공합니다.
OpenAPI 원본은 /openapi.json, 실행 가능한 문서는 /docs입니다.
기본 실행은 127.0.0.1:8000이며 인증 없는 로컬 시연용입니다.

## 엔드포인트

| 요청 | 목적 |
| --- | --- |
| GET /api/v1/health | 서버 상태 |
| GET /api/v1/demo/input?scenario=normal | 명시적인 시연용 입력. normal/capacity_limit/delivery_delay/no_doc |
| GET /api/v1/forecasts/model | 모델 버전/feature/해시와 demo_inference 모드 |
| POST /api/v1/forecasts/predict | 실제 첨부 LightGBM 추론 → ForecastInput |
| POST /api/v1/forecasts/validate | 외부 ML 결과 JSON 스키마 검증 |
| POST /api/v1/operation-plans | 입력 스냅샷으로 새 운영안 생성 (201) |
| GET /api/v1/operation-plans/latest?site_id=A사업장&meal_date=2026-09-18&meal_type=lunch | 사업장·날짜·식사별 최신 결과 |
| GET /api/v1/operation-plans/{id} | 저장된 결과 |
| GET /api/v1/operation-plans/{id}/input | 결과에 사용된 입력 스냅샷 |
| POST /api/v1/operation-plans/{id}/events | 이벤트 추가/변경/취소 후 새 revision (201) |
| POST /api/v1/operation-plans/{id}/adjust | 수동 적용량 조정 또는 권장값 복원 (201) |
| POST /api/v1/operation-plans/{id}/review | 검토 상태 저장 (실제 발주 아님) |

## 1. 실제 ML 요청

```json
{
  "site_id": "A사업장",
  "meal_date": "2026-09-18",
  "meal_type": "lunch",
  "employees": 520,
  "vacation": 0,
  "business_trip": 0,
  "work_from_home": 0,
  "overtime": 0,
  "menu": "쌀밥 제육볶음 양배추무침"
}
```

직원 관련 입력은 0 이상의 정수이며 employees는 양수입니다.
employees−vacation−business_trip−work_from_home이 양수여야 합니다.
overtime은 시간외근무 승인 건수이고 출근인원에서 빼지 않습니다.
요일은 meal_date에서 계산합니다. 날씨는 입력받지 않습니다. 현재 모델은 중식 전용입니다.

위 520명 예시는 학습자료 범위(예정 출근인원 1,372~2,921) 밖이며,
현재 모델은 924명을 반환합니다. 이를 운영 정확도가 검증된 결과로 사용하면 안 됩니다.
표본 적용 범위 검증 및 재학습은 ML 팀의 후속 작업입니다.

응답의 공통 ForecastInput:

```json
{
  "site_id": "A사업장",
  "meal_date": "2026-09-18",
  "meal_type": "lunch",
  "lower": 924,
  "mid": 924,
  "upper": 924,
  "included_event_ids": [],
  "model_version": "v20260917T054002-4222a35a",
  "interval_method": "point_only",
  "source_kind": "ml",
  "input_summary": {},
  "warnings": ["점 예측 모델입니다. P95·예측구간·부족 확률을 제공하지 않습니다."]
}
```

실제 응답은 generated_at, 원본 입력 요약, 적용 범위 경고도 포함합니다.
lower=mid=upper는 기존 엔진 계약을 유지하기 위한 표현이지 예측 불확실성이 0이라는 뜻이 아닙니다.
외부 ML이 검증된 범위를 공급하면 interval_method=supplied로 사용할 수 있습니다.
현재 시연 범위 450~510은 demo_interval이고 90%나 P95 의미가 없습니다.

included_event_ids에는 ML 기준 입력에 이미 반영된 현장 이벤트 ID를 전달합니다.
현재 수동 인사 입력에는 ID 매핑이 없으므로, 같은 출장 인원을 ML 인사 입력과 추가 이벤트에 중복 입력하지 마세요.
예측에 포함된 ID를 변경하는 이벤트 요청은 422로 막습니다. 새 기준 예측을 먼저 생성해야 합니다.

## 2. 운영안 입력

GET /demo/input의 반환 JSON을 그대로 POST /operation-plans에 보낼 수 있습니다.
일반적인 API 예시는 examples/operation-plan-request.json에도 있습니다.

| 필드 | 설명 |
| --- | --- |
| site_id, meal_date, meal_type | forecast와 반드시 같은 운영 대상 |
| current_time | 판단 시각. UI는 고정 한국시간 시뮬레이션; 실운영 시 서버가 검증해야 함 |
| forecast | 정규화된 예측과 출처 |
| events | ID별 최신 상태 하나. confirmed만 delta를 적용, pending/cancelled는 제외 |
| menus | 메뉴별 recipe_g, batches, servings_per_guest, minimum_servings, nutrition_per_portion |
| inventory | 아래 3가지 재고 입력 방식 중 하나 |
| policy | 안전여유, 수량 계산 방식, 조리 단위, 기준 확인 여부 |
| constraints | minimum_servings_by_menu, minimum_nutrition_per_guest |
| applied_servings | null이면 권장량, 정수이면 수동 적용량 |

날짜/사업장 불일치, 중복 이벤트/식재료/메뉴 이름, 음수 재고, 잘못된 단위는 422입니다.
모든 배치·납기 타임스탬프는 current_time과 timezone awareness가 같아야 합니다.
가능하면 모든 시각을 +09:00이 있는 ISO 8601로 보내세요.

### 재고 방식 (kg, 소수점 최대 3자리)

- available_kg: 이미 예약/소비분을 제외한 순 가용량. reserved_kg를 다시 넣지 않습니다.
- physical_kg + reserved_kg: 실물에서 예약을 한 번 차감합니다.
- lots: 각 id, quantity_kg, reserved_kg, expires_on. 식사일 이전 기한은 제외하고 기한순 배정.

```json
{
  "ingredient": "돼지고기",
  "physical_kg": 50,
  "reserved_kg": 5,
  "order_unit_kg": 5,
  "expected_delivery_at": "2026-09-18T08:00:00+09:00"
}
```

가용량은 45kg입니다. 잠긴 배치에 투입/예약한 재고를 아직 포함한 실물 스냅샷이면
해당 물량을 reserved_kg로 넣거나, 이미 제외한 available_kg를 보내야 합니다.
현재 엔진은 실재고를 영구 차감하지 않으며 별도 요청들이 같은 재고를 예약하지도 않습니다.

### 조리 정책

- additive (기존 API 기본): ceil((선택한 lower/mid/upper × (1+비율) + 인원 여유) / 조리 단위) × 조리 단위.
- max_interval_and_buffer (UI): ceil(max(upper, mid × (1+비율) + 인원 여유) / 조리 단위) × 조리 단위.
- UI 기본 안전여유 10명, 조리 단위 10식. 480/450/510 시연 입력에서는 510식이지 520식이 아닙니다.
- 이 정책은 명시적 운영 규칙이며 부족 확률을 보장하지 않습니다.
- 수동 적용량은 cooking_unit 배수여야 하며 권장보다 작으면 경고 및 검토 완료 제한.
- 메뉴별 최소량은 적용량보다 클 수 있습니다.
- 시작 시각 이하인 배치 또는 cooking/done 상태는 잠깁니다. 실제 수량 fixed_qty가 없으면 기존 planned를 사용하고 경고합니다.
- 여러 메뉴가 같은 재고를 쓰면 전체 공용 재고 한 번만 배정합니다. 기존 계획 우선, 증가분은 입력 메뉴 순서의 결정적 greedy 방식입니다.

## 3. 운영안 출력

| 필드 | 의미 |
| --- | --- |
| id / parent_plan_id / created_at | 계산 이력 ID / 부모 ID / 실제 저장 시각 |
| result.recommended_target | 정책으로 계산한 권장 식수 |
| result.target | 현재 적용 식수 |
| result.baseline_prediction / prediction / event_delta | 변동 전 / 후 / 증감 합계 |
| result.menus | 현재 재고만으로 가능한 메뉴·배치 계획, 잠긴 수량, 부족/초과 |
| result.inventory | 가용·배정·잔여·목표 필요량·설비 계획 필요량 |
| stock_allocations | 예약·기한 경과 제외 내역 및 FEFO lot 배정 |
| purchase_recommendations | 부족분을 포장 단위 올림한 추천, 납기 상태 |
| projected_after_purchase | 권장 구매분이 제때 도착한다는 가정의 별도 조리 계산 |
| alerts / inventory_advisories | 운영/모델 경고, 기한 소진 신호 |
| review_allowed / review_status / reviewed_at | 서버 검토 가능 여부와 시연 검토 상태 |

납기가 현재시각 이하이면 이미 들어왔다는 증거가 없으므로 unconfirmed입니다.
현재보다 미래이면서 그 재료를 쓰는 가장 이른 예정 배치 시작까지 도착해야 on_time으로 간주합니다.
여러 배치의 일부만 충족하는 늦은 입고는 보수적으로 전체 입고 가정에서 제외합니다.
부족량은 **설비로 가능한 예정 조리량** 기준입니다. 용량 자체의 부족은 구매로 해결할 수 없습니다.
배송 지연, 용량 부족, 명시 제약 위반, 권장량 미달, 기준 미확인이 있으면 검토를 제한합니다.
review_allowed=true도 실제 운영의 안전 인증이나 발주 승인을 뜻하지 않습니다.

## 4. 이벤트 / 수동 조정

```json
{
  "event": {"id": "trip-001", "status": "confirmed", "delta": -35, "note": "단체출장"},
  "current_time": "2026-09-17T18:00:00+09:00"
}
```

같은 ID의 status를 cancelled로 보내면 취소입니다.
응답의 새 id로 다음 변동을 요청하세요. 이전 부모에 또 요청하면 409입니다.
이벤트 변동은 이전 delta를 누적 더하지 않고 원래 forecast와 현재 이벤트 목록에서 계산합니다.
수동 조리량 override도 제거하고 권장량을 다시 계산합니다.

adjust 요청:

```json
{"applied_servings": 500, "current_time": "2026-09-17T18:00:00+09:00"}
```

권장 복원은 applied_servings=null입니다. 검토 완료 후 조정하면 새 revision은 다시 검토 대기입니다.
review는 body 없는 POST이며 여러 번 호출해도 검토 시각을 바꾸지 않습니다.
동시 수정은 SQLite 트랜잭션으로 한 요청만 성공시키고 나머지는 409로 돌려줍니다.

## 오류와 연결

- 404: 운영안 없음.
- 409: 이미 자식 revision이 생긴 운영안 또는 검토 불가능 상태.
- 422: 입력 형식/수량/날짜/시간 또는 엔진 도메인 검증 실패.
- 503: 실제 ML 모델 로딩 실패. 모델 파일·해시·설치 환경을 확인하세요.

외부 React/Vue로 바꾸는 경우 LASTPLATE_CORS_ORIGINS에 프런트엔드 origin을 넣습니다.
기본 허용: http://localhost:3000, http://localhost:5173. 같은 서버의 현재 HTML에는 필요하지 않습니다.
프런트엔드는 result를 표시하고 조리/발주 판단을 JS에서 다시 계산하지 마세요.
DB 경로는 LASTPLATE_DATABASE_PATH로 바꿀 수 있습니다. 기본 backend/data/lastplate.db는 Git 제외입니다.
