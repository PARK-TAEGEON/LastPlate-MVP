# v0.1.2 호환성 검토 · 수정 기록

검토일: 2026-09-18. 대상: 사용자가 제공한 `lastplate-integrated-v0.1.2` 전체 폴더.
백엔드 기준본: 기존 작업 폴더의 `backend/app`. Git 업로드용 폴더의 `backend/app` 17개 Python 파일과도
해시가 모두 일치함을 확인한 뒤 이 기준본으로 작업했습니다. 기존 폴더를 덮어쓰지 않고 별도 배포본을 만들었습니다.

## 검사 범위와 한계

캐시·가상환경·Git 메타데이터를 제외한 **633개 전체 파일**을 목록화하고 SHA-256을 기록했습니다.

| 검사 | 파일 수 |
| --- | ---: |
| Python 구문/AST 및 import·함수 목록 | 217 |
| JSON 파싱 | 229 |
| 문서·텍스트 디코딩 | 103 |
| TOML 파싱 | 5 |
| CSV/TSV 헤더·행 열 수/인코딩 확인 | 48 |
| XML 파싱 | 25 |
| 바이너리·기타: 크기/해시 확인 | 6 |

원시 날씨 CSV 일부는 CP949여서 해당 인코딩으로 검사했습니다. 위 구조 검사에서 파싱 오류는 없었습니다.
전체 목록은 `peer-file-audit.json`이며, 이 파일에는 모델·원시 데이터 행·팀원 구현 코드를 복사하지 않았습니다.

모든 파일을 사람이 한 줄씩 검증했다는 의미는 아닙니다. 전체 파일에 자동 구조 검사를 적용한 뒤,
충돌 가능성이 높은 다음 경계를 집중 검토했습니다.

- 루트 README, pyproject, 의존성 목록, 공개 API `app/main.py`
- `integration/contracts.py`, orchestrator, bridge, worker, 4개 adapter, native_stock, risk_evidence, 오류 처리
- Demand의 입력 정규화, 시간 계약, feature 규칙, 모델 선택/추론 경로
- Operation의 입력/출력 스키마, 조리량/손실률/구매량 계산, MIGRATION
- Inventory의 재고/위험 스키마, 유효 재고 판단, 출력 증빙
- Decision의 입력/출력·판단 로직, 확인 게이트·재검증 상태
- SCHEMA_MAPPING, P0/P1 수정 보고서, v0.1.2 통합 회귀 테스트와 예제

팀원 프로젝트에 들어 있던 과거 테스트 보고서는 참고 자료로만 봤습니다.
팀원 테스트 전체를 재실행하거나 모든 ML 성능·보안·운영 정확성을 검증한 것은 아닙니다.
이번에 직접 수행한 검증은 아래 31개 백엔드 테스트와 7개 실제 파이프라인 시나리오입니다.

## 충돌 원인과 해결

| 항목 | 발견한 차이 | 이 배포본의 처리 |
| --- | --- | --- |
| 프로젝트 역할 | 새 폴더는 모델뿐 아니라 4개 에이전트와 API 서버까지 포함 | 팀원 코드는 별도 서버 소유로 유지 |
| Python 패키지 | 양쪽 모두 `app.main` 사용 | 내 백엔드만 `lastplate_backend.main`으로 분리 |
| 추론 책임 | 기존 백엔드가 추출한 모델을 직접 실행했음 | 해당 모델·feature 재구현·ML 라이브러리 의존성을 배포본에서 제외 |
| HTTP | 팀원은 `/api/plan`, 기존은 `/api/v1/operation-plans` | 새 `/api/v1/agent-plans` 전달/저장 API를 별도로 추가 |
| 날짜·예측 | 기존 meal_date/current_time/lower-mid-upper와 새 target_date/as_of/demand가 다름 | 서로 다른 계약으로 유지. 임의 변환 안 함 |
| 수량·재고 | 기존 kg/배치 가용량, 새 g/kg·raw/cooking/purchase·증빙 형식 | 새 수량/단위/손실률 계산 결과 그대로 보존 |
| 조리량·설비 | 새 Operation은 필요량을 설비 한도로 잘라 버리지 않음 | recommended_servings와 capacity_excess를 모두 유지 |
| 예측 불확실성 | 새 예측구간은 null이며 적용 범위/신뢰도 경고가 별도 | null·OOD·LOW 경고를 기존 범위로 꾸며내지 않음 |
| 오류 | 422/500에도 이미 실행된 단계 결과가 남음 | 부분 결과·알림·증빙을 저장·반환 |
| 승인 | COMPLETE라도 BLOCK/NEEDS_CONFIRMATION 가능 | human approval, pending, null, rechecks를 보존. 자동 승인/발주 없음 |
| 저장소 | native ML은 자신의 request_id·receipt·시간 계약을 관리 | 별도 백엔드 SQLite에 원본 요청/응답 이력만 저장 |
| 동작 시간 | 팀원은 여러 단계 subprocess를 순차 실행 | HTTP read timeout 600초, 자동 재시도 없음 |

HTTP 방식은 현재 코드를 섞지 않고 나중에 연결하기 위한 선택입니다.
향후 반드시 한 서버/한 프로세스로 만들 계획이라면 별도 통합 작업이 필요합니다.
현재도 두 Python 패키지를 같은 환경에 함께 import할 수 있는지는 실제 검증했습니다.

