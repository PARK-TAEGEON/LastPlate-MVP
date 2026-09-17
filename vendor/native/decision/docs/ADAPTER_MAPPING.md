# 어댑터 매핑 표

검토한 원본은 참조 대화의 `lastplate-inventory-risk-v0.2.0.zip`, `LastPlate-ML-v2.zip`입니다. 구현 근거: Inventory의 `schemas/risk_report.py`, `schemas/event.py`, `schemas/request.py`, `agents/inventory_risk.py`, `tools/nutrition.py`, `tools/inventory.py`; ML의 `tools/demand.py`, `adapters/service.py`, `ml/time_contract.py`. 소스 SHA-256과 실제 실행 fixture 해시는 `tests/fixtures/capture_manifest.json`에 있습니다.

## Inventory & Risk v0.2.0

| 원본 계약 | canonical 변환 | 의미 보존·제약 |
|---|---|---|
| schema_version=2.0 | 버전 검증 | 다른 버전은 명시적 오류 |
| status=ok/needs_clarification/error | 동일 상태 | needs_clarification을 ok로 바꾸지 않음 |
| clarification.status=required | needs_clarification | 원문 clarification도 source_payload에 보존 |
| affected_menus[]의 date/meal_type/menu_name/ingredient/affected_ingredient/cause/cause_event_id | dict 목록 그대로 | 단순 메뉴 문자열로 축약하지 않음 |
| priority_use_candidates | inventory_recommendations | candidate_id, 원인·lot ID 원문 보존 |
| quantity_g | quantity + unit=g | kg로 임의 변환하지 않음 |
| expiry_date와 실제 사용 date | days_to_expiry 차이 계산 | as_of 기준으로 바꾸지 않음; 누락은 null |
| 원본 우선 소진 후보에 없는 constraint | UNKNOWN | FEFO 후보라는 이유로 영양·알레르기 PASS를 채우지 않음 |
| kind=menu_substitution, original_menu, candidate_menu | kind, menu, candidate_menu | 식재료 치환으로 오인하지 않음; ingredient=null |
| nutrition_check | constraints.nutrition | 원본 PASS/FAIL/UNKNOWN을 보존 |
| nutrition_results[].status/violations/original/candidate | 원문+canonical result | candidate_id로 연결; 독립 후보의 실패가 현재 계획 실패가 아님 |
| nutrition 결과 PASS이며 candidate.missing=[] | allergy=PASS | 원본 함수의 영양+선언 알레르기 결합 검증 근거가 실제 존재하는 경우만. 전체 급식 알레르기 보증이 아님 |
| violations에 allergy | allergy=FAIL | 명시적 실패가 우선 |
| inventory_available=false | shortage=FAIL | true로 다른 제약 전부 PASS를 생성하지 않음 |
| eligible_for_review, allocation_scope, shortages_g, price_effect, candidate supply/price risks | 후보 source_payload에 보존 | 조건·남은 위험·독립 후보 성격을 삭제하지 않음 |
| alerts evidence/details/cause_event_ids | 원문 보존 + scope 연결 | cause_event_id가 일치하는 실제 영향 메뉴만 연결; candidate_id alert는 해당 후보에만 적용 |
| price_risks | price_risks | ingredient와 price_event 원인이 일치한 영향 메뉴만 연결 |
| supply_risks(event dict) | supply_risks | supply_risk 원인·event ID·기간 유지; HIGH를 공급불가로 바꾸지 않음 |
| detected_events | 변환된 이벤트 목록+각 source_payload | 입력 이벤트에 자동 병합하지 않아 분석 이벤트의 재귀 실행 방지 |
| supply_risk 이벤트 | supply_event | source_event_type=supply_risk 유지 |
| inventory_expiry_event | expiry_event | 원래 명칭·source_type·범위 보존 |
| inventory_shortage_event | 동일 이름 | Inventory/Operation 재검토 경로 지원 |
| needs_clarification=true, 숫자 없는 attendance | 동일 미확인 이벤트 | attendance_delta를 0으로 만들지 않음 |
| recommended_rechecks의 operation_agent | operation | 원본 목록도 report source_payload에 보존 |
| decision_trace: list[str] | 문자열 그대로+upstream_traces | 자유 문자열을 삭제하거나 허구의 구조화 판단으로 바꾸지 않음 |
| execution/skipped_nodes/analysis_mode | source_payload + coverage | event/생략 결과를 full로 승격하지 않음 |
| data_sources, limitations | 그대로+data_quality_notes | DEMO:/DEMO/SIMULATION: 표시·confidence 반영 |
| cost_impacts | 그대로+trace | 금액으로 확률·영양·임의 soft 점수를 생성하지 않음 |
| input_snapshot_id | provenance.input_revision | 임의로 다른 Agent revision과 같게 덮어쓰지 않음. 생성 snapshot이면 공유 revision 불일치로 보류될 수 있음 |
| as_of, period | 원문 보존·기간 검증 | as_of는 분석일이며 급식일로 사용하지 않음. 단일 날짜 period만 target_date의 직접 근거 |
| forecast_version | 원문 보존 | prediction_id로 바꾸지 않음 |
| 공통 prediction_id/대상 메뉴·끼니/분석 범위 없음 | 호출자의 recorded provenance 또는 누락 | 부모 서비스가 실제 호출 기록으로 증명해야 함 |
| 결과 revision 없음 | 전체 원문 content fingerprint | 동일 원문은 동일 revision. 같은 결과 재전송은 정상 재실행 완료가 아님 |

