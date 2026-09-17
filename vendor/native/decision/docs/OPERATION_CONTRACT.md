# Operation 연결 계약 — 실제 구현 미제공

`adapt_operation_contract()`는 Pydantic 검증만 수행합니다. 실제 수량 산출기나 발주 엔진을 구현한 것이 아닙니다. tests의 `refreshed()` 및 callback은 **mock**이며, 해당 테스트의 PASS·revision은 명시적인 합성 fixture입니다.

Operation callback은 다음을 받아야 합니다.

- 공통 input_revision 및 현재 운영 대상 날짜·끼니·메뉴·식재료
- 새 demand_result와 필요한 경우 새 inventory_risk_result
- user_events 및 `_decision_context.recheck_requests`

반환해야 하는 항목:

| 필드 | 책임 |
|---|---|
| recommended_servings | 실제 Operation 계산 결과. Decision이 demand에 인원/MAE를 더해 만들지 않음 |
| current_plan | 실제 선택된 운영안 전체 날짜·끼니·메뉴·식재료와 목록 완전성 |
| constraints | 부족·유통기한·알레르기·영양·금지·공급 검증. 미검증은 UNKNOWN |
| nutrition_constraints | 현재 계획에 대한 영양 결과. 독립 후보와 구분 |
| order_recommendations | 품목, 범위, 현재 수량, 단위, 상태 및 제약 근거 |
| provenance | 대상일, 사용한 prediction_id, 공통 입력 revision, 새 결과 revision, 실제 분석 범위 |
| provenance.consumed_results | 초기 호출부터 소비한 현재 Demand 및 필요한 Inventory의 실제 result_revision (DEPENDENCY_POLICY.md) |
| applied_event_ids | 실제로 반영한 이벤트만 |

재실행 callback은 request_id마다 새 결과를 작성했다고 주장하는 것만으로 완료되지 않습니다. 대상·입력 revision·분석 범위가 일치하고 결과 revision이 이전 것과 다르며 새 의존 결과를 소비했는지 검사합니다.

다음은 미연결입니다.

- 실제 Operation 계산 및 모든 Agent가 공유하는 운영 입력 snapshot/revision 저장소
- 실제 운영 모드 ML 입력 가용성 수집기/인증된 provenance 발급
- 영속 checkpointer, 인증·권한·다중 사용자 승인 잠금, 장기 감사 로그
- 생산 Inventory/가격/공급 API: 제공된 Inventory는 DEMO/SIMULATION
- 발주·메뉴·재고·ERP 실행: 의도적으로 미구현, 승인 기록으로도 실행되지 않음

실제 ML+실제 Inventory+실제 Operation+Decision+승인 전체 E2E는 실행할 수 없었습니다. 제공물의 `REAL_UPSTREAM_LOG.json`은 실제 Inventory/ML 및 어댑터/보류 검증의 **부분 통합** 로그입니다.
