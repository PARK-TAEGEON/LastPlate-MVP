# LastPlate Inventory & Risk Agent

## v0.2.3 제외·해제 의도 및 residual 패치

이번 버전은 기존 규칙 파서/Agent/그래프 구조를 유지합니다. 실행 코드 수정은 제외·해제 술어, residual 검사, 이벤트 스키마의 추가 필드, trace 전달 및 기존 이벤트 ID 호환 처리입니다. UI·실제 API·Decision Agent는 변경하지 않았습니다. 아래 이전 버전 설명보다 이 절이 우선합니다.

- 제외: 쓰지 말아주세요, 사용하지 말아주세요/마세요, 빼 주세요/빼주세요, 제외해 주세요/제외해주세요/제외하고, 사용 금지/금지.
- 해제 우선: 금지 해제, 사용 금지 해제, 제외 취소, 금지 취소, 다시 사용, 사용 가능, 빼지 마세요, 제외하지 마세요. `ingredient_restriction_release_event`, `action=release_restriction`, `restriction=null`로 반환합니다.
- 충돌 정책: 입력 문자열에 명시된 순서대로, 정규화된 동일 품목·동일 date/end_date 범위에서 마지막 의도를 적용합니다. 앞선 이벤트는 `superseded=true`로 보존하고 `parsing_result.decision_trace`와 보고서 `decision_trace`에 두 의도를 기록합니다. 해제 뒤 재금지도 유지합니다. 서로 다른 날짜 범위는 덮어쓰지 않습니다. 날짜가 없으면 확인 필요 상태를 유지합니다.
- 해제는 현재 분석 안에서 해당 제한의 적용을 멈추는 자문 결과입니다. 저장된 운영 제한을 삭제하거나 사용 허가/발주/메뉴 결정을 실행하지 않습니다. 이전 대화의 상태를 저장하는 기능이나 임의 이벤트 배열 입력 API는 추가하지 않았습니다.
- residual: 제한 술어 뒤의 미처리 꼬리와 미인식 절을 검사하고, 인원/기한 절도 지원 문법 밖의 꼬리를 확인합니다. 그리고/또/또한/및/그리고요, 구두점만 남으면 무시하며 뒤의 의미 있는 요청은 partial 또는 needs_clarification로 남깁니다. 미등록 품목은 기존 warning·확인 흐름을 유지합니다.
- 날짜 없는 예문은 이벤트를 추출해도 needs_clarification입니다. 날짜·품목이 확인된 지원 표현에만 ok를 반환합니다. 전체 자연어 이해, 새로운 날짜 범위 문법, 모든 생략/대명사/복잡한 이중부정은 지원하지 않습니다. 보수적인 partial 판정이 가능합니다.

검증: 기존 192개 + 신규 48개 = 240개 통과. `RELEASE_RESIDUAL_REPORT.md`, `examples/release-test-results.xml`, `examples/release-cases.json`, `examples/release-manifest.json` 참조. 기존 테스트 파일·UI·그래프·DEMO 데이터는 v0.2.2 ZIP과 바이트 단위로 동일합니다. DEMO 출처와 자문 전용 승인 경계를 유지합니다.

## v0.2.2 연속 사용 제한 추출 패치

현재 절 분리/parser 구조를 유지하고 `tools/events.py`의 제한 표현 탐색만 보완했습니다. `RESTRICTION.finditer()`로 절 안의 모든 제한 술어를 읽고, 직전 술어 끝부터 현재 술어 앞까지의 품목을 대응시킵니다. 쉼표 품목 목록은 뒤의 공통 술어에 각각 연결합니다.

지원 예: “닭고기 쓰지 말아주세요 계란 쓰지 말아주세요”, “닭고기 쓰지 말고 계란도 쓰지 말아주세요”, “닭고기, 계란, 두부 사용하지 말아주세요”, “닭고기 금지, 계란 금지”, “닭고기는 꼭 빼주세요”. 기존 인원 복합 이벤트·별칭·공백 정규화·미등록 확인을 함께 사용합니다. 등록명 매칭 전에 `도` 등의 조사를 제거하되, 이미 등록된 이름 자체는 훼손하지 않습니다.

동일 품목·날짜·기간·제한·확인 상태·출처의 restriction은 하나로 합치고, 서로 다른 원문 표현은 `source_text`와 description에 줄바꿈으로 보존합니다. 날짜가 다르면 합치지 않습니다. 다른 이벤트 유형과 공급 이벤트의 중복 규칙은 변경하지 않았습니다.

