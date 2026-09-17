"""Audited parent graph; callbacks compute evidence, approval records intent only."""
from copy import deepcopy
from typing import TypedDict, Callable
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import InMemorySaver
from ..agents.decision import make_final_recommendation
from ..schemas.decision_input import DecisionInput, DemandResult, OperationResult, InventoryRiskResult
from ..schemas.decision_output import ApprovalResponse
from ..schemas.context import RecheckRequest
from ..config.decision_policy import DecisionPolicy
from ..rechecks import agent_name, successful_result
from ..dependencies import dependency_revisions, dependency_names


class WorkflowState(TypedDict, total=False):
    payload: dict
    queue: list[str]
    recommendation: dict
    recheck_rounds: int
    recheck_state: list[dict]
    workflow_notes: list[dict | str]
    workflow_trace: list[dict]
    run_id: str
    approval: dict | None
    approval_history: list[dict]


ORDER = ('demand_forecast', 'operation', 'inventory_risk')
RESULTS = {'demand_forecast':('demand_result',DemandResult), 'operation':('operation_result',OperationResult),
           'inventory_risk':('inventory_risk_result',InventoryRiskResult)}
EVENT_ALIASES = {'supply_risk':'supply_event', 'inventory_expiry_event':'expiry_event'}


def decision_node(state, policy=None):
    return {'recommendation':make_final_recommendation(**state['payload'],policy=policy,
        recheck_state=state.get('recheck_state'),run_id=state.get('run_id'),workflow_notes=state.get('workflow_notes'))}


def route_events(payload, policy=None):
    events = payload.get('user_events', [])
    required = set()
    inventory_first = False
    for event in events:
        kind = EVENT_ALIASES.get(event['event_type'],event['event_type'])
        if event.get('needs_clarification'):
            continue
        if kind == 'attendance_event':
            required.update(('demand_forecast','operation'))
        elif kind == 'expiry_event':
            required.add('inventory_risk')
        elif kind in {'price_event','supply_event','ingredient_restriction_event','inventory_shortage_event'}:
            required.update(('inventory_risk','operation'))
            inventory_first = True
    if not events:
        required.update(ORDER)
        r = payload.get('inventory_risk_result', {})
        inventory_first = bool(r.get('price_risks') or r.get('supply_risks'))
    if 'operation_result' in payload:
        parsed=DecisionInput.model_validate(payload)
        policy=policy or DecisionPolicy()
        if 'demand_forecast' in required and dependency_names(parsed,'inventory_risk',policy):
            required.add('inventory_risk')
        if 'inventory_risk' in required and 'inventory_risk' in dependency_names(parsed,'operation',policy):
            required.add('operation')
            inventory_first=True
    order = ('demand_forecast','inventory_risk','operation') if inventory_first else ORDER
    return [name for name in order if name in required]


def _trace(state, kind, **details):
    history = list(state.get('workflow_trace', []))
    history.append(dict(sequence=len(history)+1, run_id=state['run_id'],
        recommendation_revision=state.get('recommendation',{}).get('recommendation_revision'),
        input_revision=state['payload'].get('input_revision'),
        event=kind, details=deepcopy(details)))
    return history


