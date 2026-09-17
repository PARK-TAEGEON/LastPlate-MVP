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

# v0.2.0 수정·검증 보고서

검토 기준은 v0.1.0 ZIP과 `LastPlate-Operation-정식리뷰.md`입니다. ZIP SHA-256 및 리뷰/확인한 native Demand 코드 출처는 `evidence/input-provenance.json`에 남겼습니다. 기준 ZIP과 v0.1.0 작업 폴더는 보존하고 별도 v0.2.0 폴더에서 수정했습니다. 구현자 자체 검토이며 별도 리뷰어 검토가 아닙니다.

## 기준 상태 및 최종 검증

| 검사 | 결과 |
|---|---|
| 수정 전 기존 suite | **85 passed**, 실패/skip 0. baseline-v010.xml |
| 최종 suite | **161 passed**, 실패/skip 0. 기존85 + 추가76 |
| 기존 테스트 파일 | ZIP 원본과 바이트 동일, SHA-256 기록 |
| 일반 fixture | 523인분, 가식62,760g, 구매60,064g, 범위60,064~63,068g 유지 |
| 충분 재고+구매 quantum100g | purchase_only: 구매0g |
| 같은 재고+조리 계량100g | cooking_and_purchase: 구매100g, 추가량/evidence 보존 |
| JSON Schema/DEMO | 현재 모델과 동일성, JSON Schema 구조 유효성, 3개 예제 재계산 동일성 통과 |
| 실제 LangGraph | 원래 오류 경로+OOD/capacity/올림/ea/수치/영양/운영모드 경로에서 함수와 동일 |
| Streamlit AppTest | DEMO 표시/잘못된 JSON 처리 포함 전체 suite에서 통과 |
| v0.2.3 실제 count-only wrapper | PASS. 5개 식사 키에523인분, 원본 메뉴 불변 |
| v0.2.0 editable 설치 | 성공 |

최신 stdout는 `tests/test-results.txt`, JUnit은 `tests/test-results.xml`입니다. 연결 로그는 `evidence/inventory-bridge-smoke.txt`입니다. 이번 수정에서는 기존 Inventory **240개 전체 suite를 다시 실행하지 않았습니다**. 해당 모듈 코드를 수정하지 않았고 실제 wrapper 연결만 재검증했습니다. Demand 실제 모델 예측이나 Decision 최종 권고까지의 E2E 시험도 아닙니다.

## 리뷰 항목별 변경

- **P1 Demand 적용성:** 확인 가능한 native ML-v2 receipt의 필드명을 보존했습니다. native 구현에 없는 OOD/applicability/warnings는 제안 확장으로 구분했습니다. model_version/input_snapshot_id와 함께 source 및 trace에 보존하고 경고를 제거하지 않습니다.
- **P1 capacity:** 요구량/설비 한도/초과량을 분리했습니다. capacity로 조용히 자르지 않으며 입력 적용 범위도 별도로 검사합니다. 0/같음/초과/최소 인분 충돌을 시험했습니다.
- **P2 올림:** 기본 legacy_combined를 유지하고 purchase_only/cooking_and_purchase를 추가했습니다. 정확 원물량은 유리수로 보존하여 재고 비교 전 올림 오차를 피합니다. 정책별 추가량을 alert에 남깁니다.
- **P2 ea:** 주문은 낱개 정수, 레시피 분할은 허용, 재고 분할은 명시적 설정일 때만 허용합니다.
- **P2 수치:** 상한/최소 quantum/소수자리·유효숫자/JSON 왕복 조건, Decimal context 격리, 구조화된 산술 오류 처리를 추가했습니다. 프로그래밍 TypeError를 숨기지 않는 테스트도 포함했습니다.
- **P2 필드명:** edible_required/raw_required/cooking_required를 분리하고 기존 두 필드를 deprecated alias로 보존했습니다.
- **P2 Alert:** enum type, evidence, trace_id/trace_refs를 추가했습니다. message 문구와 소비자 분기를 분리했습니다.
- **데이터 근거:** recipe/nutrition/inventory/policy 출처·버전·스냅샷·meal_id 및 nutrition의 recipe 연결 검사. REAL 라벨과 운영 필수 근거 검사를 분리했습니다.
- **상태 우선순위:** 후속 영양 FAIL이 이전 주문 누락의 needs_clarification을 낮추지 않도록 상태 단조성을 보완했습니다. FAIL과 누락 알림은 모두 보존됩니다.
- **직렬화:** 정밀 JSON 파서 및 입력 모델의 JSON 숫자 직렬화, native metadata의 소수값 보존을 보완했습니다.

## 수정 코드와 운영 정책 선택의 구분

코드 수정은 계약 보존, 잘못된 소수 주문 거절, 수치 오류 구조화, 상태·Trace 일관성을 제공합니다. 아래는 사업장 정책으로 선택·확인해야 합니다.

1. legacy_combined 유지 또는 두 새 올림 정책 중 선택. 기본값을 자동 교체하지 않았습니다.
2. capacity_servings 및 maximum_input_servings, 안전여유/손실률/허용오차, 계량·구매 단위.
3. 분할된 ea 재고의 의미와 허용 여부.
4. 대상 식사의 영양/최소 제공 기준, 검증된 영양 근거와 스냅샷 식별자.
5. simulation에서 operation 모드로의 전환과 policy_acknowledged 선언.

이 값들의 현장 적합성을 코드 시험으로 인증하지 않습니다. policy_acknowledged는 입력자의 확인 선언이고 최종 운영 승인 기능이 아닙니다.

## 호환성·잔여 범위

- schema_version=2.0. 단순 문자열 교체가 아닌 재계산 이행이 필요합니다. `MIGRATION.md`에 수량 필드 alias, 정책 선택, 수치 범위 축소, 상태 변경을 정리했습니다.
- 85개 테스트 코드는 수정하지 않았습니다. 기존 DEMO JSON에 IN_DOMAIN과 DEMO 설명만 추가했습니다. 새 정책 테스트는 별도 파일에 있습니다.
- provenance는 선언된 ID 일치만 확인합니다. 레시피 내용 변경 후 같은 ID를 재사용하면 감지하지 못합니다. 영양값을 직접 재계산하지 않습니다.
- 실제 upstream Demand의 OOD 확장 계약은 합의가 필요합니다. 확인한 ML-v2 receipt를 보존했지만 여러 배포 버전 전체의 호환성을 보장하지 않습니다.
- used raw stock 적격성은 Inventory & Risk, 다중 식사 재고 예약/분배는 상위 계층입니다. 동일 재고를 여러 식사에 중복 차감하면 안 됩니다.
- 공급사별 MOQ·포장·납기는 확장 지점만 문서화했습니다. 현재 단위별 quantum과 동일시하지 않습니다.
- count-only bridge는 요구 인분만 전달합니다. review/OOD/capacity 경고를 포함한 전체 Operation 보고서를 별도로 Decision에 전달해야 합니다. Risk release/superseded를 Operation이 해석하지 않습니다.
- 외부 API 연결, 실제 발주, 자동 메뉴 변경, 최종 승인 기능은 추가하지 않았습니다.
- Windows의 현재 의존성 조합으로 시험했습니다. 다른 지원 버전 조합 전체와 수동 브라우저 현장 UI 검증은 수행하지 않았습니다.

실제 현장 안전성이나 폐기·비용 절감 효과는 검증하지 않았으며 이를 주장하지 않습니다.