날짜가 없는 대표 패턴도 제한 품목을 모두 추출하지만 기존 계약에 따라 needs_clarification입니다. “내일”이 명시되고 모든 품목이 등록되어 있으면 ok입니다. 미등록 목록 항목도 이벤트와 warning에 남으며, 빈 품목 등 일부 추출 실패를 ok로 반환하지 않습니다. 원문 전체의 모든 미지원 요청까지 이해한다는 보장은 아닙니다.

Graph/schema/UI/실제 API/Decision Agent는 변경하지 않았습니다. 기존 P2(문장 사이 독립된 “그리고”, 미지원 추가 요청의 완전한 검출, API timeout 구조화)는 이번 패치의 해결 범위가 아닙니다. 상세 보고와 최신 테스트 증빙은 `REPEATED_RESTRICTION_REPORT.md`, `examples/restriction-test-results.xml`에 있습니다.

## v0.2.1 P1 한정 수정

이번 패치는 복합 자연어, 등록 식재료 매칭, 주간 식단 중복 검증만 보완합니다. 그래프 노드 구조·재고/가격/영양 계산 도구와 자문 전용 경계는 유지합니다. 기존 133개 테스트는 수정하지 않았습니다. 최신 검증은 `P1_FIX_REPORT.md`와 `examples/p1-test-results.xml`을 참조하세요. 아래 v0.2.0 기록에는 이번 변경 사항을 우선 적용합니다.

### 복합 입력과 파싱 상태

`tools.events.parse_event_result()`는 `EventParseResult`를 반환합니다. 기존 `parse_event()`의 list 반환 인터페이스도 유지합니다. `추가하고`, `추가되고`, `빠지고`, `그리고`, 문장 구분자 등 지원되는 절 경계로 나누어 독립 이벤트를 추출하며 각 이벤트에 `source_text`를 남깁니다. 선행 절의 단일 날짜는 날짜가 없는 후속 절에 공유합니다. 각 절 안의 다중/충돌 날짜는 여전히 확인 대상입니다.

| parser status | 의미 |
|---|---|
| ok | 지원되는 모든 절을 파싱했고 확인할 필드가 없음 |
| partial | 이벤트를 일부 추출했으나 `unparsed_segments`가 남음 |
| needs_clarification | 날짜/숫자/등록 품목 확인이 필요하거나 모든 절이 미해석 |
| invalid_input | 비문자/빈 입력 또는 잘못된 날짜 등 정형 입력 오류 |

전체 보고서에 `parsing_result`와 `validation_warnings`를 추가했습니다. 보고서 최상위 `status`에는 `partial`이 추가됩니다. **v0.2.0 호환성을 위해 오류의 최상위 status는 `error`를 유지**하고 입력 오류는 `parsing_result.status=invalid_input`으로 구분합니다. 데이터 파일 오류에서 parsing_result는 null일 수 있습니다. `None` 이벤트는 full 분석에서 정상적인 무이벤트 입력이며, event 모드에서는 기존처럼 오류입니다.

- “내일 손님 35명 추가하고 닭고기 쓰지 말아주세요.” → 인원 + 사용 제한, 두 이벤트 모두 다음 날.
- “내일 회식으로 40명 빠지고 두부가 내일까지예요.” → 인원 -40 + 두부 기한 이벤트.
- “외부 인원 20명 추가되고 계란 쓰지 말아주세요.” → 두 이벤트 추출, 날짜가 없어 확인 필요.
- “내일 손님 35명 추가하고 냉장고 청소도 해주세요.” → partial, 미해석 절 보존, 예측 재실행 요청 차단.

미지원 복합 구문을 모두 이해한다고 주장하지 않습니다. 특히 하나의 절에 기한/사용 제한 의도가 함께 남아 분리하지 못하면 partial로 노출합니다. partial/확인 필요 입력은 event 모드의 후속 분석을 보류하며, 확인 전 인원 예측이나 operation 재실행을 권하지 않습니다. full 모드의 독립적인 재고 분석 결과도 입력이 완전하다는 뜻은 아닙니다.

### 등록 식재료 정규화

`tools/ingredients.py`에서 Unicode NFKC, 공백 제거, casefold로 정확히 대조합니다. 결과 품목은 공식 등록 데이터의 명칭을 사용합니다. `RiskConfig.ingredient_aliases`에 계란↔달걀 등의 명시적 별칭을 설정할 수 있습니다. 별칭의 기준 품목이 데이터에 없으면 별칭만으로 등록된 것으로 처리하지 않습니다. 유사도 기반 자동 선택은 없습니다.

