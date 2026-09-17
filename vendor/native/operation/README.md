# v0.2.1 Alert参照 수정 기록

기준 상태: 기존161개 테스트 통과. 기존 두 테스트 파일은 v0.2.0과 바이트 동일하게 보존했습니다.
최종 결과: **180 passed**, 실패/skip 0. 신규19개는 기본 빈 evidence/trace_refs 및 Alert별 step/식재료/근거 일치, 그래프·함수 동일성을 검사합니다.

`alert()`는 keyword-only `trace_refs`를 명시적으로 받습니다. 생략하면 []이며 evidence 생략은 {}입니다. 마지막 trace나 stage/ingredient로 근거를 만들어내지 않습니다.

`add_trace()`는 trace 생성 시 ID를 반환합니다. evidence_stage는 각 발견 항목의 evidence_check trace를 만든 뒤 그 ID를 알림에 전달합니다. 요약 evidence_gate나 Demand trace를 임의로 연결하지 않습니다.

MISSING_RECIPE/DUPLICATE_RECIPE/MISSING_INVENTORY/MISSING_PLANNED_ORDER/UNMATCHED_ORDER/UNIT_MISMATCH 등 별도 관련 검사 trace를 만들지 않은 경로는 빈 trace_refs/evidence를 사용합니다. 알려진 수치 근거를 명시한 알림은 evidence를 유지하되 관련 trace가 없으면 trace_refs는 비웁니다.

발주 알림은 해당 식재료 order_review, 재고/계량 알림은 해당 식재료 inventory_offset_and_range, 준비/capacity 초과는 관련 입력을 포함한 serving_calculator, 제약 알림은 constraint_check를 참조합니다.

산술·상태 정책과 schema_version=2.0은 유지했습니다. DEMO 출력은 새 trace/Alert 구조로 재생성했습니다. 외부 API/실제 발주 변경은 없습니다.

최신 시험 기록: tests/test-results.txt 및 tests/test-results.xml. 아래 기존 v0.2.0 기록은 이전 릴리스의 검증 범위입니다.

---

# LastPlate Operation Agent v0.2.1

예측 결과·레시피·사용 가능한 원물 재고·주문안·정책으로 조리 및 구매 검토 보고서를 만드는 결정론적 모듈입니다. 숫자를 예측하거나 자연어 이벤트를 해석하지 않습니다. 외부 API 연결, 실제 발주, 메뉴 변경, 최종 승인 기능은 없습니다.

## 설치 및 실행

Python 3.11 이상. 이 폴더에서 실행합니다.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
python -m examples.demo
python -m streamlit run examples/streamlit_app.py
```

`[test]`는 Streamlit AppTest를 포함하는 **전체 suite** 의존성입니다. pytest와 Streamlit을 함께 설치하며 UI 테스트를 skip하지 않습니다. `[ui]`는 UI만 필요할 때 사용합니다. Core 설치에는 Pydantic/LangGraph가 포함됩니다.

```python
from lastplate_operation import generate_operation_plan
from lastplate_operation.tools.json_input import load_operation_json
from pathlib import Path

