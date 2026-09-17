# LastPlate Operation Agent v0.1.0 정식 코드 리뷰

검토일: 2026-09-17. 대상: `lastplate-operation-v0.1.0.zip`.

SHA-256: `ACED2076ACC5EACE2A95C334762B129FBB916998FBFBAEECE443929D0DB6F6EE`

첨부된 리뷰 요청문은 검토 항목으로 활용했다. 참조 대화와 ZIP 내부 README·자체 REVIEW_REPORT의 주장은 검증 대상 자료로 취급했다. 원본 구현을 수정하지 않고 압축을 해제해 코드, 기존 테스트, 추가 재현을 확인했다. 아래 경로·줄 번호는 ZIP 내부 `lastplate-operation/` 기준이다.

## A. 전체 평가

**단일 식사에 대한 결정론적 계산·검수 MVP로는 잘 구현되어 있다. 정상 범위의 조리량·수율·재고·발주 계산이 맞고, 기존 테스트 85개를 이번 환경에서도 모두 통과했다. 실제 운영 통합에는 Demand 적용 가능성 전달과 사업장 설비 한도 등의 보완이 필요하다.**

| 평가 축 | 판정 | 근거와 한계 |
|---|---|---|
| 구현 완성도 | 핵심 계산·검수 구현 | 실제 StateGraph, 입력/출력 스키마, 오류 조기 종료, Streamlit 예제 존재 |
| 계산 정확성 | 일반 시나리오 정상 | 523인분, 손실률 5%, 재고 6kg, 발주 경계 재현. 올림 순서에 따른 과잉 산출 가능성은 P2 |
| 데이터 근거 | DEMO | 숫자는 예제·config·호출자 입력. 외부 레시피/영양/재고 API 구현 없음 |
| MVP 결합성 | 함수·서브그래프 단위 양호 | JSON 보고서, 자문/승인 필요 플래그. FastAPI endpoint와 완전한 4-Agent 통합은 없음 |
| 운영 준비성 | 보완 필요 | 설비 한도, OOD 계약, 식재료 ID/출처 버전, 운영 영양 정책, 재고 예약은 별도 필요 |

기존 ZIP의 `REVIEW_REPORT.md`에 적힌 Inventory 테스트 240개 및 v0.2.3 실제 wrapper 스모크는 이번에 재실행하지 않았다. 해당 Inventory·Demand·Decision 소스는 이번 ZIP에 없다. 이번에 확인한 범위는 Operation 테스트와 자체 bridge 계약까지다.

### 전체 구조

```text
lastplate-operation/
├── pyproject.toml
├── README.md
├── REVIEW_REPORT.md                   # 구현자의 기존 자체 보고서
├── contracts/
│   ├── operation_input.schema.json
│   └── operation_output.schema.json
├── examples/
│   ├── demo.py
│   ├── demo_input.json
│   ├── demo_output.json
│   ├── streamlit_app.py
│   └── inventory_v023_smoke.py
├── tests/
│   ├── test_operation_agent.py
│   └── test-results.xml               # ZIP에 포함된 과거 실행 결과
└── lastplate_operation/
    ├── __init__.py
    ├── integration.py
    ├── agents/operation.py
    ├── graph/operation_workflow.py
    ├── config/operation_policy.py
    ├── schemas/{base,operation_input,operation_output,operation_trace}.py
    └── tools/{serving,procurement,unit_conversion,constraints}.py
```

하위 Python 패키지에는 `__init__.py`가 있다. 핵심 entry point는 `generate_operation_plan(...)` (`agents/operation.py:192`), 그래프 생성은 `build_operation_subgraph()` (`graph/operation_workflow.py:15`)다.

실제 호출 흐름:

**Demand + Recipe + Inventory + Orders + Config → initialize → validate_materials → serving_stage → recipe_stage → inventory_stage → order_stage → constraint_stage → build_report**

`STAGES`는 `agents/operation.py:168`에서 정의된다. 재료 검증 중 단위·누락 문제는 수량 계산 전에 종료한다. 영양 검사는 수량 산출 이후이므로 FAIL이어도 검토용 수량은 반환한다.

## B. 잘 된 점

