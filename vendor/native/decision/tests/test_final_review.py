import unittest
from copy import deepcopy
from lastplate_decision import make_final_recommendation as decide
from lastplate_decision.schemas.decision_input import UserEvent
from examples.fixtures import baseline


class FinalReviewTests(unittest.TestCase):
    def test_shared_requested_revision_detects_stale_demand(self):
        p=baseline();p['input_revision']='new-input'
        r=decide(**p)
        self.assertIsNone(r['recommended_servings'])
        self.assertIn('demand_forecast',[q['agent'] for q in r['recommended_rechecks']])

    def test_missing_requested_revision_holds(self):
        p=baseline();del p['input_revision']
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_unrelated_restriction_date_not_applied(self):
        p=baseline();p['user_events']=[{'event_id':'future','event_type':'ingredient_restriction_event',
            'ingredient':'두부','restriction':'do_not_use','date':'2026-09-19'}]
        self.assertEqual(decide(**p)['status'],'ok')

    def test_upstream_supply_event_alias(self):
        p=baseline();p['user_events']=[{'event_type':'supply_risk','event_id':'supply','ingredient':'두부','date':'2026-09-18'}]
        r=decide(**p)
        self.assertEqual({q['agent'] for q in r['recommended_rechecks']},{'inventory_risk','operation'})
        self.assertEqual(UserEvent.model_validate(p['user_events'][0]).event_type,'supply_event')

    def test_top_level_date_conflict_holds(self):
        p=baseline();p['demand_result']['target_date']='2026-09-19'
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_upstream_completion_claim_not_trusted(self):
        p=baseline()
        p['inventory_risk_result']['recommended_rechecks']=[{'request_id':'claimed','agent':'operation_agent',
            'reason':'review','input_revision':'input-1','status':'completed','result_revision':'operation_result-1'}]
        r=decide(**p)
        self.assertEqual(r['recommended_rechecks'][0]['status'],'pending')

    def test_old_upstream_request_revision_is_not_silently_dropped(self):
        p=baseline()
        p['inventory_risk_result']['recommended_rechecks']=[{'request_id':'stale','agent':'operation_agent',
            'reason':'review','input_revision':'old-input'}]
        r=decide(**p)
        self.assertIsNone(r['recommended_servings'])
        self.assertIn('inventory_risk',[q['agent'] for q in r['recommended_rechecks']])

    def test_fresh_result_without_event_ack_does_not_complete(self):
        from lastplate_decision.graph.decision_workflow import build_decision_workflow
        from examples.fixtures import refreshed
        p=baseline();p['user_events']=[{'event_type':'price_event','event_id':'unapplied','ingredient':'두부'}]
        g=build_decision_workflow({
            'operation':lambda payload:refreshed(payload['operation_result'],payload),
            'inventory_risk':lambda payload:refreshed(payload['inventory_risk_result'],payload)})
        r=g.invoke({'payload':p},{'configurable':{'thread_id':'unapplied'},'recursion_limit':100})
        self.assertTrue(r['recommendation']['recommended_rechecks'])
        self.assertIsNone(r['recommendation']['recommended_servings'])
        self.assertTrue(any('이벤트' in (q['error'] or '') for q in r['recheck_state']))

    def test_future_inventory_action_not_selected(self):
        p=baseline();p['inventory_risk_result']['inventory_recommendations'][0]['scope']={'target_date':'2026-09-19','meal_type':'lunch'}
        r=decide(**p)
        self.assertNotIn('inventory-tofu-use',r['selected_action_ids'])
