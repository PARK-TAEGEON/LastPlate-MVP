"""Tri-state scope intersection and cross-agent evidence consistency."""
from .schemas.context import AnalysisScope, ScopeSelector

KEYS = {'demand_forecast':'demand_result', 'operation':'operation_result', 'inventory_risk':'inventory_risk_result'}


def scope_key(scope, policy):
    return (scope.target_date, scope.meal_type, scope.coverage, scope.menus_complete,
            tuple(sorted((policy.normalize(m.menu), tuple(sorted(policy.normalize(i) for i in m.ingredients)),
                          m.ingredients_complete) for m in scope.menus)))


def selector(item):
    value = item.scope.model_dump() if hasattr(item, 'scope') else {}
    raw = item.model_dump() if hasattr(item, 'model_dump') else item
    for key, alias in (('target_date','date'), ('end_date','end_date'), ('meal_type','meal_type'),
                       ('menu','menu'), ('ingredient','ingredient'), ('candidate_id','candidate_id')):
        if not value.get(key):
            value[key] = raw.get(key) or raw.get(alias)
    return ScopeSelector.model_validate(value)


def relation(rule, target, report_scope, policy, candidate_id=None):
    """All dimensions must intersect. Any explicit disjoint dimension wins over unknown."""
    if rule.candidate_id is not None and rule.candidate_id != candidate_id:
        return 'unrelated'
    explicit = any((rule.target_date, rule.meal_type, rule.menu, rule.ingredient, rule.candidate_id, rule.applies_to_all))
    if not explicit:
        return 'unknown'
    unknown = False
    day = rule.target_date or report_scope.target_date
    meal = rule.meal_type or report_scope.meal_type
    if day and target.target_date:
        if not day <= target.target_date <= (rule.end_date or day):
            return 'unrelated'
    elif not rule.applies_to_all:
        unknown = True
    if meal and target.meal_type:
        if meal != target.meal_type:
            return 'unrelated'
    elif not rule.applies_to_all:
        unknown = True
    menus = target.menus
    if rule.menu:
        menus = [m for m in menus if policy.normalize(m.menu) == policy.normalize(rule.menu)]
        if not menus:
            if target.menus_complete:
                return 'unrelated'
            unknown = True
    if rule.ingredient:
        found = any(policy.normalize(rule.ingredient) in {policy.normalize(i) for i in m.ingredients} for m in menus)
        if not found:
            if menus and all(m.ingredients_complete for m in menus) and (rule.menu or target.menus_complete):
                return 'unrelated'
            unknown = True
    return 'unknown' if unknown else 'matched'


def evidence_issues(payload, policy):
    """Returns (agent, code, human note). Never fabricates unavailable provenance."""
    d, o, r = payload.demand_result, payload.operation_result, payload.inventory_risk_result
    plan = o.current_plan
    issues = []
    if not payload.input_revision:
        issues.append(('operation', 'requested_revision_missing', '요청의 공통 input_revision 누락'))
    if not d.prediction_id:
        issues.append(('demand_forecast', 'prediction_id_missing', 'Demand prediction_id 누락'))
    if not plan.target_date or not plan.meal_type or not plan.menus or not plan.menus_complete or plan.coverage != 'full':
        issues.append(('operation', 'plan_scope_missing', '현재 운영안 날짜·끼니·전체 메뉴 범위 누락'))
    if any(not m.ingredients_complete for m in plan.menus):
        issues.append(('operation', 'plan_ingredients_unknown', '현재 메뉴 식재료 목록 완전성 미확인'))
    for agent, key in KEYS.items():
        p = getattr(payload, key).provenance
        for name in ('target_date','prediction_id','input_revision','result_revision'):
            if not getattr(p, name):
                issues.append((agent, 'missing_'+name, f'{agent}: {name} 누락'))
        extra_date = (getattr(payload, key).model_extra or {}).get('target_date')
        if extra_date and extra_date != p.target_date:
            issues.append((agent, 'top_date_mismatch', f'{agent}: 원본 대상 날짜 불일치'))
        if p.target_date and plan.target_date and p.target_date != plan.target_date:
            issues.append((agent, 'target_date_mismatch', f'{agent}: 대상 날짜 불일치'))
        if p.prediction_id and d.prediction_id and p.prediction_id != d.prediction_id:
            issues.append((agent, 'prediction_id_mismatch', f'{agent}: 예측 ID 불일치'))
        if p.input_revision and payload.input_revision and p.input_revision != payload.input_revision:
            issues.append((agent, 'input_revision_mismatch', f'{agent}: 입력 revision 불일치'))
        if scope_key(p.analysis_scope, policy) != scope_key(plan, policy) or p.analysis_scope.coverage != 'full':
            issues.append((agent, 'analysis_scope_mismatch', f'{agent}: 분석 범위 누락/불일치 또는 부분 분석'))
    if d.mode != 'operation' or d.operational_eligible is not True or d.availability_status != 'validated_declared_receipts':
        issues.append(('demand_forecast', 'demand_ineligible',
            f'Demand 운영 부적격/미확인: mode={d.mode}, operational_eligible={d.operational_eligible}, availability_status={d.availability_status}'))
    if d.input_summary.get('date') and d.input_summary['date'] != plan.target_date:
        issues.append(('demand_forecast', 'input_date_mismatch', 'Demand 원본 입력 날짜 불일치'))
    from .dependencies import dependency_issues
    issues.extend(dependency_issues(payload, policy))
    raw = r.source_payload
    declared_event = (r.model_extra.get('analysis_mode') == 'event' or
        r.model_extra.get('execution', {}).get('scope') == 'event_scoped' or
        raw.get('analysis_mode') == 'event' or raw.get('execution', {}).get('scope') == 'event_scoped')
    if r.provenance.analysis_scope.coverage == 'event' or declared_event:
        issues.append(('inventory_risk', 'event_report_requires_full',
            '부분 보고서: 현재 input_revision의 full 재분석 필요; 이전 full 재사용/coverage 라벨 승격 금지'))
    return list(dict.fromkeys(issues))