## 원본 보존

- `engine/decision_engine.py`: 기존 파일과 SHA-256 동일. 인원 변동·배치 잠금 등 계산 로직 변경 없음.
- `schemas.py`, `repositories/operation_plan_repository.py`: 기존 파일과 SHA-256 동일.
- 기존 `services/inventory_planning.py`, `services/operation_plan_service.py`, `api/demo_routes.py`, `api/routes.py`:
  `app`을 `lastplate_backend`로 import하는 이름 변경만 적용. 나머지 내용 동일.
- `main.py`, `core/config.py`: 독립 실행/설정/연결 API를 위해 변경.
- 새 파일: agent_contracts, agent_client, agent_routes, agent_plan_repository 및 관련 테스트/문서.
- 기존 엔진 테스트 5개·API 테스트 1개·운영 테스트 9개를 유지. import/예제 경로/테스트 DB 변수만 조정.
  분리한 모델·UI 전용 테스트는 이 배포본에서 제외하고 연결/오류 테스트 16개를 추가.
- 모델 번들·forecast_service·forecast_routes·UI는 **원본에서 삭제한 것이 아니라 이 배포본에 포함하지 않은 것**입니다.

정확한 비교 해시는 `preservation-check.json`에 있습니다.
별도 검증이 끝난 뒤 새 버전 원본 633개 파일도 다시 해시 비교했고 모두 변하지 않았습니다.

## 직접 실행한 검증

환경: Windows / Python 3.12. 백엔드 전용 새 가상환경에 requirements.txt만 설치했습니다.
lightgbm/pandas/numpy/sklearn/langgraph 없이 `unittest` **31개 통과**.
테스트 DB는 임시 폴더에 격리됩니다. 검증 결과·설치 패키지는 `backend-test-check.json`을 참고하세요.
Starlette의 httpx TestClient 사용 중단 예정 경고가 있으나 실패는 아니며 31개가 모두 통과했습니다.

별도의 검증 전용 환경에서는 제공된 원본 모델 및 native subprocess worker를 실제 실행했습니다.
두 FastAPI의 TestClient를 HTTP transport로 연결했으므로 **계산을 가짜로 대체한 테스트는 아닙니다**.
다만 실제 네트워크 배포·브라우저 UI·운영 모드 검증은 아닙니다. native 모드는 demo, DB는 임시 폴더입니다.

| 시나리오 | 관찰된 결과 | 확인 |
| --- | --- | --- |
| 제공된 lh_like 예제 | HTTP 200, 예측 883, 조리 권장 910, Decision BLOCK | 상태·전체 원본·이력 동일 |
| maximum_input_servings=100 | HTTP 422 PARTIAL, Demand 유지, Operation invalid_input, Decision NEEDS_CONFIRMATION | 부분 결과 소실 없음 |
| 두부 trim_loss_pct=50 | raw_required 145600g, 조리 권장 910 | 수량 의미/단위 그대로 유지 |
| small_site 예제 | 예측 856, 조리 권장 882, OOD/BLOCK | 용량 550으로 임의 절삭하지 않음 |
| 단위 ea | HTTP 422 UNIT_ERROR, 모델 미실행 | 오류 상태·본문 보존 |
| 잘못된 유통기한 | HTTP 422 INPUT_VALIDATION_ERROR, 모델 미실행 | 입력 오류·본문 보존 |
| 같은 request_id로 인사 입력 변경 | HTTP 409 idempotency_conflict | native 충돌 처리 보존 |

7건 모두 native 응답 JSON과 백엔드 응답 JSON 전체가 같고, 저장한 요청·결과도 같았습니다.
실행 요약은 `peer-live-check.json`에 있습니다.

## 나중에 UI·ML 팀과 합의할 점

1. 최종 화면이 새 전체 에이전트 결과를 보여줄지, 기존 배치 조리 시뮬레이션을 별도로 제공할지 정하세요.
   두 계산 결과를 하나의 승인 상태로 합치지 마세요. 기존 배치 잠금 기능은 보존돼 있지만 native 결과에 자동 적용되지는 않습니다.
2. 새 서버의 `event`를 보내는 것만으로 출근인원이나 모든 하위 단계가 자동 갱신되는 것은 아닙니다.
   attendance/재고/정책 입력을 갱신하고 새 request_id로 명시적으로 재요청하는 UI 흐름이 필요합니다.
3. ML 적용 범위 밖 예제는 값이 나오더라도 정확도가 검증된 운영안이 아닙니다. 이번 수정은 모델을 재학습/보정하지 않았습니다.
4. 승인·실제 발주·실재고 예약은 구현하지 않았습니다. native의 advisory_only와 검토 대기 상태를 그대로 표시하세요.
5. 백엔드와 native 서버는 의존성과 DB를 별도로 유지하세요. 구동 명령도 서로 다릅니다.
6. 인증·권한 없는 로컬 시연 범위입니다. 공개 배포 전에 인증, 데이터 격리, 요청 크기/빈도 제한, 오류 관측이 필요합니다.

GitHub push, Pull Request, merge, UI 수정은 이번 작업에서 수행하지 않았습니다.
