# v0.2.3 검증

기존 192개 및 신규 48개: 총 240 passed, 실패/skip 없음. 실행 명령: `python -m pytest -q tests --junitxml=examples/release-test-results.xml`. 복합 이벤트·normalization·식단 중복 검증·LangGraph routing·parent integration·Streamlit integration 포함. 아래는 이전 버전의 이력입니다.

# v0.2.2 최신 검증

**192 passed (기존 169 + 신규 23), 실패/skip 없음.** 최신 증빙은 `examples/restriction-test-results.xml`, `examples/restriction-cases.json`, `examples/restriction-manifest.json`입니다. `REPEATED_RESTRICTION_REPORT.md`에 요청된 10개 항목으로 정리했습니다. 아래는 이전 검증 기록입니다.

# v0.2.1 검증

기존 **133개 + 신규 36개 = 169 passed**, 실패/skip 없음. 기존 테스트 파일 3개와 DEMO 파일 7개는 v0.2.0 원본과 동일합니다. LangGraph routing, Streamlit AppTest, parent graph 결합을 포함하여 실제 실행했습니다.

최신 증빙: `examples/p1-test-results.xml`, `examples/p1-cases.json`, `examples/p1-manifest.json`. 상세 9개 항목 보고는 `P1_FIX_REPORT.md`를 확인하세요. 아래는 보존한 이전 버전 검증 기록입니다.

# v0.2.0 검증 결과

- 수정 전 원본 테스트: **28 passed**.
- 수정 후 전체 테스트: **133 passed**, 실패/skip 없음.
- 기존 `tests/test_inventory_risk_agent.py`: **28개, 원본 ZIP과 byte-for-byte 동일**.
- 신규 `tests/test_review_regressions.py`: **58개**.
- 신규 `tests/test_data_quality_and_integration.py`: **47개**.
- Streamlit AppTest 3개(정상 / clarification / invalid date)를 포함합니다.
- 실행: `python -m pytest -q --junitxml=examples/test-results.xml`.
- 실행 환경: Python 3.12, LangGraph 1.2.11, Streamlit 1.64.0. 전체 버전은 `requirements-tested.txt`.
- v0.2.0 wheel 빌드 → 별도 경로 설치 → 원본 프로젝트 밖에서 import/분석 실행 성공. 신규 integration 예시 import와 DEMO 데이터 7개 포함을 확인했습니다.
- DEMO 7개 파일은 원본 ZIP과 동일합니다. 실제 API/기관 영양 기준 검증으로 해석하지 않습니다.

증빙:
- `examples/test-results.xml`: 테스트별 실행 결과.
- `examples/regression_cases.json`: 격리 재고 부족/임박 재고/월별 급등, 모호·확정 인원, 잘못된 날짜, 사용 제한의 실제 보고서.
- `examples/revision_manifest.json`: 원본 ZIP SHA256, 수정/추가 파일, 테스트 개수, 원본 테스트 및 DEMO 파일 동일성.
- `REVISION_REPORT.md`: 항목별 수정, 실행 결과, 남은 미구현.

실제 LastPlate 저장소·공공 API 응답 명세·인증키·기관 영양 기준은 제공되지 않았으며, 해당 통합 배포나 실제 서비스 검증은 수행하지 않았습니다.
