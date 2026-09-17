"""v0.1.2 policy boundaries. Workflow callbacks below are MOCKS, not upstream E2E."""
import unittest
from copy import deepcopy
from uuid import uuid4
from lastplate_decision import make_final_recommendation as decide
from lastplate_decision.schemas.decision_input import DecisionInput
from lastplate_decision.config.decision_policy import DecisionPolicy
from lastplate_decision.dependencies import dependency_names
from lastplate_decision.graph.decision_workflow import build_decision_workflow,route_events
from lastplate_decision.adapters import adapt_inventory_v020,adapt_ml_v2
from examples.fixtures import baseline,refreshed
from tests.test_real_contracts import read


def run(payload,callbacks=None):
    return build_decision_workflow(callbacks).invoke({'payload':payload},
        {'configurable':{'thread_id':str(uuid4())},'recursion_limit':100})


class DependencyPolicyTests(unittest.TestCase):
    def test_independent_inventory_has_no_demand_dependency(self):
        p=DecisionInput.model_validate(baseline())
        self.assertEqual(dependency_names(p,'inventory_risk',DecisionPolicy()),[])
        self.assertEqual(decide(**baseline())['status'],'ok')

    def test_no_inventory_use_does_not_require_consumption(self):
        p=baseline();p['inventory_risk_result']['inventory_recommendations']=[]
        del p['operation_result']['provenance']['consumed_results']['inventory_risk']
        self.assertEqual(decide(**p)['confidence'],'HIGH')
        self.assertEqual(decide(**p,policy=DecisionPolicy(operation_inventory_dependency='always'))['status'],'needs_confirmation')

    def test_declared_inventory_cannot_be_ignored_even_if_empty(self):
        p=baseline();p['inventory_risk_result']['inventory_recommendations']=[]
        p['operation_result']['provenance']['consumed_results']['inventory_risk']='old'
        self.assertEqual(decide(**p)['status'],'needs_confirmation')

    def test_demand_scaled_inventory_requires_current_demand(self):
        p=baseline();p['inventory_risk_result']['provenance']['dependency_basis']='demand_scaled'
        self.assertEqual(decide(**p)['status'],'needs_confirmation')
        p['inventory_risk_result']['provenance']['consumed_results']={'demand_forecast':p['demand_result']['provenance']['result_revision']}
        self.assertEqual(decide(**p)['status'],'ok')
        p['demand_result']['provenance']['result_revision']='new-demand'
        self.assertTrue(any(q['agent']=='inventory_risk' for q in decide(**p)['recommended_rechecks']))

    def test_reverse_dependency_is_rejected(self):
        p=baseline();p['inventory_risk_result']['provenance']['consumed_results']={'operation':'operation_result-1'}
        r=decide(**p)
        self.assertEqual(r['status'],'needs_confirmation')
        self.assertTrue(any(q['reason']=='invalid_dependency:operation' for q in r['recommended_rechecks']))

    def test_missing_required_upstream_revision_is_not_satisfied(self):
        p=baseline();p['demand_result']['provenance']['result_revision']=None
        self.assertIsNone(decide(**p)['recommended_servings'])

    def test_imported_completed_ledger_cannot_bypass_current_dependencies(self):
        p=baseline();p['operation_result']['provenance']['consumed_results']={}
        r=decide(**p);ledger=r['recheck_history']
        for q in ledger:
            q.update(status='completed',result_revision=p['operation_result']['provenance']['result_revision'],required_dependencies={})
        r=decide(**p,recheck_state=ledger)
        self.assertEqual(r['status'],'needs_confirmation')
        self.assertTrue(r['recommended_rechecks'])

    def test_demand_scaled_attendance_routes_acyclically(self):
        p=baseline();p['inventory_risk_result']['provenance']['dependency_basis']='demand_scaled'
        p['user_events']=[{'event_type':'attendance_event','event_id':'a','attendance_delta':1}]
        self.assertEqual(route_events(p),['demand_forecast','inventory_risk','operation'])


class QualityPolicyTests(unittest.TestCase):
    def test_source_field_case_whitespace_prefix_matrix(self):
        for field in ('data_sources','data_source','source_type'):
            for token in (' DEMO:local ',' demo ',' SIMULATION:local ','simulation',' unknown '):
                with self.subTest(field=field,token=token):
                    p=baseline();p['inventory_risk_result'][field]={'feed':token} if field=='data_sources' else token
                    r=decide(**p)
                    self.assertEqual(r['confidence'],'MEDIUM')
                    self.assertTrue(r['data_quality_notes'])
                    self.assertNotIn('검증 통과',str(r['confidence_reasons']))

    def test_real_descriptions_and_ml_metadata_are_informational(self):
        p=baseline();p['inventory_risk_result']['data_sources']={'feed':'REAL:ERP (DEMO 아님)'}
        p['demand_result']['provenance_notes']=['ML operation 모드 정상']
        r=decide(**p)
        self.assertEqual(r['confidence'],'HIGH');self.assertFalse(r['data_quality_notes'])
        self.assertTrue(r['provenance_notes'])
        self.assertNotIn('DEMO 검토용',str(r['serving_action']))

    def test_unknown_does_not_get_demo_action_label(self):
        p=baseline();p['inventory_risk_result']['source_type']='UNKNOWN'
        r=decide(**p)
        self.assertEqual(r['confidence'],'MEDIUM')
        self.assertNotIn('DEMO',r['serving_action']['action'])

    def test_unrelated_supply_does_not_lower_current_confidence(self):
        p=baseline();p['inventory_risk_result']['supply_risks']=[{'ingredient':'계란','severity':'HIGH','source_type':'simulation'}]
        self.assertEqual(decide(**p)['confidence'],'HIGH')

    def test_unavailable_current_supply_has_failure_evidence(self):
        p=baseline();p['inventory_risk_result']['supply_risks']=[{'ingredient':'두부','severity':'HIGH','unavailable':True}]
        r=decide(**p)
        self.assertEqual(r['status'],'blocked');self.assertEqual(r['confidence'],'LOW')
        self.assertIn('supply',str(r['confidence_evidence']))

    def test_mae_never_converted_to_probability(self):
        p=baseline()
        for mae in (0,88.48,10000):
            p['demand_result']['validation_mae']=mae
            self.assertEqual(decide(**p)['confidence'],'HIGH')

    def test_adapters_preserve_quality_metadata(self):
        raw=read('inventory_full');raw['source_type']='simulation'
        r=adapt_inventory_v020(raw)
        self.assertEqual(r['source_type'],'simulation')
        raw=read('ml_v2_demo');raw.update(source_type='unknown',limitations=['운영 입력 미확인'])
        d=adapt_ml_v2(raw)
        self.assertEqual(d['source_type'],'unknown');self.assertEqual(d['limitations'],raw['limitations'])


