# LastPlate · UI + Operation API + ML 통합본

팀원의 HTML UI, Python 운영 판단 엔진, 첨부 LightGBM 모델을 연결한 **로컬 해커톤 시연용** 프로젝트입니다.
기존 팀 저장소의 Streamlit app.py는 수정하지 않습니다. 이 웹 UI는 별도로 FastAPI가 제공합니다.

## 이 컴퓨터에서 바로 실행

현재 작업 폴더에는 테스트된 Python 환경이 이미 있습니다. PowerShell에서:

```powershell
cd C:\Users\hijuh\Desktop\est\backend
.\.venv-runtime\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. API 문서는 http://127.0.0.1:8000/docs 입니다.
서버가 이미 실행 중이면 명령을 중복 실행하지 말고 화면만 여세요. 종료는 실행한 창에서 Ctrl+C입니다.
HTML을 더블클릭하거나 Streamlit으로 실행하는 방식이 아닙니다.

## 다른 팀원 / 압축 해제 후 처음 실행

일반 Windows CPython 3.12를 설치한 환경에서 프로젝트의 backend 폴더로 이동한 다음:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

가상환경 활성화는 필요 없습니다. MinGW Python 대신 일반 CPython을 사용하세요.
macOS/Linux는 python3.12 -m venv .venv 후 .venv/bin/python을 사용합니다.
Linux에서 libgomp.so 오류가 있으면 OS의 OpenMP 런타임 설치가 필요합니다.

## 연결 구조

```text
frontend/index.html + app.js
          │ 같은 서버로 HTTP JSON 요청
          ▼
FastAPI (backend/app/main.py)
  ├─ LightGBM native model → 기준 식수 예측
  ├─ Python engine → 인원변동 / 배치잠금 / 재고 / 발주 / 제약 검사
  └─ SQLite → 입력·결과·변동 이력·시연 검토 상태 저장
```

- frontend/: 팀원 UI 디자인을 유지하며 API 호출을 연결한 화면
- backend/app/engine/decision_engine.py: 프레임워크에 독립적인 운영 계산
- backend/app/services/forecast_service.py: 첨부 모델과 정확히 같은 feature 처리
- backend/ml_bundle/: 실제 모델 텍스트, 해시·버전·전처리 기준, 원본 스모크 입력
- backend/tests/: API·엔진·모델 통합 테스트
- docs/api-contract.md: 프런트엔드·ML 팀의 API 계약
- docs/operation-integration.md: 변경점·검증·한계·발표 시나리오
- docs/GITHUB-UPLOAD.md: 기존 팀 GitHub에 브랜치와 PR로 올리는 절차
- scripts/prepare_upload.py: 허용된 소스만 복사, 기존 대상 파일은 덮어쓰지 않음
- scripts/package_release.py: 가상환경·DB·비밀값 없이 배포 ZIP 생성

## 화면 사용

1. 처음에는 UI 예시 식수 480명, 권장량 510식이 표시됩니다. 모델 실행 결과가 아닙니다.
2. 운영 홈에서 출장 -35명 같은 **추가** 변동을 입력합니다. 취소하면 기준 예측에서 재계산합니다.
3. 조리계획에서 실제 ML 추론을 실행하거나 적용 조리량·안전여유·시뮬레이션 시각을 변경합니다.
4. 재고·발주에서 기한순 배정, 예약 제외, 포장 단위 발주, 납기 경고를 확인합니다.
5. 검토 완료는 DB에 시연 상태만 저장합니다. 발주 전송이나 재고 차감은 하지 않습니다.
6. 급식톡은 저장된 결과를 규칙 기반으로 설명합니다. LLM/RAG 연결을 가장하지 않습니다.

## 꼭 알아둘 제한

- ML은 중식 **점 예측** 모델입니다. P95/90% 구간/부족 확률 5%는 제공하지 않습니다.
- 학습자료의 예정 출근인원은 1,372~2,921명입니다. UI의 520명 예시 사업장은 적용 범위 밖입니다.
  실제 실행 시 이 입력에서 924명이 예측될 수 있으며, 범위 밖/정원 초과 경고를 표시합니다.
  작은 사업장에 적합한 정확도를 보장하지 않으며 사업장별 재학습·검증이 필요합니다.
- 첨부 ML v2 전체 운영 시스템의 HR 확보시각 검증, 실측 모니터링, 재학습 파이프라인은 이 웹 시연에 통합하지 않았습니다.
  현재 mode는 demo_inference, operational_eligible은 false입니다.
- 재고·레시피·납기·운영 기준은 시연 입력입니다. 영양 제약은 API로 받은 명시적인 기준만 검사합니다.
- 인증/사용자별 권한/실제 발주/실재고 예약이 없는 로컬 시연입니다. 외부 공개 배포용이 아닙니다.
- UI 시계는 실제 현재시각이 아니라 고정된 한국시간 시뮬레이션입니다.

## 테스트

backend 폴더에서:

```powershell
.\.venv-runtime\Scripts\python.exe -m unittest discover -s tests -v
```

새로 설치한 팀원은 .venv-runtime 대신 .venv를 사용합니다.
모델 원본 스모크 예측 1,034명 일치, 예약/기한 재고, 납기/용량, 이벤트 취소,
수동 조리량, 충돌 409, 최소 제공량/영양 기준을 검사합니다.

## GitHub

**기존 저장소는 비어 있지 않습니다. est에서 새 이력을 main으로 직접 push하지 마세요.**
docs/GITHUB-UPLOAD.md의 clone → 브랜치 → 선별 복사 → commit → push → PR 순서를 사용하세요.
UI와 모델 파일이 추가됐으므로 이전 백엔드 전용 복사 절차 대신 새 안내를 따르세요.