1. **수율 계산이 맞다.** `tools/procurement.py:21–26`은 필요량에 단순히 5%를 더하지 않고 `required / (1-loss/100)`을 적용한다.
2. **하한이 필요량보다 낮아지지 않는다.** 발주 허용오차 5%는 상한에만 적용한다. 부족 발주를 ±5%로 정상 처리하지 않는다.
3. **입력 오류를 적극 차단한다.** `schemas/base.py:6–14`는 음수, bool, 숫자 문자열, NaN, infinity, 10^12 초과를 거절한다. 손실률 100% 이상도 거절한다.
4. **재고 미확인과 0을 구분한다.** `agents/operation.py:81–85`에서 재고 행 누락 시 `needs_clarification`으로 중단한다. 예정 주문 누락도 0으로 가정하지 않는다.
5. **차원이 다른 단위를 섞지 않는다.** 재료 검증에서 g/ml/ea 불일치를 수량 산출 전에 거절한다 (`agents/operation.py:67–77`).
6. **실제 LangGraph다.** `StateGraph`, 노드, 조건부 edge, invoke가 있고 기존 테스트 6개 변형이 일반 함수와 결과 일치를 확인한다 (`tests/test_operation_agent.py:231–242`).
7. **제약 실패와 근거 부재를 구분한다.** FAIL → review, UNKNOWN → needs_clarification, 규칙 미설정 → NOT_CONFIGURED. FAIL을 PASS로 완화하는 가격·선호도 최적화는 없다.
8. **근거가 실행값이다.** 단위 변환, 조리량, 식재료 합계, 재고 차감, 발주 비교를 실제 입력과 결과로 기록한다. 계산식 문구는 고정 설명이지만 수치는 하드코딩이 아니다.
9. **역할을 제한한다.** 식수예측, 외부 가격 조회, 실제 발주, 최종 승인 구현이 없다. `requires_human_approval`와 `advisory_only`는 항상 True다.

## C. P0 — 시연·핵심 계산을 깨뜨리는 치명적 문제

**확인된 P0 없음.** 제공된 DEMO와 요구된 일반 계산 시나리오는 정상 동작했다. 아래 P1은 운영 통합 기능 공백이며, P2의 극단적인 Decimal 입력 예외를 일반적인 DEMO 장애로 확대하지 않았다.

## D. P1 — 통합 전에 수정 권장

### P1-1. Demand OOD/applicability 정보를 보존할 계약이 없다

- 위치: `schemas/operation_input.py:11–22`, `schemas/base.py:34–35`, `agents/operation.py:31–34`.
- 재현: DEMO `demand_result`에 `applicability: {status: "OOD"}` 추가 → `invalid_input`, extra field 거절.
- 영향: 현재 직접 전달하면 통합이 실패한다. 호출자가 경고를 삭제해 맞추면 예측값·model_version·snapshot만 남고 모델의 적용 불가 사유는 Operation 보고서에서 사라진다.
- 범위: 숫자를 잘못 계산하는 버그는 아니다. 실제 Demand 모듈의 필드명은 제공되지 않아 호환 여부 전체를 단정할 수 없다. 다만 현재 스키마에 어떤 형태의 OOD/경고 필드도 없다는 것은 확인했다.
- 수정: 실제 Demand 계약과 합의해 typed applicability/warnings 및 필요한 모델 메타데이터를 추가하고 `source`와 trace에 보존한다. 적용 불가·불확실 상태를 어떻게 review/needs_clarification으로 보낼지 명시한다. 임의 이벤트 증감량을 더하는 기능은 추가하지 않는다.

### P1-2. 사업장 최대 조리량·현실적 예측 범위를 검사할 수 없다

- 위치: `config/operation_policy.py:32–44`, `tools/serving.py:4–16`, `schemas/base.py:12–13`.
- 재현: prediction=10^12, 기본 안전여유 3% → **1,030,000,000,000인분** 산출. `maximum_servings=500`을 config에 넣으면 알 수 없는 필드로 거절한다.
- 영향: 최소 인분은 있으나 설비 용량과 비교하지 않는다. 수학적 숫자 상한 10^12는 사업장 정원·설비 한도가 아니다. 위 재현의 review는 발주 부족에서 생기며, 설비 한도 경고는 없다.
- 수정: 사업장별 `capacity_servings`와 입력 식수의 적용 범위를 정의한다. 요구량이 설비 용량을 넘으면 원래 요구량·초과량을 남기고 검토 대상으로 분기한다. 조용히 용량으로 잘라 수요를 충족한 것처럼 표시해서는 안 된다.

## E. P2 — 후속 개선 및 제한된 경계값 결함

### P2-1. 원물량과 발주량을 모두 올려 재고가 충분해도 발주가 발생할 수 있다

- 위치: `tools/procurement.py:21–25`.
- 재현: 523인분 × 120g, 손실 5%, 재고 **66.0632kg**, g quantum=100. 정확한 원물 필요량은 66,063.157894…g로 재고보다 작다. 코드 결과는 원물량 66,100g → 차감 후 올림 → **발주 100g**이다.
- 의미: README에 명시된 보수적 이중 올림 정책과는 일치한다. 계산식 구현 오류라기보다 조리 계량 단위와 구매 포장 단위를 하나의 quantum으로 처리하는 정책 한계다. 불필요한 발주를 줄이려는 목적에서는 점검해야 한다.
- 개선: 조리 계량 올림과 발주 포장 올림을 분리한다. 구매 단위만 설정한 경우 `ceil_purchase(max(0, exact_raw_required-stock))`을 적용한다. 기존 보수 정책을 유지한다면 추가량을 명시한다.

