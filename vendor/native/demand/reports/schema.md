# 데이터 schema

원본 train.csv 기준 1,205행입니다. 원본 날짜/메뉴는 문자열이며 전처리 날짜는 datetime, 모델 숫자 입력은 float로 통일합니다. 원본의 모든 컬럼을 아래에 기록합니다.

| 원본 컬럼 | 원본 dtype | NaN | 공백 | 내부명 | 사용 |
| --- | --- | --- | --- | --- | --- |
| 일자 | str | 0 | 0 | date | 날짜 파싱, 시간 split과 요일 산출 |
| 요일 | str | 0 | 0 | weekday | 날짜로 교정/검증, B/C 원핫 |
| 본사정원수 | int64 | 0 | 0 | employees | A/B/C 필수 |
| 본사휴가자수 | int64 | 0 | 0 | vacation | A/B/C 필수 |
| 본사출장자수 | int64 | 0 | 0 | business_trip | A/B/C 필수 |
| 본사시간외근무명령서승인건수 | int64 | 0 | 0 | overtime | A/B/C 필수, 인원 아닌 승인 건수 |
| 현본사소속재택근무자수 | float64 | 0 | 0 | work_from_home | A/B/C 필수 |
| 조식메뉴 | str | 0 | 0 | 원본 보존 | 현재 제외 |
| 중식메뉴 | str | 0 | 0 | menu | C의 키워드 지표 |
| 석식메뉴 | str | 0 | 4 | 원본 보존 | 현재 제외, 공백 4건 |
| 중식계 | float64 | 0 | 0 | actual_diners | 예측 타깃, feature 제외 |
| 석식계 | float64 | 0 | 0 | dinner_diners | 참고 타깃, feature 제외 |

파생값 available_population은 정원-휴가-출장-재택, participation_rate는 actual_diners/available_population입니다. 모두 설명용으로 보존하며 A/B/C 입력에는 추가하지 않습니다. 요일 원핫 7개는 날짜에서 결정되고, 메뉴 지표 6개는 원본 메뉴에서 고정 규칙으로 추출됩니다. 측정하지 않은 선호도나 행사값을 생성하지 않습니다.

## 날씨 원본

| 컬럼 | 결측 건수 |
| --- | --- |
| 지점 | 0 |
| 지점명 | 0 |
| 일시 | 0 |
| 기온(°C) | 10 |
| 강수량(mm) | 1648 |
| 습도(%) | 0 |

일자 73개, 시간관측 1,728건. 원본 파일은 cp949로 읽습니다. 일자별 temp_mean/temp_max/temp_min/precipitation/humidity/rain과 station/observed_hours로 집계합니다. rain은 양수 강수 관측이 있으면 1, 완전 관측 전체가 0일 때만 0, 그 외 미상입니다. 기온/습도 일요약은 24시간 비결측일 때만 산출합니다.
