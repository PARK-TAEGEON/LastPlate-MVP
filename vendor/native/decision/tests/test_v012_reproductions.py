"""Written and run against v0.1.1 before implementing v0.1.2."""
import unittest
from copy import deepcopy
from lastplate_decision import make_final_recommendation as decide
from lastplate_decision.adapters import adapt_ml_v2
from examples.fixtures import baseline, PASS


def explicit_baseline():
    p=baseline()
    p['operation_result']['provenance']['consumed_results']={
        'demand_forecast':p['demand_result']['provenance']['result_revision'],
        'inventory_risk':p['inventory_risk_result']['provenance']['result_revision']}
    return p


class V012Reproductions(unittest.TestCase):
    def test_initial_missing_demand_dependency_holds(self):
        p=explicit_baseline();del p['operation_result']['provenance']['consumed_results']['demand_forecast']
        r=decide(**p)
        self.assertEqual(r['serving_action']['decision'],'NEEDS_CONFIRMATION')
        self.assertIn('operation',[q['agent'] for q in r['recommended_rechecks']])

    def test_initial_stale_demand_dependency_holds_without_ledger(self):
        p=explicit_baseline();p['operation_result']['provenance']['consumed_results']['demand_forecast']='old-demand'
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_initial_missing_required_inventory_dependency_holds(self):
        p=explicit_baseline();del p['operation_result']['provenance']['consumed_results']['inventory_risk']
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_initial_stale_inventory_dependency_holds(self):
        p=explicit_baseline();p['operation_result']['provenance']['consumed_results']['inventory_risk']='old-inventory'
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_nutrition_block_cannot_have_high_confidence(self):
        p=explicit_baseline();p['operation_result']['nutrition_constraints']['status']='FAIL'
        r=decide(**p)
        self.assertEqual(r['status'],'blocked')
        self.assertEqual(r['confidence'],'LOW')
        self.assertIn('nutrition',str(r['confidence_reasons']))
        self.assertNotIn('검증 통과',str(r['confidence_reasons']))

    def test_allergy_generated_violation_explains_low(self):
        p=explicit_baseline();p['operation_result']['constraints']['allergy']='FAIL'
        r=decide(**p)
        self.assertEqual(r['confidence'],'LOW')
        self.assertIn('allergy',str(r['confidence_reasons']))

    def test_relevant_supply_risk_in_confidence(self):
        p=explicit_baseline();p['inventory_risk_result']['supply_risks']=[{'ingredient':'두부','severity':'HIGH'}]
        r=decide(**p)
        self.assertEqual(r['confidence'],'MEDIUM')
        self.assertIn('supply',str(r['confidence_reasons']).lower())

    def test_source_type_simulation_is_quality_warning(self):
        p=explicit_baseline();p['inventory_risk_result']['source_type']='simulation'
        r=decide(**p)
        self.assertEqual(r['confidence'],'MEDIUM')
        self.assertIn('SIMULATION',str(r['data_quality_notes']))

    def test_unknown_source_is_quality_warning(self):
        p=explicit_baseline();p['inventory_risk_result']['data_source']=' unknown: feed '
        self.assertEqual(decide(**p)['confidence'],'MEDIUM')

    def test_real_provenance_is_not_quality_warning(self):
        p=explicit_baseline();p['inventory_risk_result']['data_sources']={'inventory':'REAL:ERP'}
        r=decide(**p)
        self.assertEqual(r['confidence'],'HIGH')
        self.assertEqual(r['data_quality_notes'],[])

    def test_normal_ml_mode_info_does_not_lower_confidence(self):
        p=explicit_baseline();d=p['demand_result']
        raw={k:d[k] for k in ('prediction','prediction_id','model_version','mode','operational_eligible','availability_status')}
        raw.update(target_date='2026-09-18',input_data={'date':'2026-09-18','menu':'두부조림'})
        p['demand_result']=adapt_ml_v2(raw,provenance=d['provenance'])
        self.assertEqual(decide(**p)['confidence'],'HIGH')

    def test_unselected_candidate_demo_does_not_taint_current_plan(self):
        p=explicit_baseline();p['inventory_risk_result']['substitute_candidates']=[{
            'candidate_id':'unrelated','ingredient':'계란','menu':'다른메뉴',
            'constraints':dict(PASS,nutrition='FAIL'),'data_sources':{'nutrition':'DEMO:unused'}}]
        self.assertEqual(decide(**p)['confidence'],'HIGH')
