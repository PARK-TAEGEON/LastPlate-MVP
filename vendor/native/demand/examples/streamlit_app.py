"""Run from installed checkout. LASTPLATE_CONFIG must be an absolute server path."""
import json
import os
import uuid
import streamlit as st
from adapters.service import load_config,predict_node

st.title('LastPlate 식수 예측')
path=os.environ.get('LASTPLATE_CONFIG')
if not path:
    st.error('서버의 LASTPLATE_CONFIG에 설정 파일 절대경로를 지정하세요.')
    st.stop()
try:
    config=load_config(path)
except (ValueError,OSError) as exc:
    st.error(str(exc));st.stop()
st.caption(f'{config.mode} / {config.timezone} / 대상일 {config.deadline_days_before}일 전 {config.cutoff_time} 마감')
if 'request_id' not in st.session_state:
    st.session_state.request_id=uuid.uuid4().hex
if st.button('새 요청 시작'):
    st.session_state.request_id=uuid.uuid4().hex
st.code(st.session_state.request_id)
with st.form('predict'):
    body=st.text_area('입력 JSON',value='{}',height=190)
    receipts=st.text_area('실제 입력 확보 근거 JSON (과거 재생은 빈 객체)',value='{}')
    weather_id=st.text_input('서버 등록 날씨 ID (날씨 모델만)')
    submitted=st.form_submit_button('예측 / 동일 요청 재시도')
if submitted:
    try:
        state={'input_data':json.loads(body),'availability':json.loads(receipts),
               'weather_record_id':weather_id or None,'request_id':st.session_state.request_id}
        response=predict_node(state,config)
    except json.JSONDecodeError as exc:
        response={'result':None,'error':{'code':'validation_error','message':str(exc),'retryable':False}}
    st.json(response)
st.caption('실적은 서버 prediction_id로 연결합니다. 인증·입력 출처 연결은 서비스 계층에서 구성하세요. 재학습은 별도 관리자 명령입니다.')
