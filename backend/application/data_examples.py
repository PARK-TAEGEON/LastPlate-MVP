"""Explicit demo providers in native input units; never impersonate live API data.

Future authenticated providers can return the same patches after validating source
units and identifiers. No credentials or outbound requests are used by these demos.
"""
from copy import deepcopy
from datetime import date, timedelta

PROVIDERS = {
    'recipe': ('레시피·재료', '식약처 COOKRCP01 / 농식품 레시피 재료정보'),
    'nutrition': ('영양성분', '통합 식품영양성분 DB'),
    'price': ('일별 가격·가격 추이', 'KAMIS'),
    'supply': ('공급 위험', '공급위험 공적정보'),
}


def examples(base, day):
    menus = list(day['menus'].values())[1:3]
    recipes = [deepcopy(r) for name in menus for r in base['recipes'] if r['menu_name'] == name]
    ingredients = list(dict.fromkeys(i['ingredient'] for r in recipes for i in r['ingredients']))[:2]
    result = []
    for kind, (title, provider) in PROVIDERS.items():
        rows = []
        if kind == 'recipe':
            for r in recipes:
                for i in r['ingredients']:
                    i['amount_per_serving'] = round(i['amount_per_serving'] * .95, 4)
                rows.append({'label': r['menu_name'], 'description': '1인분 · ' + ' / '.join(
                    f"{i['ingredient']} {i['amount_per_serving']:g}{i['unit']}" for i in r['ingredients']),
                    'value': r})
        elif kind == 'nutrition':
            for name in ingredients:
                value = next((deepcopy(r) for r in base['nutrition'] if r['ingredient'] == name), None)
                if value:
                    rows.append({'label': name, 'description': f"{value['serving_basis']}g 기준 · {value['kcal']}kcal · 단백질 {value['protein']}g · 나트륨 {value['sodium']}mg", 'value': value})
        elif kind == 'price':
            for index, name in enumerate(ingredients):
                prior = next((r for r in base['prices'] if r['ingredient'] == name), None)
                if prior:
                    reference = prior['current_price']
                    value = dict(date=str(date.fromisoformat(day['date'])-timedelta(days=1)), ingredient=name,
                                 current_price=round(reference * (1.32 if index == 0 else 1.24), 2),
                                 unit=prior['unit'], **{f'price_{w}w_ago':reference for w in range(1,5)})
                    rows.append({'label': name, 'description': f"{reference:g} → {value['current_price']:g}원/{value['unit']} · 1~4주 비교", 'value': value})
        else:
            for name in ingredients:
                rows.append({'label': name, 'description': day['date']+' · 입고 지연 가능성 (중간 위험 시연)',
                    'value': dict(event_type='supply_risk', ingredient=name, date=day['date'], end_date=day['date'],
                                  severity='MEDIUM', description='DEMO: 입고 지연 가능성', source_type='DEMO')})
        result.append(dict(id=kind, title=title, provider=provider, mode='demo', rows=rows[:2]))
    return result


def apply_examples(payload, bundles):
    for bundle in bundles:
        kind=bundle['id']; values=[deepcopy(r['value']) for r in bundle['rows']]
        field, key, source = {'recipe':('recipes','menu_name','recipe'),
            'nutrition':('nutrition','ingredient','nutrition'), 'price':('prices','ingredient','price_trend'),
            'supply':('supply_events',None,'supply_risk')}[kind]
        if key:
            identities={v[key] for v in values}
            payload[field]=[r for r in payload[field] if r[key] not in identities]+values
        else:payload[field]=payload[field]+values
        payload['sources'][source]='DEMO: '+bundle['provider']+' integration example; not a live API response'
    if any(b['id'] in ('recipe','nutrition') for b in bundles):
        names={m['menu_name'] for m in payload['weekly_menu'] if m['date']==payload['target_date']}
        nutrients={r['ingredient']:r for r in payload['nutrition']}
        totals={'protein':0.,'calories':0.,'sodium':0.};allergens=set();complete=True
        for recipe in payload['recipes']:
            if recipe['menu_name'] not in names:continue
            for item in recipe['ingredients']:
                n=nutrients.get(item['ingredient'])
                if not n or not n.get('serving_basis') or item['unit'] not in ('g','kg'):
                    complete=False;continue
                factor=item['amount_per_serving']*(1000 if item['unit']=='kg' else 1)/n['serving_basis']
                for target,source in [('protein','protein'),('calories','kcal'),('sodium','sodium')]:
                    if n.get(source) is None:complete=False
                    else:totals[target]+=n[source]*factor
                if n.get('allergens') is None:complete=False
                else:allergens.update(n['allergens'])
        payload['operation_policy']['nutrition_per_serving']=({**{k:round(v,4) for k,v in totals.items()},'allergens':sorted(allergens)} if complete else {})
    return payload