payload = load_operation_json(Path("examples/demo_input.json").read_text(encoding="utf-8"))
report = generate_operation_plan(**payload)
assert report["required_servings"] == 523
```

정밀한 JSON 입력에는 제공한 `load_operation_json()`을 사용하세요. 바이너리 float로 먼저 읽어 반올림된 숫자의 원래 자릿수는 복원할 수 없습니다. 이 파서는 Decimal로 읽은 후 계약 검증을 적용합니다. 함수는 JSON 숫자에 대응하는 int/float/Decimal을 받고 숫자 문자열/bool은 거절합니다. 입력 모델의 `model_dump_json()`도 숫자로 직렬화하며 재검증할 수 있습니다.

## 정상 계산과 올림 정책 선택

기본값은 **legacy_combined**입니다. 정상 fixture는 계속 `487 / 상단507 / 여유3% → 523인분`, `120g×523=62,760g`, 손실5%·재고6kg에서 **60,064g 구매, 범위60,064~63,068g**입니다. `3`은 3%로 해석합니다. 하한은 필요량 전체를 충족하고 허용오차는 상한에만 적용합니다.

```text
required_servings = max(minimum_servings, ceil(base × (1 + safety_margin_pct/100)))
base = conservative + 구간 존재이면 upper, 아니면 prediction
edible_required = 인분 × 1인분 가식량 합계
raw_required = edible_required / (1 - trim_loss_pct/100)
cooking_required = raw_required 또는 조리 계량 단위로 올림한 원물량
purchase_need = ceil_purchase(max(0, cooking_required - usable_raw_stock))
recommended_min = purchase_need
recommended_max = ceil_purchase(purchase_need × (1 + order_tolerance_pct/100))
```

| rounding_policy | 조리 계량 | 구매 올림 | 용도 |
|---|---|---|---|
| legacy_combined (기본) | quantity_quantum | 같은 quantity_quantum | v0.1.0 수량 호환; deprecated 설정 경고 |
| purchase_only | 올리지 않음 | purchase_quantum | 정확 원물량에서 재고 차감 후 구매량만 올림 |
| cooking_and_purchase | cooking_quantum | purchase_quantum | 조리 계량 한도를 따로 적용 |

새 두 정책은 `purchase_quantum`을 명시해야 합니다. 마지막 정책은 `cooking_quantum`도 필수입니다. 각 map은 g/ml/ea를 모두 받습니다. 새 정책에서 deprecated `quantity_quantum`의 기본값 이외 값을 섞으면 오류입니다. 사용되지 않는 cooking quantum도 거절합니다.

```json
{"rounding_policy":"purchase_only", "purchase_quantum":{"g":100,"ml":1,"ea":1}}
```

회귀 사례: 재고66.0632kg이면 정확 원물량66,063.157894…g을 충족하므로 purchase_only에서 **구매0g**. 조리 계량도100g이면 cooking_required=66,100g, cooking_extra≈36.842105g, 구매100g입니다. `COOKING_ROUNDING_EXTRA` alert는 조리 올림 없는 구매량과 추가 구매량을 보여줍니다. 어느 정책이 현장에 맞는지는 설비·계량 기준으로 결정해야 하며, 코드가 이를 인증하지 않습니다.

반복소수인 원물량은 내부에서 Fraction으로 정확히 계산합니다. `raw_required`는 표시용 근삿값, `raw_required_exact={numerator,denominator}`는 기본단위의 정확한 유리수입니다. 구매 경계 비교는 표시 float로 다시 계산하지 않습니다.

## Capacity와 입력 범위

`capacity_servings`는 사업장 설정이며 기본 null입니다. `required_servings`와 호환 필드 `recommended_servings`는 같은 **요구량**입니다. 설비 한도로 자르지 않습니다. `capacity_excess=max(0,required-capacity)`를 별도로 남깁니다. 초과하면 `CAPACITY_EXCEEDED`와 review, 0이나 capacity와 같은 값은 초과가 아닙니다. minimum_servings와 capacity의 충돌도 같은 규칙으로 검토합니다.

`maximum_input_servings`는 예측값·구간의 입력 적용 범위이며 기본100,000, 설정 가능 범위1~1,000,000입니다. 이를 넘으면 invalid_input입니다. 이 기술적 범위는 실제 사업장 capacity나 모델 학습 범위를 의미하지 않습니다. capacity가 없는 simulation은 경고, operation은 확인 필요입니다.

## Demand 계약

로컬 LastPlate-ML-v2 `tools/demand.py`의 반환 구조를 확인했습니다. 실제 필드인 `operational_eligible`, `availability_status`, `prediction_id`, `created_at`, `target_date`, `deadline_at`, `timezone`, `mode`, `input_data`, `availability`, `weather`, `policy`를 그 이름으로 보존합니다. 해당 코드에는 OOD schema가 없습니다.

따라서 아래 두 필드는 **Operation의 제안 확장 계약**이며 Demand 측 합의가 필요합니다. 기존 `prediction`, optional interval, `model_version`, `input_snapshot_id`도 유지합니다. native receipt에는 input_snapshot_id가 없으므로 operation 모드 연결자는 실제 입력 스냅샷 식별자를 별도로 부여해야 합니다. prediction_id를 자동으로 스냅샷 ID로 둔갑시키지 않습니다.

```json
{"applicability":{"status":"OOD","reasons":["학습 범위 밖"]},
 "warnings":[{"code":"UPSTREAM_OOD_01","category":"OOD","severity":"HIGH","message":"검토 필요"}]}
