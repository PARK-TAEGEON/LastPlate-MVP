# LastPlate v0.1.1 — P0/P1 통합 수정 검증

요청된 통합 경계 수정만 수행했습니다. ML·Operation·Decision 원본 파일은 v0.1.0과 해시가 동일합니다. Inventory & Risk는 취소 이벤트 처리, 기존 FEFO에 Operation 원물 총량 전달, 명시적 evidence gate 출력에 필요한 최소 변경만 적용했습니다. 방문객 자동 재실행이나 운영 action 실행은 추가하지 않았습니다.

## 실제 검증 결과

- v0.1.0에 같은 재현 테스트를 적용: **6개 실패**. 원본은 수정하지 않았으며 LASTPLATE_TEST_ROOT로 원본을 지정했습니다.
- 수정본 전체 integration: **32개 통과** = 기존 20 + 실패 재현 6 + 경계 검사 6.
- 마지막 날짜 미확정 공급 관측 보존 검사: **1개 추가 통과**. 총 33개의 통합 검사를 실제 실행했습니다.
- 네 모듈 regression: ML 73, Operation 180, Inventory & Risk 240, Decision 163 = **656개 통과**. Decision의 51 subtests도 통과했습니다.
- 총 고유 검사: **689개 PASS**, 기존 라이브러리 Starlette/AnyIO deprecation warning 1건. 실제 외부 API·현장 성능 검증 결과가 아닙니다.

실패 전: `p0p1-before.txt`, `p0p1-before.xml`, `p0p1/before/*.json`.
수정 후: `final-integration-v011.txt`, `final-integration-v011.xml`, `p0p1/after/*.json`.
6개 단독 수정 후 실행도 `p0p1-after.txt/xml`에 남겼습니다. 이후 최종 32개 전체 실행에 같은 6개가 다시 포함되었습니다. `p0p1/comparison.json`이 전후 결과를 비교합니다.

## 6개 실패 불변조건의 전후

| 검사 | v0.1.0 실제 결과 | v0.1.1 실제 결과 |
|---|---|---|
| 취소된 structured supply_risk | current supply_risks·critical supply alert에 잔존 | audit 유지, current supply risk/critical supply alert 0, 취소 원인의 menu REVIEW 없음 |
| 원물 basis | Operation 145600g, Risk 72800g / 부족 0g | 양쪽 145600g / 부족 45600g |
| kg 주문 + g 재고 | PARTIAL | COMPLETE, 2kg → 2000g. ml/ea는 Demand 실행 전 UNIT_ERROR/422 |
| HTTP 오류 | 잘못된 ML·nested 입력·동일 ID 충돌 모두 200 | 각각 422/422/409, nested 실패의 Demand·Operation 결과 보존 |
| supply history / Demand metadata | 취소 공급 관측 삭제, metadata envelope 없음 | public audit/history 보존, 상세 warning/training range/confidence/model type envelope 보존 |
| 마지막 adapter 방어 | stale supply risk가 critical 경고에 재등장 | 연관 record·candidate·constraint·recheck 제거, audit 원본 별도 유지 |

수량 fixture는 **두부 총 재고 100000g인 단일 lot**, 조리량 910, 80g/인분, trim_loss_pct=50입니다. Operation의 edible_required=72800g, raw_required=cooking_required=145600g, purchase_need=45600g은 변경하지 않았습니다. Risk.required_g=145600g, shortage_at_service_g=45600g으로 일치시켰습니다. 가격·영양 recipe를 160g/인분으로 변조하지 않았습니다.

## Source of truth와 adapter 경계

| 값/판정 | 단일 기준 | 연결 방법 |
|---|---|---|
| raw ML prediction / model version | 기존 predict_demand receipt | 변경·capacity clip 없음 |
| raw/cooking 요구량·발주량 | 원본 Operation ingredient_requirements | cooking_required를 canonical g 총량으로 Risk에 전달 |
| 현재 재고 배분·부족·만료 제외 | 원본 Inventory allocate/analyze/analyze_details | optional required_totals; 기존 FEFO로 재고 배분 |
| 단위 환산 | 원본 Inventory tools.units.grams + 원본 Operation unit 함수 | kg/g canonical g, 환산식을 복제하지 않음 |
| 활성 위험·hard gate·재검증 요청 | Risk tools.active_evidence | Risk와 마지막 integration adapter가 같은 구현 사용 |
| nutrition | Operation whole-meal 입력 / Risk dish-level 원래 edible recipe | 두 범위와 DEMO 출처를 별도 표기 |
| 최종 권고 | 원본 Decision make_final_recommendation | 수량 재계산 없음, requires_human_approval=true |

### 취소 이벤트와 감사 기록

Risk의 supply/expiry/impact 단계에서 superseded 이벤트를 실제 적용하지 않습니다. `project_active`는 detected_events, price_risks, supply_risks, alerts, affected_menus, priority_use_candidates, substitute_candidates, nutrition_results, cost_impacts를 같은 event/candidate 참조 그래프로 투영합니다. 취소 cause만 있는 record 및 candidate-only 후속 record를 제거합니다. 혼합 cause는 활성 cause만 남기고 관련 없는 실제 위험은 유지합니다.

기존 coarse rechecks(operation_agent/demand_forecast)와 current_plan_checks도 활성 view로 생성합니다. 모호한 입력의 blocked_clarification은 그대로 보존합니다. native report의 detected_events/parsing_result에는 history를 남기고, 통합 report.audit.supply_events에는 기간 밖·날짜 미확정 관측까지 입력 그대로 남깁니다. Decision 최종 source_payload.inventory_risk는 감사용 원본이며 make_final_recommendation에는 투영한 현재 근거만 전달합니다. source_payload를 risk 입력으로 재투입하지 않습니다.

