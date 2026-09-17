# v0.1.2 P0/P1 해결 근거

| 결함 | 수정 위치/정책 | 검증 근거 |
|---|---|---|
| P0 초기 호출 stale/missing 소비 근거 승인 | dependencies.py + evidence.py, completed 원장 독립 검사 | V012Reproductions 초기 소비 4개; DependencyPolicyTests 원장 우회·없어진 revision·역방향 edge 검사 |
| P0 blocked nutrition/allergy에 HIGH/통과 이유 | quality.confidence_assessment는 status/선택 현재 계획 실패 우선 | nutrition/allergy 재현 2개, CONFIDENCE_EXAMPLES.json의 LOW/실패 이유/null |
| P1 관련 supply·생성 violation 근거 누락 | 선택 action_id/현재 scope 기준 confidence_evidence | supply HIGH MEDIUM, unavailable BLOCK/LOW, unrelated HIGH 비하향 테스트 |
| P1 simulation만 있을 때 경고 누락, REAL/정상 ML이 MEDIUM | 출처 prefix 정규화·provenance 정보 분리 | 원래 재현 4개, 필드/공백/대소문자 subTest, AppTest 2개, 어댑터 품질 보존 |
| P1 탈락 후보 품질이 현재 계획에 전파 | quality_records의 affects_confidence를 선택·범위로 판정 | 비선택 DEMO 후보 HIGH 유지, 무관한 공급 위험 비하향 |
| P1 workflow 노트/최종 confidence 불일치 | make_final_recommendation에 workflow_notes 입력, 계산 뒤 경고 덧붙임 제거 | 미연결+유효 입력 HIGH, callback 실패 LOW, 회복 HIGH+과거 실패 trace 보존 |
| P1 event 보고서 전체 운영 적용 | current revision full 요청, 원본 event 흔적 검사, 새 result revision 필수 | mock full fallback/old input/old result/label-only 테스트 및 실제 event fixture 변환 테스트 |

기존 107개 메서드를 유지하고 최종 144개 모두 통과했습니다. 검사 명령/환경/개별 테스트 결과는 TEST_RESULTS.txt에 있습니다. 기존 v0.1.1 해결 근거는 verification/V011_REVIEW.md, 기존 계약 마이그레이션 문서는 docs/TEST_MIGRATION.md에 그대로 보존했습니다.

실제 upstream 4회 호출 로그와 mock workflow 결과를 분리합니다. Operation은 미제공이므로 전체 실제 E2E 완료라고 주장하지 않습니다. revision은 부모 서비스가 정직하게 기록한 실행 근거라는 신뢰 경계가 있으며, 서명/원천 실행 증명 검증 서비스는 아직 없습니다.
