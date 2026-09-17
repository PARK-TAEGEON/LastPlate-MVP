# 라플 / LastPlate MVP 1.2 — 월간 급식 운영 계획

계획 생성 → 운영 계획 → 운영 결과의 세 화면으로 구성된 로컬 FastAPI 앱입니다.
기존 네 Agent·실제 모델과 DB 모듈을 유지합니다. UI는 업무 전용 HTTP API만 호출합니다.

월간 식단 CSV/XLSX를 등록하면 모든 등록일의 계획을 일괄 계산합니다. 캘린더에서 날짜별 메뉴와 인원 증감을 수정하고, Agent 권고를 수용·거절할 수 있습니다. 상단에는 라플 로고를 적용했습니다.

## 실행

현재 PC: **LastPlate-실행.cmd**를 더블클릭하면 서버를 켜고 브라우저를 엽니다.
이미 켜져 있으면 실행 중인 앱을 엽니다. 주소: http://127.0.0.1:8000/

다른 PC 또는 새 환경은 Python 3.12에서 아래 설치를 한 번 진행하세요.

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
~~~

별도 프론트 빌드나 외부 LLM 키는 필요 없습니다. 초기 패키지 설치에는 네트워크가 필요합니다.
Windows 실행 파일은 프로젝트의 .venv, 명시한 LASTPLATE_PYTHON 또는 현재 PC에 준비한 공용 환경을 사용합니다.
macOS/Linux는 .venv/bin/python을 사용하세요.

## Railway 배포

FastAPI가 정적 frontend까지 제공하는 단일 Python 서비스입니다. 루트의 `railpack.json`이 Python 3.12와 시작 명령을 지정합니다. `package.json`은 브라우저 테스트 전용입니다.
[Railway 설정·검증·SQLite 영속 저장 안내](docs/RAILWAY.md)를 따라 저장소 루트에서 배포하세요.

## 사용 순서

1. 사업장과 운영 월을 선택합니다. 끼니는 점심으로 고정됩니다.
2. 등록 인원·급식 용량을 확인하고 필요한 근무 현황만 수정합니다.
3. 월간 식단 양식을 내려받아 밥·국·메인반찬·사이드반찬을 등록하고 재고 자료를 확인합니다. 기본 식단도 사용할 수 있습니다.
4. 예정 발주는 필요한 경우 표로 입력합니다. 비워두면 미입력입니다.
5. **월간 운영 계획 생성**을 누릅니다. 실패한 날짜는 다시 계산할 수 있으며 완료된 결과는 보존합니다.
6. 캘린더의 날짜를 클릭해 메뉴, 변경 사유, 증가·감소 인원을 수정하고 **변경사항 반영 · 다시 계산**을 누릅니다.
7. Agent의 기타 사유 해석과 메뉴 권고를 수용하거나 반영하지 않기로 기록합니다. 메뉴 수용은 검토안 재계산이며, **운영 계획 확인**은 열람 기록입니다. 실제 승인·조리량 확정·자동 발주는 수행하지 않습니다.
8. 운영 결과에 실제 측정값을 저장합니다. 측정하지 않은 무게는 비워 둡니다.
9. 정정하기에서 변경값과 사유를 저장합니다. 이전 기록은 감사 이력에 남습니다.

사업장·날짜·저장 계획 버전을 URL과 브라우저 선택 상태로 복구합니다. 결과는 연결한 계획 버전과 비교합니다.
시연 사업장 자료는 실제 측정 근거가 아니며, 자동 학습 집계에서 제외됩니다.
예측값을 등록 인원이나 급식 용량에 맞춰 임의로 보정하지 않습니다.

식단은 등록된 레시피의 메뉴명을 사용합니다. 기타 사유는 기존 Agent가 해석할 수 있는 내용만 수용할 수 있습니다(예: `두부 사용 금지`). 재고는 등록 시점의 공통 자료로 각 날짜를 계산하며 월간 자동 차감·입고 예측을 하지 않습니다.

## 개발자 원문과 API

