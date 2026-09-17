# Railway 배포

FastAPI가 `/`, `/assets/*`, `/api/*`를 함께 제공하는 단일 서비스입니다. Backend, Agent, SQLite 로직 및 모델 파일은 변경하지 않습니다.

## 저장소 설정

- `railpack.json`: provider를 `python`으로 고정합니다. Python 3.12에서 기존 `requirements.txt`를 자동 설치하고, ML 패키지에 필요한 Linux OpenMP 런타임 `libgomp1`을 최종 이미지에 포함합니다.
- 시작 명령: `python run.py --host 0.0.0.0`. `run.py`가 Railway의 `PORT`를 직접 읽으므로 셸의 `$PORT` 치환에 의존하지 않습니다. 워커는 1개로 유지합니다.
- 로컬에서 `PORT`가 없으면 기존 `127.0.0.1:8000`을 유지합니다. `--host`, `--port`를 직접 주면 우선 적용합니다.
- `requirements.txt`의 고정 버전은 저장된 모델의 의존성 정보와 호환되도록 유지합니다. `requirements-dev.txt`와 `package.json`의 Playwright는 배포에 필요하지 않습니다. 별도 frontend 빌드도 없습니다.
- Procfile/Nixpacks 설정은 중복 추가하지 않습니다. 현재 Railway는 Railpack을 사용합니다. `railway.json` 방식은 공식 문서에서 폐기 예정으로 안내하므로 빌드 설정은 `railpack.json`, 서비스 설정은 대시보드를 사용합니다.

## Railway 대시보드

| 항목 | 값 |
| --- | --- |
| Source | 이 수정이 포함된 GitHub 브랜치 |
| Root Directory | 비움 또는 `/` (저장소 루트) |
| Builder | Railpack |
| Custom Build Command | 비움 — `requirements.txt` 자동 설치 |
| Custom Start Command | 비움 — `railpack.json` 사용. 직접 입력한다면 `python run.py --host 0.0.0.0` |
| Healthcheck Path | `/api/health` |
| Healthcheck Timeout | 기본값 300초 |
| Replicas | 1 |

이전에 입력한 `npm` 빌드/시작 명령은 지우세요. `RAILPACK_INSTALL_CMD`, `RAILPACK_BUILD_CMD`, `RAILPACK_START_CMD`, `RAILPACK_PYTHON_VERSION`, `RAILPACK_CONFIG_FILE`을 이미 설정했다면 이 구성과 충돌하는 값을 제거하세요. `PORT`는 Railway가 제공하는 값을 사용하며 별도로 고정할 필요가 없습니다. Public Networking에서 도메인을 생성하고 대상 포트는 실제 서버의 `PORT`와 일치시킵니다. 변경 적용 후 Deploy를 실행하세요.

`Could not load branches`가 계속되면 Railway의 GitHub 연결 및 GitHub App의 저장소 접근 권한을 확인하세요. 소스 빌드 설정과 별개의 연결 문제입니다.

## SQLite 영속 저장

데이터를 보존하려면 **같은 서비스에 Volume을 추가**하고 마운트 경로를 `/data`로 지정한 뒤 아래 변수를 설정합니다.

```text
LASTPLATE_DB_PATH=/data/lastplate.db
LASTPLATE_MODE=demo
LASTPLATE_DEBUG=false
```

환경변수는 Railway Variables에 입력합니다. `.env.example`은 자동으로 읽지 않습니다. Volume 없이 기본 `data/lastplate.db`를 사용하면 재배포 시 데이터가 사라질 수 있습니다. 기존 DB가 있다면 먼저 백업한 뒤 별도로 Volume에 옮겨야 하며, 경로 변경만으로 기존 데이터가 이동하지는 않습니다. Volume은 백업을 대체하지 않습니다.

현재 구조는 SQLite와 프로세스 내 재시도 상태를 사용하므로 단일 복제본·단일 워커로 운영합니다. 재시작하면 메모리에만 남아 있던 작업/재시도 상태는 사라질 수 있습니다.

## 배포 검증

1. Build 로그에서 Python 3.12와 `requirements.txt` 설치 성공을 확인합니다. Node/Playwright 설치나 frontend 빌드는 필요하지 않습니다.
2. Deploy 로그에서 `Uvicorn running on http://0.0.0.0:<PORT>`와 healthcheck 성공을 확인합니다.
3. 배포 도메인으로 아래 요청이 모두 HTTP 200인지 확인합니다.

   ```sh
   curl -fsS https://YOUR-DOMAIN/api/health
   # {"status":"ok"}
   curl -fsS -o /dev/null https://YOUR-DOMAIN/
   curl -fsS -o /dev/null https://YOUR-DOMAIN/assets/app.js
   curl -fsS https://YOUR-DOMAIN/api/ui/sites
   ```

4. 브라우저에서 시연 사업장을 선택해 하루 계획 생성·저장·재조회를 확인합니다. `/api/health`는 프로세스 응답 확인용이므로 실제 모델 로딩이나 DB 저장 성공을 보장하지 않습니다.
5. 테스트 기록을 저장하고 재배포한 뒤 같은 기록이 조회되는지 확인합니다. 실패하면 Volume 마운트 및 `LASTPLATE_DB_PATH`부터 확인하세요.

ML 패키지 때문에 이미지가 크고 계획 계산에는 메모리가 필요합니다. Railway 로그에서 OOM/강제 종료가 발생하면 서비스 메모리 한도를 확인하세요. 업무용 `/api/ui/*`에는 사용자 인증이 없으므로 실제 운영 데이터 공개 서비스에는 별도 인증·권한 설계가 필요합니다. 이번 변경은 배포 설정에 한정합니다.

공식 문서: [Railpack 구성](https://railpack.com/config/file), [Python 의존성 설치](https://railpack.com/languages/python), [Railway 빌드 설정](https://docs.railway.com/builds/build-configuration), [Config as Code 지원 안내](https://docs.railway.com/config-as-code/reference), [Volumes](https://docs.railway.com/volumes).