마지막 adapter 방어 테스트는 취소 event에 연결된 모든 collection 및 candidate-only 참조를 고의로 주입합니다. primary native 필터가 작동하지 않은 과거/stale 보고서도 현재 critical 경고·후보·재검증 근거에 남지 않는 것을 확인했습니다. 추가 mixed-cause 검사에서는 살아 있는 위험을 함께 삭제하지 않는 것도 확인했습니다.

### 수량 basis

Operation 수량식을 Risk/Decision에 복사하지 않았습니다. allocate의 optional total override가 기존 native edible 계산으로 얻은 메뉴별 기여도에 따라 Operation 총량을 분배합니다. 마지막 기여분은 남은 총량을 받아 aggregate를 보존합니다. 단일 service scope와 ingredient coverage를 검증하며 기존 호출은 optional 인자 없이 원래 동작을 유지합니다. 추가 native 검사에서 두 메뉴에 2000g 총량을 1600g/400g으로 배분하고, 만료된 5000g lot을 배제해 유효 1500g 대비 500g 부족을 확인했습니다.

Risk allocation_audit에 원래 edible_required_g와 quantity_basis를 기록합니다. nutrition/cost 비교용 원래 recipes는 바꾸지 않습니다. 대체 후보의 stock feasibility는 여전히 원본의 독립 edible estimate이므로 raw/cooking 차이가 있는 계획에서는 eligible_for_review=false와 operation_quantity_recheck_required=true를 표시합니다. 후보 선택 후 Operation 재계산은 자동 실행하지 않습니다.

### HTTP와 오류 분류

- 422: public contract/지원하지 않는 단위, native ML normalize, native nested model validation, Operation INVALID_INPUT 및 누락 자료.
- 409: 기존 ML의 idempotency_conflict/revision_conflict.
- 500: worker 실패·서버 설정·모델/저장소·hook 실패. 입력 검증을 통과한 서버 오류를 422로 바꾸지 않습니다.
- 200: 완료한 권고 또는 사용자 확인이 필요한 정상적인 업무 상태. BLOCK/NEEDS_CONFIRMATION 자체는 HTTP 오류가 아닙니다.

모든 status 매핑은 errors[].http_status/kind를 사용합니다. 이미 성공한 stage 결과는 오류 응답에서도 지우지 않습니다. server-failure.json은 Risk 단계에 테스트용 실패를 주입하여 HTTP 500과 Demand/Operation/Decision 보존을 확인한 결과입니다. 잘못된 서버 mode도 500으로 검증했습니다. 입력 실패 시 새 자동 재시도는 없습니다.

### Demand envelope

Operation native callable에 알 수 없는 필드를 밀어 넣지 않고 worker의 optional _demand_envelope로 전달합니다. 결과 demand_envelope에 confidence, model_type, training_ranges, warnings의 feature/value/range/category/severity, model_version, predicted_diners, applicability를 보존합니다. Decision에도 integration_envelope를 전달하고 같은 demand_envelope를 반환합니다. 원래 raw receipt, model_version, raw prediction을 변경하지 않았습니다.

## 변경 파일

전체 변경 목록·전후 SHA-256은 source-changes.json, 정확한 diff는 source-changes.diff입니다.

Inventory native 변경: inventory_risk/agents/inventory_risk.py, inventory_risk/graph/inventory_risk_workflow.py, inventory_risk/schemas/risk_report.py, inventory_risk/tools/active_evidence.py, inventory_risk/tools/inventory.py.

핵심 integration 변경: adapters/inventory_risk_adapter.py, adapters/operation_adapter.py, adapters/decision_adapter.py, risk_evidence.py, orchestrator.py, worker.py, bridge.py, errors.py. HTTP wrapper는 app/main.py입니다. ML·Operation·Decision 내부는 변경하지 않았습니다. 원본 대비 검증은 preservation-v011.json입니다.

## 실행과 재현

기존과 동일하게 이 전체 폴더에서 requirements-tested.txt를 설치한 Python으로 실행합니다.

```powershell
python -m pytest -q
python scripts/run_regression.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

구버전 실패를 재현하려면 LASTPLATE_TEST_ROOT를 v0.1.0 폴더의 절대경로로 설정하고 EVIDENCE_PHASE=before로 지정한 후 tests/integration/test_p0p1.py를 실행합니다. 동일 파일로 6 failures가 예상됩니다. 환경변수를 해제한 뒤 EVIDENCE_PHASE=after로 수정본을 실행하면 6 PASS입니다. 테스트는 임시 DB를 사용하며 실운영 주문·메뉴·재고를 변경하지 않습니다.

## 유지한 제한

raw ML capacity clipping 없음. 방문객을 employees에 가산하지 않음. 방문객 event 자동 재실행은 **미구현**이며 recommended_rechecks만 반환합니다. 새로운 자동 발주·메뉴 변경·재고 차감·자동 승인 없음. 최종 human approval은 true입니다. DEMO/REAL 출처를 유지하며 demo 입력을 실제 확보 근거로 승격하지 않습니다. Small-site 정확도·전국 일반화·실제 공급/API 연결·기관 영양기준 준수는 이 테스트로 주장할 수 없습니다.

이전 INTEGRATION_REPORT.md의 “원본 코드 수정 없음 / 주문 단위 일치 필요” 설명은 v0.1.0 이력입니다. 이번 패치의 source-of-truth는 이 보고서와 verification-v011.json입니다.
