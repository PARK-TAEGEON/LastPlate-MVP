# 107개 테스트 보존 및 계약 마이그레이션 (v0.1.2)

v0.1.1 ZIP의 테스트 메서드 107개를 삭제/이름 변경 없이 유지했습니다. 144개 실행 = 기존 107개 + 신규 37개, 실패/오류/skip 0입니다. 기존 v0.1.0 → v0.1.1의 [47개 테스트 계약 마이그레이션 설명](TEST_MIGRATION.md)은 그대로 보존했습니다.

새 재현 테스트 12개를 구현 전에 작성·실행했고 **12개 모두 assertion 실패, error 0**으로 결함을 재현했습니다. [수정 전 로그](../verification/V012_REPRO_BEFORE.txt)와 최종 TEST_RESULTS.txt를 비교할 수 있습니다. 이후 정책 경계 22개, 실제 event fixture 계약 1개, Streamlit AppTest 2개를 추가했습니다.

## 유지된 테스트에서 변경한 부분

| 파일/fixture | 수정 이유 |
|---|---|
| examples/fixtures.py baseline | 합성 Operation이 현재 Demand/Inventory를 소비했다는 계약을 명시. Inventory independent에는 불필요한 Demand 소비를 만들지 않음 |
| tests/test_v011_reproductions.py scoped() | provenance 전체를 교체하던 fixture에도 명시적 현재 소비 revision 추가. 원래의 scoped 안전성 assertion 유지 |
| test_workflow.py test_full_order_interrupt_approve_no_execution | baseline은 Inventory 소비 경로이므로 기대 순서를 Demand→Inventory→Operation으로 수정. 승인/무실행 assertion 유지 |
| test_workflow.py test_expiry_route | 새 Inventory를 사용한 Operation mock을 추가하고 Inventory→Operation 순서를 확인. 정상 완료 시 미해결 요청이 비어야 한다는 assertion 유지 |
| test_real_contracts.py / test_streamlit_integration.py | 기존 메서드 변경 없이 신규 클래스·테스트 추가 |

원본은 verification/v011_original_tests/*.txt에 보존했습니다. SHA-256, 107개 메서드 ID, 144개 실행 ID는 TEST_INVENTORY.json, diff는 TEST_MIGRATION_V012.diff에 있습니다. 이전 TEST_SUMMARY/TEST_RESULTS/REAL_UPSTREAM_LOG도 V011_ 접두어로 보존했습니다. 테스트 이름 보존과 byte-for-byte 무수정은 다른 의미이며 위 변경을 숨기지 않습니다.

## 검증 종류

| 종류 | 실행 결과 | 한계 |
|---|---|---|
| 전체 단위·정책·workflow·계약·UI suite | 144 PASS | 아래 종류가 섞인 총합이며 모두 실제 upstream E2E인 것은 아님 |
| 실제 반환 fixture 계약 변환 | 15 PASS | 실제 Inventory/ML 호출에서 캡처한 JSON 및 추가 경계 입력 검증. 매 테스트가 upstream을 호출하지 않음 |
| LangGraph callback workflow | 전체 suite에서 PASS | callbacks는 mock. 실패/복구/최신성/상한/승인 경로 검증 |
| Streamlit AppTest | 7 PASS | 실제 AppTest 실행. 화면 픽셀/외부 브라우저 E2E와는 다름 |
| 실제 Inventory 부분 호출 | full ok / event ok / needs_clarification 확인 | DEMO/SIMULATION 데이터. 실제 Operation 미연결 |
| 실제 ML 부분 호출 | 저장 모델 demo 추론 1034 | operational_eligible=false; 실운영 예측 검증 아님 |
| 실제 반환값→어댑터→Decision | needs_confirmation, 인분 null | 같은 급식일 전체 흐름이 아님. 입력 일자도 서로 다름 |
| 실제 Operation 포함 전체 E2E | **미실행** | Operation 구현 및 공통 운영 provenance가 제공되지 않음 |

실제 부분 호출 로그에는 upstream 원본 해시, 반환 fixture 해시, 상태, stderr를 기록합니다. 명령은 README의 verify_real_upstreams.py 예제입니다. 전체 테스트는 프로젝트 폴더에서 `python -m unittest discover -s tests -v`로 재실행할 수 있습니다.