### P2-2. 개수 단위의 예정 발주·재고에 소수가 허용된다

- 위치: `schemas/operation_input.py:32–41`, `config/operation_policy.py:54–55`, `tools/unit_conversion.py:12–16`.
- 재현: 1인분, 1ea/인, 재고 0ea, 안전여유 0%, 기본 허용오차 → 범위 [1,2]ea. 예정 발주 **1.5ea는 OK**, 보고서 status=ok.
- 의미: quantum만 정수로 제한하고 재고·발주 수량은 제한하지 않는다. ea를 실제 낱개 발주로 해석한다면 UI/API 계약 불일치다. 분할 사용 가능한 재료의 1인분 투입량까지 무조건 정수로 제한할 필요는 없다.
- 개선: `ea` 재고·발주의 분할 가능성을 계약으로 정하고 낱개 구매라면 정수만 허용한다.

### P2-3. 지원하는 Python Decimal 입력의 극단적인 quantum에서 구조화 오류 대신 예외 발생

- 위치: `schemas/base.py:6–14`, `config/operation_policy.py:52–53`, `tools/procurement.py:5–6`, `agents/operation.py:171–181`.
- 재현: g quantum=`Decimal('1e-1000000')` → 검증을 통과한 후 `decimal.Overflow` 발생. `run_stage`는 UnitError만 잡는다.
- 범위: Python 함수 입력에서 재현한 극단적 사례다. 일반 JSON float quantum=1e-300은 별도 실행에서 예외 없이 처리됐다. 통상적인 요청에서도 장애가 난다고 주장하지 않는다.
- 개선: 도메인에 맞는 최소 quantum/유효 자릿수를 제한하고 산술 예외를 구조화한다. schema가 받아들이는 값은 보고서의 float 정책 snapshot에서도 의미를 유지해야 한다.

### P2-4. 수량 필드명이 실제 의미와 반대여서 통합 시 오해할 수 있다

- 위치: `schemas/operation_output.py:6–16`, `agents/operation.py:117–119`.
- `gross_required`는 실제로 가식 필요량 62,760g이고 `adjusted_required`가 손실 반영 원물량 66,064g이다. README와 주석은 이를 정확히 설명한다.
- 개선: 새 schema 버전에 `edible_required`, `raw_required`를 도입하고 기존 필드는 명시적 deprecated alias로 유지한다. 현재 산술 오산으로 분류하지 않는다.

### P2-5. Alert 자체에 정형 evidence와 고정 type 계약이 없다

- 위치: `schemas/operation_trace.py:13–18`, `agents/operation.py:125–126,144–146,158–159`.
- severity/type/message와 optional ingredient/field는 있으나 evidence 필드는 없다. Decision이 UNDER_ORDER의 비교값을 확인하려면 order_reviews 또는 trace를 찾아야 한다. type은 자유 문자열이다.
- 개선: 안정된 alert code enum과 evidence 또는 trace ID를 추가한다. trace·constraints.checks에 수치가 이미 있으므로 전체 근거가 없다는 뜻은 아니다.

### 결함과 구분해야 할 설계 제한

- 영양값은 레시피로부터 재계산하지 않는다. 돼지고기 100g/인, 두부 1g/인으로 바꿔도 기존 영양값을 유지하면 PASS가 남았다. 문서대로 외부 입력을 신뢰한 결과지만, 실제 연동에는 recipe version과 nutrition version의 연결 검증이 필요하다.
- `REAL`은 사용자 지정 라벨이다. 출처 인증이 아니다. 영양 규칙 미설정 시 NOT_CONFIGURED이고 status=ok도 가능하다. 운영 모드의 필수 정책 검사와 Decision의 허용 조건을 별도 정의해야 한다.
- 만료일 필드를 넣으면 extra field로 거절한다. 만료·예약 재고를 제거한 **사용 가능한 원물 재고**를 upstream에서 제공해야 한다.
- 동일 식재료는 이름 문자열로 결합한다. 식재료 ID·품종·가공 상태·로트 원본 ID가 없으므로 경계 adapter가 이를 정리해야 한다.
- `required_menus`는 누락 검사용이지 선택 필터가 아니다. 다른 메뉴 행도 입력하면 함께 합산한다. 선택식/메뉴별 서로 다른 식수는 지원하지 않는다.

## F. 기능별 상태 표

