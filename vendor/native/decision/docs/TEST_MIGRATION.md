# 기존 47개 테스트 유지와 계약 마이그레이션

원본 v0.1.0 ZIP의 테스트 메서드 47개를 삭제하거나 skip/expectedFailure로 전환하지 않았습니다. 최종 검증에서 47개 메서드의 이름 집합을 비교하고 전체 실행 결과를 기록합니다. v0.1.0 테스트 소스의 원문·해시는 verification/original_tests와 TEST_INVENTORY.json에 보존합니다.

v0.1.1이 누락 provenance를 보류해야 하므로, 예전 정상 fixture 자체를 그대로 사용하면 정상 경로 테스트가 모두 보류로 바뀝니다. 이를 피하려고 제품 코드에 legacy 통과 우회를 만들지 않았습니다. 대신 테스트 입력 계약을 다음처럼 명시적으로 이행했습니다.

1. imports를 `lastplate_decision.*`로 변경했습니다.
2. 공통 baseline fixture에 합성 현재 계획, 공통 요청 input_revision, 세 Agent의 provenance, 운영 적격성 필드를 추가했습니다. 실제 외부 데이터의 검증을 PASS로 채운 것이 아니라 기존 테스트의 정상 상태를 명시한 fixture입니다.
3. 문자열 recheck 목록을 비교하던 assertion은 요청 객체의 agent 목록을 투영해 같은 대상·순서를 비교합니다.
4. 승인 응답은 graph의 최신 recommendation_revision을 포함합니다.
5. 정상 재실행 mock callback은 실제 callback 계약과 같이 새 합성 result_revision 및 consumed_results를 반환합니다. 오래된 결과를 반환하는 기존 반복상한 테스트는 그대로 오래된 결과를 반환합니다.
6. CASE 3의 전역 문자열 affected_menus는 관련 품목을 증명하지 못하므로, 해당 계란 price/supply 위험에 `affected_menus=['계란찜']`를 명시했습니다. 기존 '계란 위험→계란찜 검토' assertion은 유지했습니다. 관련 없는 전역 메뉴 연결을 차단하는 별도 새 회귀 테스트도 추가했습니다.

수정 전에 새 `test_v011_reproductions.py`의 10개 테스트를 v0.1.0 코드에 실행했으며 **10개 assertion 실패, import/schema 오류 0개**였습니다. `REPRO_BEFORE.txt`가 원본 실패 로그입니다. 새 구현에서는 동일 재현 테스트가 통과해야 릴리스를 생성합니다.

테스트 유형은 구분합니다.

- 기존·신규 단위/워크플로: 명시적 합성 payload와 mock callbacks, 실제 LangGraph 실행
- 계약 변환: 실제 원본 Agent를 실행해 캡처한 JSON fixture 사용
- 실제 upstream 부분 통합: 원본 Inventory 함수와 저장 ML 모델을 직접 호출하고 어댑터→Decision 보류 검증
- Streamlit: 실제 `streamlit.testing.v1.AppTest`; 브라우저 픽셀/클라우드 배포 검증은 아님
- 실제 Operation 포함 전체 운영 E2E: 미실행
