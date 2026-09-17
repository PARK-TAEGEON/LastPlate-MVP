# GitHub에 올리기 — 이번 통합본 전용

저장소: https://github.com/PARK-TAEGEON/lastplate

**기존 팀 저장소는 비어 있지 않습니다.** 2026-09-17 확인한 main HEAD는
476961d947645f03a344572834c69e959cfaa91a 입니다. 기존 Streamlit 파일을 보존하기 위해
팀 저장소를 새로 clone한 후, 새 브랜치에 이번 통합 폴더만 추가합니다.
이전과 브랜치/PR 방식은 같지만 **frontend와 backend/ml_bundle이 추가**됐으므로 아래 순서를 사용하세요.
이 작업에서 자동 commit/push는 하지 않았습니다.

## 1. 새 PowerShell 창 열기

서버가 실행 중인 창은 그대로 두세요. 새 PowerShell 창에 아래를 순서대로 입력합니다.
대상 폴더가 이미 있으면 다른 새 이름을 정해 다음 명령의 경로도 같이 바꾸세요.
오류가 나오면 다음 단계로 넘어가지 말고 메시지를 확인하세요.

```powershell
cd C:\Users\hijuh\Desktop
git clone https://github.com/PARK-TAEGEON/lastplate.git lastplate-integration-upload
cd C:\Users\hijuh\Desktop\lastplate-integration-upload
git switch -c feat/operation-ui-ml
```

## 2. 소스만 복사하기

```powershell
& "C:\Users\hijuh\Desktop\est\backend\.venv-runtime\Scripts\python.exe" "C:\Users\hijuh\Desktop\est\scripts\prepare_upload.py" "C:\Users\hijuh\Desktop\lastplate-integration-upload"
git status --short
```

이 스크립트는 backend 소스·테스트·모델·requirements, frontend, 관련 docs/scripts만 복사합니다.
가상환경, SQLite DB, .env, 원본 ZIP, 학습 원자료는 복사하지 않습니다.
팀원의 기존 app.py, graph.py, 루트 requirements.txt, README, .gitignore는 변경하지 않습니다.
대상에 같은 파일이 있으면 덮어쓰지 않고 멈춥니다. 그 경우 오류와 git status 결과를 공유해 주세요.

## 3. 확인하고 커밋·업로드하기

```powershell
git add backend frontend docs/api-contract.md docs/operation-integration.md docs/GITHUB-UPLOAD.md docs/examples/operation-plan-request.json scripts/import_ml_bundle.py scripts/prepare_upload.py scripts/package_release.py
git diff --cached --stat
git status --short
git commit -m "feat: integrate operation API, team UI and LightGBM model"
git push -u origin feat/operation-ui-ml
```

확인 목록: .venv/.venv-runtime, backend/data, .env, 원본 학습자료가 올라갈 목록에 없어야 합니다.
처음 커밋할 때 작성자 정보가 없다는 오류가 나오면 이 저장소에서만 본인의 정보를 설정한 뒤 commit을 다시 실행하세요.

```powershell
git config user.name "본인 이름"
git config user.email "본인 GitHub 이메일 또는 GitHub 비공개 noreply 이메일"
```

push에서 로그인 창이 뜨면 직접 로그인하세요. 비밀번호나 토큰은 채팅에 붙여 넣지 마세요.
403이 나오면 팀 저장소 쓰기 권한(협업자 초대 수락)이 필요합니다.
동일한 원격 브랜치가 이미 있어 push가 거절되면 force push하지 말고 팀원과 브랜치 이름을 조율하세요.

## 4. Pull Request 만들기

1. 팀 GitHub 저장소에서 Compare & pull request를 누릅니다.
2. base: main / compare: feat/operation-ui-ml 을 선택합니다.
3. 제목 예시: Operation 백엔드 + 팀 UI + ML 모델 연결.
4. 설명에 독립 실행 경로, 점 예측 모델 제한, 시연 데이터, 테스트 결과를 적습니다.
5. 팀원이 확인한 다음 Merge합니다. 기존 Streamlit 실행 경로는 그대로 남습니다.

## 팀원이 받아서 실행하는 방법

PR merge 이후 팀원이 최신 main을 pull한 뒤 backend 폴더에서:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. 이 통합 화면에는 Streamlit 명령을 사용하지 않습니다.
모델 파일은 압축본에서 추출된 native text이고 소스와 함께 포함됩니다. 일반 Git으로 올릴 수 있는 크기입니다.
모델과 데이터의 팀 공유·공개 권한은 팀에서 확인하세요.
