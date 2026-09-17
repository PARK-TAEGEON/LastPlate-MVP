from copy import deepcopy
from ..native_stock import usable_stock

def build_operation(p, demand):
    menus=[m['menu_name'] for m in p['weekly_menu'] if m['date']==p['target_date'] and m['meal_type']==p['meal_type']]
    recipes=[dict(menu_name=r['menu_name'],**i) for r in p['recipes'] if r['menu_name'] in menus for i in r['ingredients']]
    cfg=deepcopy(p['operation_policy'])
    cfg.update(capacity_servings=p['meal_capacity'],required_menus=menus)
    labels=[v.upper() for v in p['sources'].values()]
    cfg['data_mode']=('DEMO' if any('DEMO' in v or 'SIMULATION' in v for v in labels) else
        'REAL' if all(v.startswith(('REAL','USER_UPLOAD','PUBLIC_API')) for v in labels) else 'UNSPECIFIED')
    raw=deepcopy(demand['source_payload'])
    raw['input_snapshot_id']=p['input_revision']
    raw['applicability']={'status':{'IN_RANGE':'IN_DOMAIN','OUT_OF_DISTRIBUTION':'OOD','UNKNOWN':'UNKNOWN'}[demand['applicability']],
        'reasons':[x['message'] for x in demand['warnings']]}
    raw['warnings']=[{k:w[k] for k in ('code','category','severity','message')} for w in demand['warnings']]
    return dict(demand_result=raw,_demand_envelope={k:deepcopy(demand[k]) for k in ('confidence','model_type','training_ranges','warnings','model_version','predicted_diners','applicability') if k in demand},recipe_data=recipes,
        inventory_data=[dict(ingredient=x['ingredient'],stock=usable_stock(x['current_stock'],x['expiry_date'],p['target_date']),
            unit=x['unit']) for x in p['inventory']],planned_orders=p['planned_orders'],config=cfg)
