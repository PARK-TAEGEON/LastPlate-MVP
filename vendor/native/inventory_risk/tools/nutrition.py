from .units import grams

NUTRIENTS = ("kcal", "protein", "carbohydrate", "fat", "sodium")

def calculate(recipe, adapter):
    totals = {n:0.0 for n in NUTRIENTS}
    allergens, missing = set(), []
    serving = 0
    for item in recipe.ingredients:
        amount = grams(item.amount_per_serving,item.unit)
        serving += amount
        row = adapter.get_nutrition(item.ingredient)
        if row is None or row.allergens is None:
            missing.append(item.ingredient)
            continue
        for n in NUTRIENTS:
            totals[n] += getattr(row,n) * amount/row.serving_basis
        allergens.update(row.allergens)
    return dict(totals={k:round(v,4) for k,v in totals.items()},serving_g=serving,allergens=sorted(allergens),missing=missing)

def check(original, candidate, adapter, config, prohibited_allergens):
    old, new = calculate(original,adapter), calculate(candidate,adapter)
    if old["missing"] or new["missing"]:
        return dict(status="UNKNOWN", violations=["missing_nutrition_or_allergens"],original=old,candidate=new)
    n, o = new["totals"], old["totals"]
    tests = {"minimum_protein":n["protein"]>=config.min_protein,
             "kcal_range":config.min_kcal<=n["kcal"]<=config.max_kcal,
             "sodium_limit":n["sodium"]<=config.max_sodium,
             "minimum_serving":new["serving_g"]>=config.min_serving_g,
             "fat_limit":n["fat"]<=config.max_fat,
             "protein_similarity":n["protein"]>=o["protein"]*config.min_protein_ratio,
             "kcal_similarity":abs(n["kcal"]-o["kcal"])<=o["kcal"]*config.max_kcal_change_ratio,
             "fat_similarity":n["fat"]-o["fat"]<=config.max_fat_increase,
             "allergy":not set(new["allergens"]) & set(prohibited_allergens)}
    violations = [key for key,ok in tests.items() if not ok]
    return dict(status="FAIL" if violations else "PASS",violations=violations,original=old,candidate=new,delta={k:round(n[k]-o[k],4) for k in NUTRIENTS})
