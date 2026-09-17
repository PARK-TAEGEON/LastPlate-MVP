# v0.1.2 제출 요약

**기존 107개 + 신규 37개 = 144개 테스트 통과** (실패 0, 오류 0, skip 0). 구현 전 새 재현 테스트 12개가 모두 assertion 실패했고, 수정 후 통과했습니다.

## 변경 내용

- 초기/일반 호출부터 Operation의 현재 Demand 및 필요한 Inventory 소비 revision을 검증합니다. completed 원장이 없어도 검사하며, 오래된 completed 원장으로 우회할 수 없습니다.
- 독립 Inventory와 Demand 기반 Inventory의 의존성을 구분했습니다. 전체 갱신 순서는 필요한 경우 Demand→Inventory→Operation이며 역방향 의존성은 거부합니다.
- 현재 계획 nutrition/allergy FAIL은 blocked/LOW와 실제 실패 근거를 반환합니다. 관련 supply risk·constraint_violation을 포함하고 무관한 탈락 후보는 현재 계획 confidence를 낮추지 않습니다.
- DEMO/SIMULATION/UNKNOWN을 출처 필드별로 정규화합니다. REAL·정상 ML mode 설명은 provenance 정보로 분리했습니다. MAE 확률 환산은 없습니다.
- 부분 보고서는 현재 입력 revision의 full 재분석을 요청합니다. 이전 full 재사용·event 라벨 승격·검증되지 않은 병합은 하지 않습니다. 실패/복구 노트와 confidence를 동일한 근거로 계산합니다.
- Streamlit은 정규화된 품질 표시·confidence 근거·별도 provenance 설명을 표시합니다. 세션의 그래프/checkpointer/thread_id, 최신 state.approval 계약을 유지합니다.

## 문서와 검증물

- [초기/재실행 의존 정책표](docs/DEPENDENCY_POLICY.md)
- [confidence 정책·실패 근거](docs/CONFIDENCE_POLICY.md), [실행 예시 JSON](verification/CONFIDENCE_EXAMPLES.json)
- [부분 보고서 full 재검증 전략](docs/PARTIAL_REPORT_POLICY.md)
- [어댑터 매핑표](docs/ADAPTER_MAPPING.md)
- [107개 보존/마이그레이션·테스트 구분](docs/TEST_MIGRATION_V012.md)
- [전체 테스트 로그](TEST_RESULTS.txt), [수정 전 실패 로그](verification/V012_REPRO_BEFORE.txt)
- [실제 upstream 부분 호출 로그](verification/REAL_UPSTREAM_LOG.json)
- [P0/P1 해결 근거](REVIEW.md), [남은 미연결 기능](docs/UNCONNECTED.md)

## 검증 경계

실제 계약 fixture 테스트 15개, Streamlit AppTest 7개를 포함합니다. LangGraph 재실행/승인 테스트의 callback은 mock입니다. 제공된 실제 Inventory는 full/event/확인 필요 경로를 호출했고 실제 ML 저장 모델은 DEMO 예측 1034를 반환했습니다. 어댑터와 Decision 부분 연결은 보류/null을 확인했습니다.

**실제 Operation 구현이 없어 전체 운영 E2E는 미실행입니다.** 실제 발주·메뉴 변경·재고 차감·ERP 실행은 추가하지 않았습니다. 승인 의사만 기록합니다.
