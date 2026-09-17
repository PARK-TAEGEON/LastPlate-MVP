"""Adapters backed by the delivered Inventory & Risk 0.2.0 / ML v2 sources.

Unknown fields are retained in source_payload; no external agent is imported here.
Provenance context must be recorded by the invoking integration, never guessed.
"""
from copy import deepcopy
from datetime import date
from ..schemas.context import Provenance
from ..schemas.decision_input import DemandResult, InventoryRiskResult, OperationResult, UserEvent
from ..rechecks import agent_name, fingerprint

EVENT_ALIASES = {'supply_risk':'supply_event', 'inventory_expiry_event':'expiry_event'}


QUALITY_FIELDS=('data_sources','data_source','source_type','is_demo','limitations','data_quality_notes')


def quality_fields(raw):
    return {k:deepcopy(raw[k]) for k in QUALITY_FIELDS if k in raw}


def adapt_events(events):
    result = []
    for raw in events:
        item = deepcopy(raw)
        item['source_event_type'] = raw['event_type']
        item['event_type'] = EVENT_ALIASES.get(raw['event_type'], raw['event_type'])
        item['reason'] = raw.get('reason') or raw.get('description') or '상위 이벤트'
        item['scope'] = {k:v for k,v in {
            'target_date':raw.get('date'), 'end_date':raw.get('end_date'),
            'meal_type':raw.get('meal_type'), 'ingredient':raw.get('ingredient')}.items() if v is not None}
        item['source_payload'] = deepcopy(raw)
        result.append(UserEvent.model_validate(item).model_dump(mode='json'))
    return result


def _scope(raw, *, menu=None, ingredient=None):
    return {k:v for k,v in {
        'target_date':raw.get('date'), 'end_date':raw.get('end_date'),
        'meal_type':raw.get('meal_type'), 'menu':menu or raw.get('menu_name'),
        'ingredient':ingredient or raw.get('ingredient') or raw.get('affected_ingredient'),
        'candidate_id':raw.get('candidate_id')}.items() if v is not None}


