"""Explicit synthetic evidence for tests, not assertions about real operations."""
from copy import deepcopy

PASS = dict.fromkeys(('shortage','expiry','allergy','nutrition','restriction','supply'), 'PASS')


def baseline():
    scope={'target_date':'2026-09-18','meal_type':'lunch','coverage':'full','menus_complete':True,
           'menus':[{'menu':'두부조림','ingredients':['두부'],'ingredients_complete':True}]}
    p={'input_revision':'input-1',
      'demand_result':{'prediction':487,'prediction_id':'fixture-1','model_version':'fixture','validation_mae':88.48,
                      'mode':'operation','operational_eligible':True,'availability_status':'validated_declared_receipts'},
      'operation_result':{'recommended_servings':523,'constraints':PASS,'nutrition_constraints':{'status':'PASS'},'current_plan':scope},
      'inventory_risk_result':{'status':'ok','inventory_recommendations':[{
          'candidate_id':'tofu-use','ingredient':'두부','menu':'두부조림','quantity':8,'unit':'kg','days_to_expiry':1,
          'constraints':PASS,'reason':'합성 fixture: 사용일 기준 D-1 및 제약 검증 완료'}]}}
    for key in ('demand_result','operation_result','inventory_risk_result'):
        p[key]['provenance']={'target_date':'2026-09-18','prediction_id':'fixture-1','input_revision':'input-1',
                             'result_revision':key+'-1','analysis_scope':scope}
    p['operation_result']['provenance']['consumed_results']={
        'demand_forecast':p['demand_result']['provenance']['result_revision'],
        'inventory_risk':p['inventory_risk_result']['provenance']['result_revision']}
    p['inventory_risk_result']['provenance']['dependency_basis']='independent'
    p['inventory_risk_result']['provenance']['consumed_results']={}
    p['demand_result']['provenance']['consumed_results']={}
    return deepcopy(p)


def recheck_names(result):
    return [q['agent'] for q in result['recommended_rechecks']]


def refreshed(result, payload, suffix='fresh'):
    """MOCK callback helper: explicit fictional revision/dependency assertions."""
    result=deepcopy(result)
    result['provenance']['result_revision'] += '-'+suffix
    if 'recommended_servings' in result:
        dependencies=('demand_forecast','inventory_risk')
    elif 'prediction' in result:
        dependencies=()
    else:
        dependencies=('demand_forecast',) if result['provenance'].get('dependency_basis')=='demand_scaled' or 'demand_forecast' in result['provenance'].get('consumed_results',{}) else ()
    keys={'demand_forecast':'demand_result','inventory_risk':'inventory_risk_result'}
    result['provenance']['consumed_results']={name:payload[keys[name]]['provenance']['result_revision'] for name in dependencies}
    return result