| 기능 | 판정 | 실제 동작·근거 |
|---|---|---|
| prediction 단독 입력 | 구현 | interval 없으면 prediction 사용, 487 → 502인분; serving.py:5–11 |
| 예측 구간 검증 | 구현 | lower ≤ prediction ≤ upper; operation_input.py:17–22 |
| 음수·0 식수 | 구현 | 음수 거절, 0은 최소 인분에 따라 0 가능 |
| OOD/적용 가능성·확장 메타데이터 | 미구현 | model_version/input_snapshot_id만 보존 |
| 안전여유·부족 정책·최소 조리량 | 구현 | config 기반 conservative/expected, ceil |
| 설비 최대 capacity | 미구현 | 최대 인분 정책 없음 |
| 1인분 기준량·수율·재고 차감 | 구현 | aggregate → purchase_range |
| g/kg, ml/l, ea 변환 | 구현 | 소문자 지원; 차원 혼용 거절 |
| 대소문자·공백 | 부분구현 | `KG` 거절, ` kg `는 schema에서 공백 제거 후 정상 |
| 재고 여러 행·단위 혼합 | 구현 | 동일 식재료 합산; g와 kg 정상 |
| 재고 누락/0/초과 | 구현 | 누락 확인 필요, 0 계산, 초과 시 발주 필요 0 |
| 만료·예약·끼니 간 배분 | 미구현 | upstream 책임, lot/date/reservation schema 없음 |
| 발주 min/max, UNDER/OK/OVER | 구현 | 양 끝값 포함, difference는 위반 경계와의 양의 거리 |
| 포장·MOQ·품목별 구매 단위 | 부분구현 | 단위별 quantum만 존재 |
| 단백질·열량·나트륨·알레르기 | 구현 | 외부 한 끼/인분 영양값 검사 |
| 최소 제공량 | 구현 | 식재료별 모든 메뉴의 1인분 투입량 합계 검사 |
| 영양 API 집계·실제 조리 영양 계산 | 미구현 | caller 제공 snapshot 사용 |
| FAIL/UNKNOWN 경로 | 구현 | review / needs_clarification, 수량은 검토용 유지 |
| LangGraph | 구현 | 실제 StateGraph·조건부 조기 종료·route 반환 |
| 독립 error/review 작업 노드 | 부분구현 | 별도 노드 대신 report/status; 상위 그래프 분기는 미포함 |
| 실행값 trace | 구현 | 정규화·수식·입력·결과 |
| Alert 정형 evidence | 부분구현 | 관련 보고서 수치는 있지만 Alert evidence 없음 |
| Decision 입력 | 부분구현 | 필요한 주요 필드는 존재, 실제 Decision 연동 검증 없음 |
| Streamlit | 구현 | AppTest로 DEMO/깨진 JSON 통과 |
| FastAPI endpoint | 미구현 | callable을 감싸는 wrapper 필요 |
| 실제 Recipe/Nutrition/Inventory adapter | 미구현 | 현재는 외부에서 list/config를 구성해 전달 |
| 패키지 import·JSON 출력 | 구현 | 테스트에서 import, output schema, allow_nan=False 검사 |

### 실제 Demand·Recipe·Nutrition 계약

```json
{
  "demand_result": {
    "prediction": 487,
    "prediction_interval": {"lower": 469, "upper": 507},
    "model_version": "demo-v1",
    "input_snapshot_id": "demo-meal-001"
  },
  "recipe_data": [
    {"menu_name": "제육볶음", "ingredient": "돼지고기", "amount_per_serving": 120, "unit": "g"}
  ],
  "inventory_data": [{"ingredient": "돼지고기", "stock": 6, "unit": "kg"}],
  "planned_orders": [{"ingredient": "돼지고기", "planned_order": 61000, "unit": "g"}],
  "config": {"nutrition_per_serving": {"protein": 30, "calories": 700, "sodium": 1000, "allergens": ["대두"]}}
}
```

위 nutrition 값은 계약 설명용 DEMO이며 제육볶음 1개 레시피에서 산출했다는 뜻이 아니다. `prediction_interval`, model_version, snapshot ID는 선택 사항이다. recipe/inventory/orders 리스트 자체는 필수다. Recipe amount는 0보다 커야 하며, 재고·발주는 0 이상이다. nutrition은 완성된 전체 한 끼의 1인분 합계로 protein=g, calories=kcal, sodium=mg다. 지방 검사는 없다. allergen은 이름 정확 일치이고 교차오염을 판단하지 않는다.

### Alert 이름과 상태

| 요청문 표현 | 실제 type | 주요 severity |
|---|---|---|
| UNDER_PREP | UNDER_PREPARATION | HIGH |
| OVER_PREP | OVER_PREPARATION | MEDIUM |
| UNDER_ORDER | UNDER_ORDER | HIGH |
| OVER_ORDER | OVER_ORDER | MEDIUM |
| STOCK_SHORTAGE | STOCK_SHORTAGE | MEDIUM |
| UNIT_ERROR | UNIT_MISMATCH | HIGH |
| RECIPE_MISSING | MISSING_RECIPE | HIGH |
| CONSTRAINT_FAIL | HARD_CONSTRAINT_VIOLATION | HIGH |

단위 오류와 레시피 누락은 halt=True로 report builder에 조기 분기한다. FAIL은 마지막 constraint_stage에서 review를 설정한다. `build_report`는 status=ok일 때 HIGH가 있으면 review로 올린다. 따라서 OVER만 있는 DEMO는 status=ok일 수 있다. 이는 문서화된 상태 의미이며 승인이나 모든 검수 정상이라는 뜻이 아니다.

