# 이벤트 부분 보고서 → 전체 운영 검증

v0.1.2는 **현재 입력 revision에서 full 분석을 다시 요청하는 전략**을 구현했습니다. 서로 다른 분석의 배열을 무조건 합치는 방식은 구현하지 않았습니다.

1. provenance.analysis_scope.coverage=event 또는 원본 analysis_mode=event / execution.scope=event_scoped이면 보류합니다. 어댑터의 event-scoped/skipped 상태도 보존합니다.
2. `recommended_rechecks`에 Inventory의 `analysis_mode=full` 요청을 생성합니다. callback에 `_decision_context.analysis_request`로 mode, 현재 input_revision, prediction_id, 전체 current_plan scope, request_ids, reuse_previous_full=false를 전달합니다.
3. callback은 그 입력·범위에서 실제 full 분석을 수행해야 합니다. Decision이 coverage만 full로 고치거나 이전 full 결과를 가져오는 동작은 없습니다.
4. 같은 input_revision, 대상/예측/full scope, 필요한 의존 revision, 새로운 result_revision을 확인합니다. 이전 입력 full 또는 기존 result_revision 재전송은 완료가 아닙니다. 원문이 event인 채 label만 full로 변경되어도 보류합니다.
5. Inventory를 소비하는 Operation을 새 Inventory 다음 실행합니다. 누락된 영양/안전 검증은 PASS로 채우지 않습니다. 미완료 요청은 상한까지 유지하고 보류합니다.
6. 교체 전 결과는 callback_started.previous_result에 원문/trace와 함께 보존됩니다. 최신 upstream_traces와 과거 workflow_trace를 분리합니다.

## 왜 domain merge를 보류했는가

실제 v0.2.0 보고서에는 부분 분석 실행 노드/생략 노드가 있지만, 모든 제약 항목의 유효 기간, 입력·레시피·원천 스냅샷별 의존 revision을 증명하는 세부 coverage 계약은 없습니다. 같은 날짜 또는 event의 input revision만 같다는 이유로 이전 full의 각 검증이 여전히 유효하다고 판정할 수 없습니다.

향후 병합에는 각 검증 항목별 입력 snapshot, 분석 영역·범위, 실제 소비 원천 revision, 검증 시점, 무효화 조건, complete/unknown 증명이 필요합니다. 그러한 증명이 없는 항목은 보류해야 합니다. 이번 버전은 이전 full과 event를 병합하거나 event를 full로 승격하지 않으므로 잘못된 최신성 주장을 하지 않습니다.

## 연결 범위

full fallback 요청·검증·Operation 후속 순서는 **mock callback workflow 테스트**로 검증했습니다. 제공된 실제 Inventory의 full/event/needs_clarification 호출은 별도로 실행했고 실제 event 반환 fixture에 거짓 full 라벨을 붙여도 보류됨을 계약 테스트했습니다. 실제 upstream 호출을 부모 workflow의 production callback으로 자동 연결한 것은 아닙니다. 실제 Operation과 공통 운영 snapshot 서비스가 없어 전체 운영 E2E는 미실행입니다.