업무 화면: / 및 /api/ui/*
사업장 설정: /admin, 개발자 화면: /debug (기본 비활성화)

원문 요청/응답·모델 버전·실행 ID·출처·모델 관리 지표·API 문서는 일반 화면에 포함하지 않습니다.
기존 통합 API의 요청/응답 구조는 유지하며, 원문이 나오는 /api/* 경로는 개발자 인증을 추가했습니다.
/api/health와 업무용 /api/ui/*는 제외됩니다. 기존 API 클라이언트에는 아래 인증 설정이 필요합니다.

개발 도구를 사용할 때만 실행하는 터미널에서 환경변수를 지정하세요.

~~~powershell
$env:LASTPLATE_DEBUG='true'
$env:LASTPLATE_DEBUG_TOKEN=[guid]::NewGuid().ToString('N')
# 생성된 비밀번호를 개인적으로 확인하고 보관한 뒤 같은 터미널에서 실행
.\.venv\Scripts\python.exe run.py
~~~

/debug 접속 시 사용자 이름 developer, 비밀번호 LASTPLATE_DEBUG_TOKEN 값을 사용합니다.
끄려면 LASTPLATE_DEBUG=false로 바꾸고 서버를 재시작합니다. .env.example은 설명 파일이며 자동으로 읽지 않습니다.
HTTP 인증은 로컬 개발 도구용입니다. 외부 서비스로 배포하려면 업무 사용자 인증·권한과 HTTPS가 별도로 필요합니다.
[FastAPI HTTP Basic Auth 문서](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/)의 의존성·인증 응답 방식에 따릅니다.

발표 준비 화면에서 기본/소규모/재고 위험 자료를 조회하고 업무 화면을 열 수 있습니다.
등록 인원·급식 용량·안전 여유분·영양·알레르기 정책은 /admin에서 저장합니다.
레시피 기준량과 가격도 /admin에서 표로 조회합니다. 설정 저장 후 계획 생성 화면에서
“등록 자료로 새로 준비”를 누르면 최신 설정·등록 자료를 불러옵니다. 저장 계획은 원래 설정을 보존합니다.
새 레시피·가격 데이터 연결과 다중 사용자별 권한 관리는 별도 배포 작업입니다.

## 저장

기본 DB: data/lastplate.db. LASTPLATE_DB_PATH로 기존 파일을 지정할 수 있습니다.
기존 lastplate_db 모듈의 테이블·검증·KPI·감사 이력 기능을 재사용합니다.
통합 메타데이터는 같은 DB의 api_runs, api_acknowledgements, api_actual_links, api_site_settings에 저장합니다.
api_actual_links는 실측 기록과 선택한 계획을 연결하는 추가 테이블입니다.
api_month_schedules는 월간 식단·날짜별 입력·계획 연결·권고 선택 이력을 보관합니다.
운영 DB, 개인 환경변수와 임시·생성 파일은 저장소에 포함하지 않습니다. 처음 실행하면 새 로컬 DB를 생성합니다.

기존 값과 다른 재저장은 거부합니다. 정정 API는 원본 생성 시각·연결 계획을 유지하고
정정 사유·이전값·새값을 기록합니다. 다른 작업에서 정정했다면 재조회 전 재정정을 차단합니다.
DEMO 구분은 사업장 기록에서 결정합니다. 폐기량 미측정은 null이며 0과 구별됩니다.

계획 저장 실패 시 계산 결과를 유지하고 저장만 재시도할 수 있습니다.
완전히 저장되지 않은 계산의 재시도 정보는 단일 서버 프로세스의 최근 30건까지 보관합니다.
DB에 계획 이력도 저장하지 못한 상태에서 서버까지 종료하면 새 계산이 필요합니다.

## 구조

~~~text
backend/api/workspace.py         업무용 API, 사업장·계획·실측 맥락
backend/api/monthly.py           월간 식단 저장, 날짜별 계산, Agent 권고 검토
backend/application/presentation.py  승인된 업무 필드와 한국어 표시 모델
backend/api/access.py            개발자 도구와 원문 API 접근 제어
backend/api/routes.py            기존 통합 API 계약
backend/application/service.py   기존 Agent orchestration 연결
backend/adapters/persistence.py  저장·정정·정확한 계획 연결
vendor/native/                  원본 Agent 633개 파일
lastplate_db/                   원본 DB v0.3.0
frontend/app.js                  화면·맥락·입력 상태
frontend/monthly.js              월간 캘린더, 일괄 생성, 날짜별 수정
frontend/api/lastplateApi.js     HTTP 호출
frontend/components/cards.js    업무 요약·표·위험·이력 렌더링
developer/                     인증된 원문·발표 준비 화면
~~~

## 검증

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/run_tests.py
.\.venv\Scripts\python.exe -m pytest tests/test_monthly_ui.py -q
npm install
npm run test:browser
~~~

Windows Edge가 있으면 브라우저 검증에 사용합니다.
다른 브라우저 경로는 LASTPLATE_BROWSER_PATH, Python 경로는 LASTPLATE_TEST_PYTHON으로 지정합니다.
브라우저 테스트는 독립 테스트 DB와 서버를 생성하며 사용자 DB를 수정하지 않습니다.
scripts/e2e_server.py의 장애 주입 엔드포인트는 테스트 전용이며 run.py 서버에는 없습니다.

월간 브라우저 검증: scripts/browser-monthly.cjs (16개 시나리오). 기존 API 43개와 신규 월간 API 6개를 검증했습니다.
테스트 실행 결과는 로컬 reports/ 폴더에 생성되며 Git에는 포함하지 않습니다.
개편 변경 설명: docs/UX-UPGRADE.md.
기존 A–R 보고서 docs/FINAL-REPORT.md와 v1 브라우저 증빙은 이전 버전의 기록입니다.
