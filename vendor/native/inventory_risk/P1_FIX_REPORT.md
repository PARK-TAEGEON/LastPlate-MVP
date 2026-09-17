# v0.2.1 P1 수정 보고

## 1. 수정한 파일

- `tools/events.py`: 절별 복합 이벤트 추출, 원문, partial/미해석 구간, 호환 list API.
- `tools/ingredients.py` (신규): 공백/casefold/NFKC 및 명시적 별칭 등록 매칭.
- `config.py`: 별칭 설정, 중복/미등록 경고 severity.
- `schemas/event.py`, `schemas/risk_report.py`: 파싱 상태·출처·경고의 추가 필드.
- `agents/inventory_risk.py`: 등록 목록 결합, 복합 이벤트 routing 조건, warning 전달 및 재실행 차단.
- `graph/inventory_risk_workflow.py`: 기존 노드/edge 구조를 유지하며 두 state 채널만 추가.
- `adapters/inventory_adapter.py`: 주간 식단 복합키 중복 검증 및 clean copy.
- `tools/identity.py`: 새 provenance 필드를 이벤트 ID 계산에서 제외해 기존 ID 안정성 유지.
- `examples/forecast_wrapper.py`, `examples/streamlit_app.py`: 진단 전달, partial/경고 표시.
- `tests/test_p1_fixes.py` (신규): 36개 테스트.
- `pyproject.toml`, `README.md`, `VALIDATION.md`: 패치 버전 0.2.1 및 상태/중복 정책 문서.

원본은 `lastplate-inventory-risk-v0.2.0.zip`입니다. SHA256·정확한 수정/추가 파일 목록은 `examples/p1-manifest.json`에 기록했습니다. 분석 구조를 다시 설계하거나 가격·영양·대체 후보 계산을 리팩터링하지 않았습니다.

## 2. 각 P1 수정 내용

**P1-1 복합 입력:** 단일 if/elif에서 첫 이벤트만 반환하던 동작을 절별 추출로 보완했습니다. CASE A는 +35 인원/닭고기 제한, CASE B는 -40 인원/두부 기한을 함께 반환합니다. CASE C도 두 이벤트를 반환하며 날짜 미지정으로 확인이 필요합니다. 미해석 절은 삭제하지 않고 partial과 unparsed_segments로 남깁니다. 이벤트별 source_text를 제공합니다.

**P1-2 식재료:** 등록 inventory/recipe/weekly_menu를 확인하고 matched_sources를 기록합니다. “닭 고기”, “두 부”, “ 계 란 ” 및 설정된 “달걀”을 매칭합니다. 영문은 casefold로 대조합니다. 미등록 품목이나 정규화 키의 등록명 충돌은 임의로 비슷한 품목을 선택하지 않고 확인을 요청합니다. 인원 전용 입력은 기존의 재고 읽기 생략 경로를 유지합니다.

**P1-3 중복 행:** 현재 schema에서 한 행이 한 식재료이므로 키는 (date, meal_type, menu_name, ingredient)입니다. 같은 키의 모든 값이 같을 때만 분석 복사본에서 제외하고 HIGH 경고에 개수·key·행 번호를 남깁니다. 같은 키의 제공량/단위/식수 등이 충돌하면 정형 오류입니다. 다른 식재료·다른 날짜·다른 끼니는 유지합니다. target_group은 현재 Menu schema에 없어 값이 들어오면 명시적 오류로 처리하며 조용히 합치지 않습니다. 원본 Excel은 수정하지 않습니다.

## 3. 신규 테스트 목록

모두 `tests/test_p1_fixes.py`에 있으며 parameterized 사례를 포함해 36개입니다.

- CASE A/B/C × full/event: 6개
- 부분 파싱, 분리하지 못한 복수 식재료 의도, 사용 금지의 연속 공백: 3개
- 공백/별칭 매칭: 4개
- 영문 casefold: 1개
- 미등록 자연어/구조화 입력: 2개
- inventory/recipe/weekly_menu 단독 등록 출처: 3개
- 별칭만으로 미등록 품목을 등록하지 않음: 1개
- “오이”의 끝 글자를 조사로 잘못 제거하지 않음: 1개
- parser invalid_input: 3개
- 정확한 중복 제외·8,000g 유지·원본 불변: 1개
- 같은 메뉴의 서로 다른 식재료 유지: 1개
- 날짜/끼니/식재료가 다른 정상 반복: 3개
- 제공량/식수/단위 충돌: 3개
- target_group 묵시적 병합 거부: 1개
- forecast wrapper의 중복 경고 전달: 1개
- Streamlit partial 화면: 1개
- 복합 입력의 parent graph 결합: 1개