## G. DEMO 값과 threshold 목록

| 값 | 위치 | 출처 분류 | 실제 데이터 전환 |
|---|---|---|---|
| prediction 487, interval 469–507 | examples/demo_input.json:2 | DEMO 입력 | 실제 Demand 결과 |
| model demo-v1, snapshot demo-meal-001 | 같은 위치 | DEMO 메타데이터 | 실제 모델/입력 ID |
| 돼지고기 120g/인 | demo_input.json:4 | DEMO 레시피 | 검수된 가식 1인분량 |
| 두부 80g/인 | demo_input.json:5 | DEMO 레시피 | 검수된 가식 1인분량 |
| 돼지고기 6kg, 두부 8000g | demo_input.json:8–9 | DEMO 재고 | 배정된 사용 가능 원물 재고 |
| 발주 105000g, 34000g | demo_input.json:12–13 | DEMO 예정 주문 | 실제 주문안 |
| safety margin 3% | demo_input.json:16, operation_policy.py:33 | DEMO + config 기본값 | 사업장 승인 정책 |
| 돼지고기 trim loss 5% | demo_input.json:16 | DEMO config | 식재료·손질 상태별 수율 |
| 미지정 손실률 0% | agents/operation.py:114 | core fallback | 생략 의미를 명시, 실데이터에서는 확인 권장 |
| order tolerance 5% | operation_policy.py:37 | config 기본값 | 운영 발주 허용오차 |
| 최소 인분 0, conservative | operation_policy.py:35–36 | config 기본값 | 사업장 운영 정책 |
| quantum g/ml/ea 각각 1 | operation_policy.py:38–39 | config 기본값 | 조리 계량/구매 단위 분리 권장 |
| 돼지고기 최소 100g/인 | demo_input.json:17 | DEMO 제약 | 사업장 식단 기준 |
| 단백질 최소 20g/인 | demo_input.json:17 | DEMO 제약 | 적용 대상별 검수 기준 |
| 열량 500–900kcal/인 | demo_input.json:17 | DEMO 제약 | 검수 기준 |
| 나트륨 최대 1500mg/인 | demo_input.json:17 | DEMO 제약 | 검수 기준 |
| 땅콩 제한 | demo_input.json:17 | DEMO 제약 | 실제 알레르기 제한 |
| 단백질30, 열량700, 나트륨1000, 대두 | demo_input.json:18 | DEMO 영양 근거 | 동일 식사 버전의 영양 합계 |

영양 제약에는 core의 법적·의학적 기본값이 없다. README도 DEMO라고 명시한다. 3%와 5%는 설정으로 바꿀 수 있지만 config를 생략하면 실제로 적용되므로 운영 배포 시 검토해야 한다.

| threshold | 책임 | 현재 사용 |
|---|---|---|
| Demand 구간 상단 | ML이 산출, Operation이 선택 | conservative 정책의 base |
| safety margin | Operation/site policy | 조리량 여유 비율 |
| trim loss | Recipe/site yield policy | 원물 환산, 이상탐지 기준 아님 |
| order tolerance | Operation/site policy | 구매 필요량 대비 상한 +5%; 별도 절대 오차 없음 |
| quantum | Operation 계량/발주 정책 | 절대 수량 올림 단위; 이상탐지 cutoff 아님 |
| 영양·최소 제공량 | 적용 대상의 검수 정책 | 입력된 규칙만 검사 |
| 가격 급등·공급위험 | Inventory & Risk | 이 ZIP에는 없음 |
| OOD/applicability | Demand/통합 계약 | 현재 입력 필드 없음 |

ML 임계값·가격 이상탐지 임계값과 Operation 허용오차를 혼용하는 코드 증거는 없다.

## H. 계산식 검증 결과

```text
base = interval.upper (conservative + interval 존재)
     = prediction (expected 또는 interval 없음)
servings = max(minimum_servings, ceil(base × (1 + safety_margin_pct/100)))
edible_required = servings × sum(동일 식재료의 1인분 투입량)
raw_required = ceil_q(edible_required / (1 - trim_loss_pct/100))
purchase_need = ceil_q(max(0, raw_required - usable_raw_stock))
recommended_min = purchase_need
recommended_max = ceil_q(purchase_need × (1 + order_tolerance_pct/100))
```

