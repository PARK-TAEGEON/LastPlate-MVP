import unittest
from copy import deepcopy
from uuid import uuid4
from langgraph.types import Command
from lastplate_decision.agents.decision import make_final_recommendation as decide
from lastplate_decision.graph.decision_workflow import build_decision_workflow
from lastplate_decision.config.decision_policy import DecisionPolicy
from examples.fixtures import baseline, PASS, refreshed


class ScopeFreshnessTests(unittest.TestCase):
    def alert(self, **scope):
        return {'type':'allergy','severity':'HIGH','message':'scope regression','scope':scope}

    def test_other_date_is_not_blocked(self):
        p=baseline();p['inventory_risk_result']['alerts']=[self.alert(target_date='2026-09-19',menu='두부조림')]
        self.assertEqual(decide(**p)['status'],'ok')

    def test_other_meal_is_not_blocked(self):
        p=baseline();p['inventory_risk_result']['alerts']=[self.alert(meal_type='dinner',menu='두부조림')]
        self.assertEqual(decide(**p)['status'],'ok')

    def test_other_menu_is_not_blocked(self):
        p=baseline();p['inventory_risk_result']['alerts']=[self.alert(menu='계란찜')]
        self.assertEqual(decide(**p)['status'],'ok')

    def test_other_ingredient_is_not_blocked(self):
        p=baseline();p['inventory_risk_result']['alerts']=[self.alert(ingredient='땅콩')]
        self.assertEqual(decide(**p)['status'],'ok')

    def test_unscoped_hard_alert_is_unknown(self):
        p=baseline();p['inventory_risk_result']['alerts']=[self.alert()]
        self.assertEqual(decide(**p)['serving_action']['decision'],'NEEDS_CONFIRMATION')

    def test_explicit_global_rule_blocks(self):
        p=baseline();p['inventory_risk_result']['alerts']=[self.alert(applies_to_all=True)]
        self.assertEqual(decide(**p)['status'],'blocked')

    def test_candidate_specific_alert_not_selected(self):
        p=baseline();p['inventory_risk_result']['alerts']=[self.alert(candidate_id='unused')]
        self.assertEqual(decide(**p)['status'],'ok')

    def test_each_provenance_missing_holds(self):
        for agent in ('demand_result','operation_result','inventory_risk_result'):
            for field in ('target_date','prediction_id','input_revision','result_revision','analysis_scope'):
                with self.subTest(agent=agent,field=field):
                    p=baseline();del p[agent]['provenance'][field]
                    self.assertIsNone(decide(**p)['recommended_servings'])

    def test_each_provenance_mismatch_holds(self):
        for agent in ('operation_result','inventory_risk_result'):
            for field,value in (('target_date','2026-09-19'),('prediction_id','old-pred'),('input_revision','old-input')):
                with self.subTest(agent=agent,field=field):
                    p=baseline();p[agent]['provenance'][field]=value
                    self.assertIsNone(decide(**p)['recommended_servings'])

    def test_event_scoped_report_holds(self):
        p=baseline();p['inventory_risk_result']['provenance']['analysis_scope']['coverage']='event'
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_no_mae_probability(self):
        p=baseline();p['demand_result']['validation_mae']=999
        r=decide(**p)
        self.assertEqual(r['recommended_servings'],523)
        self.assertNotIn('shortage_probability',r)

    def test_demand_missing_operating_fields(self):
        for field in ('mode','operational_eligible','availability_status'):
            p=baseline();del p['demand_result'][field]
            self.assertEqual(decide(**p)['confidence'],'LOW')

    def test_quality_sources_and_limitations(self):
        for source in ('DEMO:recipe','DEMO','SIMULATION:events'):
            p=baseline();p['inventory_risk_result'].update(data_sources={'test':source},limitations=['dish-only'])
            r=decide(**p)
            self.assertEqual(r['confidence'],'MEDIUM')
            self.assertIn(source,str(r['data_quality_notes']))
            self.assertIn('dish-only',str(r['data_quality_notes']))

    def test_unknown_candidate_does_not_block_safe_current_plan(self):
        p=baseline();p['inventory_risk_result']['substitute_candidates']=[{'candidate_id':'unknown','ingredient':'계란','menu':'다른메뉴'}]
        r=decide(**p)
        self.assertEqual(r['status'],'ok')
        self.assertNotIn('candidate-unknown',r['selected_action_ids'])

    def test_global_affected_menus_not_fanned_out(self):
        p=baseline();p['inventory_risk_result'].update(price_risks=[{'ingredient':'계란'}],
            affected_menus=[{'ingredient':'닭고기','menu_name':'닭볶음','date':'2026-09-18','meal_type':'lunch'}])
        self.assertEqual(decide(**p)['menu_actions'],[])


