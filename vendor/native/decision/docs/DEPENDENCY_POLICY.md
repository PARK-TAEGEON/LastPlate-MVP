# 초기·재실행 소비 의존 정책 (v0.1.2)

`confidence`와 승인 판단 전에 `evidence_issues()`가 항상 검사합니다. completed 원장 유무, LangGraph 사용 여부와 무관합니다. 원장은 실행 이력이며 최신성 검사를 생략하는 허가가 아닙니다.

| 결과/경로 | 초기·직접 호출 필수 소비 근거 | 재실행 정책 |
|---|---|---|
| Demand | incoming dependency 없음 | 현재 입력·대상·예측 ID·full 범위, 운영 적격성 검증. 새 result_revision 필요 |
| Inventory independent | Demand/Operation 불필요 | 독립 원천 분석. Demand를 무조건 소비했다고 기록하지 않음 |
| Inventory demand_scaled | 현재 Demand result_revision | Demand 다음 실행. 실제 소비 revision 반환 |
| Inventory가 명시적으로 Demand 소비를 선언 | 현재 Demand result_revision | dependency_basis가 independent여도 선언한 소비의 최신성 검사 |
| Operation 일반 경로 | 항상 현재 Demand result_revision | Demand 갱신 다음 Operation. 예측 ID 일치만으로 소비 증명을 대체하지 않음 |
| Operation Inventory 사용 경로 | 위 Demand + 현재 Inventory result_revision | Inventory 갱신 다음 Operation. 가격·공급, 재고 우선 사용, 발주 검토 포함 |
| Operation 단순 식수 경로 | Demand만. 아래 Inventory 필요 조건이 모두 없을 때 | Inventory에 불필요한 소비 edge를 만들지 않음 |
| 모든 결과 | 위 경로에서 허용하지 않은 self/reverse/unknown dependency 금지 | 잘못된 edge는 보류. 자동 순환 재실행 대신 상한 내 확인 요청 |

Inventory 필요 조건은 `dependencies.inventory_required()`에 한 곳으로 정의합니다.

- `operation_inventory_dependency=always` 정책이거나 Operation의 order_recommendations가 존재
- Operation이 Inventory 소비를 명시한 경우 (보고서가 비어도 선언을 무시하지 않음)
- Inventory 미완료/부분 범위/재실행 요청 존재
- 현재 계획과 관련 있거나 적용 범위가 불명확한 alerts, nutrition_results, price/supply risk, inventory recommendation 존재
- 관련 유통기한·가격·공급·사용금지·재고부족 사용자 이벤트 존재

독립 대체 후보의 alert/nutrition은 제외합니다. 명시적으로 무관한 메뉴/식재료/날짜 위험은 Inventory 소비 필요성의 근거로 사용하지 않습니다. 전체 Inventory 근거 자체의 날짜/입력/분석 범위 검사는 별도로 계속 적용됩니다.

가능한 그래프는 `Demand → Operation`, 선택적 `Demand → Inventory`, 필요한 `Inventory → Operation`뿐입니다. Inventory → Operation → Inventory 순환은 허용하지 않습니다.

## 요청·완료

누락/불일치: NEEDS_CONFIRMATION, 권고 인분 null, `consumed_dependency:<agent>` 사유의 재실행 요청. 필수 upstream revision 자체가 없을 때도 불일치입니다. 요청이 만들어질 때와 dispatch할 때 같은 의존 정책을 사용하고, dispatch는 최신 upstream revision에 바인딩합니다.

완료: callback 성공 + 새 result_revision + 공통 input_revision/target/prediction/전체 scope 일치 + 모든 필수 소비 근거 + 필요한 applied_event_ids. 현재 검증 실패가 있으면 imported completed 원장도 stale로 돌아갑니다. 이전 입력 revision의 원장은 감사 이력으로 남고 새 입력을 차단하지 않습니다.

기본 상한은 **2회 재검증 라운드**입니다. 세 Agent가 필요하면 Demand → Inventory → Operation. Inventory만 바뀌어도 이를 소비하는 Operation을 같은 순서로 갱신합니다. 실패·오래된 결과·미연결은 요청을 유지합니다.

## baseline 마이그레이션

`examples.fixtures.baseline()`은 합성 계약 fixture입니다. Demand={}, Inventory independent/consumed_results={}, Operation={현재 Demand, 현재 Inventory}를 명시합니다. `refreshed()`는 mock helper이며 실제 소비를 증명하는 운영 구현이 아닙니다. 초기 입력의 누락을 자동 보정하는 코드로 사용하면 안 됩니다.
