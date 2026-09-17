from schemas.models import Recipe

def menu_key(menu):
    return (menu.date.isoformat(),menu.meal_type,menu.menu_name)

def scheduled_recipe(menu, adapter):
    """Scheduled quantities are authoritative; catalog fills missing ingredients."""
    catalog = adapter.get_recipe(menu.menu_name)
    ingredients = list(menu.ingredients)
    present = {i.ingredient for i in ingredients}
    if catalog:
        ingredients += [i for i in catalog.ingredients if i.ingredient not in present]
    return Recipe(recipe_id=catalog.recipe_id if catalog else "schedule", menu_name=menu.menu_name, category=catalog.category if catalog else "unknown", ingredients=ingredients)
