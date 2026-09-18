"""Map evidence to Decision's native contract; Decision alone chooses actions."""
from copy import deepcopy
import hashlib,json
from ..risk_evidence import project_active

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def decide(value):
    from lastplate_decision import make_final_recommendation
    from lastplate_decision.adapters import adapt_ml_v2,adapt_inventory_v020
    p,d,o,r=(value.get(k) for k in ('payload','demand','operation','inventory_risk'))
    scope=value['scope']; revision=p['input_revision']
    def provenance(name,raw,consumed=None):
        return dict(target_date=p['target_date'],prediction_id=d['prediction_id'] if d else None,input_revision=revision,
            result_revision=name+'-'+fingerprint(raw),analysis_scope=scope,consumed_results=consumed or {},
            metadata_source='parent-service-execution-record')
    dd={}
    if d:
        dd=adapt_ml_v2(d['source_payload'],provenance=provenance('demand',d))
        dd.update(applicability=d['applicability'],warnings=d['warnings'],source_type='MODEL',
            data_quality_notes=[w['message'] for w in d['warnings']])
        dd['integration_envelope']={k:deepcopy(d[k]) for k in ('confidence','model_type','training_ranges','warnings','model_version','predicted_diners','applicability') if k in d}
        if d['applicability']!='IN_RANGE': dd['operational_eligible']=False
        # Explicit operator scenario is separate from the preserved ML source payload.
        # Decision must compare planned portions to the selected operational count.
        if value.get('operating_diners') is not None:
            dd['prediction']=value['operating_diners']
            dd['source_type']='MANUAL'
            dd['integration_envelope']['operator_diners']=value['operating_diners']
            dd['provenance']['result_revision']='operator-scenario-'+fingerprint([d,value['operating_diners']])
            dd['data_quality_notes'].append('운영자가 직접 입력한 식수로 검토; 원본 모델 예측은 source_payload에 보존')
    rr={}; events=[]; confirmation_gates=[]
    if r:
        active=project_active(r)
        pr=provenance('inventory',active,{'demand_forecast':dd['provenance']['result_revision']} if dd else {})
        pr['dependency_basis']='demand_scaled'
        rr=adapt_inventory_v020(active,provenance=pr)
        # Transport the upstream requirement into Decision's existing pending-recheck gate.
        # No quantity calculation or callback: native Decision holds selection/approval.
        from lastplate_decision.schemas.context import RecheckRequest
        for candidate in active.get('substitute_candidates',[]):
            if not candidate.get('operation_quantity_recheck_required'):
                continue
            cid=candidate['candidate_id']
            reason='operation_quantity_recheck_required:'+cid
            request=RecheckRequest(request_id='rq-'+fingerprint([revision,pr['result_revision'],reason])[:24],
                agent='operation',reason=reason,input_revision=revision,source_agent='inventory_risk',
                source_result_revision=pr['result_revision'],status='pending')
            rr['recommended_rechecks'].append(request.model_dump())
            confirmation_gates.append(dict(candidate_id=cid,code='operation_quantity_recheck_required',
                status='pending',request_id=request.request_id,requires_human_approval=True,
                automatic_execution=False,quantity_basis=candidate.get('quantity_basis')))
        # User-only events are delivered separately. Derived inventory events are already scoped alerts.
        events=[e for e in rr['detected_events'] if e.get('event_type') in ('attendance_event','ingredient_restriction_event')]
    oo={}
    if o:
        checks={k:'UNKNOWN' for k in ('shortage','expiry','allergy','nutrition','restriction','supply')}
        nutrition=[x['status'] for x in o['constraints']['checks'] if x.get('constraint')!='allergy_restriction']
        checks['nutrition']='FAIL' if 'FAIL' in nutrition else 'UNKNOWN' if not nutrition or 'UNKNOWN' in nutrition else 'PASS'
        allergy=[x['status'] for x in o['constraints']['checks'] if x.get('constraint')=='allergy_restriction']
        if allergy: checks['allergy']=allergy[0]
        # Native Risk owns FEFO/expiry/supply/restriction gates. No parallel Decision rules.
        if r: checks.update(active['current_plan_checks'])
        deps={'demand_forecast':dd['provenance']['result_revision']} if dd else {}
        if rr: deps['inventory_risk']=rr['provenance']['result_revision']
        oo=dict(recommended_servings=o['recommended_servings'],current_plan=scope,
            provenance=provenance('operation',{'operation':o,'inventory_evidence':active if r else None},deps),
            constraints=checks,nutrition_constraints={'status':checks['nutrition']},
            order_recommendations=[{**q,'constraints':checks} for q in o['order_reviews']],
            source_payload=o,data_sources=p['sources'],
            data_quality_notes=[a['message'] for a in o.get('alerts',[]) if a['severity']=='HIGH'],
            decision_trace=o['decision_trace'])
        # This adapter consumes the risk report for evidence only; no recalculation of quantities.
        if o['status'] in ('invalid_input','needs_clarification') or (o.get('capacity_excess') or 0)>0:
            oo['data_quality_notes'].append('Operation requires confirmation: '+o['status'])
            # Translate a non-executable upstream plan into Decision's evidence gate.
            # Preserve the original ML eligibility in d.source_payload.
            if dd: dd['operational_eligible']=False
    final=make_final_recommendation(dd,oo,rr,events,input_revision=revision,run_id=p['request_id'])
    if final['status']=='blocked': decision='BLOCK'
    elif final['status']=='needs_confirmation': decision='NEEDS_CONFIRMATION'
    else:
        decisions=[final['serving_action']['decision']]+[a['decision'] for k in ('procurement_actions','inventory_actions','menu_actions') for a in final[k] if a['selected']]
        decision='REVIEW' if 'REVIEW' in decisions else 'ADJUST' if 'ADJUST' in decisions else 'KEEP'
    final['decision_type']=decision
    final['confirmation_gates']=confirmation_gates
    final['operation_recommended_servings']=o.get('recommended_servings') if o else None
    final['adapter_provenance']={k:v.get('provenance') for k,v in [('demand',dd),('operation',oo),('inventory_risk',rr)]}
    final['source_payload']={'inventory_risk':deepcopy(r)} # audit only, never fed back into Decision
    final['active_evidence_summary']={'current_plan_checks':active['current_plan_checks'] if r else {},
        'recommended_rechecks':active['recommended_rechecks'] if r else [],
        'projection':active.get('evidence_projection') if r else None}
    if d: final['demand_envelope']={k:deepcopy(d[k]) for k in ('confidence','model_type','training_ranges','warnings','model_version','predicted_diners','applicability') if k in d}
    return final