| 검증 | 결과 |
|---|---|
| 487, upper507, safety3% | ceil(522.21) = **523인분** |
| interval 없음 또는 expected | ceil(487×1.03) = **502인분** |
| 523 × 120g | **62,760g 가식 필요량** |
| 손실 0%, 재고6kg | **56,760g 구매 필요량** |
| 손실5% 적용 | 62,760 / 0.95 = 66,063.157894…g → **66,064g** |
| 손실5%, 재고6kg | **60,064g 구매 필요량** |
| 발주 상한 +5% | ceil(60,064×1.05) = **63,068g** |
| 발주105,000g | OVER, difference=**41,932g** |
| 발주60,063g | UNDER, difference=**1g** |
| 발주60,064g 또는63,068g | OK, difference=0 |
| 발주63,069g | OVER, difference=1g |
| 재고100kg | purchase_need=min=max=0 |
| 두부80g×523, 재고8000g, 손실0 | 필요41,840g, 구매33,840g, 상한35,532g, 주문34,000g=OK |

Decimal 비교·계산은 각 stage에서 precision=50으로 수행하고 출력에서 float로 변환한다. 일반 수량에는 문제가 재현되지 않았다. 출력이 임의 정밀도를 보장하는 Decimal 계약은 아니며 극단적인 큰 수·작은 quantum은 추가 제한이 필요하다. 입력을 mutate하는 코드, 실제 import에서 circular import 오류, 실행 간 결과 변동은 발견하지 못했다. 다만 `UNITS` dict는 모듈 전역의 가변 객체라 읽기 전용화 개선 여지는 있다.

## I. 테스트 실행 결과

### 기존 suite — 원본 코드와 테스트 수정 없음

- Python **3.12.14**, Pydantic **2.13.5**, LangGraph **1.2.11**, pytest **9.1.1**, Streamlit **1.64.0**.
- 실행: `python -m pytest work/source/lastplate-operation/tests -q --junitxml=outputs/original-tests.xml` (작업 폴더 설치 의존성 경로를 PYTHONPATH에 지정).
- 결과: **85 passed in 7.74s**, 실패·skip 0.
- 이번 실행 로그: `original-tests.txt`, `original-tests.xml`. ZIP 내부의 기존 `tests/test-results.xml`을 재사용하지 않았다.
- Streamlit AppTest도 포함했다. 웹 브라우저 수동 UI 검사나 실제 서버 배포는 수행하지 않았다.

| 요청 CASE | 확인 결과 | 근거 |
|---|---|---|
| 1 조리량523 | PASS | test_reference_arithmetic |
| 2 120g×523, 재고6kg | PASS | 기존 손실5% + 추가 lossless_case_2 |
| 3 손실5% 수율 | PASS | test_reference_arithmetic |
| 4 상한 초과 OVER | PASS | test_order_boundaries |
| 5 하한 미달 UNDER | PASS | test_order_boundaries |
| 6 재고 초과 → 구매0 | PASS | test_excess_stock_zero_order |
| 7 kg/g 혼합 | PASS | test_unit_normalization |
| 8 지원하지 않는 단위 | PASS, invalid_input | test_bad_units_fail_closed |
| 9 레시피 누락 | PASS, needs_clarification | test_empty_and_missing_menu 등 |
| 10 영양 FAIL | PASS, review + FAIL | test_hard_constraints |

추가 재현 스크립트는 **18개 관찰 항목**을 기록했다. 15개 동작 assertion과 2개 schema artifact 일치 검사는 통과했고, 1개 극단적 Decimal 입력은 Overflow를 포착했다. 이는 “추가 정상성 테스트 18개 통과”라는 뜻이 아니다. 1.5ea 허용 등 일부 assertion은 결함/제한의 현재 동작을 재현하기 위해 작성했다.

추가로 대문자/공백 단위, OOD 거절, capacity config 거절, 10^12 및 초과 예측, 영양값 미재계산, 만료 필드 거절, 필요 이상 올림, NaN 재고, infinity 레시피, Decimal 예외, JSON 미소 quantum을 확인했다. 상세 값은 `review-probes.json`에 저장했다. 두 JSON Schema 산출물은 현재 모델에서 생성한 schema와 동일했다.

패키지 설치 의존성은 `[test,ui]`를 함께 준비해야 현재 전체 suite가 실행된다. `pyproject.toml`의 `[test]`에는 streamlit이 없지만 테스트는 AppTest를 직접 import한다. README는 `[test,ui]` 설치를 안내하므로 그 경로에서는 문제없다. CI에서는 이를 명시하거나 UI 테스트를 분리하는 편이 낫다.

## J. Operation / Inventory / Decision 책임 분리

| 모듈 | 맡을 책임 | 현재 코드 평가 |
|---|---|---|
| Demand | 식수·구간·모델 적용 가능성 | Operation은 예측하지 않음. OOD 계약 확장 필요 |
| Inventory & Risk | 만료·예약·가격·공급위험·대체 후보, 사용 가능 재고 | Operation에 이 로직 없음. 이중 구현은 발견되지 않음 |
| Operation | 조리량·필요량·원물 환산·재고 차감·발주 검수·제약 검사 | 구현. STOCK_SHORTAGE는 현재 재고와 필요량 비교이며 공급 위험 예측과 다름 |
| Decision | 여러 보고서 종합, 실행 후보 배제, 최종 권고·승인 절차 | 현재 ZIP에 없으며 Operation은 최종 승인하지 않음 |

