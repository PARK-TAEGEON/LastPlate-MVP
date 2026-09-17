# v0.1.1 제출 요약

## 결과

- 전체 **107개 테스트 통과**, 실패 0, 오류 0, skip 0
- 기존 테스트 메서드 **47개 유지**, 신규 **60개**
- 수정 전 결함 재현 테스트 **10개 전부 assertion 실패** → 수정 후 통과
- 실제 반환 계약 fixture 테스트 **14개**, 실제 Streamlit AppTest **5개** 포함
- 독립 namespace wheel 빌드 성공. 원본 tests 보존·마이그레이션 diff 제공

## 주요 수정

현재 계획의 scoped 알레르기·안전 제약을 놓치던 승인 경로를 수정했습니다. 날짜·끼니·메뉴·식재료가 불명확하면 보류하며 관련 없는 위험과 탈락 대안으로 안전한 현재 계획을 차단하지 않습니다. 공통 입력 revision 및 세 Agent의 provenance를 검증하고, 버전 있는 재실행 요청·완료·실패·오래된 결과를 추적합니다. 원본 Inventory/ML 계약 어댑터, 누적 workflow trace, 최신 revision 승인, 세션 유지 Streamlit 예제를 추가했습니다.

## 검증 경계

| 검증 | 실행 여부 |
|---|---|
| 순수 Decision·scope·confidence·freshness 단위 테스트 | 실행·통과 |
| mock callbacks + 실제 LangGraph 승인/재실행 | 실행·통과 |
| 실제 Inventory v0.2.0 + 제공 DEMO 파일 분석 | 실행 |
| 실제 ML v2 코드 + 제공 저장 모델, demo 모드 추론 | 실행; 예측 1034, operational_eligible=false |
| 실제 반환값 → 어댑터 → Decision 보류 | 실행; needs_confirmation, 인분 null |
| 실제 Operation 포함 동일 급식 건의 운영 E2E | **미실행: 실제 Operation 및 공유 provenance 미제공** |
| Streamlit AppTest | 5개 통과; 실제 브라우저/클라우드 배포 검증과 구분 |

실제 호출 캡처는 Inventory 기간 2026-09-18~2026-09-24와 ML 과거 입력 2021-01-26을 사용했습니다. 하나의 운영 급식 건을 연결한 성공 사례가 아니며, 날짜·근거 불일치와 미연결을 보류하는 부분 통합 검증입니다.

## 제출 파일

- `CHANGELOG.md`: 변경 요약·호환성 변경
- `docs/ADAPTER_MAPPING.md`: 원본→canonical 매핑과 근거
- `TEST_RESULTS.txt`, `verification/TEST_SUMMARY.json`: 최종 테스트 로그·수치
- `REPRO_BEFORE.txt`: 구현 전 재현 실패 로그
- `verification/TEST_INVENTORY.json`, `TEST_MIGRATION.diff`: 기존 47개 보존 근거
- `verification/REAL_UPSTREAM_LOG.json`: 실제 upstream 호출·부분 통합 로그
- `REVIEW.md`: P0/P1 해결 근거
- `docs/OPERATION_CONTRACT.md`: 남은 미연결 기능과 실제 Operation 계약

실제 발주·메뉴 변경·재고 차감·ERP 실행은 구현하지 않았습니다. approval.executed는 항상 false입니다.
