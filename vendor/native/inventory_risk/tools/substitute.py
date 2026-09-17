from .units import grams, price_per_kg
from .inventory import allocate
from .events import applies

def candidates(original, ingredient, recipes, blocked):
    """Curated recipe category is the menu-characteristic constraint."""
    return [r for r in recipes if r.menu_name != original.menu_name and original.category != "unknown" and r.category == original.category and not any(i.ingredient in blocked | {ingredient} for i in r.ingredients)]

def inventory_feasibility(candidate, target, menus, scheduled, inventory, restrictions):
    # Reserve stock for every other scheduled meal, then test this independent option.
    others = [m for m in menus if m != target]
    _,_,remaining = allocate(inventory,others,scheduled,restrictions)
    demand = {}
    for i in candidate.ingredients:
        demand[i.ingredient] = demand.get(i.ingredient,0)+grams(i.amount_per_serving,i.unit)*target.expected_max_diners
    shortages = {}
    for name, amount in demand.items():
        valid = sum(remaining[j] for j,lot in enumerate(inventory) if lot.ingredient==name and lot.expiry_date>=target.date)
        if any(e.ingredient==name and applies(e,target.date) for e in restrictions):
            valid=0
        if valid<amount:
            shortages[name]=round(amount-valid,4)
    return dict(inventory_available=not shortages,shortages_g=shortages,allocation_scope="independent option after reserving all other scheduled menus")

def cost(recipe, adapter, as_of, max_age):
    total = 0
    for i in recipe.ingredients:
        p=adapter.get_price_trend(i.ingredient,as_of)
        if p is None or (as_of-p.date).days>max_age:
            return None
        total += grams(i.amount_per_serving,i.unit)/1000 * price_per_kg(p.current_price,p.unit)
    return round(total,4)
