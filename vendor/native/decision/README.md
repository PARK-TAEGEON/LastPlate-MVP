# LastPlate Decision Agent v0.1.3

v0.1.3은 InventoryUse의 ingredient/unit을 필수·공백 제거 후 비어 있지 않은 문자열로 검증하는 한정 패치입니다. 누락/null/빈 값은 ValidationError이며, 메뉴 대체 Candidate의 ingredient는 선택적으로 유지합니다. [이번 변경 요약 및 163개 테스트 결과](RELEASE_SUMMARY.md)를 먼저 확인하세요. 아래 v0.1.2 의존·confidence 계약은 유지됩니다.

범위가 일치하는 상위 Agent의 근거만 종합하는 **권고·승인 계층**입니다. 현재 계획과 탈락 대안을 분리하며, 날짜·끼니·메뉴·식재료 범위 또는 provenance가 불명확하면 보류합니다. 발주, 메뉴 변경, 재고 차감, ERP 실행 기능은 없습니다.

## 설치와 실행

Python 3.11 이상. 압축을 푼 프로젝트 폴더에서:

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[ui]"
python -m unittest discover -s tests -v
python -m examples.demo
streamlit run examples/streamlit_app.py
```

`lastplate_decision`만 배포 패키지로 설치합니다. 상위 프로젝트의 `agents`, `schemas`, `graph`, `config`, `tools`, `adapters`를 덮어쓰지 않습니다. 예제·테스트는 소스 폴더에서 실행하세요.

## 직접 호출

```python
from lastplate_decision import make_final_recommendation
from lastplate_decision.adapters import adapt_inventory_v020, adapt_ml_v2

report = make_final_recommendation(
    demand_result=adapt_ml_v2(ml_output, provenance=recorded_ml_context),
    operation_result=operation_output,
    inventory_risk_result=adapt_inventory_v020(risk_output, provenance=recorded_risk_context),
    user_events=[],
    input_revision="authoritative-input-revision",
)
```

`recorded_*_context`는 실제 호출에 사용한 입력과 분석 범위를 기록한 **부모 서비스 메타데이터**입니다. 예측 결과만 보고 날짜·끼니·메뉴 목록·입력 revision을 임의 채우지 마세요. 누락을 보충하지 않고 호출하면 정상적으로 보류됩니다. ML 모델 버전은 prediction_id가 아니고, Inventory의 as_of는 급식 대상 날짜가 아닙니다.

## 현재 계획·근거 계약

현재 운영안은 `operation_result.current_plan`에 명시합니다.

```json
{
  "target_date": "2026-09-18",
  "meal_type": "lunch",
  "coverage": "full",
  "menus_complete": true,
  "menus": [
    {"menu": "두부조림", "ingredients": ["두부"], "ingredients_complete": true}
  ]
}
```

위 목록은 **스키마 예시**입니다. 실제 레시피에는 모든 식재료를 기록해야 합니다. 알레르기 항목을 이름이나 메뉴 문자열에서 추정하지 않습니다.

각 Agent는 실제 provenance를 반환합니다. 다음 consumed_results는 **Operation용 예시**입니다. Demand는 비어 있고, 독립 Inventory도 비어 있습니다. Demand 기반 Inventory만 demand_forecast를 선언합니다. [초기/재실행 의존 정책](docs/DEPENDENCY_POLICY.md)을 따르세요.

```json
{
  "target_date": "2026-09-18",
  "prediction_id": "stored-prediction-id",
  "input_revision": "authoritative-input-revision",
  "result_revision": "agent-specific-result-revision",
  "analysis_scope": {
    "target_date": "2026-09-18", "meal_type": "lunch", "coverage": "full",
    "menus_complete": true,
    "menus": [{"menu": "두부조림", "ingredients": ["두부"], "ingredients_complete": true}]
  },
  "consumed_results": {"demand_forecast": "demand-result-revision", "inventory_risk": "inventory-result-revision"},
  "metadata_source": "parent-service-execution-record"
}
```

`input_revision`은 함수에 전달한 공통 요청 revision과 세 Agent 모두 일치해야 합니다. 날짜·prediction_id·분석 범위도 일치해야 합니다. result_revision은 Agent마다 다르며, **초기/직접 호출부터** 필요한 소비 의존 revision이 일치해야 합니다. 재실행 완료를 증명할 때는 결과 revision이 이전 결과와 달라야 합니다. 운영안/분석 메뉴 순서는 의미에 영향을 주지 않습니다.

Demand는 `mode=operation`, `operational_eligible=true`, `availability_status=validated_declared_receipts`를 모두 충족해야 운영 권고에 사용됩니다. demo/replay/historical_unknown은 LOW 및 보류입니다. MAE는 보존만 하며 부족 확률이나 신뢰구간으로 변환하지 않습니다.

## Scoped Hard Constraint

Alert/Nutrition/Risk의 `scope`에 target_date, end_date, meal_type, menu, ingredient, candidate_id를 제공할 수 있습니다. 기존 ingredient/menu/candidate_id 필드도 해석합니다.

- 현재 서비스의 날짜·끼니와 메뉴/식재료가 일치하는 allergy 등 제약 위반은 현재 계획을 BLOCK합니다.
- 명시적으로 다른 날짜·끼니·메뉴·식재료·후보이면 현재 계획에는 적용하지 않습니다.
- 범위를 판정할 수 없으면 UNKNOWN → NEEDS_CONFIRMATION입니다. 단순히 HIGH라고 전부 차단하지 않습니다.
- 범위 없는 전체 적용은 `scope.applies_to_all=true`로 명시합니다.
- Report의 검증된 analysis_scope가 날짜·끼니의 기본 문맥입니다. ingredient/menu 정보가 없는 무범위 hard alert는 확인 대상입니다.
- 식품 안전·영양 등의 FAIL은 비용 점수보다 우선합니다. 정책 priorities를 바꿔도 Hard Constraint는 해제되지 않습니다.

`selected_action_ids`는 승인 대상인 현재 계획과 해당 범위에서 검증을 통과한 조정만 포함합니다. 독립 대체 후보는 자동 선택하지 않으며 `candidate_evaluations`, `rejected_candidate_ids`로 분리합니다. 후보만 탈락했다는 이유로 안전한 현재 계획을 승인 불가로 만들지 않습니다.

## 재실행과 LangGraph

```python
from lastplate_decision.graph.decision_workflow import build_decision_workflow
from langgraph.types import Command