식재료 의도가 있는 입력은 inventory, recipe, weekly_menu의 등록 목록을 합쳐 확인합니다. `matched_sources`에 확인된 출처를 기록합니다. 인원 전용 입력은 기존처럼 재고 읽기를 생략합니다. 등록되지 않은 품목은 이벤트에 `reason=unregistered_ingredient`와 `needs_clarification=true`, 보고서에 해당 validation warning을 남깁니다. 서로 다른 등록 명칭이 동일 정규화 키에 충돌하면 임의로 택하지 않고 확인 요청을 반환합니다.

### 식단 중복 정책

현재 한 행은 한 메뉴의 식재료 기여량입니다. 따라서 키는 **(date, meal_type, menu_name, ingredient)**이며 menu_name만으로 합치지 않습니다. 같은 메뉴의 두부와 간장 행은 정상입니다. 날짜/끼니가 다르면 별도 제공입니다.

- 같은 키와 모든 값이 같은 중복은 분석 메모리에서 첫 행만 유지합니다. `duplicate_menu_rows` HIGH alert 및 validation warning에 제외 행 수, key, 원본/중복 행 번호, 파일을 기록합니다.
- 같은 키이지만 serving_amount·unit·식수 등 값이 다르면 합산/삭제를 추정하지 않고 DataQualityError를 반환합니다.
- 현재 `Menu` schema에는 target_group이 없습니다. 값이 있는 target_group 컬럼은 조용히 무시하지 않고 명시적 오류로 반환합니다. 배식 대상 구분을 수용하는 schema 확장은 이번 패치에서 하지 않았습니다.
- 원본 Excel을 쓰거나 덮어쓰지 않습니다. `get_validation_warnings()`는 선택적인 adapter 진단 메서드이며 기존 adapter에는 없어도 됩니다. 예측 주입 wrapper는 진단을 전달합니다.

Decision Agent/MVP는 `partial`도 처리하고, `parsing_result.unparsed_segments`, `matched_sources`, `validation_warnings`를 표시해야 합니다. 실제 예측/운영 재실행의 허용 여부는 기존 `recheck_status`를 계속 확인하세요. 최종 결정 필드는 추가하지 않았습니다.

## v0.2.0 리뷰 수정

**자문 전용 경계는 유지됩니다.** 메뉴·발주 변경, 승인, 자동 반영, 수요 예측 실행은 추가하지 않았습니다. 보고서 계약은 `schema_version="2.0"`입니다. 수정 파일 및 검증 증빙은 `REVISION_REPORT.md`, 기계 판독 테스트 결과는 `examples/test-results.xml`을 확인하세요.

### Alert 계약과 이름 변경

모든 alert는 `schemas/alert.py`의 `Alert`로 검증되며 `type`, `severity`, `message`, 비어 있지 않은 `evidence`가 필수입니다. `config.py`의 `severity_policy`, 가격 임계값, `expiry_high_days`에서 내부 판정 정책을 관리합니다. 공급 이벤트의 severity는 입력 관측값을 보존합니다. 상세 가격/재고 정보는 `details`에 둡니다.

| 이전 이름 | v2 canonical 이름 |
|---|---|
| excess_inventory | overstock |
| excess_order | over_order |
| price_anomaly | price_risk |
| menu_restriction_conflict | menu_conflict |
| nutrition_constraint_violation | nutrition_violation |

`expiry_risk`, `low_stock`, `ingredient_shortage`, `insufficient_order`, `supply_risk`는 유지합니다. Alert 모델은 위 이전 이름도 받아 canonical 이름으로 정규화합니다. 기존 UI가 `type`으로 분기한다면 위 매핑을 적용해야 합니다.

### 재고 → 영향 → 후보

FEFO 감사 기록에 날짜·끼니·메뉴·재료별 소요량, 배분 lot, 부족량을 남깁니다. 재고 부족은 `inventory_shortage_event`와 `affected_menus[].cause_event_id`를 만들고 대체 메뉴 검토로 연결됩니다. 유통기한은 `inventory_expiry_event` impact를 만들며, 기한 내 기존 메뉴에 실제 FEFO 배분 가능한 물량만 별도 `priority_use_candidates`로 반환합니다. 이 후보도 `requires_approval=true`이며 원본 재고는 변경하지 않습니다. 이미 만료됐거나 제공일 전에 만료되는 lot은 우선 사용 후보가 될 수 없습니다.

