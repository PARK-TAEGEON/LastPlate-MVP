"""Run: python -m streamlit run examples/streamlit_app.py (optional UI extra)."""
from agents.inventory_risk import analyze_inventory_and_risk, error_report
from schemas.errors import DataQualityError, validation_error
from schemas.request import AnalysisRequest
from pydantic import ValidationError

def validated_analysis(inputs, event=None, adapter_factory=None):
    """Testable UI boundary. File and input errors are rendered, never replaced."""
    try:
        state=AnalysisRequest.model_validate(inputs).model_dump(mode="json")
        if adapter_factory is not None:
            state["adapters"]=adapter_factory()
        return analyze_inventory_and_risk(state,event or None)
    except DataQualityError as exc:
        return error_report(exc.detail,inputs)
    except ValidationError as exc:
        return error_report(validation_error(exc).detail,inputs)

def main():
    import streamlit as st
    st.title("LastPlate Inventory & Risk")
    st.warning("DEMO / SIMULATION · 실제 공공 API 미연동 · 영양 기준은 DEMO 설정")
    st.caption("자문 전용: 메뉴·발주 변경, 자동 반영, 수요 예측 실행 기능 없음")
    with st.form("analysis"):
        as_of=st.text_input("기준일 YYYY-MM-DD","2026-09-17")
        mode=st.selectbox("분석 모드",["full","event"])
        event=st.text_area("이벤트 입력")
        submitted=st.form_submit_button("자문 보고서 분석")
    if not submitted:
        return
    report=validated_analysis({"as_of":as_of,"mode":mode},event)
    if report["status"]=="error":
        st.error("입력 또는 데이터 오류: 수정 후 다시 분석하세요. DEMO 자동 대체 없음.")
        st.dataframe(report["errors"])
    elif report["status"]=="partial":
        st.warning("일부 입력을 해석하지 못했습니다. 미해석 구간 확인 전 재실행 요청이 차단됩니다.")
    elif report["clarification"]["status"]=="required":
        st.warning("날짜 또는 인원을 확인해야 합니다. 확인 전 예측 실행이 차단됩니다.")
    st.subheader("데이터 출처")
    st.json(report["data_sources"])
    st.json({"parsing_result":report["parsing_result"],"validation_warnings":report["validation_warnings"]})
    st.json({"period":report["period"],"forecast_version":report["forecast_version"],"input_snapshot_id":report["input_snapshot_id"],"recheck_status":report["recheck_status"]})
    for field in ("alerts","affected_menus","priority_use_candidates","substitute_candidates","nutrition_results"):
        st.subheader(field)
        st.dataframe(report[field])
    st.subheader("실행과 생략")
    st.json(report["execution"])
    st.code("\n".join(report["decision_trace"]))
    st.download_button("보고서 JSON 저장",__import__("json").dumps(report,ensure_ascii=False,indent=2),file_name="risk-report.json",mime="application/json")

if __name__=="__main__":
    main()
