"""In-memory providers implementing the original module's public protocols."""
from copy import deepcopy
from ..errors import StageError

def analyze(value):
    from schemas.models import InventoryLot,Menu,Recipe,Nutrition,PriceTrend,MonthlyPrice
    from schemas.event import Event
    from adapters.bundle import AdapterBundle
    from agents.inventory_risk import analyze_inventory_and_risk
    from tools.units import grams
    p=value['payload']; count=value['recommended_servings']
    class Provider:
        def __init__(self,kind,rows,model):
            self.source=p['sources'][kind]
            self.rows=[model.model_validate(r) for r in rows]
        def get_recipe(self,name):
            return next((r.model_copy(deep=True) for r in self.rows if r.menu_name==name),None)
        def list_recipes(self): return deepcopy(self.rows)
        def get_nutrition(self,name):
            return next((r.model_copy(deep=True) for r in self.rows if r.ingredient==name),None)
        def get_price_trend(self,name,as_of):
            rows=[r for r in self.rows if r.ingredient==name and r.date<=as_of]
            return max(rows,key=lambda r:r.date) if rows else None
        def get_monthly_history(self,name,as_of):
            return [r for r in self.rows if r.ingredient==name and r.year_month<as_of.strftime('%Y-%m')]
        def get_events(self,as_of,horizon_end):
            return [r for r in self.rows if r.date is None or r.date<=horizon_end and (r.end_date or r.date)>=as_of]
    class Stock(Provider):
        def get_inventory(self): return deepcopy(self.rows)
        def get_weekly_menu(self): return deepcopy(self.menus)
        def get_requirement_totals(self):
            requirements=value.get('ingredient_requirements')
            return None if requirements is None else {x['ingredient']:grams(x['cooking_required'],x['unit']) for x in requirements}
    stock=Stock('inventory',p['inventory'],InventoryLot)
    stock.menu_source=p['sources']['weekly_menu']
    recipes={r['menu_name']:r for r in p['recipes']}
    if len(recipes)!=len(p['recipes']): raise ValueError('Duplicate recipe menu identity')
    stock.menus=[Menu.model_validate(dict(date=m['date'],meal_type=m['meal_type'],menu_name=m['menu_name'],
        expected_max_diners=count,ingredients=recipes[m['menu_name']]['ingredients']))
        for m in p['weekly_menu'] if (m['date'],m['meal_type'])==(p['target_date'],p['meal_type'])]
    bundle=AdapterBundle(Provider('recipe',p['recipes'],Recipe),Provider('nutrition',p['nutrition'],Nutrition),
        Provider('price_trend',p['prices'],PriceTrend),Provider('monthly_price',p['monthly_prices'],MonthlyPrice),
        stock,Provider('supply_risk',p['supply_events'],Event))
    # Canonical g mapping uses the native mass converter; quantities and prices retain their bases.
    for lot in stock.rows:
        old_unit=lot.unit
        for field in ('current_stock','minimum_stock','planned_order'): setattr(lot,field,grams(getattr(lot,field),old_unit))
        lot.unit_price=lot.unit_price/grams(1,old_unit)
        lot.unit='g'
    for r in stock.rows: r.planned_order=0
    for order in p['planned_orders']:
        matches=[r for r in stock.rows if r.ingredient==order['ingredient']]
        if not matches: raise StageError('inventory_risk','INVENTORY_DATA_MISSING','Inventory planned order requires an existing lot for the ingredient',422)
        matches[0].planned_order+=grams(order['planned_order'],order['unit'])
    raw=analyze_inventory_and_risk(dict(as_of=p['as_of'],horizon_start=p['target_date'],horizon_end=p['target_date'],
        mode='full',input_snapshot_id=p['input_revision'],forecast_version=value['operation_revision'],
        prohibited_allergens=p['operation_policy'].get('constraints',{}).get('allergy_restriction') or [],adapters=bundle),p.get('event'))
    raw['data_sources'].update({k:v for k,v in p['sources'].items() if k!='constraints'})
    raw['data_sources']['risk_constraints']='DEMO:original RiskConfig dish-level thresholds'
    raw['data_sources']['operation_constraints']=p['sources']['constraints']
    raw['risk_events']=deepcopy(raw.get('detected_events',[]))
    raw['audit']={'supply_events':deepcopy(p['supply_events']),'event':deepcopy(p.get('event'))}
    raw['quantity_basis']={'current_plan':'operation_cooking_raw_g' if value.get('ingredient_requirements') is not None else 'native_edible_g',
        'operation_revision':value['operation_revision'],'requirements':deepcopy(value.get('ingredient_requirements')),
        'nutrition':'original edible recipe; dish-level candidate checks',
        'candidate_stock':'native independent edible-basis estimate; Operation raw/cooking recheck required before selection'}
    if any(x['cooking_required']!=x['edible_required'] for x in value.get('ingredient_requirements') or []):
        for candidate in raw.get('substitute_candidates',[]):
            candidate['eligible_for_review']=False
            candidate['operation_quantity_recheck_required']=True
            candidate['quantity_basis']='native edible estimate; raw/cooking requirement not recalculated'
    raw['requires_confirmation']=raw['status']!='ok'
    return raw