모든 대체 후보·영양 검증·비용 비교는 `cause_event_ids`를 보존합니다. 동일 메뉴 후보가 부족·공급 등 여러 원인에서 생성되면 원인 ID를 합칩니다. 공급 중복 제거 키는 이벤트 내용(유형·식재료·기간·severity·출처·설명 등)의 정규 JSON 해시이며 전달된 `event_id`는 키 계산에서 제외합니다. 순서와 재실행에 안정적이며 서로 다른 출처/설명은 독립 관측으로 남깁니다.

### 가격 판정

`weekly_direction`, `monthly_direction`, `triggered_rules`를 독립적으로 반환합니다. 주간 방향의 구형 호환 필드 `direction`도 유지하지만 routing에는 쓰지 않습니다. 주간 또는 월별 **상승 규칙**이 발동하면 영향 분석으로 연결합니다. 주간 -4.7619%, 월별 +100% 사례에서는 `triggered_rules=["monthly_increase"]`로 대체 검토가 실행됩니다. 하락 위험은 보고하지만 하락만으로 대체 후보를 생성하지 않습니다.

### 전체 분석과 이벤트 재분석

`state["mode"]`는 `full`(기본) 또는 `event`입니다. LangGraph의 실제 `add_conditional_edges`로 다음 경로를 선택합니다.

| 입력 | 선택 실행 | 생략 |
|---|---|---|
| full | parser → 재고 → 가격 → 공급 → 영향 → 후보 → 영양 → report | 영향/후보가 없으면 관련 후속 단계 |
| event + 확인된 인원 | parser → report | 모든 분석 도구; 예측 **요청 정보**만 반환 |
| event + 모호한/다중 날짜/미해석 입력 | parser → report | 분석 도구; 확인 필요 상태 |
| event + 가격 | full의 분석 경로 | 영향/후보가 없는 후속 단계 |
| event + 공급/사용 제한/유통기한 | parser → 재고 → 공급 → 영향 → 후보 → 영양 → report | 가격 이상탐지 노드 |
| 정형 입력/데이터 오류 | 오류 지점 → error report | 남은 분석 노드 |

공급 노드는 대체 후보 안전성 검토를 위해 이벤트 재분석에서도 읽습니다. 가격 이상탐지 노드가 생략되어도 후보 비용 도구는 최신 단가를 읽을 수 있습니다. 영향이 없으면 후보/영양 노드를, 후보가 없으면 영양 노드를 실제로 실행하지 않습니다. `execution.executed_nodes`, `skipped_nodes`, 동적 `SKIP` trace로 확인할 수 있습니다.

이벤트 보고서는 **이벤트 범위의 새 보고서**입니다. 이전 보고서의 일부 값을 재사용하거나 합치지 않습니다. 생략 필드의 빈 목록을 “위험 없음”으로 해석하지 마세요. 전체 현황이 필요하거나 새 수요 예측 결과를 받았다면 `full`로 다시 분석합니다.

### 확인과 오류 계약

“내일 사람이 좀 많이 올 것 같아요.”는 `attendance_event`, 다음 날 날짜, `attendance_delta=null`, `needs_clarification=true`입니다. `recommended_rechecks`에 demand_forecast를 넣지 않고 `recheck_status.demand_forecast`를 `blocked_clarification`, `execute_allowed=false`, `executed=false`로 반환합니다. 숫자와 날짜가 확인된 이벤트에만 `requested`를 반환합니다. 어느 경로에서도 예측 도구를 실행하지 않습니다.

`attendance_delta`는 `StrictInt`로 bool/실수/숫자 문자열을 거부합니다. 자연어 숫자가 없는 경우 추정하지 않습니다. 다중 날짜는 같은 날짜 반복도 확인 대상으로 처리하며 자연어에서 기간을 추론하지 않습니다. 기간 지정은 구조화 이벤트의 `date`/`end_date`로 전달하세요. 잘못된 날짜는 `errors[].code=input_validation_error`로 반환합니다.