class VersionedWorkflowTests(unittest.TestCase):
    def config(self):
        return {'configurable':{'thread_id':str(uuid4())},'recursion_limit':100}

    def with_request(self):
        p=baseline();p['inventory_risk_result']['recommended_rechecks']=['operation_agent']
        return p

    def test_success_resolves_unchanged_source_request(self):
        p=self.with_request();calls=[]
        def operation(payload):
            calls.append(1)
            return refreshed(payload['operation_result'],payload)
        g=build_decision_workflow({'operation_agent':operation})
        r=g.invoke({'payload':p},self.config())
        self.assertEqual(r['recommendation']['recommended_rechecks'],[])
        self.assertEqual(r['recommendation']['status'],'ok')
        self.assertEqual(len(calls),1)
        self.assertTrue(any(q['status']=='completed' for q in r['recheck_state']))
        self.assertIn('recheck_completed',[t['event'] for t in r['workflow_trace']])

    def test_old_result_does_not_resolve(self):
        g=build_decision_workflow({'operation':lambda p:p['operation_result']})
        r=g.invoke({'payload':self.with_request()},self.config())
        self.assertTrue(r['recommendation']['recommended_rechecks'])
        self.assertIn('recheck_stale',[t['event'] for t in r['workflow_trace']])
        self.assertIn('recheck_limit',[t['event'] for t in r['workflow_trace']])

    def test_failed_result_does_not_resolve(self):
        def failure(payload):raise RuntimeError('failure')
        r=build_decision_workflow({'operation':failure}).invoke({'payload':self.with_request()},self.config())
        self.assertTrue(r['recommendation']['recommended_rechecks'])
        self.assertIn('callback_failure',[t['event'] for t in r['workflow_trace']])
        self.assertIn('recheck_failed',[t['event'] for t in r['workflow_trace']])

    def test_compound_recheck_inventory_before_operation(self):
        p=self.with_request();p['inventory_risk_result']['recommended_rechecks']+=['demand_forecast','inventory_risk']
        calls=[]
        def cb(agent,key):
            def run(payload):
                calls.append(agent)
                return payload[key]
            return run
        g=build_decision_workflow({a:cb(a,k) for a,k in [('demand_forecast','demand_result'),('inventory_risk','inventory_risk_result'),('operation','operation_result')]},policy=DecisionPolicy(max_recheck_rounds=1))
        r=g.invoke({'payload':p},self.config())
        self.assertEqual(calls[-3:],['demand_forecast','inventory_risk','operation'])

    def test_trace_survives_modify_reject_and_preserves_original(self):
        p=baseline();p['inventory_risk_result']['decision_trace']=['ORIGINAL STRING TRACE']
        g=build_decision_workflow();c=self.config();r=g.invoke({'payload':p},c)
        before=deepcopy(r['workflow_trace']);run_id=r['run_id']
        p['operation_result']['recommended_servings']=600
        r=g.invoke(Command(resume={'choice':'modify','operator_id':'op','revised_input':p,
            'recommendation_revision':r['recommendation']['recommendation_revision']}),c)
        self.assertEqual(r['workflow_trace'][:len(before)],before)
        r=g.invoke(Command(resume={'choice':'reject','operator_id':'op','recommendation_revision':r['recommendation']['recommendation_revision']}),c)
        events=[t['event'] for t in r['workflow_trace']]
        self.assertIn('approval_modify',events);self.assertIn('approval_reject',events)
        self.assertEqual({t['run_id'] for t in r['workflow_trace']},{run_id})
        self.assertEqual([t['sequence'] for t in r['workflow_trace']],list(range(1,len(r['workflow_trace'])+1)))
        self.assertIn('ORIGINAL STRING TRACE',str(r['workflow_trace']))
        self.assertFalse(r['approval']['executed'])

    def test_stale_approval_revision_rejected(self):
        g=build_decision_workflow();c=self.config();g.invoke({'payload':baseline()},c)
        with self.assertRaises(ValueError):g.invoke(Command(resume={'choice':'approve','operator_id':'op','recommendation_revision':'stale'}),c)

    def test_completed_request_invalidated_by_dependency_change(self):
        p=self.with_request()
        g=build_decision_workflow({'operation':lambda p:refreshed(p['operation_result'],p)})
        r=g.invoke({'payload':p},self.config())
        changed=r['payload'];changed['inventory_risk_result']['provenance']['result_revision']='new-report'
        report=decide(**changed,recheck_state=r['recheck_state'])
        self.assertTrue(report['recommended_rechecks'])
        self.assertTrue(any(q['status']=='stale' for q in report['recheck_history']))
