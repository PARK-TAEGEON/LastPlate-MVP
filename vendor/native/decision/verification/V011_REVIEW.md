# P0/P1 리뷰 해결 근거

## P0 — 현재 메뉴 알레르기 HIGH인데 승인 가능

v0.1.0은 servings 평가에 menu/ingredient=None을 전달해 현재 메뉴의 scoped alert가 누락됐습니다. v0.1.1은 `Operation.current_plan` 전체와 scope를 대조합니다. matched 제약 위반은 BLOCK, unrelated는 현재 계획에서 제외, unknown은 NEEDS_CONFIRMATION입니다. 전체 HIGH 일괄 차단을 사용하지 않습니다.

근거: `test_current_menu_allergy_must_block`, `test_unknown_scope_must_hold`, `test_other_date_is_not_blocked`, `test_other_meal_is_not_blocked`, `test_other_menu_is_not_blocked`, `test_unscoped_hard_alert_is_unknown`, `test_critical_alert_and_modify_to_reject`.

## P1 — 실제 계약과 다른 schema / 패키지 충돌

원본 ZIP을 읽고 실제 Inventory v0.2.0 report와 ML v2 반환값을 생성했습니다. dict affected_menus, priority_use_candidates, menu_substitution, needs_clarification, 문자열 trace, 이벤트 이름, operation_agent, source·limitations를 변환하고 원문을 모두 보존합니다. 미검증 제약은 UNKNOWN입니다. 배포 namespace는 lastplate_decision으로 통합했습니다.

근거: `RealContractTests`, fixture 캡처 manifest 및 `docs/ADAPTER_MAPPING.md`. 실제 Operation은 `docs/OPERATION_CONTRACT.md`대로 미연결입니다.

## P1 — DEMO·운영 부적격·서로 다른 입력 혼합

DEMO:/DEMO/SIMULATION: 출처와 limitations를 notes·confidence에 표시합니다. Demand가 operation/eligible/validated_declared_receipts 조건을 만족하지 않으면 보류합니다. 공통 요청 input_revision과 대상 날짜·prediction_id·분석 범위·결과 revision 누락/불일치를 점검합니다. MAE는 그대로 보존합니다.

근거: `test_ineligible_demand_not_approved`, `test_each_provenance_missing_holds`, `test_each_provenance_mismatch_holds`, `test_shared_requested_revision_detects_stale_demand`, `test_no_mae_probability`, `test_ml_demo_operational_hold`.

## P1 — 해소되지 않는 재실행 / 잘못된 순서

요청을 revision에 연결한 객체로 관리하고, 동일 source 요청은 완료 ledger로 해소합니다. callback 성공만으로 완료하지 않으며 fresh 결과·소비한 의존 결과·날짜·범위를 검사합니다. 실패나 stale 결과는 요청을 유지합니다. 재실행에서 Inventory를 Operation보다 먼저 실행하고 2회 라운드 상한을 유지합니다.

근거: `test_success_resolves_unchanged_source_request`, `test_old_result_does_not_resolve`, `test_failed_result_does_not_resolve`, `test_compound_recheck_inventory_before_operation`, `test_completed_request_invalidated_by_dependency_change`, `test_upstream_completion_claim_not_trusted`.

## P1 — 누적 trace / 승인 revision 누락

route와 callback, 요청 수명주기, Decision 결과, 승인·수정·거절을 workflow_trace에 누적합니다. run_id와 recommendation_revision을 기록하고 원문 upstream trace를 보존합니다. 이전 revision의 승인 요청은 거절합니다. 변경 후에는 새 승인 대기로 돌아갑니다.

근거: `test_trace_survives_modify_reject_and_preserves_original`, `test_stale_approval_revision_rejected`, `test_session_and_latest_approval`.

## P1 — 탈락 대안이 현재 계획 차단 / 중복 메뉴 카드

독립 후보는 자동 선택하지 않습니다. selected_action_ids의 현재 계획·검증된 현재 범위 조정만 승인에 포함합니다. 탈락 후보는 별도 목록입니다. 메뉴 카드는 날짜·끼니·메뉴 키로 합치고, 품목·원인이 다른 영향 메뉴는 연결하지 않습니다.

근거: `test_rejected_alternative_does_not_block_current_plan`, `test_unknown_candidate_does_not_block_safe_current_plan`, `test_one_menu_card_for_two_risks`, `test_global_affected_menus_not_fanned_out`, `test_price_impacts_only_link_price_causes`.

## 남은 한계와 미연결

실제 Operation 계산, 공통 입력 snapshot/provenance 발급, 운영 인증·권한·영속 checkpointer·동시 승인 제어는 미연결입니다. 원본 Inventory는 DEMO dish-level 영양 검증이고 ML 실제 실행은 demo 모드였습니다. 이것을 실제 운영 E2E 통과라고 표현하지 않습니다.

현재 모듈은 상위 검증 PASS가 진실하다는 인증된 계약을 전제로 합니다. metadata_source 문자열이나 해시는 실제 원천의 인증을 대신하지 않습니다. 원문 trace는 보존되지만 이 라이브러리가 외부 데이터의 진실성·최신 수집시각을 증명하지는 않습니다. 여러 대체를 한꺼번에 채택하는 조합 최적화도 구현하지 않습니다.

재실행 완료 후에도 상위 Agent가 계속 잘못된 event 적용 ID나 서로 다른 입력 revision을 반환하면 보류가 유지되는 것이 의도된 동작입니다. 누락 검증을 PASS로 보충하거나 상한에서 임의 승인하지 않습니다.
