# 저장소·장애 복구

## 운영 저장

서버는 명시적 storage_dir 아래의 `operation/service.sqlite3`, `replay/service.sqlite3`, `demo/service.sqlite3`를 각각 사용합니다. 새 API는 과거 `data/operational_history.csv`에 쓰지 않습니다. prediction 요청 키는 DB UNIQUE 제약으로 중복을 막고 입력 해시 충돌을 별도 오류로 반환합니다. 실제값과 수정 이벤트는 하나의 트랜잭션으로 저장합니다. 동일 요청 재시도는 그 요청의 원래 결과를 반환합니다. 수정 뒤 과거 요청을 재시도해도 최신값으로 바꿔 반환하지 않습니다.

정정은 새 request_id, current expected_revision, correction_reason, 인증된 서버 actor가 필요합니다. 이전 값, 새 값, revision, 요청 키, 서버 기록 시각이 actual_events에 남습니다. 하루 한 기관의 중식 1건을 전제로 하므로 다른 예측 ID로 같은 날 실적을 또 등록하지 않습니다.

SQLite WAL, synchronous=FULL, 쓰기 트랜잭션, 스키마 초기화 잠금을 사용합니다. 분산 서버가 공유 네트워크 파일시스템으로 SQLite를 접근하는 배포는 검증하지 않았습니다. DB 접근 권한과 인증은 서비스 배포가 담당합니다.

## 배치 정책

기본값은 신규 60건, 미래 gate 30건, 새 학습용 최소 10건, 최소 개선 **max(5명, 기존 MAE의 2%)**입니다. 이 폭을 **엄격히 초과**해야 승격하므로 동점과 경계값은 유지합니다. 설정에서 평가 건수를 바꿀 수 있으나 10건 미만은 거절합니다. 작은 표본으로의 변경은 통계적 불안정을 키울 수 있습니다. 자동 유의성 검정은 수행하지 않습니다.

count/weekly/monthly/manual은 명시적 관리자 명령입니다. weekly는 직전 시도 후 7일, monthly는 30일 조건입니다. 최초 실행에는 시도 이력이 없어 신규 자료 요건으로 판단합니다. 실제 OS 스케줄러는 등록하지 않았습니다. 예측 요청 경로에서 재학습하지 않습니다.

## 복구 상태

`models/retrain.sqlite3`의 runs와 consumed_dates가 권위 있는 실행 기록입니다. 보고서는 재생성 가능한 뷰입니다.

1. `reserved`: 모델 평가 전에 gate 날짜와 hash를 영속적으로 예약합니다. 이미 예약한 날짜는 실패해도 다시 쓰지 않습니다.
2. `evaluated`: 점수·날짜별 예측·승격 여부를 SQLite에 저장합니다. 기존 모델과 challenger가 보지 않은 같은 미래 날짜로 평가합니다.
3. `prepared`: 승인된 전체 자료 재학습 release를 완성했습니다. 불완전 파일은 staging에만 남습니다.
4. `committed`: 단일 current 포인터를 전환했습니다. 포인터 전환은 해당 버전이 이미 current이면 멱등적으로 완료됩니다.
5. `kept`: 탈락 모델이므로 기존 포인터 유지. `interrupted`: 평가/완전 모델 저장이 끝나기 전에 중단되어 기존 포인터 유지. `conflict`: 다른 모델이 이미 전환되어 강제 교체하지 않음.

평가 없이 중단되면 interrupted로 표시하고 gate는 소모 상태로 남깁니다. 평가가 완료되고 완전한 후보 release도 있으면 복구 시 동일 후보를 한 번만 활성화합니다. 포인터만 이미 바뀐 경우도 같은 버전을 인식합니다. 보고서 경로 장애는 복구 후 같은 ledger에서 보고서를 재생성하며 재학습이나 평가 구간 재사용을 하지 않습니다.

```powershell
python -m ml.retrain --config C:/LastPlate/service.json --base-path C:/LastPlate/data/processed/lunch.csv --report-dir C:/LastPlate/retraining-reports --recover-only
```

동시 배치는 파일 잠금으로 직렬화하고, 활성화 직전 기대 incumbent 버전을 검사합니다. 원자적 rename, 파일 flush/fsync와 SQLite 트랜잭션을 사용합니다. 실제 전원 차단·디스크 손상·네트워크 파일시스템까지 검증한 것은 아닙니다. 테스트는 코드 경계에서 예외 주입, 보고서 I/O 실패, SQLite 이벤트 삽입 실패를 재현했습니다.

전체 자료 재학습본은 gate 평가 모델과 다른 fit입니다. gate MAE를 그 재학습본의 독립 성능이라고 표현하지 않습니다. 새 운영 결과로 검증해야 합니다.