def adapt_inventory_v020(report, *, provenance=None):
    raw = deepcopy(report)
    if raw.get('schema_version') != '2.0':
        raise ValueError('Expected Inventory & Risk schema_version=2.0')
    p = deepcopy(provenance or {})
    p.setdefault('result_revision', 'inventory-'+fingerprint(raw))
    if raw.get('input_snapshot_id'):
        # A generated snapshot may not equal the shared revision: let consistency fail.
        p['input_revision'] = raw['input_snapshot_id']
    period = raw.get('period', {})
    if period.get('start') == period.get('end') and period.get('start'):
        p['target_date'] = period['start']
    notes = []
    scope = p.setdefault('analysis_scope', {})
    if raw.get('execution', {}).get('scope') != 'full' or raw.get('analysis_mode') != 'full':
        scope['coverage'] = 'event'
        notes.append('event_scoped/skipped 분석은 전체 운영 검증을 대체하지 않습니다.')
    target = p.get('target_date')
    if target and (not period.get('start') or not period.get('end') or not period['start'] <= target <= period['end']):
        scope['coverage'] = 'unknown'
        notes.append('대상 날짜가 원본 분석 period에 포함되지 않습니다.')
    p = Provenance.model_validate(p).model_dump(mode='json')
    impacts = deepcopy(raw.get('affected_menus', []))
    alerts = []
    for alert in raw.get('alerts', []):
        linked = [i for i in impacts if i.get('cause_event_id') in alert.get('cause_event_ids', [])]
        if alert.get('candidate_id'):
            linked = []
        for impact in linked or [None]:
            item = deepcopy(alert)
            item['source_payload'] = deepcopy(alert)
            item['scope'] = _scope(impact or alert)
            if impact:
                item['menu'] = impact.get('menu_name')
                item['ingredient'] = impact.get('ingredient') or impact.get('affected_ingredient')
            if alert.get('candidate_id'):
                item['scope']['candidate_id'] = alert['candidate_id']
            alerts.append(item)
    risks = {}
    for category in ('price_risks', 'supply_risks'):
        risks[category] = []
        for value in raw.get(category, []):
            item = deepcopy(value)
            item['scope'] = _scope(value)
            item['message'] = value.get('message') or value.get('description') or category
            item['source_payload'] = deepcopy(value)
            item['affected_menus'] = [deepcopy(i) for i in impacts
                if (i.get('ingredient') or i.get('affected_ingredient')) == value.get('ingredient')
                and i.get('cause') == ('price_event' if category == 'price_risks' else 'supply_risk')
                and (not value.get('event_id') or i.get('cause_event_id') == value['event_id'])]
            if value.get('event_id'):
                item['cause_event_ids'] = [value['event_id']]
            # HIGH supply risk is not a declaration of unavailable inventory.
            risks[category].append(item)
    priority = []
    for value in raw.get('priority_use_candidates', []):
        expiry, service = value.get('expiry_date'), value.get('date')
        priority.append(dict(candidate_id=value['candidate_id'], kind='priority_inventory_use',
            ingredient=value.get('ingredient') or value.get('affected_ingredient'), menu=value.get('menu_name'),
            scope=_scope(value), quantity=value.get('quantity_g'), unit='g' if 'quantity_g' in value else None,
            days_to_expiry=(date.fromisoformat(expiry)-date.fromisoformat(service)).days if expiry and service else None,
            reason=value.get('reason', '상위 FEFO 후보; 검증되지 않은 제약은 UNKNOWN'),
            cause_event_ids=value.get('cause_event_ids', []), source_payload=deepcopy(value), **quality_fields(value)))
    substitutions = []
    nutrition = []
    for value in raw.get('nutrition_results', []):
        item = deepcopy(value)
        item['scope'] = _scope(value)
        item['source_payload'] = deepcopy(value)
        nutrition.append(item)
    for value in raw.get('substitute_candidates', []):
        checks = {}
        if value.get('nutrition_check') in ('PASS','FAIL','UNKNOWN'):
            checks['nutrition'] = value['nutrition_check']
        if value.get('inventory_available') is False:
            checks['shortage'] = 'FAIL'
        proof = next((n for n in nutrition if n.get('candidate_id') == value.get('candidate_id')), None)
        if proof:
            if 'allergy' in proof.get('violations', []):
                checks['allergy'] = 'FAIL'
            elif proof.get('status') == 'PASS' and proof.get('candidate', {}).get('missing') == []:
                checks['allergy'] = 'PASS'  # Explicit combined upstream test, not a missing default.
        substitutions.append(dict(candidate_id=value['candidate_id'], kind='menu_substitution',
            menu=value.get('original_menu'), candidate_menu=value.get('candidate_menu'),
            scope=_scope(value, menu=value.get('original_menu')), constraints=checks,
            cause_event_ids=value.get('cause_event_ids', []),
            reason=value.get('reason','독립 메뉴 대체 후보'), source_payload=deepcopy(value), **quality_fields(value)))
    output = dict(status=raw.get('status','error'), provenance=p, alerts=alerts, **risks,
        affected_menus=impacts, affected_ingredients=raw.get('affected_ingredients', []),
        inventory_recommendations=priority, substitute_candidates=substitutions,
        nutrition_results=nutrition, cost_impacts=raw.get('cost_impacts', []),
        detected_events=adapt_events(raw.get('detected_events', [])),
        recommended_rechecks=[agent_name(x) for x in raw.get('recommended_rechecks', [])],
        decision_trace=raw.get('decision_trace', []), data_sources=raw.get('data_sources', {}),
        limitations=raw.get('limitations', []), source_payload=raw, adapter_notes=notes)
    if raw.get('clarification', {}).get('status') == 'required':
        output['status'] = 'needs_clarification'
    output.update(quality_fields(raw))
    return InventoryRiskResult.model_validate(output).model_dump(mode='json')


def adapt_ml_v2(result, *, provenance=None):
    envelope = deepcopy(result)
    if 'result' in result and ('error' in result):
        if result.get('error') or result.get('result') is None:
            return DemandResult(source_payload=envelope,
                data_quality_notes=['ML v2 predict_node 실패: '+str(result.get('error'))]).model_dump(mode='json')
        result = result['result']
    raw = deepcopy(result)
    p = deepcopy(provenance or {})
    p['target_date'] = raw.get('target_date')
    p['prediction_id'] = raw.get('prediction_id')
    p.setdefault('result_revision', 'demand-'+fingerprint(raw))
    output = dict(prediction=raw.get('prediction'), prediction_id=raw.get('prediction_id'),
        model_version=raw.get('model_version'), validation_mae=raw.get('validation_mae'),
        input_summary=raw.get('input_data',{}), mode=raw.get('mode'),
        operational_eligible=raw.get('operational_eligible'), availability_status=raw.get('availability_status'),
        provenance=p, source_payload=envelope,
        provenance_notes=[f"ML v2: mode={raw.get('mode')}, operational_eligible={raw.get('operational_eligible')}, availability_status={raw.get('availability_status')}"])
    output.update(quality_fields(raw))
    return DemandResult.model_validate(output).model_dump(mode='json')


def adapt_operation_contract(result):
    """Validation-only adapter. There is no supplied real Operation implementation."""
    return OperationResult.model_validate(result).model_dump(mode='json')
