"""Exact normalized/alias lookup only. No fuzzy replacement or invented registration."""
import re
import unicodedata

def normalize_ingredient(value):
    return re.sub(r"\s+","",unicodedata.normalize("NFKC",value).strip()).casefold()

class IngredientRegistry:
    def __init__(self, sources, aliases=None):
        self.entries={}
        for source,names in sources.items():
            for name in names:
                key=normalize_ingredient(name)
                entry=self.entries.setdefault(key,{"names":set(),"sources":set()})
                entry["names"].add(name)
                entry["sources"].add(source)
        self.aliases={}
        for canonical,variants in (aliases or {}).items():
            key=normalize_ingredient(canonical)
            if key not in self.entries:
                continue  # Config aliases cannot register a missing ingredient.
            for variant in variants:
                self.aliases.setdefault(normalize_ingredient(variant),set()).add(key)

    def resolve(self,value):
        key=normalize_ingredient(value)
        targets=({key} if key in self.entries else set()) | self.aliases.get(key,set())
        if len(targets)!=1:
            return None
        entry=self.entries[next(iter(targets))]
        # Conflicting official spellings require source cleanup instead of a guess.
        if len(entry["names"])!=1:
            return None
        return {"ingredient":next(iter(entry["names"])),"matched_sources":sorted(entry["sources"])}

def ingredient_intent(value):
    if isinstance(value,dict):
        return bool(value.get("ingredient"))
    from schemas.event import Event
    if isinstance(value,Event):
        return value.ingredient is not None
    return isinstance(value,str) and any(t in value for t in ("쓰지","사용하지","금지","빼","제외","다시 사용","사용 가능","까지","유통기한"))