## 4. 기존 테스트 통과 수

**133 passed**. 수정 전 실행했고, 수정 후 전체 suite에서도 동일한 133개가 통과했습니다. 기존 세 테스트 파일은 v0.2.0 ZIP과 byte-for-byte 동일합니다.

기존 항목에는 LangGraph conditional routing/stream 실행, parent graph, Streamlit 정상/확인/오류 AppTest가 포함됩니다.

## 5. 신규 포함 전체 테스트 통과 수

**169 passed (기존 133 + 신규 36), 실패/skip 없음.**

실행 명령:

```sh
python -m pytest -q --junitxml=examples/p1-test-results.xml
```

실제 실행 환경의 Streamlit 의존성도 설치되어 있었으며 UI 테스트를 생략하지 않았습니다. `examples/p1-test-results.xml`에 개별 결과, `examples/p1-cases.json`에 실제 CASE A/B/C·partial·정규화·미등록 출력이 있습니다.

## 6. 회귀 발생 여부

검증한 범위에서 의도하지 않은 회귀는 발견되지 않았습니다. 원본 DEMO 7개 파일을 바꾸지 않았습니다. 같은 입력 “내일 외부 손님 35명 추가됩니다.”의 full 분석을 v0.2.0 저장 보고서와 비교해 inventory_status, price_risks, supply_risks, substitute_candidates, priority_use_candidates, nutrition_results, cost_impacts가 동일함을 확인했습니다. 새 provenance 필드만 비교에서 제외했습니다.

중복 파일에서는 잘못된 16,000g 합산을 방지하고 기존 정상 수요 **8,000g**을 유지합니다. 복합 입력은 예전에 누락되던 제한/기한 이벤트가 실제 분석에 반영되므로 해당 입력의 영향과 후보가 달라지는 것이 의도된 수정입니다.

## 7. 남은 P2 문제

이번 범위에서 API TimeoutError 구조화, 완전한 audit log schema, snapshot 복구, 후보별 unresolved risk 고도화를 구현하지 않았습니다. 일반 한국어 전체에 대한 파싱도 보장하지 않으며 미지원 절은 partial/확인 대상으로 남깁니다. target_group을 포함한 배식 대상별 계산은 명시적 schema 확장이 필요합니다.

## 8. Decision Agent/MVP 결합 영향

- 최상위 status에 **partial**을 추가했습니다. 기존 오류 status=error는 유지하며 parser의 invalid_input은 parsing_result.status에서 확인합니다.
- parsing_result.parsed_events/unparsed_segments, validation_warnings, 이벤트 source_text/matched_sources/reason은 추가 필드입니다.
- 기존 detected_events·분석 보고서·parse_event의 list API·그래프 노드 구조는 유지합니다.
- partial 또는 미등록 품목 등 확인이 필요한 복합 입력에서는 확인 전에 재실행 요청을 내보내지 않습니다. 소비자는 recheck_status를 확인해야 합니다.
- DemoInventoryAdapter의 선택적 get_validation_warnings() 진단을 전달합니다. 메서드가 없는 기존 adapter도 동작합니다.
- Streamlit 예시는 partial과 validation_warnings를 표시합니다. 실제 운영 데이터 쓰기, 최종 메뉴/발주 결정, 자동 반영, 예측 실행을 추가하지 않았습니다.
- DEMO 데이터와 DEMO 단일 메뉴 영양 기준을 실제 API·공식 기관 기준으로 표시하지 않습니다.

## 9. 다음 단계 권장사항

Decision Agent/MVP에서 partial과 validation_warnings를 표시하고 확인 후 재입력하는 흐름을 먼저 연결하세요. 실제 기관의 배식 대상 schema와 자주 쓰는 식재료 별칭을 확정한 뒤 필요한 범위만 확장하는 것이 다음 단계입니다. 실제 API는 명세·인증키·fixture 확보 후 adapter에서 검증하며 endpoint/응답을 추정하지 않습니다.