CSV/Excel의 빈 파일·누락 컬럼·형식/손상 오류는 `DataQualityError`로 통일합니다. `detail`에는 `code`, `message`, `file`, `row`(1-based, 헤더=1), `field`가 있습니다. 파일/헤더 오류는 행 1, 데이터가 전혀 없으면 행 2를 사용합니다. 직접 adapter 생성 시 이 예외를 받고, 분석 함수 내부/Streamlit 경계에서는 `status="error"` 및 `errors` 목록으로 반환합니다. 오류 시 자동 DEMO 대체가 없습니다. 빈 공급 이벤트 목록은 실제 adapter의 `[]`로 표현할 수 있지만 헤더만 있는 DEMO 파일은 잘못된 파일로 취급합니다.

보고서는 모든 경로에서 `period`, `forecast_version`, `input_snapshot_id`, `clarification`, `recheck_status`, `execution`, `errors`를 포함합니다. 기준일 자체가 잘못되면 `as_of=null`, 기간은 null입니다. 권위 있는 snapshot ID를 제공하지 않으면 관측 입력을 해시한 ID를 생성하며, 외부 데이터 전체의 불변 snapshot을 보장하지는 않습니다.

### 통합 예시

```python
# 이미 수요 예측 도구가 산출한 결과를 분석 전용 메뉴 snapshot에 주입
from examples.forecast_wrapper import analyze_with_forecast

report = analyze_with_forecast(adapters, {"as_of":"2026-09-17"}, {
    "forecast_version":"forecast-v2",
    "input_snapshot_id":"snapshot-42",
    "rows":[
        # 실제 예측값을 각 날짜/끼니별로 전달; 모든 원본 메뉴 끼니가 필요
        {"date":"2026-09-18", "meal_type":"lunch", "expected_max_diners":135},
        # 나머지 날짜/끼니를 생략하면 정형 오류로 반환
    ],
})
```

`ForecastInventoryAdapter`는 원본을 복제하고 식수만 분석용으로 주입합니다. 누락 끼니·중복 끼니·bool/음수 식수를 거부합니다. 실제 예측 호출이나 운영 DB 변경은 없습니다.

```sh
python -m pip install -e ".[test,ui]"
python -m streamlit run examples/streamlit_app.py
```

Streamlit 예시는 입력 검증, 정형 오류, 확인 상태, DEMO 출처, 재실행 상태, 실제 실행/생략 trace와 후보 표를 표시합니다. `validated_analysis(..., adapter_factory=...)`는 adapter 초기화 오류도 처리합니다. 앱은 DEMO 전용 예시이며 실제 API adapter·공식 영양 기준·운영 승인 화면은 구현하지 않았습니다. 공식 참고: [conditional edges](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges), [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest).

**DEMO / SIMULATION — 실제 공공 API는 호출하지 않습니다.** 로컬 Excel·CSV로 실행되는 독립적인 Python/LangGraph subgraph입니다. Python 3.11 이상이 필요합니다.

## 책임 경계

| Inventory & Risk Agent | Decision Agent / 운영자 |
|---|---|
| 재고·유통기한·가격·공급 이상 계산 | 최종 운영안 선택과 승인 |
| 영향받는 날짜·끼니·메뉴·식재료 검색 | 메뉴 변경 적용 |
| 대체 메뉴 후보와 영양·재고·비용 검증 결과 제공 | 발주량 변경과 발주 실행 |
| `attendance_event` 및 `demand_forecast` 재실행 요청 전달 | 수요 예측 도구 실행 후 결과 반영 |

`final_decision` 필드는 없습니다. `RiskReport`는 추가 최상위 필드를 거부합니다. 재고·식단 원본을 변경하는 API, 발주 실행 API, 식수 예측 기능은 없습니다. `eligible_for_review`도 승인이나 실행 지시가 아닙니다.

## 실행

프로젝트 루트에서 실행합니다.

```sh
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
python demo.py --as-of 2026-09-17 --event "내일 외부 손님 35명 추가됩니다." --output examples/demo_report.json --html examples/demo_report.html
```

HTML 보고서는 브라우저에서 직접 열 수 있으며 외부 서비스가 필요 없습니다. 화면에 DEMO/SIMULATION 및 최종 결정 없음이 표시됩니다. `examples/demo_report.json`은 Decision Agent에 전달할 실제 실행 예시입니다. 테스트에 사용한 정확한 의존성은 `requirements-tested.txt`에 기록했습니다.

## 호출 인터페이스