```

| 근거 상태 | 보고서 최소 상태 |
|---|---|
| IN_DOMAIN | 추가 문제 없으면 ok |
| OOD / NOT_APPLICABLE / operational_eligible=false | review |
| UNKNOWN / applicability 생략 / historical_unknown | needs_clarification |
| warning category=EVIDENCE_UNKNOWN | needs_clarification |
| warning category=OOD/NOT_APPLICABLE 또는 severity=HIGH | review |
| 그 외 INFO/MEDIUM warning | 보존하여 alert, 강제 상태 상향 없음 |

warning category는 `OOD/NOT_APPLICABLE/EVIDENCE_UNKNOWN/OTHER`, severity는 `INFO/MEDIUM/HIGH`입니다. upstream code와 message는 별도로 보존합니다. `operational_eligible=true`는 IN_DOMAIN의 증거로 자동 변환하지 않습니다. 모든 메타데이터·경고는 `source`와 `demand_source` trace에 남습니다. 미지원 필드를 없애서 통합하지 말고 계약을 확장하세요. attendance_delta 직접 가산은 거절하며 새 Demand 결과를 입력받는 방식만 유지합니다.

## 데이터 근거와 운영 모드

`data_mode=DEMO/REAL/UNSPECIFIED`는 라벨입니다. **REAL은 인증이 아닙니다.** 별도 `execution_mode=simulation/operation`이 검증 정책을 선택합니다. 기본 simulation은 기존 호출 호환용이며 실제 운영 승인이 아닙니다.

`config.provenance`는 recipe/nutrition/inventory/policy별 `{source,version,snapshot_id,meal_id}`를 받습니다. nutrition에는 `recipe_version`, `recipe_snapshot_id`도 필수입니다. 제공된 근거의 meal_id가 다르거나 nutrition→recipe 연결이 다르면 needs_clarification입니다. 수치 영양 검사에 실패한 항목은 계속 FAIL로 보존하고, 그 외에는 UNKNOWN으로 표시합니다. 버전 비교는 호출자가 선언한 식별자의 일치 검사이며 데이터 인증·영양 재계산·해시 기반 내용 검증은 아닙니다.

operation 모드에서 아래 누락은 `OPERATION_EVIDENCE_MISSING`와 needs_clarification입니다.

- policy_acknowledged=true: 유효 정책값(기본값 포함)을 운영 책임자가 확인했다는 입력 선언
- capacity_servings 및 네 종류의 provenance
- minimum_protein(g/인분), calorie_range(kcal/인분), sodium_max(mg/인분), allergy_restriction(없으면 명시적 [])
- 비어 있지 않은 minimum_serving_amount: `{식재료:{amount,unit}}`
- nutrition_per_serving의 protein/calories/sodium/allergens (없음은 명시적 [])
- Demand model_version와 input_snapshot_id

nutrition_per_serving은 **동일 레시피·식사 스냅샷 전체의 1인분 영양 총합**입니다. 필드 생략과 0을 구분합니다. 알레르겐은 정확한 이름 일치만 검사합니다. 교차오염을 판단하지 않습니다. 예제의 영양값·3% 여유·5% 허용오차 등은 DEMO/기본 정책이며 공식 영양·법정 기준이 아닙니다.

## 단위와 수치 경계

- g/kg→g, ml/l→ml, ea→ea. 차원 간 환산은 거절합니다.
- ea 주문은 낱개 구매로 정의하여 1.5ea를 거절합니다. 1인분 레시피의 0.5ea 같은 분할 사용은 허용합니다.
- ea 재고는 기본 정수이며 `fractional_ea_inventory=true`를 명시하면 분할된 사용 가능 원물 재고를 허용합니다. 구매 quantum은 여전히 정수입니다. cooking quantum의 ea는 분할 계량을 허용합니다.
- 일반 입력 수량은 0~10^9, 최대15 유효숫자·소수6자리, quantum은 0.001~1,000,000입니다. 예측값·구간·최소/예정 인분·capacity에는 별도의 1,000,000 상한이 있습니다.
- 손실률은 이번 MVP에서 0~99%로 제한합니다. 99% 초과는 v0.1.0 대비 명시적 계약 강화입니다.
- 내부 Decimal context는 외부 context와 분리합니다. DecimalException은 NUMERIC_ERROR로 구조화하고 부분 수량을 제거합니다. TypeError 등 프로그래밍 오류를 광범위하게 숨기지 않습니다.
- 계산 결과의 원물/계량/재고/구매 관련 수량이 10^12를 넘거나 정확한 가식량·재고·구매 경계가 JSON 숫자로 왕복되지 않으면 OUTPUT_PRECISION_LIMIT입니다. 반복소수 원물/계량 표시값은 exact 유리수 및 정책으로 재구성합니다.
- JSON Schema는 타입·범위·deprecated 필드를 표현합니다. 15 유효숫자, ea 정수 정책, map 완전성, 교차 필드·버전 관계는 Python 계약 검증도 실행해야 합니다. `x-max-significant-digits`는 문서용 확장 키입니다.

## 출력·Alert·상태

schema_version은 **2.0**입니다. 수량 필드 이행은 `MIGRATION.md`를 참조하세요. Alert `type`은 AlertType enum이며 UI message로 분기하지 않습니다. 각 alert는 evidence 및/또는 trace_refs를 제공하고 trace마다 `trace-0001` 형태의 보고서 내부 ID가 있습니다.

상태는 `invalid_input > needs_clarification > review > ok` 우선순위입니다. 하나의 최상위 상태로 다른 문제를 지우지 않고 모든 alerts/checks를 함께 확인합니다. ok는 계산 완료이지 승인/위험 없음이 아닙니다. OVER 같은 MEDIUM 경고가 남을 수 있습니다. OOD/capacity 경고가 있어도 비교 검토용 요구 수량은 계산합니다. 단위·필수 재료·입력 범위 오류는 조기 중단합니다.

## 역할과 연결

```text
Inventory & Risk: 만료·예약·재고 적격성 판단
     ↓ 단일 식사에 배정된 사용 가능 원물 재고
