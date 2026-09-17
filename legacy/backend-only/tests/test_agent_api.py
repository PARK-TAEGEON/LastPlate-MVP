"""Isolated transport/storage tests. No ML package, model, or teammate code needed."""
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from lastplate_backend.core.config import get_settings
from lastplate_backend.main import create_app
from lastplate_backend.services.agent_client import AgentClient


def request_fixture():
    return dict(request_id='request-1', site_id='school', target_date='2026-09-18',
        as_of='2026-09-17', meal_type='lunch', meal_capacity=100,
        attendance={'registered_population':100, 'future_metadata':None},
        weekly_menu=[dict(date='2026-09-18', meal_type='lunch', menu_name='두부국')],
        recipes=[dict(menu_name='두부국', ingredients=[dict(ingredient='두부', amount_per_serving=80, unit='g')])],
        inventory=[dict(ingredient='두부', current_stock=8, unit='kg', expiry_date='2026-09-18')],
        planned_orders=[], nutrition=[], prices=[], monthly_prices=[], supply_events=[],
        sources={key:'test-fixture' for key in ('recipe','inventory','nutrition','price_trend',
                    'monthly_price','supply_risk','weekly_menu','constraints')}, operation_policy={},
        event={'event_type':'attendance_event', 'event_id':'trip-1', 'delta':-20})


