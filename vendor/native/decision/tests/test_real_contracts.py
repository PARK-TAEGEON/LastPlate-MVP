"""Tests consume outputs captured from actual delivered Agents, not hand-invented contracts."""
import json
import hashlib
import unittest
from pathlib import Path
from copy import deepcopy
from lastplate_decision.adapters import adapt_inventory_v020, adapt_ml_v2, adapt_events, adapt_operation_contract
from lastplate_decision import make_final_recommendation
from examples.fixtures import baseline

FIXTURES=Path(__file__).parent/'fixtures'


def read(name):return json.loads((FIXTURES/(name+'.json')).read_text(encoding='utf-8'))


class RealContractTests(unittest.TestCase):
    def test_fixture_capture_hashes(self):
        manifest=read('capture_manifest')
        for item in manifest['calls']:
            data=(FIXTURES/(item['case']+'.json')).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),item['fixture_sha256'])

    def test_inventory_preserves_entire_original(self):
        raw=read('inventory_full'); before=deepcopy(raw);r=adapt_inventory_v020(raw)
        self.assertEqual(r['source_payload'],before);self.assertEqual(raw,before)
        self.assertEqual(r['affected_menus'],raw['affected_menus'])
        self.assertEqual(r['decision_trace'],raw['decision_trace'])
        self.assertEqual(r['data_sources'],raw['data_sources'])
        self.assertEqual(r['limitations'],raw['limitations'])

    def test_priority_use_scope_and_grams(self):
        raw=read('inventory_full');r=adapt_inventory_v020(raw)
        a=r['inventory_recommendations'][0];b=raw['priority_use_candidates'][0]
        self.assertEqual(a['quantity'],b['quantity_g']);self.assertEqual(a['unit'],'g')
        self.assertEqual(a['scope']['target_date'],b['date'])
        self.assertEqual(a['days_to_expiry'],0)
        self.assertTrue(all(v=='UNKNOWN' for v in a['constraints'].values()))
        self.assertEqual(a['source_payload'],b)

    def test_menu_candidate_not_ingredient_substitution(self):
        raw=read('inventory_full');r=adapt_inventory_v020(raw)
        for a,b in zip(r['substitute_candidates'],raw['substitute_candidates']):
            self.assertEqual(a['kind'],'menu_substitution')
            self.assertEqual(a['menu'],b['original_menu']);self.assertEqual(a['candidate_menu'],b['candidate_menu'])
            self.assertIsNone(a['ingredient'])
            self.assertEqual(a['cause_event_ids'],b['cause_event_ids'])
            self.assertEqual(a['source_payload'],b)
            self.assertEqual(a['constraints']['expiry'],'UNKNOWN')
            self.assertEqual(a['constraints']['supply'],'UNKNOWN')

    def test_operation_agent_alias(self):
        r=adapt_inventory_v020(read('inventory_full'))
        self.assertIn('operation',r['recommended_rechecks'])
        self.assertNotIn('operation_agent',r['recommended_rechecks'])

    def test_detected_event_names_and_original_fields(self):
        raw=read('inventory_full');r=adapt_inventory_v020(raw)
        for a,b in zip(r['detected_events'],raw['detected_events']):
            self.assertEqual(a['source_payload'],b)
            self.assertEqual(a['source_event_type'],b['event_type'])
            self.assertEqual(a['scope']['target_date'],b['date'])
        self.assertTrue(any(e['event_type']=='supply_event' for e in r['detected_events']))

    def test_clarification_and_skipped_analysis_retained(self):
        raw=read('inventory_clarification');r=adapt_inventory_v020(raw)
        self.assertEqual(r['status'],'needs_clarification')
        self.assertEqual(r['provenance']['analysis_scope']['coverage'],'event')
        self.assertTrue(r['detected_events'][0]['needs_clarification'])
        self.assertEqual(r['source_payload']['execution'],raw['execution'])
        result=make_final_recommendation({}, {}, r)
        self.assertIsNone(result['recommended_servings'])

    def test_price_impacts_only_link_price_causes(self):
        raw=read('inventory_full');r=adapt_inventory_v020(raw)
        for risk in r['price_risks']:
            self.assertTrue(all(i['cause']=='price_event' for i in risk['affected_menus']))
        for risk in r['supply_risks']:
            self.assertTrue(all(i['cause']=='supply_risk' for i in risk['affected_menus']))

    def test_ml_v2_true_contract_preserved(self):
        raw=read('ml_v2_demo');r=adapt_ml_v2(raw)
        self.assertEqual(r['source_payload'],raw)
        self.assertEqual(r['prediction'],raw['prediction'])
        self.assertEqual(r['input_summary'],raw['input_data'])
        self.assertEqual(r['provenance']['prediction_id'],raw['prediction_id'])
        self.assertEqual(r['provenance']['target_date'],raw['target_date'])
        self.assertEqual(r['mode'],'demo');self.assertFalse(r['operational_eligible'])
        self.assertEqual(r['availability_status'],'historical_unknown')
        self.assertIsNone(r['provenance']['input_revision'])
        self.assertNotIn('shortage_probability',r)

    def test_ml_demo_operational_hold(self):
        p=baseline();p['demand_result']=adapt_ml_v2(read('ml_v2_demo'))
        r=make_final_recommendation(**p)
        self.assertNotEqual(r['status'],'ok');self.assertEqual(r['confidence'],'LOW')
        self.assertIsNone(r['recommended_servings'])
        self.assertIn('historical_unknown',str(r['data_quality_notes']))

    def test_ml_error_envelope_kept(self):
        raw={'result':None,'error':{'code':'availability_error','message':'missing'}}
        r=adapt_ml_v2(raw)
        self.assertIsNone(r['prediction']);self.assertEqual(r['source_payload'],raw)

    def test_inventory_period_cannot_be_overridden(self):
        raw=read('inventory_full');context=deepcopy(baseline()['inventory_risk_result']['provenance'])
        context['target_date']='2030-01-01'
        r=adapt_inventory_v020(raw,provenance=context)
        self.assertEqual(r['provenance']['analysis_scope']['coverage'],'unknown')

    def test_missing_operation_is_not_completed(self):
        operation=adapt_operation_contract({})
        self.assertIsNone(operation['recommended_servings'])
        self.assertTrue(all(v=='UNKNOWN' for v in operation['constraints'].values()))

    def test_partial_real_pipeline_cannot_claim_operational_e2e(self):
        result=make_final_recommendation(adapt_ml_v2(read('ml_v2_demo')),{},adapt_inventory_v020(read('inventory_full')),
            input_revision='captured-fixture-input')
        self.assertNotEqual(result['status'],'ok');self.assertIsNone(result['recommended_servings'])
        self.assertTrue(result['recommended_rechecks'])
        self.assertIn('SIMULATION',str(result['data_quality_notes']))

class V012CapturedEventContractTests(unittest.TestCase):
    def test_actual_event_report_cannot_be_promoted_to_full(self):
        raw=read('inventory_event');p=baseline()
        context=deepcopy(p['inventory_risk_result']['provenance'])
        r=adapt_inventory_v020(raw,provenance=context)
        self.assertEqual(r['provenance']['analysis_scope']['coverage'],'event')
        self.assertEqual(r['source_payload']['execution']['scope'],'event_scoped')
        self.assertEqual(r['decision_trace'],raw['decision_trace'])
        # Even a caller's false full label cannot override the captured raw execution.
        r['provenance']['analysis_scope']['coverage']='full'
        p['inventory_risk_result']=r
        result=make_final_recommendation(**p)
        self.assertIsNone(result['recommended_servings'])
        self.assertTrue(any(q['analysis_mode']=='full' and q['reason']=='event_report_requires_full' for q in result['recommended_rechecks']))