```python
from agents.inventory_risk import analyze_inventory_and_risk

report = analyze_inventory_and_risk(
    {
        "as_of": "2026-09-17",              # 반드시 명시, 날짜 재현성
        "horizon_start": "2026-09-17",      # 기본 as_of
        "horizon_end": "2026-09-24",        # 기본 start + 7일, 양끝 포함
        "prohibited_allergens": ["밀"],      # 운영자가 선언한 제외 목록
    },
    user_event="내일 닭고기 쓰지 말아주세요.",
)
assert report["advisory_only"] is True
```

출력에는 요청된 `inventory_status`, `detected_events`, `alerts`, `price_risks`, `supply_risks`, `affected_menus`, `affected_ingredients`, `substitute_candidates`, `nutrition_results`, `cost_impacts`, `recommended_rechecks`, `decision_trace`, `data_sources`가 포함됩니다. 추가 메타데이터는 스키마 버전·기준일·자문 전용 표시·한계입니다. 가격·영양·재고 계산은 모두 Python 함수가 수행하며 LLM 호출이 없습니다.

인원 입력은 일정의 `expected_max_diners`를 수정하지 않습니다. 기존 인원을 기준으로 분석하고 `demand_forecast` 재실행 요청만 전달합니다. 예측 도구를 다시 실행한 후 갱신된 식단 adapter로 재분석해야 합니다.

구조화 이벤트도 받습니다.

```python
event = {
    "event_type": "ingredient_restriction_event",
    "ingredient": "닭고기",
    "restriction": "do_not_use",
    "date": "2026-09-18",
    "end_date": "2026-09-18",
    "severity": "HIGH",
    "source_type": "operator",
}
```

한국어 파서는 명시된 식재료명·오늘/내일/ISO 날짜·정수 인원 증감·사용 제한·유통기한의 제한된 문법입니다. 날짜 미지정, 모호한 수치, 범위, 미지원 문장은 `needs_clarification`으로 전달하며 임의로 수치를 추정하지 않습니다. 사용 제한은 해당 날짜 구간에만 적용합니다. 유통기한 입력은 분석 스냅샷에서 기존 기한을 앞당길 수 있지만 원본을 변경하거나 기존 기한을 연장하지 않습니다.

## 분석 방식

- **재고:** g/kg를 g로 통일하고 제공일 순서·FEFO(빠른 유통기한 우선)로 배분합니다. 제공일까지 유효하지 않은 lot은 제외합니다. 임박/만료/최소재고 미달/필요량 부족/과다재고/장기 미사용/발주 과다·부족을 탐지합니다. 같은 이름의 메뉴라도 날짜·끼니별 제공량을 구분합니다.
- **발주:** 예정 발주는 수량 비교에만 사용합니다. 입고일 미확인으로 가용 재고에 합산하지 않습니다. 식재료별 최소재고·예정발주 값은 lot 행을 합산하므로 동일 값을 여러 lot에 중복 입력하지 마세요.
- **가격:** `(현재가 - 과거 1~4주 평균) / 평균 × 100`. DEMO 경고 10%, HIGH 20%이며 급락도 탐지합니다. 월별 장기 평균 대비 편차 및 관측 범위 이탈도 반환합니다. 같은 달 과거 관측이 2개 이상이면 역사적 범위와 비교하며 계절성 원인을 확정하지 않습니다. 과거 월만 사용하고 기준일 이후 가격은 읽지 않습니다. 누락/오래된 가격은 경고하고 비용을 `null`로 반환합니다.
- **공급:** SIMULATION 이벤트의 시작일·종료일과 분석 구간의 겹침을 확인합니다. 재고와 예정발주 수량을 함께 보고합니다. 공급 위험만으로 보유 재고의 사용을 금지하지 않습니다.
- **영향:** 주간 식단 재료와 레시피 catalog를 연결합니다. 식단의 제공량이 우선이며 catalog에만 있는 재료는 보완합니다.
- **후보:** 같은 `category`의 대체 메뉴를 탐색합니다. 영향을 받은 재료, 제공일의 금지 재료, HIGH 공급위험 재료를 포함하는 후보는 제외합니다. 이 MVP는 검증 가능한 메뉴 단위 대체를 구현하며 임의 식재료 치환은 하지 않습니다.
- **영양:** Nutrition Tool에서 제공량 비례 합산. 최소 단백질·열량 범위·나트륨 상한·최소 제공량·지방 상한과 원메뉴 대비 단백질/열량/지방 차이를 검사합니다. 탄수화물도 합계와 차이에 포함합니다. 누락 영양·알레르기 데이터는 UNKNOWN, 제약 위반은 FAIL입니다. FAIL 후보도 위반 사유와 함께 보고하여 검토가 가능합니다.
- **후보 재고:** 다른 모든 기존 메뉴를 먼저 예약한 후 해당 후보 하나의 제공일별 재고를 확인합니다. 후보마다 독립 계산하므로 여러 후보를 동시에 선택할 때는 다시 배분해야 합니다.
- **비용:** 모든 재료의 최신 단가로 1인분과 기존 최대 인원 전체의 차이를 계산합니다. KRW 기준 구매 대체가치 추정이며 인건비·배송비·폐기비·실제 현금 지출은 아닙니다.