def build_decision_workflow(callbacks: dict[str,Callable] | None=None, *, policy=None, checkpointer=None):
    callbacks = callbacks or {}
    normalized = {}
    for name, cb in callbacks.items():
        canonical = agent_name(name)
        if canonical not in RESULTS or canonical in normalized:
            raise ValueError('Unknown/duplicate callback: '+name)
        normalized[canonical] = cb
    callbacks = normalized
    policy = policy or DecisionPolicy()

    def initialize(state):
        payload = DecisionInput.model_validate(state['payload']).model_dump(mode='json')
        out = dict(payload=payload, run_id=str(uuid4()), queue=route_events(payload,policy),
            recheck_rounds=0, workflow_notes=[], approval=None, approval_history=[], workflow_trace=[], recommendation={})
        initial = make_final_recommendation(**payload,policy=policy,run_id=out['run_id'])
        out['recheck_state'] = initial['recheck_history']
        out['workflow_trace'] = _trace(out,'route',queue=out['queue'],reason='initial')
        for q in initial['recommended_rechecks']:
            out['workflow_trace'] = _trace(out,'recheck_requested',request=q)
        return out

    def run_agent(state):
        out = deepcopy(state)
        name = out['queue'].pop(0)
        key, model = RESULTS[name]
        pending = [RecheckRequest.model_validate(q) for q in out['recheck_state']
                   if q['agent']==name and q['status']!='completed' and
                   q['input_revision']==out['payload'].get('input_revision')]
        # Dependency requirements are bound to the newly refreshed results at dispatch.
        parsed_before=DecisionInput.model_validate(out['payload'])
        for q in pending:
            q.required_dependencies={k:v for k,v in dependency_revisions(parsed_before,name,policy).items() if v}
        out['workflow_trace'] = _trace(out,'callback_started',agent=name,
            request_ids=[q.request_id for q in pending],previous_result=out["payload"][key])
        if name not in callbacks:
            note = name+': callback 미연결; 제공 결과만 검증'
            out['workflow_notes'].append(note)
            out['workflow_trace'] = _trace(out,'callback_unconnected',agent=name)
        else:
            call_payload = deepcopy(out['payload'])
            call_payload['_decision_context'] = {'run_id':out['run_id'],
                'recheck_requests':[q.model_dump() for q in pending]}
            full_requests=[q for q in pending if q.analysis_mode=='full']
            if full_requests:
                call_payload['_decision_context']['analysis_request']={
                    'mode':'full','input_revision':out['payload'].get('input_revision'),
                    'prediction_id':out['payload']['demand_result'].get('prediction_id'),
                    'analysis_scope':out['payload']['operation_result']['current_plan'],
                    'request_ids':[q.request_id for q in full_requests],
                    'reuse_previous_full':False}
            try:
                result = model.model_validate(callbacks[name](call_payload))
                out['payload'][key] = result.model_dump(mode='json')
                parsed = DecisionInput.model_validate(out['payload'])
                out['workflow_notes']=[n for n in out['workflow_notes'] if not (
                    isinstance(n,dict) and n.get('kind')=='callback_failure' and n.get('agent')==name)]
                out['workflow_trace'] = _trace(out,'callback_success',agent=name,
                    result_revision=result.provenance.result_revision,
                    upstream_trace=result.model_dump().get('decision_trace',[]))
                for q in pending:
                    q.attempts += 1
                    issue = successful_result(q,result,parsed,policy)
                    if issue:
                        q.status, q.error = 'stale', issue
                        out['workflow_trace'] = _trace(out,'recheck_stale',request=q.model_dump())
                    else:
                        q.status, q.error, q.result_revision = 'completed',None,result.provenance.result_revision
                        out['workflow_trace'] = _trace(out,'recheck_completed',request=q.model_dump())
            except Exception as exc:
                # Preserve the requested plan scope, not failed computational evidence.
                empty=model().model_dump(mode='json')
                if name=='operation':empty['current_plan']=out['payload'][key]['current_plan']
                out['payload'][key] = empty
                out['workflow_notes'].append(dict(kind='callback_failure',agent=name,message=name+': 재실행 실패 ('+type(exc).__name__+')'))
                out['workflow_trace'] = _trace(out,'callback_failure',agent=name,error_type=type(exc).__name__)
                for q in pending:
                    q.attempts += 1
                    q.status, q.error = 'failed',type(exc).__name__
                    out['workflow_trace'] = _trace(out,'recheck_failed',request=q.model_dump())
        changes = {q.request_id:q.model_dump() for q in pending}
        out['recheck_state'] = [changes.get(q['request_id'],q) for q in out['recheck_state']]
        return out

    def decide(state):
        result = make_final_recommendation(**state['payload'],policy=policy,
            recheck_state=state['recheck_state'],run_id=state['run_id'],workflow_notes=state['workflow_notes'])
        pending = result['recommended_rechecks']
        rounds = state['recheck_rounds']
        queue = []
        if pending and rounds < policy.max_recheck_rounds:
            requested = {q['agent'] for q in pending}
            if 'demand_forecast' in requested:
                requested.add('operation')
            parsed=DecisionInput.model_validate(state['payload'])
            if 'demand_forecast' in requested and dependency_names(parsed,'inventory_risk',policy):
                requested.add('inventory_risk')
            if 'inventory_risk' in requested and 'inventory_risk' in dependency_names(parsed,'operation',policy):
                requested.add('operation')
            # Every recheck with inventory + operation uses new inventory first,
            # including compound demand+price/supply rechecks.
            queue = [n for n in ('demand_forecast','inventory_risk','operation') if n in requested and n in callbacks]
        out = dict(state, recommendation=result, recheck_state=result['recheck_history'],queue=queue,
                   recheck_rounds=rounds+bool(queue))
        known = {q['request_id'] for q in state['recheck_state']}
        for q in pending:
            if q['request_id'] not in known:
                out['workflow_trace'] = _trace(out,'recheck_requested',request=q)
        out['workflow_trace'] = _trace(out,'decision_result',status=result['status'],
            confidence=result['confidence'],selected_action_ids=result['selected_action_ids'],
            decision_trace=result['decision_trace'],upstream_traces=result['upstream_traces'])
        if queue:
            out['workflow_trace'] = _trace(out,'route',queue=queue,reason='recheck',round=rounds+1)
        elif pending:
            event = 'recheck_limit' if rounds >= policy.max_recheck_rounds else 'recheck_unresolved'
            out['workflow_trace'] = _trace(out,event,requests=[q['request_id'] for q in pending])
            result['provenance_notes'].append('미해결 재실행 요청: 상한/콜백 미연결/입력 확인 필요')
        return out

    def await_approval(state):
        return dict(workflow_trace=_trace(state,'approval_pending'),
            approval={'choice':'pending','run_id':state['run_id'],
                'recommendation_revision':state['recommendation']['recommendation_revision'],'executed':False})

    def approval(state):
        result = state['recommendation']
        response = ApprovalResponse.model_validate(interrupt({'type':'human_approval',
            'run_id':state['run_id'],'recommendation':result,
            'choices':['approve','modify','reject'],'execution':'none'}))
        if response.recommendation_revision != result['recommendation_revision']:
            raise ValueError('최신 recommendation_revision을 포함해야 합니다.')
        if response.choice=='approve' and result['status']!='ok':
            raise ValueError('확인 필요/차단된 현재 계획은 승인할 수 없습니다.')
        record = response.model_dump(mode='json')
        record.update(executed=False,run_id=state['run_id'],selected_action_ids=result['selected_action_ids'])
        out = dict(approval=record,approval_history=state['approval_history']+[record],
                   workflow_trace=_trace(state,'approval_'+response.choice,response=record))
        if response.choice=='modify':
            revised=DecisionInput.model_validate(response.revised_input).model_dump(mode='json')
            out.update(payload=revised,queue=route_events(revised,policy),recheck_rounds=0,workflow_notes=[])
            merged=dict(state,**out)
            out['workflow_trace']=_trace(merged,'route',queue=out['queue'],reason='operator_revision')
        return out

    graph=StateGraph(WorkflowState)
    for name,node in (('initialize',initialize),('run_agent',run_agent),('decision',decide),
                      ('await_approval',await_approval),('human_approval',approval)):
        graph.add_node(name,node)
    graph.add_edge(START,'initialize')
    graph.add_conditional_edges('initialize',lambda s:'run_agent' if s['queue'] else 'decision')
    graph.add_conditional_edges('run_agent',lambda s:'run_agent' if s['queue'] else 'decision')
    graph.add_conditional_edges('decision',lambda s:'run_agent' if s['queue'] else 'await_approval')
    graph.add_edge('await_approval','human_approval')
    graph.add_conditional_edges('human_approval',lambda s:
        ('run_agent' if s['queue'] else 'decision') if s['approval']['choice']=='modify' else END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
