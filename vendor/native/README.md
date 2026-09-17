# LastPlate 통합 MVP backend v0.1.2

v0.1.2 최소 P1 수정과 실제 검증: `reports/P1_FINAL_REVIEW.md`.
Operation invalid_input은 원본 alert/evidence를 보존한 HTTP 422이며, 성공한 단계 결과는 유지합니다.
서비스 날짜의 사용 가능 재고는 native Inventory helper를 공유합니다.
raw/cooking 후보의 재검토 요구는 기존 Decision pending recheck gate로 전달하며 자동 재실행하지 않습니다.

세 Agent 원본을 보존하고 Inventory의 제한된 P0/P1 패치를 Adapter / Orchestrator에 연결한 **권고 전용 backend**입니다. 실제 저장된 ML 모델을 실행합니다. 레시피·재고·가격·영양 예제는 DEMO이며, 실제 API 연결이나 현장 정확도 검증을 의미하지 않습니다.

이번 버전은 취소 이벤트의 active evidence, raw/cooking 수량 basis, 단위 정규화, HTTP 오류 분류, audit·Demand metadata 전달을 수정했습니다. **[수정 검증 보고서](reports/P0P1_FIX_REPORT.md)**와 [전후 JSON](reports/p0p1/comparison.json)을 확인하세요.

## 실행

Python 3.12 권장. 이 전체 폴더를 유지하세요. 기존 모듈을 각각 pip install하면 `tools`, `adapters`가 충돌할 수 있어 통합 worker가 독립 프로세스로 실행합니다. 일반 wheel 하나로 배포하는 구성은 아닙니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-tested.txt
python scripts/run_demo.py examples/lh_like.json --output reports/my-lh-result.json
python scripts/run_demo.py examples/small_site.json --output reports/my-small-result.json
python -m pytest -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

POST `/api/plan`에 `examples/lh_like.json` 전체 내용을 보냅니다. 서버 기본 모드는 `demo`입니다. `LASTPLATE_STORAGE`는 기존 ML SQLite 저장 디렉터리, `LASTPLATE_MODE`는 demo/replay/operation입니다. operation 모드에는 원본 ML이 요구하는 실제 수집 출처·확보 시각이 필요합니다. 공개 배포용 인증·신뢰할 수 있는 수집기는 포함하지 않습니다.

```python
import json
from pathlib import Path
from integration import run_lastplate_pipeline, PipelineConfig

payload = json.loads(Path('examples/lh_like.json').read_text(encoding='utf-8'))
result = run_lastplate_pipeline(
    payload,
    config=PipelineConfig(storage_dir=Path('runtime').resolve(), mode='demo'),
)
print(result['pipeline_status'])
print(result['decision']['decision_type'])
```

`COMPLETE`는 네 단계 실행이 완료됐다는 뜻입니다. 안전성·승인 여부는 `decision.decision_type`, `confidence`, `critical_alerts`로 확인합니다. DEMO는 일반적으로 NEEDS_CONFIRMATION이며 실제 재고 부족 등 hard FAIL은 BLOCK이 우선합니다. 승인 상태는 항상 pending입니다.

## 입력과 출력

한 요청은 한 사업장의 **특정 날짜 점심 한 끼**입니다. `weekly_menu` 중 대상 날짜/끼니만 평가합니다. 주간 재고 공유 계획이나 저녁 수요 모델로 확대하지 않습니다. 레시피별 모든 식재료를 명시해야 합니다.

입력은 site_id, request_id, target_date, as_of, meal_capacity, attendance, weekly_menu, recipes, inventory, planned_orders, nutrition, prices, monthly_prices, supply_events, sources, operation_policy, 선택 event입니다. `attendance.registered_population`을 원본 ML의 `employees`로 변환합니다. 임의의 수요값을 입력받아 ML 결과를 대체하지 않습니다.

`inventory`는 원본 InventoryLot 형태입니다. `planned_orders`만 발주량 입력의 단일 기준이며 lot의 planned_order는 분석 복사본에서 이 값으로 대체됩니다. g/kg 주문과 재고는 원본 단위 함수로 canonical g 환산합니다. 없는 품목은 재고 0인 lot을 제공하세요. Operation은 g/kg 외 단위도 지원하지만 현재 Inventory 엔진은 g/kg만 지원합니다. ml/ea 등 지원하지 않는 연결은 Demand 실행 전에 UNIT_ERROR/HTTP 422로 거절합니다.

출력은 demand, operation, inventory_risk, decision, pipeline_status, errors, warnings, timings, input_revision입니다. 원본 Operation/Risk 보고서와 ML receipt를 보존합니다. `decision.operation_recommended_servings`는 Operation의 원래 값입니다. 원본 Decision이 근거 부족으로 보류하면 `decision.recommended_servings=null`일 수 있으며, 다른 수량으로 다시 계산하지 않습니다.

ML의 lower_bound, upper_bound, predicted_rate, available_population은 해당 public receipt에 없으므로 null입니다. 학습 CSV에 participation_rate 열이 있다는 사실을 참여율 모델 구현으로 해석하지 않습니다. IN_RANGE는 단변량 학습 범위 내라는 뜻이며 정확도나 사업장 일반화 보증이 아닙니다.

## 이벤트와 재실행

기본 흐름은 Demand → Operation → Inventory/Risk → Decision입니다. Decision adapter가 Operation 수량과 Inventory 근거를 함께 소비한 revision을 기록합니다. Operation이 미래 Risk 결과를 미리 소비했다고 표시하지 않습니다.

자연어 event는 기존 Inventory parser가 해석합니다. superseded 이벤트는 audit에만 유지합니다. 인원 증가 이벤트를 employees 증가로 추정하지 않습니다. 새로운 인사 입력과 request_id로 전체 pipeline을 다시 호출하세요. 필요한 재검증은 Decision.recommended_rechecks에 남습니다. 자동 incremental rerun과 후보 선택 뒤 재배분은 이번 버전에 포함하지 않습니다.

## 저장과 부작용

첨부 ML 안에 있던 SQLite ServiceStore만 사용합니다. 예측 기록은 원본 API의 멱등 request_id 계약을 그대로 지킵니다. 실제 주문·메뉴 변경·재고 차감은 수행하지 않습니다. 재고 차감량은 계산상의 offset입니다.

추가 저장은 선택 hook으로 연결합니다:

```python
def save_decision(report, input_revision):
    # 연결할 저장 계층에서 input_revision으로 upsert하세요.
    pass

result = run_lastplate_pipeline(payload, hooks={
    'on_decision_complete': save_decision,
})
```

on_demand_complete, on_operation_complete, on_inventory_risk_complete도 가능합니다. 재시도 때 hook은 재호출되므로 외부 구현이 idempotent upsert를 보장해야 합니다. hook 실패는 결과를 보존하고 PERSIST_HOOK_FAILED/PARTIAL을 반환합니다.

v0.1.1 수정·전후 검증은 `reports/P0P1_FIX_REPORT.md`, 이전 통합 이력은 `reports/INTEGRATION_REPORT.md`, 계약 차이는 `reports/SCHEMA_MAPPING.md`, 원본 해시 비교는 `reports/preservation-check.json`을 보세요.
