"""Run: streamlit run examples/streamlit_app.py (from the installed source tree)."""
import json
from uuid import uuid4
import streamlit as st
from pydantic import ValidationError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from lastplate_decision.graph.decision_workflow import build_decision_workflow
from lastplate_decision.schemas.decision_input import DecisionInput
from examples.fixtures import baseline

st.set_page_config(page_title='LastPlate Decision 검토',layout='wide')
st.title('LastPlate 운영 권고 검토')
st.caption('DEMO 통합 예제 · 실제 Operation 미연결 · 승인 의사만 기록합니다.')

if 'decision_graph' not in st.session_state:
    st.session_state.decision_checkpointer=InMemorySaver()
    # Inject real read-only canonical callbacks here when available. None are fabricated.
    st.session_state.decision_graph=build_decision_workflow(checkpointer=st.session_state.decision_checkpointer)
    st.session_state.decision_thread_id=str(uuid4())
    st.session_state.decision_state=None
    st.session_state.decision_error=None
    sample=baseline()
    sample['inventory_risk_result']['is_demo']=True
    sample['inventory_risk_result']['data_quality_notes']=['모든 수치·PASS는 합성 UI DEMO fixture입니다.']
    st.session_state.input_json=json.dumps(sample,ensure_ascii=False,indent=2)

config={'configurable':{'thread_id':st.session_state.decision_thread_id},'recursion_limit':100}
graph=st.session_state.decision_graph
if st.button('새 검토',key='new_review'):
    st.session_state.decision_thread_id=str(uuid4())
    st.session_state.decision_state=None
    st.session_state.decision_error=None
    st.rerun()

text=st.text_area('구조화된 Agent 결과 JSON',key='input_json',height=200)
state=st.session_state.decision_state
pending=bool(state and (state.get('approval') or {}).get('choice')=='pending')

if st.button('권고 생성',key='analyze',disabled=pending):
    try:
        payload=json.loads(text)
        DecisionInput.model_validate(payload)
        state=graph.invoke({'payload':payload},config)
        st.session_state.decision_state=state
        st.session_state.submitted_text=text
        st.session_state.decision_error=None
    except (ValidationError,ValueError,TypeError) as exc:
        st.session_state.decision_error='입력 검증 오류: '+str(exc)
    except Exception as exc:
        st.session_state.decision_error='워크플로 실행 오류: '+type(exc).__name__

if st.session_state.decision_error:
    st.error(st.session_state.decision_error)
state=st.session_state.decision_state
if state:
    report=state['recommendation']
    st.subheader('우선 확인 위험')
    for alert in report['critical_alerts']:
        st.error(alert.get('message',str(alert)))
    if any(q['kind'] in {'DEMO','SIMULATION'} and q['affects_confidence'] for q in report['quality_records']):
        st.warning('DEMO / SIMULATION — 실제 운영 확정 근거로 사용하지 마세요.')
    st.metric('권고 인분','보류' if report['recommended_servings'] is None else str(report['recommended_servings']))
    st.write('상태:',report['status'],' / confidence:',report['confidence'])
    st.subheader('미해결 재검증 요청')
    if report['recommended_rechecks']:
        st.warning('미해결 재검증 요청이 있어 현재 계획의 승인이 보류됩니다.')
        st.json(report['recommended_rechecks'])
    st.subheader('데이터 품질 및 검증 근거')
    st.json(report['data_quality_notes'])
    st.json(report['confidence_evidence'])
    with st.expander('출처 및 운영 모드 설명'):
        st.json(report['provenance_notes'])
    st.subheader('최신 승인 상태')
    # The recommendation is an immutable pending snapshot. Latest state lives here.
    st.json(state.get('approval'))
    st.subheader('권고 및 제외 후보')
    st.json({k:report[k] for k in ('selected_action_ids','procurement_actions','inventory_actions','menu_actions','candidate_evaluations')})
    pending=(state.get('approval') or {}).get('choice')=='pending'
    dirty=text!=st.session_state.get('submitted_text')
    if dirty:
        st.info('입력 내용이 바뀌었습니다. 수정 후 재검증을 선택하세요.')

    def respond(choice):
        try:
            response={'choice':choice,'operator_id':'demo-operator',
                'recommendation_revision':report['recommendation_revision']}
            if choice=='modify':
                response['revised_input']=json.loads(text)
                DecisionInput.model_validate(response['revised_input'])
            updated=graph.invoke(Command(resume=response),config)
            st.session_state.decision_state=updated
            st.session_state.submitted_text=text
            st.session_state.decision_error=None
        except (ValidationError,ValueError,TypeError) as exc:
            st.session_state.decision_error='입력 검증 오류: '+str(exc)
        except Exception as exc:
            st.session_state.decision_error='승인 처리 오류: '+type(exc).__name__

    cols=st.columns(3)
    if cols[0].button('권고 적용 의사 기록',key='approve',disabled=not pending or report['status']!='ok' or dirty or bool(st.session_state.decision_error)):
        respond('approve');st.rerun()
    if cols[1].button('수정 후 재검증',key='modify',disabled=not pending):
        respond('modify');st.rerun()
    if cols[2].button('거절',key='reject',disabled=not pending):
        respond('reject');st.rerun()
    with st.expander('누적 Workflow Trace'):
        st.json(state['workflow_trace'])
