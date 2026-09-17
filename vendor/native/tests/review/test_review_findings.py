"""System invariants checked against freshly executed, unmodified pipeline outputs."""
import json
from pathlib import Path
OUT=Path(__file__).resolve().parents[2]/'reports/p1-v012/previous-invariants'
def get(name):return json.loads((OUT/(name+'.json')).read_text(encoding='utf-8'))
def test_superseded_supply_must_not_create_current_menu_action():
    assert not any('REVOKED_PUBLIC_SUPPLY' in a['reason'] for a in get('public-superseded')['decision']['menu_actions'])
def test_superseded_supply_must_not_be_current_critical_alert():
    assert not any(a.get('superseded') for a in get('public-superseded')['decision']['critical_alerts'])
def test_inventory_must_use_operation_raw_requirement_for_raw_stock():
    r=get('loss-gap-single-lot')
    o=next(x for x in r['operation']['ingredient_requirements'] if x['ingredient']=='두부')
    i=next(x for x in r['inventory_risk']['inventory_status'] if x['ingredient']=='두부')
    assert i['shortage_at_service_g']==max(0,o['cooking_required']-o['stock'])
def test_invalid_ml_input_must_return_http_4xx():
    assert 400<=get('probes')['api-invalid-ml']['http']<500
def test_convertible_order_units_must_not_fail_inventory_stage():
    r=get('order-convertible-unit')
    assert r['inventory_risk'] is not None and r['pipeline_status']=='COMPLETE'
def test_supply_superseded_history_must_be_retained():
    r=get('superseded-supply-audit')
    assert any(e.get('superseded') for e in r['inventory_risk']['detected_events'])
def test_partial_failure_preserves_prior_results():
    r=get('inventory-failure')
    assert r['pipeline_status']=='PARTIAL' and r['demand'] and r['operation'] and r['decision'] and r['inventory_risk'] is None
def test_operation_quantity_identity():
    x=get('probes')['523-identity'];assert x['operation']==x['decision_operation']==523 and x['decision_final'] in (None,523)
def test_ood_warning_reaches_decision():
    for pop in (600,5000):
        r=get('ood-valid-'+str(pop))
        assert r['demand']['applicability']=='OUT_OF_DISTRIBUTION' and r['decision']['confidence']=='LOW'
        assert any('outside training range' in x for x in r['decision']['data_quality_notes'])
def test_raw_prediction_not_clipped():
    r=get('ood-valid-520')
    assert r['demand']['predicted_diners']==r['demand']['source_payload']['prediction']==r['operation']['predicted_diners']>550
    assert r['operation']['capacity_excess']>0
def test_human_approval_always_required():
    for f in OUT.glob('*.json'):
        r=json.loads(f.read_text(encoding='utf-8'))
        if isinstance(r,dict) and r.get('pipeline_status') and isinstance(r.get('decision'),dict):assert r['decision']['requires_human_approval'] is True and r['decision']['approval_status']=='pending'
def test_strict_json_output():
    for f in OUT.glob('*.json'):
        json.dumps(json.loads(f.read_text(encoding='utf-8')),allow_nan=False)
def test_ban_release_superseded_does_not_block_restriction():
    r=get('superseded');assert any(e['superseded'] for e in r['inventory_risk']['detected_events'])
    assert 'restriction' not in r['decision']['serving_action']['failed_constraints']
def test_idempotent_no_input_mutation():
    r=get('probes')['retry'];assert all(r[k] is True for k in ('input_unchanged','prediction_id_same','recommendation_revision_same')) and r['prediction_rows']==1
def test_hard_nutrition_failure_blocks():
    r=get('nutrition-hard-fail');assert r['operation']['constraints']['status']=='FAIL' and r['decision']['decision_type']=='BLOCK'
def test_nutrition_provider_missing_does_not_pass_candidates():
    r=get('nutrition-provider-missing');assert r['inventory_risk']['nutrition_results']
    assert all(n['status']=='UNKNOWN' for n in r['inventory_risk']['nutrition_results'])
