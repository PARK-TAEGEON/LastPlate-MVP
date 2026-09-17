import json
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
from examples.fixtures import baseline

APP=Path(__file__).resolve().parents[1]/'examples'/'streamlit_app.py'


class StreamlitIntegrationTests(unittest.TestCase):
    def launch(self):
        app=AppTest.from_file(str(APP),default_timeout=15).run()
        self.assertEqual(len(app.exception),0)
        return app

    def test_session_and_latest_approval(self):
        app=self.launch()
        graph=app.session_state['decision_graph']; saver=app.session_state['decision_checkpointer']; tid=app.session_state['decision_thread_id']
        app.button(key='analyze').click().run()
        self.assertEqual(len(app.exception),0)
        app.button(key='approve').click().run()
        self.assertEqual(app.session_state['decision_state']['approval']['choice'],'approve')
        self.assertFalse(app.session_state['decision_state']['approval']['executed'])
        self.assertEqual(app.session_state['decision_state']['recommendation']['approval_status'],'pending')
        self.assertIs(graph,app.session_state['decision_graph'])
        self.assertIs(saver,app.session_state['decision_checkpointer'])
        self.assertEqual(tid,app.session_state['decision_thread_id'])
        self.assertTrue(any('DEMO' in w.value for w in app.warning))

    def test_null_servings_unresolved_and_disabled_approval(self):
        app=self.launch();p=baseline();p['demand_result']['operational_eligible']=False
        app.text_area(key='input_json').set_value(json.dumps(p)).run()
        app.button(key='analyze').click().run()
        self.assertEqual(app.metric[0].value,'보류')
        self.assertTrue(app.button(key='approve').disabled)
        self.assertTrue(any('미해결' in w.value for w in app.warning))

    def test_invalid_json_and_schema(self):
        app=self.launch()
        app.text_area(key='input_json').set_value('{bad').run()
        app.button(key='analyze').click().run()
        self.assertTrue(any('입력 검증 오류' in e.value for e in app.error))
        self.assertIsNone(app.session_state['decision_state'])
        p=baseline();p['demand_result']['prediction']=-3
        app.text_area(key='input_json').set_value(json.dumps(p)).run()
        app.button(key='analyze').click().run()
        self.assertTrue(any('입력 검증 오류' in e.value for e in app.error))
        self.assertEqual(len(app.exception),0)

    def test_critical_alert_and_modify_to_reject(self):
        app=self.launch();p=baseline()
        p['inventory_risk_result']['alerts']=[{'type':'allergy','severity':'HIGH','message':'현재 메뉴 알레르기','menu':'두부조림'}]
        app.text_area(key='input_json').set_value(json.dumps(p)).run()
        app.button(key='analyze').click().run()
        self.assertTrue(any('알레르기' in e.value for e in app.error))
        self.assertTrue(app.button(key='approve').disabled)
        app.text_area(key='input_json').set_value(json.dumps(baseline())).run()
        app.button(key='modify').click().run()
        self.assertEqual(app.session_state['decision_state']['approval']['choice'],'pending')
        app.button(key='reject').click().run()
        self.assertEqual(app.session_state['decision_state']['approval']['choice'],'reject')
        self.assertEqual(len(app.exception),0)

    def test_edited_payload_cannot_approve_previous_result(self):
        app=self.launch();app.button(key='analyze').click().run()
        app.text_area(key='input_json').set_value('{}').run()
        self.assertTrue(app.button(key='approve').disabled)

class V012StreamlitQualityTests(unittest.TestCase):
    def test_real_provenance_does_not_display_demo_warning(self):
        app=AppTest.from_file(str(APP),default_timeout=15).run();p=baseline()
        p['inventory_risk_result']['data_sources']={'feed':'REAL:ERP'}
        app.text_area(key='input_json').set_value(json.dumps(p)).run()
        app.button(key='analyze').click().run()
        self.assertEqual(len(app.exception),0)
        r=app.session_state['decision_state']['recommendation']
        self.assertEqual(r['confidence'],'HIGH')
        self.assertFalse(any('DEMO / SIMULATION' in w.value for w in app.warning))

    def test_simulation_source_type_is_visible(self):
        app=AppTest.from_file(str(APP),default_timeout=15).run();p=baseline()
        p['inventory_risk_result']['source_type']='simulation'
        app.text_area(key='input_json').set_value(json.dumps(p)).run()
        app.button(key='analyze').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any('DEMO / SIMULATION' in w.value for w in app.warning))
        self.assertEqual(app.session_state['decision_state']['recommendation']['confidence'],'MEDIUM')
