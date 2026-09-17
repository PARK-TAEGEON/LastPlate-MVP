"""Acyclic, shared dependency policy for first calls and reruns."""
from .evidence import selector, relation, KEYS

ALLOWED = {'demand_forecast':set(), 'inventory_risk':{'demand_forecast'},
           'operation':{'demand_forecast','inventory_risk'}}


def inventory_required(payload, policy):
    o,r=payload.operation_result,payload.inventory_risk_result
    if policy.operation_inventory_dependency=='always' or o.order_recommendations:
        return True
    if 'inventory_risk' in o.provenance.consumed_results:
        return True  # An explicitly consumed result cannot later be treated as unused.
    if r.status!='ok' or r.provenance.analysis_scope.coverage!='full':
        return True
    if r.recommended_rechecks:
        return True
    plan=o.current_plan
    for item in r.alerts+r.nutrition_results+r.price_risks+r.supply_risks+r.inventory_recommendations:
        rule=selector(item)
        if getattr(item,'candidate_id',None) and (item in r.alerts or item in r.nutrition_results):
            continue  # Independent rejected candidates are not the selected plan.
        rule=rule.model_copy(update={'candidate_id':None})
        if relation(rule,plan,r.provenance.analysis_scope,policy)!='unrelated':
            return True
    for event in payload.user_events:
        if event.event_type in {'expiry_event','price_event','supply_event','ingredient_restriction_event','inventory_shortage_event'}:
            if relation(selector(event),plan,plan,policy)!='unrelated':
                return True
    return False


def dependency_names(payload, agent, policy):
    names=set()
    if agent=='operation':
        names.add('demand_forecast')
        if inventory_required(payload,policy):names.add('inventory_risk')
    if agent=='inventory_risk' and (payload.inventory_risk_result.provenance.dependency_basis=='demand_scaled'
            or 'demand_forecast' in payload.inventory_risk_result.provenance.consumed_results):
        names.add('demand_forecast')
    return [name for name in ('demand_forecast','inventory_risk') if name in names]


def dependency_revisions(payload, agent, policy):
    # Missing upstream revision stays missing and is an evidence error, never satisfied.
    return {name:getattr(payload,KEYS[name]).provenance.result_revision
            for name in dependency_names(payload,agent,policy)}


def dependency_issues(payload, policy):
    issues=[]
    for agent,key in KEYS.items():
        consumed=getattr(payload,key).provenance.consumed_results
        for name in consumed:
            if name not in ALLOWED[agent]:
                issues.append((agent,'invalid_dependency:'+name,f'{agent}: 허용되지 않는/순환 소비 의존성 {name}'))
        for name,revision in dependency_revisions(payload,agent,policy).items():
            actual=consumed.get(name)
            if not revision or not actual or actual!=revision:
                issues.append((agent,'consumed_dependency:'+name,
                    f'{agent}: {name} 소비 의존 근거 누락/불일치 (required={revision}, consumed={actual})'))
    return issues
