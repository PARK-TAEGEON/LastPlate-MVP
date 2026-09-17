"""Stable request identity, acknowledgements and dependency freshness."""
from hashlib import sha256
import json
from copy import deepcopy
from .schemas.context import RecheckRequest
from .evidence import KEYS

ALIASES = {'operation_agent':'operation', 'inventory_risk_agent':'inventory_risk',
           'demand':'demand_forecast'}


def agent_name(name):
    return ALIASES.get(name, name)


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]


def request(agent, reason, payload, *, source_agent='decision', source_revision=None, request_id=None, policy=None):
    agent = agent_name(agent)
    p = payload.demand_result.provenance
    result = getattr(payload, KEYS[agent]) if agent in KEYS else None
    from .config.decision_policy import DecisionPolicy
    from .dependencies import dependency_revisions
    dependencies = {k:v for k,v in dependency_revisions(payload,agent,policy or DecisionPolicy()).items() if v}
    identity = [agent, reason, payload.input_revision, source_agent, source_revision]
    return RecheckRequest(analysis_mode='full' if agent=='inventory_risk' and (
        payload.inventory_risk_result.provenance.analysis_scope.coverage!='full' or
        reason in {'event_report_requires_full','analysis_scope_mismatch'}) else None, request_id=request_id or 'rq-'+fingerprint(identity), agent=agent, reason=reason,
        input_revision=payload.input_revision, source_agent=source_agent, source_result_revision=source_revision,
        baseline_result_revision=result.provenance.result_revision if result else None,
        required_dependencies=dependencies)


def reconcile(generated, previous, payload, policy=None):
    """Completed requests remain auditable and suppress unchanged upstream requests.

    Completion is recorded by the workflow, then invalidated if the result/dependencies
    no longer match. Imported caller ledgers require the same validation.
    """
    from .evidence import evidence_issues
    from .config.decision_policy import DecisionPolicy
    invalid_agents={a for a,_,_ in evidence_issues(payload,policy or DecisionPolicy())}
    ledger = {x.request_id:x.model_copy(deep=True) for x in previous}
    for q in generated:
        if q.request_id not in ledger:
            ledger[q.request_id] = q.model_copy(deep=True)
    for q in ledger.values():
        if q.status != 'completed':
            continue
        current = getattr(payload, KEYS[q.agent], None) if q.agent in KEYS else None
        fresh = q.agent not in invalid_agents and current is not None and q.input_revision is not None and (
            current.provenance.input_revision == q.input_revision == payload.input_revision
            and current.provenance.result_revision == q.result_revision
        )
        for name, rev in q.required_dependencies.items():
            upstream = getattr(payload, KEYS[name]).provenance.result_revision
            fresh = fresh and upstream == rev and current.provenance.consumed_results.get(name) == rev
        if not fresh:
            q.status = 'stale'
            q.error = '완료 뒤 결과/입력/의존 revision 변경'
    # Old input revisions never block the newly revised plan, but remain history.
    active_revision = payload.input_revision
    unresolved = [q for q in ledger.values() if q.status != 'completed' and
                  (q.input_revision == active_revision or active_revision is None)]
    return unresolved, list(ledger.values())


def successful_result(q, result, payload, policy):
    """A successful callback alone is not completion: require fresh matching evidence."""
    from .evidence import evidence_issues
    p = result.provenance
    if not q.input_revision or p.input_revision != q.input_revision:
        return '입력 revision 누락/불일치'
    if not p.result_revision or p.result_revision == q.baseline_result_revision:
        return '이전 결과 revision 재사용'
    if not p.prediction_id or p.prediction_id != payload.demand_result.prediction_id:
        return '예측 ID 불일치'
    for name, rev in q.required_dependencies.items():
        actual = getattr(payload, KEYS[name]).provenance.result_revision
        if p.consumed_results.get(name) != actual or actual != rev:
            return f'{name} 최신 결과 소비 근거 없음'
    if any(agent == q.agent for agent, _, _ in evidence_issues(payload, policy)):
        return '대상 날짜/분석 범위/운영 적격성 불일치'
    from .evidence import selector, relation
    for event in payload.user_events:
        rule = selector(event)
        if (rule.target_date or rule.meal_type) and relation(rule, payload.operation_result.current_plan,
                payload.operation_result.current_plan, policy) == 'unrelated':
            continue
        targets = ({'demand_forecast','operation'} if event.event_type == 'attendance_event' else
                   {'inventory_risk'} if event.event_type == 'expiry_event' else
                   {'inventory_risk','operation'} if event.event_type in {'price_event','supply_event','ingredient_restriction_event','inventory_shortage_event'} else set())
        if q.agent in targets and (not event.event_id or event.event_id not in result.applied_event_ids):
            return '사용자 이벤트 반영 ID 누락'
    if q.agent == 'inventory_risk' and result.status != 'ok':
        return 'Inventory 분석 미완료'
    return None
