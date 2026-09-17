# Inventory & Risk Agent v0.2.3 수정 보고

## 1. 수정 파일

- `tools/events.py`: 제외 표현, 해제 우선 탐색, 연결어 및 미처리 꼬리 검증, 같은 날짜 범위의 마지막 의도 적용, trace.
- `tools/ingredients.py`: 추가 표현에서도 등록 식재료 조회를 수행.
- `schemas/event.py`: release event type, action, superseded, parsing decision_trace 추가 및 검증.
- `agents/inventory_risk.py`: 파싱 trace를 기존 보고 trace로 전달하는 한 줄 변경. Agent 구조는 유지.
- `tools/identity.py`: 새 필드의 기본값은 기존 이벤트 ID 계산에서 제외하여 v0.2.2의 안정된 ID 유지.
- `tests/test_release_and_residual.py`: 독립 회귀 48개 추가. 기존 테스트 변경 없음.
- `pyproject.toml`, `README.md`, `VALIDATION.md`: 버전 및 계약/검증 기록.
- 증빙: `examples/release-test-results.xml`, `release-cases.json`, `release-manifest.json` 및 이 보고서.

## 2. 두 P1의 원인

제외 술어가 `빼주세요` 일부 형태에 한정되어 띄어 쓴 표현과 제외 동의어를 읽지 못했습니다. 긍정 금지 패턴이 `금지 해제` 안의 `금지`를 먼저 소비하여 신규 restriction으로 반전시켰습니다. 절에서 이벤트 하나를 찾으면 남은 꼬리를 확인하지 않는 경로도 있었습니다.

## 3. 해제/취소 우선 및 충돌 정책

같은 정규식의 첫 번째 대안에 release 패턴을 둡니다. `ingredient_restriction_release_event`는 `action=release_restriction`이며 신규 금지 값을 갖지 않습니다. `빼지 마세요`와 `제외하지 마세요`도 해제로 인식합니다.

입력 순서가 명시된 문자열에서 정규화된 같은 품목·같은 date/end_date에는 마지막 명시적 의도를 적용합니다. 이전 이벤트는 superseded로 남고 원문 및 두 이벤트의 변화가 decision_trace에 남습니다. 기존 applies 검사에서 superseded를 제외하므로 재고·영향·대체 후보 검토에 취소된 금지가 재적용되지 않습니다. 해제 뒤 재금지도 보존합니다. 다른 날짜 범위는 덮어쓰지 않으며, 날짜/등록 품목이 불확실하면 기존 확인 상태를 유지합니다.

해제는 현재 분석의 자문 상태입니다. 실제 운영 제한 삭제나 사용 승인, 최종 메뉴·발주 자동 실행은 하지 않습니다.

## 4. residual 처리

지원 제한 술어의 마지막 끝 이후 꼬리를 검사합니다. 미인식 절은 그대로 unparsed_segments에 남깁니다. 인원·기한 표현 역시 지원 문법 뒤의 의미 있는 꼬리를 확인합니다. 알려지지 않은 재료 구간은 기존 미등록 warning과 확인 상태를 유지합니다. 연결어 단어 전체와 구두점만 있는 경우에만 무시하므로 뒤의 ‘재고도 알아서 처리해 주세요’를 삭제하지 않습니다. ‘그리고요’는 ‘그리고’보다 먼저 절 경계로 인식합니다.

## 5. 신규 테스트

48개: 요청 TEST 1–8, 제외 동의어 9개, 해제 표현 8개, 연결어/구두점 8개, 의미 있는 residual 6개, 재금지, 다른 날짜, 미등록 해제, full/event 보고 및 재고/후보 격리 비교, 구조화 이벤트 검증, 기존 ID 보존, 부모 LangGraph 및 실제 Streamlit AppTest.

날짜 없는 TEST 2–8의 일부는 기존 날짜 확인 계약에 따라 needs_clarification입니다. 연결어가 원인인 partial은 발생하지 않습니다. 날짜를 제공한 지원 표현은 ok로 검증했습니다.

## 6. 실행 결과

변경 전 192 passed. 변경 후 기존 192개와 신규 48개를 모두 실행하여 **240 passed, 실패 0, skip 0**입니다. 전체 명령은 `python -m pytest -q tests --junitxml=examples/release-test-results.xml`입니다. 실제 XML과 8개 요청 예문의 출력 JSON을 동봉했습니다.

## 7. 회귀 여부

테스트 범위 내 기존 기능 회귀는 발견되지 않았습니다. 복합 이벤트, normalization, 중복 식단 검증, LangGraph routing, parent 및 Streamlit integration을 포함합니다. 기존 테스트 파일, 그래프, Streamlit UI, DEMO 데이터는 v0.2.2 ZIP과 동일함을 확인했습니다. 신규 테스트에서 발견한 ‘그리고요’ 분리 문제를 수정한 뒤 전체 재실행했습니다. 해제 테스트는 공급 이벤트를 제거하고 release-only 분석과 재고·후보 결과를 비교하여 다른 위험이 금지 적용 오류를 가리지 않게 했습니다.

호환 변경은 이벤트/파싱 결과의 추가 필드와 release event type입니다. 기존 이벤트 ID는 새 필드가 기본값이면 유지됩니다. 외부 소비자가 이벤트 enum을 고정했으면 release 유형과 superseded 표시를 수용해야 합니다.

## 8. 남은 parser 제한

결정론적 지원 문법만 처리합니다. 자유로운 생략·대명사·이중부정·새로운 날짜 범위·모든 한국어 표현을 이해하지 않습니다. 지원되지 않는 형식에는 보수적인 partial/확인 요청이 가능합니다. 서로 다른 날짜 범위의 제한/해제를 합성하거나 이전 대화·저장된 제한 상태를 조회/수정하는 기능은 추가하지 않았습니다. 기존 입력 API는 문자열 또는 단일 구조화 Event이며 임의 이벤트 배열 API는 도입하지 않았습니다. 실제 API 및 timeout 구조화는 이번 범위 밖입니다.

## 9. MVP 통합 가능 여부

기존 자문용 호출 및 부모 그래프 결합은 테스트 범위에서 가능합니다. UI/Graph 구조/Decision Agent는 수정하지 않았고 LLM parser·API 연동은 추가하지 않았습니다. 해제는 명령 실행이 아닌 분석 결과입니다. DEMO 데이터는 실제 API 또는 기관 영양 기준 검증 결과가 아닙니다. 기존 승인 경계를 유지하며 외부 소비자는 추가된 이벤트 필드를 처리해야 합니다.
