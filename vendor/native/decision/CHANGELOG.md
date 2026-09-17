# v0.1.3

- InventoryUse.ingredient/unit만 필수 non-blank 문자열로 검증. 정상 값은 앞뒤 공백 제거.
- 누락/null/빈 값에서 명시적 ValidationError. expiry_risk 동시 입력의 normalize(None) AttributeError 방지.
- 메뉴 대체 Candidate.ingredient 선택 계약 유지.
- 기존 144개 테스트 소스 무수정 + 신규 19개 = 163개 PASS. 상세: RELEASE_SUMMARY.md.

---

# v0.1.2

- 초기/직접 Decision 및 재실행 모두 현재 Demand/필요 Inventory 소비 revision 검사. 완료 원장이 없어도 보류·재실행 요청. 원장 위조/오래된 의존성으로 우회할 수 없음.
- Demand → 선택적 demand-scaled Inventory → Operation의 비순환 정책. 독립 Inventory에 불필요한 Demand 의존성을 만들지 않음.
- 현재 계획 영양/알레르기 FAIL은 blocked/LOW. 관련 공급 위험·생성 constraint_violation을 confidence_evidence에 포함.
- 출처 플래그 정규화 및 정보성 provenance 분리. REAL/정상 ML 운영 메타데이터만으로 confidence를 낮추지 않음. 비선택 후보의 품질 경고는 현재 계획에 전파하지 않음.
- event 보고서는 현재 입력 revision의 full 재분석 요청. 이전 full 근거 병합/라벨 승격 없음. 교체 전 원본 결과도 workflow trace에 기록.
- callback 실패·회복 시 품질 노트와 최종 confidence를 한 번에 계산. Operation 단독 실패에 무관한 Demand 재실행 요청을 만들던 경로도 수정.
- 기존 107개 유지 + 신규 37개 = 144개 PASS. 실제 계약 fixture 15개, Streamlit AppTest 7개 포함. 실제 upstream 4회 부분 호출, 전체 Operation E2E 미실행.

---

# v0.1.1 변경 요약

1. 현재 계획과 위험을 날짜·끼니·메뉴·식재료·후보 범위로 비교합니다. 일치/무관/불명확을 구분하고, 현재 메뉴 알레르기 누락을 수정했습니다.
2. 배포 경로를 `lastplate_decision.*`로 통합했습니다. 일반 이름 `agents/schemas/graph/config`를 설치하지 않습니다.
3. Inventory & Risk v0.2.0과 LastPlate ML v2의 원본 ZIP 소스를 읽고 실제 반환값을 생성해 어댑터를 작성했습니다. 원문 payload, 문자열 trace, event ID, 원인 연결, 분석 생략, limitations를 보존합니다.
4. 현재 입력 revision과 세 Agent provenance의 일치를 요구합니다. ML 운영 부적격·불명확 상태 및 부분 분석을 보류합니다.
5. 재실행 요청을 버전 객체로 확장했습니다. 새 결과·의존 revision 확인 후 완료 처리하고, 실패/오래된 결과는 유지합니다. operation_agent 별칭과 Inventory→Operation 순서를 처리합니다.
6. run_id와 recommendation_revision을 포함한 누적 workflow_trace를 추가했습니다. 수정·승인·거절에도 이전 기록을 보존합니다.
7. 승인 대상 현재 계획과 탈락 후보를 분리했습니다. 날짜·끼니·메뉴별 위험 카드를 합치고 원인과 식재료가 다른 영향 메뉴의 연결을 제거했습니다.
8. Streamlit 예제와 실제 AppTest를 추가했습니다. 세션의 그래프·checkpointer·thread_id 유지, 최신 state.approval, 오류·보류·DEMO를 검증합니다.
9. 기존 47개 테스트 메서드를 유지했고 새 결함 재현 테스트 10개를 구현 전에 실행해 전부 실패하는 로그를 남겼습니다. API 확장에 따른 fixture/호출부 이동은 TEST_MIGRATION.md에 명시했습니다.

## 호환성 변경

- import: `agents.decision` → `lastplate_decision.agents.decision`
- 함수의 keyword-only `input_revision` 및 Agent provenance/current_plan이 추가됐습니다. 누락된 v0.1.0 입력은 삭제/예외 대신 보류합니다.
- `recommended_rechecks`는 문자열 목록에서 요청 객체 목록으로 변경했습니다. 기존 문자열 입력 및 operation_agent 별칭은 수용합니다.
- 승인·수정·거절 응답은 최신 recommendation_revision을 포함해야 합니다.
- 독립 탈락 후보가 현재 계획의 전체 status를 낮추지 않습니다. candidate_evaluations를 별도로 표시하세요.

숫자 재예측, 가격 조회, 발주 실행, 메뉴 자동 변경, 재고 차감, ERP 기능은 추가하지 않았습니다.