Demand 결과 → Operation → Inventory 위험 분석 / Decision
                  └──── 전체 Operation 보고서 ────┘
```

상위 계층은 여러 식사에 같은 재고를 각각 전량 차감하지 않도록 예약·분배해야 합니다. Operation은 예약, 가격, 공급위험, 만료 판단을 재구현하지 않습니다. `STOCK_SHORTAGE`는 수량 비교이며 공급 위험 예측이 아닙니다.

```python
from lastplate_operation.graph.operation_workflow import build_operation_subgraph
state = build_operation_subgraph().invoke({"payload":payload})
assert state["operation_report"] == generate_operation_plan(**payload)
# state["route"]를 상위 검토/확인 노드에 연결

from lastplate_operation.integration import to_inventory_forecast, to_decision_payload
forecast = to_inventory_forecast(
    [{"date":"2026-09-17","meal_type":"lunch","operation_report":report}],
    forecast_version="operation-0.2.0", input_snapshot_id="meal-001")
# 기존 Inventory wrapper는 forecast를 받음. 전체 메뉴 날짜/끼니 키 필요.
decision_input = to_decision_payload(report, inventory_risk_report)
```

count-only bridge는 요구 조리량을 기존 expected_max_diners에 넣는 **중간 위험 분석 연결**입니다. 일부 review/OOD/capacity 초과도 전달할 수 있으므로 최종 승인 기능이 아닙니다. invalid_input/needs_clarification 및 제약 FAIL/UNKNOWN은 거절합니다. Decision에는 반드시 전체 보고서를 보내 경고·근거를 유지하세요. `to_decision_payload`는 Risk 이벤트의 release/superseded를 변형하지 않습니다. 최신 유효 이벤트 판단은 Decision 책임입니다.

공급사별 MOQ/포장/납기는 미구현입니다. 향후 구매 어댑터가 ingredient/supplier ID, pack_size, MOQ, lead_time, availability snapshot을 검증하고 별도 procurement_constraints를 제공할 확장 지점으로 남깁니다. 이번 단위별 quantum을 공급사 계약 구현으로 해석하지 마세요.

## 산출물과 검증 범위

`MIGRATION.md`: 호환성·정책 선택. `REVIEW_REPORT.md`: 수정·시험 결과와 제한. `contracts/`: 생성 JSON Schema. `examples/`: DEMO 입력/출력과 올림 정책 사례. `evidence/`: 기준 테스트와 리뷰 출처. `tests/test-results.xml`, `tests/test-results.txt`: 최신 전체 실행 기록.

실제 현장 운영 안전성, 영양 적합성, 폐기·비용 절감 효과, 실제 Demand 모델/Decision까지의 E2E는 검증하지 않았습니다. 코드 검증과 합성 입력 시험 결과만 제공합니다.
