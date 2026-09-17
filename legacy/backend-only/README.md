# LastPlate 백엔드 전용 — v0.2.0

이 폴더만 백엔드 결과물입니다. UI, ML 모델, 학습 데이터, 팀원의 에이전트 구현은 포함하지 않습니다.
검토 대상은 `lastplate-integrated-v0.1.2`이며, 그 폴더와 기존 백엔드 원본은 수정하지 않았습니다.

## 무엇을 유지하고 바꿨나요?

- 기존 조리 판단 엔진, 입력 스키마, 기존 운영안 저장 로직은 원본 그대로입니다.
- 기존 서비스·운영 API는 Python import 경로만 변경했습니다.
- 패키지 이름을 `app` → `lastplate_backend`로 바꿔 팀원 서버의 `app`과 충돌하지 않게 했습니다.
- 모델 직접 실행·UI 제공 부분은 이 배포본에서 제외했습니다.
- 새 에이전트 서버에 요청하고 결과를 그대로 저장·조회하는 별도 API를 추가했습니다. 아직 서버를 연결하지 않아도 기존 조리 엔진은 실행됩니다.

## 1. 백엔드만 실행하기

이 README와 `requirements.txt`가 있는 **backend 폴더에서** PowerShell을 열고 입력하세요.
Python 3.12로 검증했습니다. 가상환경 활성화가 필요 없는 명령입니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn lastplate_backend.main:app --host 127.0.0.1 --port 8000
```

다른 서버가 8000을 쓰면 그 서버를 종료하거나 `--port 8002`로 실행하세요.
브라우저에서 <http://127.0.0.1:8000/docs>를 엽니다. 홈(`/`)은 웹 UI가 아니라 서버 정보 JSON입니다.
종료는 서버가 실행 중인 PowerShell에서 `Ctrl+C`입니다.

Swagger에서 `GET /api/v1/demo/input`의 결과를 복사해 `POST /api/v1/operation-plans`에 넣으면
ML 없이 기존 인원 변동·조리·발주 추천 기능을 확인할 수 있습니다.
별도 예제는 [docs/examples/operation-plan-request.json](docs/examples/operation-plan-request.json)에 있습니다.

테스트는 새 PowerShell에서 같은 backend 폴더로 이동한 뒤 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 2. 나중에 팀원 서버와 연결하기

지금 파일을 합치거나 ML 파일을 이 폴더에 복사할 필요는 없습니다.
팀원의 v0.1.2 서버가 별도 환경에서 `http://127.0.0.1:8001`로 실행된 뒤,
백엔드 PowerShell에서 아래처럼 주소만 지정하고 서버를 재시작하세요.

```powershell
$env:LASTPLATE_AGENT_BASE_URL = "http://127.0.0.1:8001"
.\.venv\Scripts\python.exe -m uvicorn lastplate_backend.main:app --host 127.0.0.1 --port 8000
```

이후 UI는 백엔드의 `POST /api/v1/agent-plans`를 호출합니다.
백엔드는 별도 에이전트 서버의 `POST /api/plan`에 전달하고, 응답을 수정 없이 저장·반환합니다.
이 연결 방식을 위한 준비만 했으며, 두 프로젝트를 merge하거나 GitHub에 업로드하지 않았습니다.

두 계산 경로는 자동 연결되지 않습니다.

| 사용할 기능 | UI가 호출할 백엔드 API |
| --- | --- |
| 기존 배치 조리·인원 변동 시뮬레이션 | `/api/v1/operation-plans` |
| 새 Demand → Operation → Inventory → Decision 전체 결과 | `/api/v1/agent-plans` |

새 에이전트 결과를 기존 엔진에 다시 넣으면 안전여유·재고·정책을 중복 적용할 수 있으므로 자동 재계산하지 않습니다.
새 에이전트의 인원 변경은 입력을 갱신하고 **새 request_id**로 전체 요청하세요.
자세한 필드와 UI 처리 규칙은 [docs/API.md](docs/API.md)를 팀원에게 전달하면 됩니다.

## 3. 설정·주의사항

- 백엔드 DB 기본 위치: `backend/data/backend.sqlite3`. 실행할 때 생성되며 전달 파일에는 없습니다.
- 변경: `$env:LASTPLATE_BACKEND_DATABASE_PATH = "C:\경로\backend.sqlite3"`. 팀원 ML DB와 다른 파일을 사용하세요.
- 이전 `LASTPLATE_DATABASE_PATH`도 호환되지만 새 변수 설정이 우선합니다.
- UI 포트가 3000/5173이 아니면 `LASTPLATE_CORS_ORIGINS`에 정확한 UI 주소를 쉼표로 나열하세요. HTML 파일 직접 열기(`file://`)보다 개발 서버를 사용하세요.
- `LASTPLATE_AGENT_TIMEOUT_SECONDS` 기본 600초. 단계별 처리가 오래 걸릴 수 있어 자동 재시도하지 않습니다.
- `.env.example`은 설명용입니다. `.env`로 복사만 해서는 자동 적용되지 않습니다. 위 PowerShell 환경변수 방식을 쓰세요.
- `/api/v1/integration`의 configured는 주소 설정 여부이지 실제 서버 접속 성공 여부가 아닙니다.
- 새 에이전트 서버를 설정하지 않은 `/agent-plans` 요청은 503입니다. 백엔드 자체의 오류가 아니라 아직 연결하지 않았다는 뜻입니다.
- 인증 없는 로컬 개발·시연용입니다. 인터넷에 공개하지 마세요. 실서비스에는 인증·사업장별 접근권한·입력 제한·실제 승인/발주 절차가 추가로 필요합니다.
- 모든 결과는 운영자 검토용입니다. `COMPLETE`나 HTTP 200은 조리/발주 승인 완료를 뜻하지 않습니다.

## 검증 결과

Windows / Python 3.12에서 백엔드 테스트 31개 통과.
ML 라이브러리 없는 환경에서 독립 실행·기존 엔진을 확인했고, 별도의 검증 환경에서
팀원의 실제 ML·에이전트를 실행하는 호환 시나리오 7개도 통과했습니다.
전체 파일 검사 범위·수정 이유·한계는 [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)에 기록했습니다.