def result_fixture():
    return dict(pipeline_status='COMPLETE', demand={'predicted_diners':883, 'lower_bound':None,
        'upper_bound':None, 'applicability':'OUT_OF_DISTRIBUTION', 'confidence':'LOW'},
        operation={'schema_version':'2.0', 'recommended_servings':910, 'capacity_excess':810,
            'ingredient_requirements':[{'ingredient':'두부', 'required_amount':145600.0, 'unit':'g'}],
            'alerts':[{'type':'capacity_exceeded', 'evidence':{'capacity':100}, 'trace_refs':['op-1']}]},
        inventory_risk={'status':'partial','allocation_audit':[{'lot_id':'test-lot','allocated':0}]},
        decision={'schema_version':'0.1.3', 'recommended_servings':None, 'operation_recommended_servings':910,
            'decision':'BLOCK', 'approval_status':'pending', 'requires_human_approval':True,
            'recommended_rechecks':[{'agent':'operation','status':'pending'}]},
        errors=[], warnings=[{'code':'OUT_OF_DISTRIBUTION'}], timings={'demand':0.125},
        input_revision='revision-test', advisory_only=True, future_metadata={'nested':[None,1,False]})


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LASTPLATE_BACKEND_DATABASE_PATH':str(Path(self.temp.name)/'backend.db'),
            'LASTPLATE_AGENT_BASE_URL':'http://agent.test:8001', 'LASTPLATE_AGENT_TIMEOUT_SECONDS':'600'})
        self.env.start()
        get_settings.cache_clear()
        self.app = create_app()
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.calls = []
        self.upstream_status = 200
        self.upstream_body = result_fixture()
        self.install_transport(self.respond)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        get_settings.cache_clear()
        self.temp.cleanup()

    def respond(self, request):
        self.calls.append(request)
        return httpx.Response(self.upstream_status, json=self.upstream_body)

    def install_transport(self, handler):
        self.app.state.agent_client.close()
        self.app.state.agent_client = AgentClient('http://agent.test:8001', transport=httpx.MockTransport(handler))

    def submit(self, payload=None):
        return self.client.post('/api/v1/agent-plans', json=payload or request_fixture())

    def test_complete_blocked_output_is_preserved_not_approved_or_clipped(self):
        response = self.submit()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),self.upstream_body)
        self.assertEqual(json.loads(self.calls[0].content),request_fixture())
        self.assertEqual(str(self.calls[0].url),'http://agent.test:8001/api/plan')
        self.assertEqual(response.json()['decision']['recommended_servings'],None)
        self.assertEqual(response.json()['operation']['recommended_servings'],910)

    def test_history_and_latest_retain_full_request_result_and_http_status(self):
        response = self.submit()
        saved = self.client.get(response.headers['Location']).json()
        self.assertEqual(saved['request'],request_fixture())
        self.assertEqual(saved['result'],self.upstream_body)
        self.assertEqual(saved['upstream_http_status'],200)
        self.assertEqual(saved['id'],response.headers['X-LastPlate-Record-Id'])
        self.upstream_status=422
        self.upstream_body.update(pipeline_status='PARTIAL',inventory_risk=None,
            errors=[{'stage':'operation','code':'INVALID_INPUT','http_status':422}])
        second=self.submit()
        latest=self.client.get('/api/v1/agent-plans/latest',params={'site_id':'school','target_date':'2026-09-18'}).json()
        self.assertEqual(latest['id'],second.headers['X-LastPlate-Record-Id'])
        self.assertEqual(latest['upstream_http_status'],422)
        self.assertEqual(latest['result'],self.upstream_body)
        self.assertNotEqual(latest['id'],saved['id'])

    def test_partial_422_unknown_or_empty_alerts_are_preserved(self):
        for alerts in ([],[{'type':'future_unknown_error','evidence':{'why':'test'}}]):
            self.upstream_status=422
            self.upstream_body=result_fixture()
            self.upstream_body.update(pipeline_status='PARTIAL',inventory_risk=None,
                errors=[{'stage':'operation','code':'INVALID_INPUT','http_status':422}])
            self.upstream_body['operation'].update(status='invalid_input',alerts=alerts)
            response=self.submit()
            self.assertEqual(response.status_code,422)
            self.assertEqual(response.json(),self.upstream_body)
            self.assertEqual(self.client.get(response.headers['Location']).json()['result'],self.upstream_body)

    def test_native_409_and_500_preserve_partial_results(self):
        for code in (409,500):
            self.upstream_status=code
            self.upstream_body.update(pipeline_status='PARTIAL',inventory_risk=None,decision=None,
                errors=[{'stage':'inventory_risk','http_status':code,'code':'NATIVE_ERROR'}])
            response=self.submit()
            self.assertEqual(response.status_code,code)
            self.assertEqual(response.json(),self.upstream_body)
            self.assertIn('X-LastPlate-Record-Id',response.headers)

    def test_optional_fields_are_not_injected_and_explicit_null_is_kept(self):
        payload=request_fixture()
        del payload['meal_type']
        payload['availability']=None
        self.submit(payload)
        self.assertEqual(json.loads(self.calls[0].content),payload)

    def test_input_errors_have_pipeline_envelope_without_calling_peer(self):
        for field,value in [('as_of','2026-09-17T10:00:00+09:00'),('as_of','2026-09-19'),
                ('meal_type','dinner'),('meal_capacity',True),('meal_capacity',-1),('request_id',' '),
                ('site_id','a'*200),('weekly_menu',[]),('unrecognized_top_field',1)]:
            with self.subTest(field=field,value=value):
                payload=request_fixture(); payload[field]=value
                response=self.submit(payload)
                self.assertEqual(response.status_code,422,response.text)
                self.assertEqual(response.json()['pipeline_status'],'FAILED')
                self.assertEqual(response.json()['errors'][0]['code'],'INPUT_VALIDATION_ERROR')
        self.assertEqual(len(self.calls),0)

    def test_nan_request_is_rejected_without_leaking_input(self):
        payload=request_fixture(); payload['attendance']['employees']=float('nan')
        response=self.client.post('/api/v1/agent-plans',content=json.dumps(payload),headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(len(self.calls),0)

    def test_unconfigured_service_returns_503_but_local_backend_still_works(self):
        self.app.state.agent_client.base_url=None
        response=self.submit()
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['errors'][0]['code'],'AGENT_SERVICE_NOT_CONFIGURED')
        self.assertEqual(self.client.get('/api/v1/health').status_code,200)
        self.assertEqual(self.client.get('/api/v1/demo/input').status_code,200)

    def test_timeout_is_504_and_has_no_automatic_retry(self):
        attempts=[]
        def timeout(request):
            attempts.append(request)
            raise httpx.ReadTimeout('test timeout',request=request)
        self.install_transport(timeout)
        response=self.submit()
        self.assertEqual(response.status_code,504)
        self.assertEqual(response.json()['errors'][0]['code'],'AGENT_SERVICE_TIMEOUT')
        self.assertEqual(len(attempts),1)

    def test_connection_failure_is_503(self):
        def unavailable(request):
            raise httpx.ConnectError('test unavailable',request=request)
        self.install_transport(unavailable)
        self.assertEqual(self.submit().status_code,503)

    def test_unexpected_status_or_bad_json_is_502(self):
        cases=[httpx.Response(302,headers={'Location':'http://unexpected.test'}),
               httpx.Response(503,text='proxy unavailable'), httpx.Response(200,text='<html>not JSON</html>'),
               httpx.Response(200,json={'pipeline_status':'COMPLETE'}),
               httpx.Response(200,content=json.dumps(dict(result_fixture(),timings={'demand':float('nan')})))]
        for reply in cases:
            self.install_transport(lambda request,reply=reply:reply)
            response=self.submit()
            self.assertEqual(response.status_code,502,response.text)
            self.assertEqual(response.json()['pipeline_status'],'FAILED')

    def test_storage_failure_does_not_discard_native_results(self):
        with patch.object(self.app.state.agent_repository,'save',side_effect=sqlite3.OperationalError('test disk full')):
            response=self.submit()
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json(),self.upstream_body)
        self.assertEqual(response.headers['X-LastPlate-Storage'],'failed')
        self.assertEqual(response.headers['X-LastPlate-Upstream-Status'],'200')
        self.assertNotIn('X-LastPlate-Record-Id',response.headers)

    def test_cors_exposes_record_id_to_ui(self):
        response=self.client.post('/api/v1/agent-plans',json=request_fixture(),headers={'Origin':'http://localhost:5173'})
        self.assertEqual(response.headers['access-control-allow-origin'],'http://localhost:5173')
        self.assertIn('X-LastPlate-Record-Id',response.headers['access-control-expose-headers'])

    def test_agent_record_cannot_use_legacy_review_or_event_mutation(self):
        response=self.submit(); record_id=response.headers['X-LastPlate-Record-Id']
        self.assertEqual(self.client.post(f'/api/v1/operation-plans/{record_id}/review').status_code,404)
        self.assertEqual(self.client.post(f'/api/v1/agent-plans/{record_id}/review').status_code,404)

    def test_missing_history_is_404(self):
        self.assertEqual(self.client.get('/api/v1/agent-plans/missing').status_code,404)
        self.assertEqual(self.client.get('/api/v1/agent-plans/latest',params={'site_id':'missing','target_date':'2026-09-18'}).status_code,404)

    def test_root_is_backend_only_and_old_model_ui_routes_are_absent(self):
        self.assertFalse(self.client.get('/').json()['model_bundled'])
        self.assertFalse(self.client.get('/').json()['frontend_bundled'])
        self.assertEqual(self.client.get('/frontend/index.html').status_code,404)
        self.assertEqual(self.client.post('/api/v1/forecasts/predict',json={}).status_code,404)
        self.assertEqual(self.client.get('/api/v1/forecasts/model').status_code,404)
        self.assertEqual(self.client.get('/api/v1/integration').json()['peer_contract'],'lastplate-integrated-v0.1.2')


if __name__ == '__main__':
    unittest.main()
