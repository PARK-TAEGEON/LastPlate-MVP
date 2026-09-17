"""Regression coverage for the supplied HTML + native ML + operation API."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import get_settings
from app.services.forecast_service import BUNDLE, ForecastRequest, predict_forecast, build_feature_values, model_metadata


class IntegratedApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LASTPLATE_DATABASE_PATH': str(Path(self.temp.name)/'test.db')})
        self.env.start(); get_settings.cache_clear()
        self.client = TestClient(create_app()); self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop(); get_settings.cache_clear(); self.temp.cleanup()

    def input(self, scenario='normal'):
        response = self.client.get('/api/v1/demo/input', params={'scenario':scenario})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def create(self, payload=None):
        response = self.client.post('/api/v1/operation-plans', json=payload or self.input())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_normal_plan_reservations_fefo_and_projected_arrival(self):
        p = self.create()
        self.assertEqual(p['result']['target'], 510)  # not 520: do not double-add buffer
        pork = next(x for x in p['stock_allocations'] if x['ingredient']=='돼지고기')
        self.assertEqual(pork['usable_kg'], 45)
        buy = p['purchase_recommendations'][0]
        self.assertEqual((buy['shortage_kg'],buy['recommended_order_kg'],buy['package_count']), (16.2,20,4))
        self.assertEqual(p['result']['menus'][1]['final'],375)
        self.assertEqual(p['projected_after_purchase']['menus'][1]['final'],510)
        cabbage = next(x for x in p['stock_allocations'] if x['ingredient']=='양배추')
        self.assertEqual([x['allocated_kg'] for x in cabbage['lots']], [10,10.4])
        self.assertTrue(p['review_allowed'])

    def test_invalid_scenarios_block_review(self):
        for scenario in ('capacity_limit','delivery_delay','no_doc'):
            with self.subTest(scenario=scenario):
                p=self.create(self.input(scenario))
                self.assertFalse(p['review_allowed'])
                response=self.client.post(f"/api/v1/operation-plans/{p['id']}/review")
                self.assertEqual(response.status_code,409)

    def test_review_is_persistent_idempotent_and_not_real_order(self):
        p=self.create()
        url=f"/api/v1/operation-plans/{p['id']}/review"
        first=self.client.post(url).json(); second=self.client.post(url).json()
        self.assertEqual(first['review_status'],'reviewed_demo')
        self.assertEqual(first['reviewed_at'],second['reviewed_at'])
        self.assertEqual(first['stock_allocations'],p['stock_allocations'])
        self.assertEqual(self.client.get(f"/api/v1/operation-plans/{p['id']}").json()['review_status'],'reviewed_demo')

    def test_event_revision_cancel_and_conflict(self):
        p=self.create(); event={'id':'trip','delta':-35,'status':'confirmed'}
        body={'current_time':p['result']['current_time'],'event':event}
        endpoint=f"/api/v1/operation-plans/{p['id']}/events"
        new=self.client.post(endpoint,json=body)
        self.assertEqual(new.status_code,201,new.text)
        self.assertEqual(new.json()['result']['target'],480)
        self.assertEqual(self.client.post(endpoint,json=body).status_code,409)
        self.assertEqual(self.client.post(f"/api/v1/operation-plans/{p['id']}/review").status_code,409)
        event['status']='cancelled'
        cancelled=self.client.post(f"/api/v1/operation-plans/{new.json()['id']}/events",json=body)
        self.assertEqual(cancelled.json()['result']['target'],510)

    def test_concurrent_revisions_only_one_wins(self):
        p=self.create()
        def update(delta):
            return self.client.post(f"/api/v1/operation-plans/{p['id']}/events",json={
                'current_time':p['result']['current_time'], 'event':{'id':str(delta),'delta':delta,'status':'confirmed'}}).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(update, [10,20])),[201,409])

    def test_manual_adjustment_and_event_resets_override(self):
        p=self.create(); time=p['result']['current_time']
        invalid=self.client.post(f"/api/v1/operation-plans/{p['id']}/adjust",json={'current_time':time,'applied_servings':501})
        self.assertEqual(invalid.status_code,422)
        adjusted=self.client.post(f"/api/v1/operation-plans/{p['id']}/adjust",json={'current_time':time,'applied_servings':500}).json()
        self.assertEqual(adjusted['result']['target'],500)
        self.assertFalse(adjusted['review_allowed'])
        next_plan=self.client.post(f"/api/v1/operation-plans/{adjusted['id']}/events",json={
            'current_time':time,'event':{'id':'visitors','status':'confirmed','delta':35}}).json()
        self.assertEqual(next_plan['result']['target'],550)

    def test_expired_reserved_and_subgram_validation(self):
        request=self.input()
        request['inventory'][2]['lots'][0]['expires_on']='2026-09-17'
        request['inventory'][2]['lots'][1]['reserved_kg']=5
        p=self.create(request)
        row=next(x for x in p['stock_allocations'] if x['ingredient']=='양배추')
        self.assertEqual((row['usable_kg'],row['expired_kg'],row['reserved_kg']),(10,10,5))
        self.assertEqual(row['lots'][0]['allocated_kg'],0)
        request['inventory'][0]['order_unit_kg']=.0001
        self.assertEqual(self.client.post('/api/v1/operation-plans',json=request).status_code,422)

    def test_embedded_event_must_be_reforecast_before_edit(self):
        request=self.input(); request['forecast']['included_event_ids']=['embedded']
        p=self.create(request)
        response=self.client.post(f"/api/v1/operation-plans/{p['id']}/events",json={
            'current_time':request['current_time'],'event':{'id':'embedded','delta':-35,'status':'confirmed'}})
        self.assertEqual(response.status_code,422)

    def test_unknown_or_past_delivery_not_counted_as_new_stock(self):
        for arrival in (None,'2026-09-17T10:00:00+09:00'):
            request=self.input();request['inventory'][1]['expected_delivery_at']=arrival
            p=self.create(request)
            self.assertEqual(p['purchase_recommendations'][0]['delivery_status'],'unconfirmed')
            self.assertEqual(p['projected_after_purchase']['menus'][1]['final'],375)

    def test_frontend_and_model_metadata_routes(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertIn('/assets/app.js',self.client.get('/').text)
        self.assertEqual(self.client.get('/assets/app.js').status_code,200)
        meta=self.client.get('/api/v1/forecasts/model').json()
        self.assertFalse(meta['operational_eligible']);self.assertFalse(meta['weather_used'])

    def test_forecast_api_invalid_and_out_of_range_input(self):
        body=dict(site_id='A사업장',meal_date='2026-09-18',employees=520,vacation=0,business_trip=0,work_from_home=0,overtime=0,menu='쌀밥 제육볶음 양배추무침')
        response=self.client.post('/api/v1/forecasts/predict',json=body)
        self.assertEqual(response.status_code,200,response.text)
        f=response.json();self.assertEqual(f['lower'],f['upper']);self.assertEqual(f['interval_method'],'point_only')
        self.assertTrue(any('밖' in w for w in f['warnings']))
        request=self.input();request['forecast']=f
        self.create(request)
        body['vacation']=600
        self.assertEqual(self.client.post('/api/v1/forecasts/predict',json=body).status_code,422)


class ModelParityTests(unittest.TestCase):
    def test_supplied_model_smoke_matches_original(self):
        smoke=json.loads((BUNDLE/'inference_smoke.json').read_text(encoding='utf-8'))['result']
        data=smoke['input_data']
        request=ForecastRequest(site_id='historical-smoke',meal_date=data['date'],menu=data['menu'],
                                **{key:int(data[key]) for key in ['employees','vacation','business_trip','work_from_home','overtime']})
        forecast=predict_forecast(request)
        self.assertEqual(forecast.mid,smoke['prediction'])
        self.assertEqual(forecast.model_version,smoke['model_version'])

    def test_v1_menu_features_and_weekday(self):
        request=ForecastRequest(site_id='test',meal_date='2026-09-18',employees=2000,vacation=0,business_trip=0,work_from_home=0,overtime=0,menu='제육볶음(국내산)')
        features=dict(zip(model_metadata()['features'],build_feature_values(request)))
        self.assertEqual(features['menu_meat'],1);self.assertEqual(features['menu_soup'],0)
        self.assertEqual(features['weekday_4'],1)


if __name__=='__main__':
    unittest.main()