권장 연결은 `Inventory 재고 적격성/예약 → usable_inventory → Operation 계산 → Inventory 위험 분석 및 Decision 종합`이다. Inventory가 조리량을 필요로 하면 재고 적격성 조회와 위험 분석 단계를 나눠 데이터 의존성을 해결한다. 재고를 여러 식사에 중복 배정하지 않도록 상위 orchestration이 예약해야 한다.

`integration.py:6–34`의 `to_inventory_forecast`는 recommended_servings를 `expected_max_diners`에 담는 **count-only bridge**다. 수율·발주량은 넘기지 않는다. prediction 자체와 의미가 다르므로 이 필드는 Operation 조리량이라는 출처를 유지해야 한다. FAIL/UNKNOWN, invalid_input/needs_clarification을 거절하지만 NOT_CONFIGURED나 일부 review는 허용한다. 이는 최종 실행 승인이 아닌 중간 위험 분석 전달이며, Decision은 원 보고서를 별도로 받아야 한다.

## K. 실제 API 교체 계획

코어가 특정 API/CSV에 결합되어 있지 않아 **외부 adapter가 현재의 정규화된 list/config를 만들면 산술 core를 유지할 수 있다.** 다만 adapter 클래스/인터페이스가 이미 구현된 것은 아니다. 출처·버전·식재료 ID를 엄격하게 검증하려면 schema 확장도 필요하다.

| 입력 원천 | 필요한 변환 | 변경 위치 제안 |
|---|---|---|
| 식약처 COOKRCP01 | RCP_NM을 메뉴명에, RCP_PARTS_DTLS를 검수된 재료별 수량으로 변환. 인분 기준과 가식/원물 여부 확인. INFO_WGT를 각 재료량으로 오인하지 않기 | 새 adapters/recipe_mfds.py |
| 농정원 레시피 재료정보 | RECIPE_ID로 메뉴/기준 인분 정보를 연결, IRDNT_NM 정규화, IRDNT_CPCTY 문자열 수량 파싱. 컵/모/약간은 승인된 환산표 없으면 확인 필요 | 새 adapters/recipe_epis.py |
| 농진청 메뉴젠 음식별 영양정보 | 음식·식품 코드와 식품중량 매핑, 제공량·영양 기준 단위 확인 후 음식 구성 정규화 | 새 adapters/recipe_menuzen.py |
| 통합 식품영양성분 DB | 코드·생/조리 상태·함량 기준량을 맞추고 1인분 영양량으로 환산, 메뉴별 합산 후 한 끼 합산 | 새 adapters/nutrition.py |
| Excel/SQLite/DB 재고 | 식재료 ID 매핑, 단위 변환, 만료/예약/다른 끼니 배정 제외, 원물 기준의 사용 가능량 snapshot | 새 adapters/inventory.py, 적격성 판정은 Inventory 책임 |
| 사업장 정책 | 여유율·손실률·영양 기준·설비 한도 및 정책 버전 | config 로딩 계층 + 정책 schema 확장 |

