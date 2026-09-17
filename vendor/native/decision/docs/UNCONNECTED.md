# 미연결/미구현 목록

| 항목 | 현재 상태 |
|---|---|
| 실제 Operation Agent | 미제공. adapt_operation_contract는 검증만 수행. 예제 refreshed/callback은 mock |
| 실제 Operation 포함 전체 E2E | 미실행. 실제 ML·Inventory 부분 호출과 혼동하지 않음 |
| 공통 운영 input snapshot/revision 및 소비 실행 증명 서비스 | 미연결. 전달받은 revision 비교는 구현했으나 출처의 허위 주장을 인증하지 않음 |
| 이벤트별 부분 검증을 full로 안전하게 병합 | 미구현. 현재 revision의 full 재분석 요청·검증을 대신 구현. 항목별 상세 coverage 계약 필요 |
| Inventory full 재분석 production callback | 호출 계약/보류/순서 구현 및 mock 검증. 실제 부모 workflow callback 자동 연결은 미완료 |
| 실제 운영 ML 입력 가용성 수집 | 미연결. 실제 호출은 demo 저장 모델이며 operational_eligible=false |
| 운영 재고·가격·공급 API | 미연결. 제공된 Inventory 분석은 DEMO/SIMULATION 자료 |
| 영속 checkpointer·인증·다중 운영자 승인 잠금·장기 감사 저장 | 미연결. Streamlit 세션 + InMemorySaver 예제 |
| 발주·메뉴 변경·재고 차감·ERP 실행 | 범위 제외, 의도적으로 미구현. approve도 executed=false |

세부 반환 계약은 [OPERATION_CONTRACT.md](OPERATION_CONTRACT.md), 초기/재실행 의존 조건은 [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md)를 따릅니다.
