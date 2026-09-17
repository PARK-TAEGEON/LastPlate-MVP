from dataclasses import dataclass, field

DEFAULT_SEVERITY = {
    "expiry_risk":"MEDIUM", "expired_inventory":"HIGH", "urgent_expiry":"HIGH",
    "low_stock":"MEDIUM", "ingredient_shortage":"HIGH", "insufficient_order":"HIGH",
    "overstock":"MEDIUM", "over_order":"MEDIUM", "long_unused_inventory":"MEDIUM",
    "price_risk":"MEDIUM", "price_high":"HIGH", "price_low":"LOW",
    "supply_risk":"MEDIUM", "menu_conflict":"HIGH", "nutrition_violation":"HIGH",
    "nutrition_data_unavailable":"HIGH", "price_data_unavailable":"MEDIUM",
    "clarification_required":"MEDIUM", "input_error":"HIGH",
    "duplicate_menu_rows":"HIGH", "unregistered_ingredient":"MEDIUM",
}

@dataclass(frozen=True)
class RiskConfig:
    """DEMO thresholds, not legal/institutional nutrition standards."""
    price_alert_medium: float = 10
    price_alert_high: float = 20
    monthly_alert_pct: float = 20
    expiry_days: int = 3
    unused_days: int = 30
    excess_factor: float = 1.5
    min_protein: float = 6
    min_kcal: float = 50
    max_kcal: float = 400
    max_sodium: float = 600
    min_serving_g: float = 70
    max_fat: float = 25
    min_protein_ratio: float = 0.65
    max_kcal_change_ratio: float = 0.6
    max_fat_increase: float = 10
    price_max_age_days: int = 7
    expiry_high_days: int = 1
    severity_policy: dict[str, str] = field(default_factory=lambda:dict(DEFAULT_SEVERITY))
    ingredient_aliases: dict[str, list[str]] = field(default_factory=lambda:{"계란":["달걀","계 란"],"닭고기":["닭 고기"],"두부":["두 부"]})

    def severity(self, kind):
        from schemas.alert import ALERT_ALIASES
        return self.severity_policy[ALERT_ALIASES.get(kind,kind)]

    def price_severity(self, magnitude, triggered):
        return self.severity("price_high" if magnitude >= self.price_alert_high else "price_risk" if triggered else "price_low")

    def __post_init__(self):
        from math import isfinite
        if any(not isfinite(v) or v < 0 for k,v in vars(self).items() if k not in {"severity_policy","ingredient_aliases"}):
            raise ValueError("Thresholds must be finite and nonnegative")
        if self.price_alert_high < self.price_alert_medium or self.max_kcal < self.min_kcal or self.excess_factor < 1:
            raise ValueError("Inconsistent threshold ranges")
        if set(self.severity_policy) != set(DEFAULT_SEVERITY) or any(v not in {"LOW","MEDIUM","HIGH"} for v in self.severity_policy.values()):
            raise ValueError("Incomplete or invalid severity policy")
        if any(not isinstance(k,str) or not k.strip() or not isinstance(v,list) or any(not isinstance(a,str) or not a.strip() for a in v) for k,v in self.ingredient_aliases.items()):
            raise ValueError("Invalid ingredient alias mapping")