`config.py`의 영양 수치는 **단일 메뉴의 DEMO 검증값**으로 실제 법령·급식기관 기준이 아닙니다. 전체 한 끼의 영양 균형을 보증하지 않습니다. 실제 기관 적용 시 전체 식단 맥락과 승인된 기준을 추가해야 합니다. 알레르기 목록이 비어 있으면 선언된 금지 항목이 없다는 뜻이며 모든 사람에게 안전하다는 뜻이 아닙니다.

## 데이터 7개

`data/demo/`의 모든 값은 합성 DEMO 데이터입니다. Excel의 데이터 시트명은 `DEMO`, 첫 행은 영문 필드명입니다. 날짜는 Excel 날짜형, 수량과 영양값은 숫자형입니다.

| 파일 | 의미 |
|---|---|
| `weekly_menu.xlsx` | 날짜·끼니·메뉴·재료별 1인 제공량, 최대 식수. 영양 열은 해당 재료의 제공량에 대한 값이며 계산의 원천은 NutritionAdapter |
| `food_inventory.xlsx` | 재고 lot별 수량·기한·단가·최소재고·예정발주·보관·최종사용일 |
| `demo_recipe_ingredients.csv` | 메뉴 재료 구성, 제공량, 메뉴 분류 |
| `demo_nutrition.csv` | 100g 기준 영양, `allergens`는 `\|` 구분; 빈 문자열은 DEMO상 알려진 알레르기 없음 |
| `demo_price_trend.csv` | kg당 KRW 현재가 및 1~4주 전 가격 |
| `demo_monthly_price.csv` | kg당 KRW 월별 평균과 과거 동일 월 관측 |
| `demo_risk_events.csv` | 조류인플루엔자 공급위험 SIMULATION, 명시된 활성 구간 |

두부는 D-1 8kg lot과 이후 기한 30kg lot을 나누어 임박 재고 사용과 다음 주 대체 가능성을 함께 확인합니다. 계란은 5,000 → 6,100원/kg으로 정확히 +22%입니다. 계란찜·계란말이는 다음 주, 닭갈비는 내일과 다음 주에 배치되어 날짜 제한도 테스트합니다. 저단백 버섯볶음·고나트륨 두부 메뉴는 영양 실패를 확인하는 의도적인 DEMO 후보입니다.

## Adapter 교체

Agent는 파일명이나 CSV parser를 참조하지 않습니다. `AdapterBundle`에 같은 Protocol을 구현하는 객체를 주입합니다.

| 인터페이스 | 메서드 / 정규화 반환형 | 향후 구현명 |
|---|---|---|
| RecipeAdapter | `get_recipe(menu_name) -> Recipe 또는 None`, `list_recipes() -> list[Recipe]` | MafraRecipeAdapter |
| NutritionAdapter | `get_nutrition(ingredient) -> Nutrition 또는 None` | FoodNutritionApiAdapter |
| PriceTrendAdapter | `get_price_trend(ingredient, as_of) -> PriceTrend 또는 None` | KamisPriceTrendAdapter |
| MonthlyPriceAdapter | `get_monthly_history(ingredient, as_of) -> list[MonthlyPrice]` | KamisMonthlyPriceAdapter |
| InventoryAdapter | `get_inventory() -> list[InventoryLot]`, `get_weekly_menu() -> list[Menu]` | LastPlate의 저장소 adapter |
| SupplyRiskAdapter | `get_events(as_of, horizon_end) -> list[Event]` | 검증된 운영자 이벤트 저장소 |

모델은 `schemas/models.py`, 이벤트는 `schemas/event.py`를 따릅니다. 모든 adapter는 `source`를 제공하고 InventoryAdapter는 `menu_source`도 제공합니다. 파일 I/O는 DEMO adapter에만 있습니다. 오류는 호출자에게 전달하며 실제 API 장애를 DEMO 데이터로 자동 대체하지 않습니다.

