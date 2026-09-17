import json
from pathlib import Path
import streamlit as st
from lastplate_operation import generate_operation_plan
from lastplate_operation.tools.json_input import load_operation_json

st.title("LastPlate · Operation Agent")
st.warning("DEMO / SIMULATION — 예제 영양값은 공식 기준이 아닙니다. 모든 결과는 자문 전용입니다.")
text = st.text_area("Operation 입력 JSON", Path(__file__).with_name("demo_input.json").read_text(encoding="utf-8"), height=320)
if st.button("운영 계획 계산"):
    try:
        payload = load_operation_json(text)
        if not isinstance(payload, dict):
            raise ValueError("입력은 JSON 객체여야 합니다.")
        result = generate_operation_plan(**payload)
    except (ValueError, TypeError) as exc:
        st.error(str(exc))
    else:
        st.write("상태:", result["status"], "데이터:", result["data_mode"])
        st.metric("예상 식수", result["predicted_diners"])
        st.metric("요구 조리량 (capacity로 자르지 않음)", result["required_servings"])
        st.write("설비 capacity:", result["capacity_servings"], "초과 인분:", result["capacity_excess"])
        st.caption("edible_required=가식량 · raw_required=올림 전 원물량 · cooking_required=계량 정책 반영 원물량 · purchase_need=재고 차감 후 구매량")
        st.write("올림 정책:", result["policy"].get("rounding_policy"), "실행 모드:", result["policy"].get("execution_mode"))
        st.dataframe(result["ingredient_requirements"])
        st.dataframe(result["order_reviews"])
        st.json(result["constraints"])
        st.json(result["alerts"])
        with st.expander("Demand 적용 가능성·데이터 근거"):
            st.json({"source":result["source"], "provenance":result["provenance"]})
        with st.expander("Decision Trace"):
            st.json(result["decision_trace"])
        st.caption("REAL은 인증이 아닙니다. 모든 결과는 검토 자료이며 사람 승인이 필요합니다.")
