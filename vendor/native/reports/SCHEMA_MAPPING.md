# 실제 모듈 계약 차이와 연결

| 영역 | 원본 계약 | 통합 처리 |
|---|---|---|
| ML entry | tools.demand.predict_demand(input_data, request_id, config, availability) | 별도 프로세스, 기존 SQLite 저장/멱등 계약 유지 |
| ML 수요 | prediction, target_date, prediction_id, model_version, mode, operational_eligible, availability_status | predicted_diners 별칭 추가, source_payload에 receipt 전체 보존 |
| ML 구간·OOD | public receipt에 없음 | 구간/rate는 null, 학습 데이터 해시·기간·행 수가 일치할 때만 feature 범위 검사 |
| Operation entry | lastplate_operation.generate_operation_plan(demand_result, recipe_data, inventory_data, planned_orders, config) | nested recipes를 행으로 평탄화, service-date에 만료된 재고 제외, 원본 계산 호출 |
| Operation applicability | IN_DOMAIN / OOD / NOT_APPLICABLE / UNKNOWN 객체 | IN_RANGE → IN_DOMAIN, OUT_OF_DISTRIBUTION → OOD, warning category 유지 |
| Operation evidence | recipe/inventory/nutrition/policy evidence bundle | 원본 계약 그대로 전달; Decision 실행 revision과 혼동하지 않음 |
| Operation 제약 | status + checks 배열 | 명시된 nutrition/allergy 결과만 항목별 mapping, 부족은 원본 STOCK_SHORTAGE와 Risk 계산으로 판정 |
| Operation 수량 | ingredient_requirements, order_reviews | 원본 그대로 보존; Decision order_recommendations로 형태만 변환 |
| Inventory entry | agents.inventory_risk.analyze_inventory_and_risk(state, user_event) | 기존 AdapterBundle protocol에 메모리 provider 주입; 암묵적 DEMO fallback 없음 |
| Inventory 메뉴 | Menu.expected_max_diners, ingredients | 대상 service만 선택, Operation recommended_servings 그대로 주입 |
| Inventory 단위 | g/kg | Operation이 지원하는 ml/ea까지 지원한다고 주장하지 않음 |
| Inventory 발주 | lot.planned_order | 입력 planned_orders를 분석 복사본의 동일 단위 lot에 한 번만 배치; arrival stock으로 간주하지 않음 |
| Inventory 이벤트 | detected_events + parsed_events, superseded | 원본 audit 보존; Decision 현재 이벤트·연결된 근거에서 superseded 제외 |
| Inventory 영양 | 대체 후보에 대한 dish-level 검사 | 후보 범위를 유지, 원래 메뉴 영양 전체 검증으로 승격하지 않음 |
| Decision entry | lastplate_decision.make_final_recommendation | 기존 ML/Inventory adapters 재사용 + 새 Operation mapping |
| Decision dependency | Demand → Inventory → Operation 근거 소비 계약 | adapter가 Operation 보고서와 Risk 근거를 함께 소비한 최종 evidence revision 생성; 수량 재계산 없음 |
| Decision 수량 | 근거 부족 시 recommended_servings=null | null 유지, operation_recommended_servings에 원래 계산값 별도 보존 |
| Decision status | ok / needs_confirmation / blocked | 기존 선택 action 결과에서 KEEP/ADJUST/REVIEW, 또는 NEEDS_CONFIRMATION/BLOCK 표시 |
| Source | 데이터별 문자열/DEMO flags | MODEL 수요와 DEMO 원재료를 구분. RiskConfig 원본 DEMO threshold 출처 별도 보존 |

모든 adapter는 형식 변환·검증·원본 근거 보존만 담당합니다. 조리량/발주량/FEFO/대체 후보 계산을 복사하지 않습니다. 새 OOD 검사는 모델 적용범위 보호 계층이며, 예측값을 보정하거나 clip하지 않습니다.
