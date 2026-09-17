# Confidence 정책과 실패 근거 (v0.1.2)

confidence는 **선택된 현재 운영 권고안을 검토·사용할 근거의 완전성과 품질**입니다. 모델 정답 확률이나 “차단 진단이 확실하다”는 점수가 아닙니다. MAE를 확률로 환산하지 않습니다. 승인 권한은 status와 최신 권고 revision으로 별도 검사합니다.

| 조건 | confidence | 근거 |
|---|---|---|
| 현재 계획 Hard Constraint FAIL | LOW | 실제 실패 항목 및 생성 constraint_violation. status=blocked, 인분 null |
| 필수 근거/의존 revision 누락·불일치, 미완료 보고서, 미해결 요청 | LOW | status=needs_confirmation 및 구체적 validation 노트 |
| 해결되지 않은 callback 실패 | LOW | WORKFLOW_FAILURE. workflow 노트와 confidence에 같은 실패 반영 |
| 검증된 현재 계획 + 관련 HIGH/CRITICAL 공급/alert, DEMO/SIMULATION/UNKNOWN, limitations | MEDIUM | 위험 또는 적용 가능한 출처·제한 근거. HIGH supply만으로 임의 unavailable 판정하지 않음 |
| 필수 검증 완료 + 위 위험/품질 제한 없음 | HIGH | 필수 근거·소비 의존·Hard Constraint 검증 통과 |
| 무관한/비선택 탈락 대안의 FAIL·DEMO | 현재 계획을 자동 하향하지 않음 | 탈락 후보·critical alert 자체는 보존. 해당 quality_record의 affects_confidence=false |
| REAL 출처, 정상 ML 운영 모드 설명, callback 미연결이나 유효한 제공 결과 | 하향 사유 아님 | provenance_notes로 정보 분리. 누락 결과는 별도 보류 규칙 적용 |

`source_type=simulation` 단독으로도 MEDIUM 및 SIMULATION 표시가 생깁니다. DEMO, DEMO:, SIMULATION:, UNKNOWN의 공백·대소문자를 정규화합니다. REAL 설명에 DEMO라는 단어가 포함되어도 REAL 접두어를 존중합니다. UNKNOWN에는 잘못된 DEMO 행동 라벨을 붙이지 않습니다.

`quality_records`가 출처·범위·warning·affects_confidence를 기록합니다. 이 레코드로 data_quality_notes와 confidence를 함께 계산하며, 계산 뒤 workflow 경고를 덧붙여 불일치를 만들지 않습니다. callback 복구 성공 시 활성 실패 노트를 해소하지만 workflow_trace의 과거 실패 기록은 유지합니다. 재실행 결과가 오래되면 검증/요청이 남아 LOW입니다.

## 실행된 합성 예시

| 입력 변경 | 결과 | confidence_reasons 발췌 |
|---|---|---|
| nutrition_constraints.status=FAIL | blocked / LOW / null | 현재 계획 Hard Constraint FAIL: nutrition |
| constraints.allergy=FAIL | blocked / LOW / null | 현재 계획 Hard Constraint FAIL: allergy |
| 현재 두부 supply HIGH (unavailable 아님) | ok / MEDIUM | 현재 계획 supply_risk HIGH |
| source_type=simulation | ok / MEDIUM | SIMULATION 출처: simulation |
| Operation이 old Demand revision 소비 | needs_confirmation / LOW / null | demand_forecast 소비 의존 근거 누락/불일치 |
| 정상 검증 + REAL:ERP | ok / HIGH / 523 | 현재 계획의 필수 근거·소비 의존성·Hard Constraint 검증 통과 |

전체 출력은 [CONFIDENCE_EXAMPLES.json](../verification/CONFIDENCE_EXAMPLES.json)입니다. 여기의 수치와 PASS는 합성 fixture이며 실제 운영 적격성을 증명하지 않습니다. blocked/보류 결과에는 “검증 통과” fallback 이유가 붙지 않습니다.
