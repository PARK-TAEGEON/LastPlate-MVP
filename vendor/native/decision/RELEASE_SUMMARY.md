# v0.1.3 — InventoryUse 입력 검증 한정 패치

v0.1.2의 재고 후보 식재료명·단위 누락 결함만 수정한 패치 릴리스입니다.

## 변경

`lastplate_decision/schemas/decision_input.py`의 InventoryUse에서만 ingredient와 unit을 필수 문자열로 재정의했습니다. 앞뒤 공백을 제거하고 최소 길이 1을 검사합니다.

| 입력 | 처리 |
|---|---|
| ingredient / unit 누락 또는 null | 필드 경로가 포함된 명시적 Pydantic ValidationError |
| 빈 문자열 또는 공백·탭·개행만 있는 문자열 | strip 후 ValidationError |
| `  두부  ` / ` kg ` | `두부` / `kg`로 정리한 뒤 기존 판단 수행 |
| 식재료명 없는 menu_substitution 후보 | 기존 Candidate 계약 유지. 허용 |

잘못된 재고 후보는 Decision 입력 검증을 통과하지 못하므로 selected=true/ADJUST 권고나 normalize(None) 실행으로 진행하지 않습니다. quantity·days_to_expiry의 기존 UNKNOWN/보류 정책과 단위 종류/환산 정책은 변경하지 않았습니다. 모든 입력을 normalize(None)으로 우회하거나 메뉴 대체 후보까지 필수 식재료명을 강제하지 않습니다.

## 검증

- 수정 전에 신규 19개 테스트를 실행: 실패 15, AttributeError 2, 통과 2. [재현 로그](verification/V013_REPRO_BEFORE.txt)
- 수정 후 **163개 통과**, 실패/오류/skip 0 = 기존 144개 + 신규 19개. [전체 로그](TEST_RESULTS.txt)
- 기존 144개 테스트 소스는 byte-for-byte 동일하며 기존 메서드 ID를 전부 유지했습니다. [검증 요약](verification/TEST_SUMMARY.json)
- 재현 행렬: ingredient/unit × missing/null/empty/whitespace × 단독/expiry_risk 동시 입력 = 16개. 정상 trim, 식재료명 없는 메뉴 대체, 잘못된 자료형 검사 3개 추가.
- 기존 실제 반환 계약 fixture 검사 15개와 Streamlit AppTest 7개를 포함한 전체 suite를 실행했습니다. 이번 패치에서 실제 upstream 호출은 다시 수행하지 않았으며 기존 REAL_UPSTREAM_LOG는 v0.1.2 당시 부분 호출 기록입니다.

## 범위

런타임 정책 변경은 InventoryUse 입력 스키마에 한정했습니다. 버전 표시(0.1.3)와 배포 JSON 스키마도 갱신했습니다. [코드 diff](verification/INVENTORY_FIX.diff)를 제공합니다. 기존 의존성·confidence 정책과 계약 마이그레이션 문서는 보존했습니다.

실제 Operation·Agent callback·공통 provenance 연결 및 같은 급식일 전체 E2E는 후속 단계이며 이번 패치에 포함하지 않았습니다. 실제 발주·메뉴 변경·재고 차감·ERP 실행 기능도 없습니다.
