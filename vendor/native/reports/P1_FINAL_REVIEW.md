# LastPlate v0.1.2 최종 P1 리뷰

요청 범위의 수정과 검증을 완료했습니다. 기준 소스는 이 작업의 v0.1.1이며, 원본 ML·Operation·Decision은 파일 해시가 모두 동일합니다. Inventory에서는 `tools/inventory.py` 1개를 수정하고 `tools/usable_stock.py` 1개를 추가했습니다. 자동 재실행·주문·승인 기능을 추가하지 않았습니다.

## 수정 결과

| 항목 | v0.1.1 | v0.1.2 |
|---|---|---|
| maximum_input_servings=100, raw=883 | native invalid_input / HTTP 200 / errors=[] | HTTP 422 / INPUT_DEMAND_OUT_OF_RANGE / 원본 evidence·alerts 보존 |
| 알 수 없는 alert 또는 빈 alerts + invalid_input | whitelist에 따라 누락 가능 | native status를 기준으로 반드시 input stage error 생성 |
| 사용 가능 재고 | Operation adapter의 직접 날짜 비교 | native Inventory helper를 allocation·usable_today·Operation adapter가 공유 |
| raw/cooking 후보 재검토 | source payload의 flag | pending RecheckRequest + public confirmation_gates; 선택·승인 보류 |

한도 초과의 실제 evidence는 `maximum_input_servings: 100, received_max: 883.0`입니다. raw forecast와 model_version은 변경하지 않았습니다. Demand와 Operation의 원본 응답, Decision의 NEEDS_CONFIRMATION 및 human approval=true를 HTTP 422 본문에 보존하며, invalid Operation 이후 Risk는 실행하지 않습니다.

## 계산 및 판단의 소스

- Operation은 기존 수요 한도 검증·조리량·원물 필요량·발주 계산의 소스입니다. Orchestrator는 모든 `invalid_input`을 오류로 전달합니다. 알려진 alert 목록은 다른 상태의 기존 분류에만 남아 있으며 invalid_input의 오류 생성 여부를 결정하지 않습니다.
- Inventory의 `usable_stock(quantity, expiry_date, service_date)`는 기존 만료 당일 포함 정책을 공용 함수로 추출한 것입니다. 날짜의 정책이나 FEFO 순서를 바꾸지 않았고, 함수는 입력 단위를 그대로 유지합니다. FEFO 및 제한 이벤트 처리는 기존 allocator에 남습니다.
- 수량 전달과 g/kg 정규화, active evidence projection 및 취소 이력은 v0.1.1 코드를 유지했습니다. 기존 raw requirement 145600g / 원물 재고 100000g / 부족량 45600g 검사가 다시 통과했습니다.
- Decision adapter는 active 후보의 재검토 flag를 기존 native `RecheckRequest(status=pending)`로 전달합니다. `confirmation_gates`에는 candidate_id, request_id, quantity_basis와 자동 실행 없음이 표시됩니다. 계산식을 추가하지 않았습니다.
- native Decision의 pending recheck는 후보뿐 아니라 해당 요청의 실행 가능한 권고를 보수적으로 보류하는 기존 동작입니다. 이번 변경은 그 gate를 재사용합니다. 취소된 후보는 active projection 뒤에 제외되어 gate를 남기지 않습니다. 제약이 모두 PASS인 native fixture에서도 후보 REVIEW가 NEEDS_CONFIRMATION으로 바뀌고 선택되지 않음을 별도로 확인했습니다.

## 실제 검증

| 검사 | 결과 |
|---|---|
| ML | 73 passed |
| Operation | 180 passed |
| Inventory | 240 passed |
| Decision | 163 passed + 51 subtests passed |
| 기존 integration/E2E | 33 passed |
| 신규 P1 | 7 passed |
| 이전 별도 리뷰 불변조건 | 16 passed |

기존 33개는 `all-integration.xml`의 39개 실행 중 기존 test node이며, 신규 7개는 최종 `new-tests.xml`로 재검증했습니다. 별도 리뷰의 16개는 저장된 원본 assertion 함수의 AST가 동일함을 검증했고, 과거 JSON을 재사용하지 않고 새로 pipeline을 실행했습니다. 리뷰 runner의 경로와 검증에 필요한 시나리오 선택만 조정했습니다. 각 node·해시·결과는 [verification.json](p1-v012/verification.json)에 있습니다.

검증된 불변조건: 취소 이벤트의 public audit 보존과 현재 근거 제외, 원물/조리량 전달, g/kg 변환, 잘못된 ML/nested input의 422, 서버 실패 500, idempotency conflict 409, 업무 confirmation 200, 성공 단계 보존, g/kg 외 단위의 모델 기록 전 거절, OOD 전달과 raw 예측 미클리핑, nutrition FAIL/UNKNOWN 처리, DEMO provenance 및 human approval=true.

신규 테스트의 unknown/empty alert와 서버 실패 검사는 명시적으로 주입한 fixture입니다. 한도 초과·수량·기존 불변조건은 실제 모듈 실행입니다. all-PASS 후보 비교는 native Decision의 테스트 fixture이며 REAL 운영 증거로 취급하지 않습니다. 테스트에는 Starlette/AnyIO deprecation warning 1종이 있으며 실패는 없습니다.

## 증거와 재실행

- [한도 초과 전후 요약](p1-v012/limit-comparison.json), [수정 전 실제 JSON](p1-v012/limit-before.json), [수정 후 실제 HTTP JSON](p1-v012/limit-after.json)
- [전체 통합 실행 로그](p1-v012/all-integration.txt), [신규 최종 로그](p1-v012/new-tests.txt), [이전 16개 최종 로그](p1-v012/previous-invariants/review-invariants.txt)
- 네 native 로그: `regression-demand.txt`, `regression-operation.txt`, `regression-inventory_risk.txt`, `regression-decision.txt`
- [source diff](p1-v012/source.diff), [파일별 해시](p1-v012/source-changes.json)
- 신규 후보 gate JSON: `p1-v012/candidate-gate.json`, `all-pass-candidate-gate.json`, `cancelled-candidate-gate.json`
- 기존 P0/P1 새 실행 JSON: `p0p1/after/`; 이전 16개 새 입력/출력: `p1-v012/previous-invariants/`

프로젝트 루트에서 동일 의존성이 설치된 Python으로 실행합니다.

```text
python scripts/run_regression.py
python -m pytest -q tests/integration
python tests/review/run.py
```

방문객을 employees에 더하거나 방문객 이벤트를 자동 재실행하는 기능은 미구현입니다. DEMO와 REAL의 구분, whole-meal/dish-level 영양 근거와 모델 metadata/audit 전달은 유지했습니다. 승인은 항상 사람의 확인이 필요하며 이 backend는 실제 주문·메뉴 변경을 실행하지 않습니다.

`P0P1_FIX_REPORT.md` 및 v011 이름의 보고서는 이전 버전 이력입니다. 이번 릴리스의 최종 판단은 이 문서와 `p1-v012/verification.json`을 기준으로 합니다.