class WorkflowRecoveryTests(unittest.TestCase):
    def test_unconnected_with_valid_inputs_is_information_not_failure(self):
        r=run(baseline())['recommendation']
        self.assertEqual(r['confidence'],'HIGH');self.assertEqual(r['data_quality_notes'],[])
        self.assertTrue(any('미연결' in n for n in r['provenance_notes']))

    def test_callback_failure_is_consistent_low_evidence(self):
        def fail(_):raise RuntimeError('mock error')
        r=run(baseline(),{'operation_agent':fail})
        self.assertEqual(r['recommendation']['confidence'],'LOW')
        self.assertIn('재실행 실패',str(r['recommendation']['confidence_reasons']))
        self.assertIn('재실행 실패',str(r['recommendation']['data_quality_notes']))
        self.assertTrue(any(t['event']=='recheck_limit' for t in r['workflow_trace']))

    def test_recovered_callback_clears_active_failure_but_keeps_trace(self):
        p=baseline();original=deepcopy(p['operation_result']);calls=[]
        def recover(payload):
            calls.append(1)
            if len(calls)==1:raise RuntimeError('once')
            return refreshed(original,payload)
        r=run(p,{'operation_agent':recover})
        self.assertEqual(r['recommendation']['status'],'ok')
        self.assertEqual(r['recommendation']['confidence'],'HIGH')
        self.assertFalse(r['recommendation']['recommended_rechecks'])
        self.assertNotIn('재실행 실패',str(r['recommendation']['confidence_reasons']))
        events=[t['event'] for t in r['workflow_trace']]
        self.assertIn('callback_failure',events);self.assertIn('recheck_completed',events)

    def test_partial_report_requests_current_full_then_operation(self):
        p=baseline();full=deepcopy(p['inventory_risk_result'])
        # Isolate report scope from the source fixture's shared current plan.
        p['inventory_risk_result']=deepcopy(full)
        p['inventory_risk_result']['provenance']['analysis_scope']['coverage']='event'
        p['inventory_risk_result']['decision_trace']=['original event analysis']
        calls=[]
        def inv(payload):
            calls.append('inventory')
            ctx=payload['_decision_context']['analysis_request']
            self.assertEqual(ctx['mode'],'full');self.assertEqual(ctx['input_revision'],p['input_revision'])
            self.assertFalse(ctx['reuse_previous_full'])
            out=refreshed(full,payload);out['decision_trace']=['new full analysis']
            return out
        def op(payload):
            calls.append('operation');return refreshed(payload['operation_result'],payload)
        r=run(p,{'inventory_risk':inv,'operation':op})
        self.assertEqual(r['recommendation']['status'],'ok')
        self.assertFalse(r['recommendation']['recommended_rechecks'])
        self.assertEqual(calls,['inventory','operation'])
        self.assertIn('new full analysis',str(r['recommendation']['upstream_traces']))
        self.assertIn('original event analysis',str(r['workflow_trace']))

    def test_label_only_promotion_stays_pending(self):
        p=baseline();p['inventory_risk_result']['source_payload']={'analysis_mode':'event','execution':{'scope':'event_scoped'}}
        r=run(p,{'inventory_risk':lambda x:refreshed(x['inventory_risk_result'],x),'operation':lambda x:refreshed(x['operation_result'],x)})
        self.assertEqual(r['recommendation']['status'],'needs_confirmation')
        self.assertTrue(any(q['reason']=='event_report_requires_full' for q in r['recommendation']['recommended_rechecks']))

    def test_previous_full_old_input_revision_stays_pending(self):
        p=baseline();old=deepcopy(p['inventory_risk_result']);old['provenance']['input_revision']='previous-input'
        p['inventory_risk_result']=deepcopy(old)
        r=run(p,{'inventory_risk':lambda _:deepcopy(old)})
        self.assertIsNone(r['recommendation']['recommended_servings'])
        self.assertTrue(r['recommendation']['recommended_rechecks'])

    def test_partial_request_old_result_revision_cannot_complete(self):
        p=baseline();old=deepcopy(p['inventory_risk_result'])
        p['inventory_risk_result']=deepcopy(old);p['inventory_risk_result']['provenance']['analysis_scope']['coverage']='event'
        r=run(p,{'inventory_risk':lambda _:deepcopy(old)})
        self.assertEqual(r['recommendation']['status'],'needs_confirmation')
        self.assertTrue(any(q['status']=='stale' for q in r['recommendation']['recommended_rechecks']))
