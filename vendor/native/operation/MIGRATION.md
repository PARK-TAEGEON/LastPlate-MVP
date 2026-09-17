# v0.2.1 Alert参照 수정 기록

기준 상태: 기존161개 테스트 통과. 기존 두 테스트 파일은 v0.2.0과 바이트 동일하게 보존했습니다.
최종 결과: **180 passed**, 실패/skip 0. 신규19개는 기본 빈 evidence/trace_refs 및 Alert별 step/식재료/근거 일치, 그래프·함수 동일성을 검사합니다.

`alert()`는 keyword-only `trace_refs`를 명시적으로 받습니다. 생략하면 []이며 evidence 생략은 {}입니다. 마지막 trace나 stage/ingredient로 근거를 만들어내지 않습니다.

`add_trace()`는 trace 생성 시 ID를 반환합니다. evidence_stage는 각 발견 항목의 evidence_check trace를 만든 뒤 그 ID를 알림에 전달합니다. 요약 evidence_gate나 Demand trace를 임의로 연결하지 않습니다.

MISSING_RECIPE/DUPLICATE_RECIPE/MISSING_INVENTORY/MISSING_PLANNED_ORDER/UNMATCHED_ORDER/UNIT_MISMATCH 등 별도 관련 검사 trace를 만들지 않은 경로는 빈 trace_refs/evidence를 사용합니다. 알려진 수치 근거를 명시한 알림은 evidence를 유지하되 관련 trace가 없으면 trace_refs는 비웁니다.

발주 알림은 해당 식재료 order_review, 재고/계량 알림은 해당 식재료 inventory_offset_and_range, 준비/capacity 초과는 관련 입력을 포함한 serving_calculator, 제약 알림은 constraint_check를 참조합니다.

산술·상태 정책과 schema_version=2.0은 유지했습니다. DEMO 출력은 새 trace/Alert 구조로 재생성했습니다. 외부 API/실제 발주 변경은 없습니다.

최신 시험 기록: tests/test-results.txt 및 tests/test-results.xml. 아래 기존 v0.2.0 기록은 이전 릴리스의 검증 범위입니다.

---

# v0.1.0 → v0.2.0 / schema 1.0 → 2.0

## 기존 호출과 계산

함수 인자와 기본 계산 정책은 유지됩니다. 기존 85개 테스트 파일은 바이트 단위로 보존했습니다. DEMO fixture에는 제안 applicability의 IN_DOMAIN 선언만 추가했습니다. 실데이터를 IN_DOMAIN으로 가정하는 변경이 아닙니다.

새 결과는 schema_version=2.0입니다. 1.0 출력 그대로를 새 Output 모델/bridge에 넣지 마세요. 원 입력에 보완 근거를 추가하여 재계산해야 합니다. 1.0 결과의 버전 문자열만 바꾸는 것은 유효한 마이그레이션이 아닙니다.

| v0.1.0 | v0.2.0 권장 필드/해석 |
|---|---|
| gross_required | edible_required. 기존 필드는 deprecated alias로 같은 값을 유지 |
| adjusted_required | cooking_required. 기존 필드는 deprecated alias로 같은 값을 유지 |
| 원물량을 adjusted_required에서 추정 | raw_required=올림 전 원물량. exact numerator/denominator 제공 |
| recommended_servings | required_servings와 같은 요구 인분. capacity로 잘라내지 않음 |
| quantity_quantum | 기본 legacy_combined에서 유지. 새 정책은 cooking_quantum/purchase_quantum |
| 자유 문자열 alert.type | 고정 AlertType enum. UI message는 분기 계약 아님 |
| trace step만 존재 | 보고서 내부 trace_id 추가; alert.trace_refs로 참조 |

기본 legacy_combined에서 66,064g인 adjusted_required/cooking_required는 유지됩니다. purchase_only를 선택하면 두 필드는 올림 전 원물량과 같아질 수 있으므로, 정책을 함께 읽어야 합니다. raw_required는 항상 조리 올림 전 값입니다.

## 상태·범위 변경 (의도적)

- applicability 생략은 UNKNOWN → needs_clarification. 근거 없는 구형 입력을 ok로 표시하지 않습니다. 수량 계산은 남아 있을 수 있습니다.
- OOD/적용불가는 review. 불명확한 근거와 함께 있으면 needs_clarification이 우선하되 OOD 경고는 남습니다.
- REAL 라벨과 operation 정책을 분리했습니다. operation에서는 capacity·정책 확인·근거 및 완전한 영양 제약을 요구합니다.
- ea 주문의 소수는 거절. ea 재고는 기본 정수, 분할 재고는 명시적 허용 필요. 레시피의 분할 사용은 허용.
- 일반 숫자 최대10^9, 소수6자리/15 유효숫자, quantum 최소0.001, 손실률 최대99%. 구형의 극단값 허용 범위는 축소했습니다.
- 입력 Demand 기본 적용 범위100,000, 기술 상한1,000,000. 사업장 capacity와 별개입니다.
- allergy_restriction 기본값은 null(미확인)이며 []는 제한 없음의 명시적 선언입니다.
- 누락 정책을 자동 채운 뒤 승인하는 기능은 없습니다. policy_acknowledged는 입력자의 정책 확인 선언이며 인증/최종 승인 필드가 아닙니다.

## 운영 정책 선택

다음은 버그 수정과 구분되는 정책 선택입니다.

1. 호환성이 필요하면 legacy_combined 유지. 이중 올림 경고/추가량을 검토합니다.
2. 구매 포장만 제한하면 purchase_only + purchase_quantum을 명시합니다.
3. 조리 계량도 제한하면 cooking_and_purchase + 두 quantum을 명시합니다.
4. 현장 기준으로 capacity_servings, maximum_input_servings, 안전여유·손실률·허용오차·영양 기준을 설정합니다. 기본값을 공식 기준으로 사용하지 않습니다.
5. 출처 식별자와 같은 식사·레시피 스냅샷의 영양 근거를 준비하고 operation 모드 검사를 적용합니다.

## Demand native vs 제안 확장

검토한 native 구현: LastPlate-ML-v2/tools/demand.py의 prediction receipt. operational_eligible/availability_status 및 기존 metadata 이름을 우선 보존했습니다. upstream code는 수정하지 않았습니다. applicability/warnings의 typed 구조는 그 native 코드에 없는 제안 확장입니다. 예측 결과를 새로 만들거나 native 상태에서 IN_DOMAIN을 자동 유추하지 않습니다.

입력 스키마가 달라지면 명시적으로 어댑터 계약을 갱신해야 합니다. unknown 경고를 버리는 필드 필터를 두지 마세요. 영양·레시피 provenance 역시 Operation이 제안하는 계약이며 upstream 스냅샷 생성 규칙과 합의해야 합니다.

## 책임 유지

사용 가능 원물 재고 선정은 Inventory & Risk, 다중 식사 배정/예약은 상위 계층입니다. count-only 결과만으로 최종 승인하지 않습니다. Decision에는 전체 Operation/Risk 보고서가 필요합니다. 공급사 MOQ·포장·납기, 외부 API, 실제 발주는 이번 버전에 없습니다.