## LastPlate ML v2

| 원본 계약 | canonical 변환 | 의미 보존·제약 |
|---|---|---|
| prediction, prediction_id, model_version | 그대로 | 직접 예측·재계산 없음 |
| input_data | input_summary + source_payload | 전체 메뉴 문자열을 레시피/끼니/식재료 목록으로 임의 분해하지 않음 |
| target_date | provenance.target_date | as_of 또는 현재 날짜로 대체하지 않음 |
| created_at/deadline_at/timezone/policy/availability/weather | source_payload | 실제 서버 메타데이터 보존 |
| mode=operation/demo/replay | mode | operation 외에는 운영안 보류 |
| operational_eligible | 같은 boolean/null | 누락을 true로 채우지 않음 |
| availability_status | 그대로 | validated_declared_receipts 이외는 보류 |
| validation_mae가 존재하면 | 그대로 | 실제 v2 반환에는 없을 수 있음. 확률·신뢰구간 변환 없음 |
| predict_node의 result/error envelope | 성공 result 변환, 전체 envelope 보존 | error이면 빈 예측+오류 note, 성공처럼 처리하지 않음 |
| 입력 revision/끼니/정규화 식재료 범위 없음 | recorded provenance 또는 누락 | 대상 문자열/예측 ID로 생성하지 않음 |
| 결과 revision 없음 | 원문 content fingerprint | 모델 버전만으로 결과 동일성을 판단하지 않음 |

## 원문 보존 방식

각 report의 `source_payload`는 입력 dict의 깊은 복사입니다. 후보·위험·이벤트에도 해당 원문을 보존합니다. 원문에 있는 값과 부모 서비스의 실행 메타데이터를 구분하며, 변환 계약 테스트가 원문 equality와 fixture SHA-256을 검사합니다.

두 upstream 프로젝트는 일반 이름 `tools`, `adapters`, `config`를 서로 사용합니다. Decision 자체의 namespace 충돌은 해결했고, 두 upstream의 동시 호출 예제는 프로세스로 격리합니다. upstream끼리의 패키지 구조를 이번 패치에서 수정하지 않았습니다.


## v0.1.2 추가/정정 매핑

| 입력/출력 | 처리 |
|---|---|
| data_sources / data_source / source_type | Inventory·ML 어댑터 및 canonical 입력에서 보존. 공백·대소문자·접두어 정규화 후 DEMO/SIMULATION/UNKNOWN만 출처 품질 경고로 분류 |
| REAL 출처 설명 | provenance_notes/source_provenance에 정보로 기록. 품질 경고 아님 |
| ML 정상 mode/operational_eligible/availability_status 설명 | provenance_notes. 운영 적격성 검사는 별도 evidence_issues에서 계속 수행 |
| limitations | 어댑터 보존 + 적용 범위에 따른 품질 경고. 무관한 탈락 후보의 제한은 현재 계획 confidence에 미반영 |
| provenance.dependency_basis | independent(기본) 또는 demand_scaled. 상위 호출자가 실제 분석 경로를 기록하며 어댑터가 소비 증명을 합성하지 않음 |
| operation.provenance.consumed_results | 직접 호출부터 현재 result_revision 검사. 누락 PASS/최신 값 자동 채우기 없음 |
| event execution 원문 | source_payload를 보존하고 라벨 승격 여부를 이중 확인. full 재실행 요청의 analysis_mode=full 생성 |
| confidence_evidence / quality_records | confidence_reasons·data_quality_notes와 동일한 평가 입력에서 생성 |

원본 source_payload는 그대로 유지합니다. quality metadata를 canonical에 노출하는 것은 원문 수정이나 운영 검증 PASS 생성이 아닙니다.
