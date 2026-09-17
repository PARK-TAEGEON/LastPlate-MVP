import unittest
from copy import deepcopy
from lastplate_decision.agents.decision import make_final_recommendation as decide
from examples.fixtures import baseline, PASS
from lastplate_decision.graph.decision_workflow import build_decision_workflow


def scoped():
    p = baseline()
    scope = {'target_date': '2026-09-18', 'meal_type': 'lunch',
             'menus': [{'menu': '두부조림', 'ingredients': ['두부'], 'ingredients_complete': True}],
             'menus_complete': True, 'coverage': 'full'}
    p['operation_result']['current_plan'] = deepcopy(scope)
    for key in ('demand_result', 'operation_result', 'inventory_risk_result'):
        p[key]['provenance'] = dict(target_date='2026-09-18', prediction_id='fixture-1',
            input_revision='input-1', result_revision=key+'-1', analysis_scope=deepcopy(scope))
    p['operation_result']['provenance']['consumed_results']={'demand_forecast':'demand_result-1','inventory_risk':'inventory_risk_result-1'}
    p['demand_result'].update(mode='operation', operational_eligible=True, availability_status='validated_declared_receipts')
    return p


class ReviewReproductionTests(unittest.TestCase):
    def test_current_menu_allergy_must_block(self):
        p = scoped()
        p['inventory_risk_result']['alerts'] = [{'type':'allergy', 'severity':'HIGH',
            'menu':'두부조림', 'ingredient':'두부', 'message':'현재 메뉴 알레르기'}]
        self.assertEqual(decide(**p)['status'], 'blocked')

    def test_unknown_scope_must_hold(self):
        p = scoped()
        p['operation_result']['current_plan']['menus'][0]['ingredients_complete'] = False
        p['inventory_risk_result']['alerts'] = [{'type':'allergy','severity':'HIGH',
            'ingredient':'계란', 'message':'포함 여부 미확인'}]
        self.assertEqual(decide(**p)['serving_action']['decision'], 'NEEDS_CONFIRMATION')

    def test_rejected_alternative_does_not_block_current_plan(self):
        p = scoped()
        p['inventory_risk_result']['substitute_candidates'] = [{'candidate_id':'unused',
            'ingredient':'계란', 'menu':'다른메뉴', 'constraints':dict(PASS, nutrition='FAIL')}]
        self.assertEqual(decide(**p)['status'], 'ok')

    def test_simulation_source_lowers_confidence(self):
        p = scoped()
        p['inventory_risk_result']['data_sources'] = {'supply':'SIMULATION:local'}
        self.assertEqual(decide(**p)['confidence'], 'MEDIUM')

    def test_ineligible_demand_not_approved(self):
        p = scoped()
        p['demand_result'].update(mode='replay', operational_eligible=False, availability_status='historical_unknown')
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_revision_mismatch_holds(self):
        p = scoped()
        p['operation_result']['provenance']['input_revision'] = 'old-input'
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_missing_provenance_holds(self):
        p = scoped()
        del p['inventory_risk_result']['provenance']
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_one_menu_card_for_two_risks(self):
        p = scoped()
        risk = {'ingredient':'두부','affected_menus':['두부조림']}
        p['inventory_risk_result'].update(price_risks=[risk], supply_risks=[dict(risk,severity='HIGH')])
        self.assertEqual(len(decide(**p)['menu_actions']), 1)

    def test_versioned_recheck_objects_and_alias(self):
        p = scoped()
        p['inventory_risk_result']['recommended_rechecks'] = ['operation_agent']
        q = decide(**p)['recommended_rechecks'][0]
        self.assertIsInstance(q, dict)
        self.assertEqual(q['agent'], 'operation')
        self.assertIn('request_id', q)
        self.assertIn('input_revision', q)
        self.assertIn('result_revision', q)
        self.assertIn('status', q)

    def test_workflow_trace_is_cumulative(self):
        p = scoped()
        r = build_decision_workflow().invoke({'payload':p}, {'configurable':{'thread_id':'reproduction'}})
        self.assertIn('workflow_trace', r)
        self.assertIn('run_id', r)
        self.assertIn('recommendation_revision', r['recommendation'])


if __name__ == '__main__':
    unittest.main()