식약처 공식 명세에는 메뉴명·1인분 중량·영양값·재료정보 필드가 존재한다. 재료 문자열을 바로 숫자 배열로 쓸 수 있다는 뜻은 아니다. [COOKRCP01 공식 명세](https://www.foodsafetykorea.go.kr/api/newDatasetDetail.do?svc_no=COOKRCP01)

농정원 공식 출력 예에는 재료용량이 `4컵`, `200g`, `1/2모`처럼 혼합 표기된다. Operation 지원 단위로 변환할 수 없는 행을 임의 추정하면 안 된다. 공식 응답 필드는 레시피 코드·재료순번·재료명·용량·재료타입이며, 이 endpoint만으로 영양값까지 모두 제공된다고 가정하지 않는다. [농정원 레시피 재료정보 공식 명세](https://data.mafra.go.kr/opendata/data/indexOpenDataDetail.do?data_id=20150827000000000465)

농진청은 음식별 영양성분 정보 서비스를 제공하며, 음식·식품 코드와 식품중량 등 연결 정보를 확인할 후보가 된다. 실제 인분 기준과 인증 호출 결과는 adapter 구현 단계에서 확인해야 한다. [메뉴젠 음식별 영양성분 정보](https://www.data.go.kr/data/15143461/openapi.do)

통합 영양 데이터에는 영양성분 함량 기준량·식품코드·식품중량·출처 등이 있다. 고정적으로 모든 값을 “한 끼” 또는 “100g”으로 취급하지 않고 각 행의 기준량을 확인해야 한다. [공식 통합 데이터 메타데이터](https://www.data.go.kr/catalog/15100064/standard.json)

영양 aggregation 설계 예: `재료 영양 기여 = 기준량당 영양값 × 일치하는 상태의 1인분 투입량 / 기준량` → 메뉴 합계 → 한 끼 합계. 조리·수율 상태가 다른 자료를 연결할 때는 검수된 변환이 필요하다. 구매용 원물량을 영양 계산의 섭취량으로 그대로 사용하지 않는다. 알레르겐은 별도 검증된 원재료/제품 라벨 정보를 결합해야 하며, 미확인을 빈 배열로 바꾸지 않는다.

위는 공식 문서에 근거한 adapter 설계 제안이다. API 인증키 발급·실제 API 호출·데이터 품질 검수는 이번 코드 리뷰에서 수행하지 않았다.

## L. MVP 결합 방법

Streamlit에서는 제공된 `examples/streamlit_app.py`가 함수 호출을 감싸고 예상 식수와 권장 조리량을 별도로 표시한다. 함수의 내부 입력 오류는 구조화 보고서지만 필수 Python 인자 생략·잘못된 keyword는 TypeError다. FastAPI에서는 이를 별도 처리해야 한다.

현재 함수는 numeric string을 거절하므로 **Pydantic 입력을 `model_dump(mode="json")`로 바꾸면 Decimal이 문자열이 되는 기본 동작에 주의**해야 한다. wrapper에서 모델을 검증한 뒤 `model_dump()`로 Python Decimal을 보존해 함수에 전달하는 방법이 맞다. 아래는 구현 제안이며 이 리뷰에서 endpoint를 생성하거나 HTTP 통합 시험한 것은 아니다.

```python
from fastapi import FastAPI
from lastplate_operation import generate_operation_plan
from lastplate_operation.schemas.operation_input import OperationInput
from lastplate_operation.schemas.operation_output import OperationOutput

app = FastAPI()

@app.post("/operation/plan", response_model=OperationOutput)
def plan(payload: OperationInput):
    return generate_operation_plan(**payload.model_dump())
```

이 방식의 구조 오류는 FastAPI validation 응답(422)이고, 도메인 결과는 OperationOutput이다. 오류 형식을 하나로 통일하려면 별도 exception handler 정책이 필요하다. 극단적 Decimal 처리도 P2-3을 먼저 보완해야 한다.

Decision에는 operation_report 전체를 전달한다. status뿐 아니라 constraints.status/checks, alerts, data_mode, source/policy, advisory flags를 확인한다. FAIL은 실행 후보에서 제외하고 UNKNOWN/누락은 보완 대상으로 둔다. NOT_CONFIGURED를 운영에서 허용할지는 별도 정책으로 확정한다. 그래프 전체 state에는 내부 모델·Decimal이 있으므로 외부에는 operation_report만 JSON으로 내보낸다.

## M. 발표에서 주장 가능한 내용

- “예측 식수와 구간, 레시피, 사용 가능 재고, 운영 정책을 받아 조리량과 발주 검수 보고서를 산출하는 결정론적 Operation 모듈을 구현했다.”
- “수율·단위 변환·재고 차감·발주 범위와 영양 입력 제약을 검사하며 계산 근거를 기록한다.”
- “실제 LangGraph 조건부 경로와 Streamlit 데모가 있고, Operation 기존 테스트 85개를 재실행해 통과했다.”
- “레시피·영양·재고 예제는 DEMO이며 실제 데이터 정규화 adapter를 연결할 수 있는 함수 입력 경계를 갖췄다.”
- “최종 승인과 실제 발주는 하지 않는 자문용 모듈이다.”

## N. 발표에서 아직 주장하면 안 되는 내용

- “Operation이 식수를 예측한다 / ML 정확도를 개선했다.”
- “공공 Recipe·Nutrition API와 실제 재고 DB를 이미 연결했다.”
- “3% 안전여유·단백질20g 등의 값이 공식 기준이다.”
- “레시피만으로 한 끼 영양·알레르기 안전성을 자동 검증한다.”
- “모든 설비 capacity, OOD, 만료 재고, 주간 재고 예약, 공급사 포장단위를 처리한다.”
- “최적 발주량을 계산해 폐기량·비용 절감 효과가 현장 검증됐다.”
- “PASS/ok면 자동 실행·최종 승인할 수 있다.”
- “이번 리뷰에서 기존 Inventory 테스트 240개와 4-Agent E2E를 재검증했다.”

## O. 다음 수정 프롬프트

별도 `LastPlate-Operation-다음수정프롬프트.md`에 바로 사용할 수 있는 작업 지시문을 제공했다. 우선순위는 Demand 적용 가능성 계약, 설비 capacity, 구매 올림 정책, ea 수량 규칙, 수치 경계, trace/출처 계약이다. 수정 후 기존 85개 테스트와 새 회귀 테스트를 함께 실행하고, 호환성 변경을 schema 버전에 반영해야 한다.

이 보고서는 코드와 합성 입력에 대한 검토 결과다. 실제 급식 운영·영양 적합성·폐기 절감 효과를 검증한 현장 시험은 아니다.