app = build_decision_workflow({
    "demand_forecast": demand_callback,
    "inventory_risk": inventory_callback,
    "operation_agent": operation_callback,  # operation 별칭 지원
})
config = {"configurable": {"thread_id": "review-session-123"}, "recursion_limit": 100}
state = app.invoke({"payload": canonical_input}, config)
state = app.invoke(Command(resume={
    "choice": "approve",
    "operator_id": authenticated_operator_id,
    "recommendation_revision": state["recommendation"]["recommendation_revision"],
}), config)
```

현재 **실제 Operation 구현은 제공되지 않았습니다**. 위 이름들은 사용자가 연결할 callback이며 구현이 완료된 것으로 주장하지 않습니다. `adapt_operation_contract()`는 검증 전용 어댑터입니다.

callback은 전체 payload와 `_decision_context.recheck_requests`를 받으며 해당 Agent의 완전한 canonical 결과를 반환합니다. 읽기·계산 전용이고 멱등적이어야 합니다. 같은 결과를 단순 재전송하는 것은 fresh completion이 아닙니다.

재실행 요청은 request_id, agent, reason, input_revision, source_result_revision, baseline_result_revision, result_revision, status, attempts, required_dependencies를 포함합니다. `recommended_rechecks`에는 미해결 요청만, `recheck_history`에는 완료 요청도 남습니다.

- 정상 완료: callback 성공 + 새 결과 revision + 공통 입력·예측 ID·날짜·범위 일치 + 새 의존 결과 소비 근거. 단순 `completed` 주장은 신뢰하지 않습니다.
- 실패·옛 결과·의존 결과 미반영은 failed/stale로 유지합니다.
- 동일 Inventory 보고서가 같은 operation 요청 문자열을 계속 보유해도 완료 ledger가 중복 요청을 해소합니다. 새 Inventory revision이면 새 요청입니다.
- 재검증에서 Demand·Inventory·Operation이 함께 필요하면 **Demand→Inventory→Operation** 순서입니다. 가격·공급 이벤트도 Inventory→Operation입니다.
- 기본 상한은 2회 재검증 라운드이며 미해결 상태로 운영자에게 돌아갑니다. 상한이나 콜백 미연결로 요청을 삭제하지 않습니다.
- 이벤트 반영은 applied_event_ids도 확인합니다. ID는 불변이고 고유해야 합니다. 상위 결과의 `detected_events`는 보존하며 사용자의 요청 이벤트와 자동으로 합쳐 재실행 루프를 만들지 않습니다.

`workflow_trace`는 route, callback 시작/성공/실패/미연결, 요청/완료/실패/오래된 결과/상한, Decision 결과, 승인 대기/승인/수정/거절을 누적합니다. 같은 run_id와 권고 revision으로 연결하고 상위 문자열 trace도 원문으로 보존합니다. 수정 이후에도 이전 trace를 초기화하지 않습니다.

## 승인과 Streamlit

승인은 실행이 아니라 의사 기록입니다. `approve`는 status=ok인 **최신 recommendation_revision**만 받습니다. `modify`는 revised_input 전체를 다시 검증하고 새 권고·승인 대기로 돌아갑니다. `reject`는 거절을 기록합니다. `executed`는 항상 false입니다.

`recommendation.approval_status`는 생성 당시 pending 스냅샷입니다. **최신 상태는 `state.approval`**입니다. `approval_history`는 전체 응답 기록입니다.

예제 UI는 critical alerts, DEMO/SIMULATION, null 인분(보류), 검증 오류, 미해결 요청과 제외 후보를 표시합니다. 그래프·checkpointer·thread_id를 session_state에 저장하며 JSON을 편집한 뒤 이전 결과를 승인하지 못하게 합니다. 운영 적용 버튼 대신 승인 의사 기록 기능만 제공합니다.

InMemorySaver와 Streamlit 세션은 영속 저장/인증을 제공하지 않습니다. 프로세스 재시작 복구, 인증·권한, 다중 운영자 잠금, 서버의 provenance 검증은 미연결 범위입니다.

## 검증·제출 문서

- [v0.1.3 패치 요약](RELEASE_SUMMARY.md)
- [초기/재실행 의존 정책](docs/DEPENDENCY_POLICY.md)
- [confidence 정책 및 예시](docs/CONFIDENCE_POLICY.md)
- [부분 보고서 처리 전략](docs/PARTIAL_REPORT_POLICY.md)
- [107개 테스트 보존 및 마이그레이션](docs/TEST_MIGRATION_V012.md)
- [수정 전 12개 재현 실패](verification/V012_REPRO_BEFORE.txt)
- [변경 요약](CHANGELOG.md)
- [어댑터 매핑 표](docs/ADAPTER_MAPPING.md)
- [P0/P1 해결 근거와 남은 범위](REVIEW.md)
- [기존 47개 테스트 계약 마이그레이션](docs/TEST_MIGRATION.md)
- [전체 테스트 로그](TEST_RESULTS.txt), [수정 전 10개 재현 실패](REPRO_BEFORE.txt)
- [실제 upstream 호출 로그](verification/REAL_UPSTREAM_LOG.json)
- [실제 반환 계약 fixture 출처](tests/fixtures/capture_manifest.json)
- [Operation 미연결 계약](docs/OPERATION_CONTRACT.md)

실제 Inventory v0.2.0의 DEMO 파일 분석과 ML v2 저장 모델 DEMO 추론은 실행했습니다. 반환값→어댑터→Decision이 보류되는 부분 통합도 실행했습니다. mock callbacks로 검증한 승인·재실행 흐름과 구분합니다. **실제 Operation을 포함한 전체 운영 E2E는 미실행**입니다.

재현하려면 원본 ZIP을 별도 폴더에 풀고 upstream 의존성을 설치한 환경에서:

```bash
python examples/verify_real_upstreams.py --inventory-root /absolute/inventory-root --ml-root /absolute/ml-root --storage /absolute/demo-store --output /absolute/lastplate-decision-v0.1.3/tests/fixtures
```

ML은 지정한 demo-store에 예측 이력을 기록합니다. 실제 주문·메뉴·재고·ERP·실적 기록 API는 호출하지 않습니다. 두 upstream의 일반 패키지 이름 충돌을 막기 위해 별도 프로세스로 실행합니다.

승인 흐름과 UI 테스트는 [LangGraph interrupt](https://reference.langchain.com/python/langgraph/types/interrupt), [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest) 공식 API를 사용합니다.