```python
from adapters.bundle import AdapterBundle
from config import RiskConfig

# 아래 객체는 실제 API 계약을 확인한 뒤 구현하여 주입합니다.
adapters = AdapterBundle(
    recipe=mafra_recipe_adapter,
    nutrition=food_nutrition_adapter,
    price_trend=kamis_trend_adapter,
    monthly_price=kamis_monthly_adapter,
    inventory=lastplate_inventory_adapter,
    supply_risk=operator_event_adapter,
)
report = analyze_inventory_and_risk({
    "as_of":"2026-09-17", "adapters":adapters,
    "config":RiskConfig(price_alert_medium=12,price_alert_high=25),
})
```

실제 서비스 연결 절차:

1. **농림수산식품교육문화정보원 레시피 재료정보:** 발급받은 API의 실제 응답 명세 확인 → 레시피 ID/메뉴명/재료명/제공량 매핑. 메뉴 분류는 별도 curated taxonomy로 보완합니다. 전체 후보 목록은 pagination 또는 캐시로 제공합니다.
2. **식품영양성분 DB:** 기관·제품·조리상태·가식부 기준을 선택하고 `serving_basis` g, 열량 kcal, 단백질·탄수화물·지방 g, 나트륨 mg로 변환합니다. 해당 API에 없는 알레르기 정보는 검증된 별도 자료와 결합하고 확인 불가 시 `None`으로 반환합니다.
3. **aT 가격 추이:** 품목코드·품종·등급·지역·도소매 구분·통화를 고정한 뒤 현재 및 1~4주 값을 같은 g/kg 단위로 변환합니다. 결측을 0으로 채우지 않습니다. kg로 변환할 수 없는 개수/묶음은 검증된 중량 없이는 거부합니다.
4. **aT 월별 소매가격:** 동일 품목·등급·지역·가격 종류를 단기 가격과 맞추고 과거 월별 기록을 정규화합니다. 미래 관측을 제외합니다.
5. 인증키는 환경변수 또는 secret manager에서 읽고 로그에 출력하지 않습니다. timeout·제한된 재시도·rate limit·캐시·조회시각·출처 식별자를 adapter에 추가합니다. `source`에는 서비스명, dataset/version 및 기준시각을 기록합니다.
6. 실제 응답 fixture로 adapter 계약 테스트를 추가합니다. 기존 Agent 테스트와 비교하고 기관 영양 기준 및 품목명 정규화 규칙을 승인한 뒤 운영 연동합니다.

위 실제 adapter 클래스 및 HTTP 호출은 **아직 구현하지 않았습니다**. 알려지지 않은 endpoint나 인증 방식은 가정하지 않았습니다. DEMO source 문자열은 실제 adapter가 전달한 출처로 자동 교체됩니다.

## LangGraph 결합

```text
Input → Event Parser → Inventory Analyzer → Price Risk Analyzer
      → Supply Risk Analyzer → Impact Analyzer
      → Substitute Candidate Generator → Nutrition Constraint Checker
      → Risk Report Builder → report
```

```python
from graph.inventory_risk_workflow import build_inventory_risk_subgraph
subgraph = build_inventory_risk_subgraph(adapters, RiskConfig())
result = subgraph.invoke({"request":{"as_of":"2026-09-17"},"user_event":event})
decision_input = result["report"]
```

부모 그래프와 `request`, `user_event`, `report` 채널을 공유하면 `parent.add_node("inventory_risk", subgraph)`로 붙일 수 있습니다. 다른 부모 상태 스키마는 wrapper node에서 입력·보고서 채널을 명시적으로 매핑합니다. 부모 그래프 결합은 테스트에 포함됩니다. 내부 레시피 키는 tuple이므로 영속 체크포인터를 추가할 때 serializer와 상태 정규화 계약을 별도 검증하세요. 공식 API 참고: [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph).

## 구성 및 테스트

`agents/` 단계 로직, `graph/` 연결, `schemas/` 계약, `adapters/` 외부 데이터 경계, `tools/` 순수 계산, `tests/` 실행 검증으로 분리되어 있습니다. 요청된 5개 사례 외에도 날짜 범위, 모호한 인원, 유통기한, 재고 이중 사용, 영양 누락, 알레르기, 가격 급락/오래된 가격, 데이터 교체, 부모 그래프 결합을 검증합니다.
