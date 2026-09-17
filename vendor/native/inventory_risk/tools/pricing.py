from statistics import mean
from .units import price_per_kg

def analyze_price(trend, history, config):
    reference = mean([trend.price_1w_ago,trend.price_2w_ago,trend.price_3w_ago,trend.price_4w_ago])
    change = (trend.current_price-reference)/reference*100
    direction=lambda pct: "increase" if pct>0 else "decrease" if pct<0 else "stable"
    result = dict(ingredient=trend.ingredient, current_price=trend.current_price, reference_price=reference, unit=trend.unit, price_change_pct=round(change,4), weekly_direction=direction(change), direction=direction(change))
    monthly = [price_per_kg(x.average_price,x.unit) for x in history]
    result.update(long_term_change_pct=None, outside_monthly_range=None, seasonal_assessment="insufficient_history")
    if monthly:
        current = price_per_kg(trend.current_price,trend.unit)
        result.update(long_term_change_pct=round((current/mean(monthly)-1)*100,4), outside_monthly_range=not min(monthly)<=current<=max(monthly))
        same_month = [price_per_kg(x.average_price,x.unit) for x in history if int(x.year_month[-2:])==trend.date.month]
        if len(same_month)>=2:
            result["seasonal_assessment"] = "within_historical_same_month_range" if min(same_month)<=current<=max(same_month) else "outside_historical_same_month_range"
    monthly_change=result["long_term_change_pct"]
    result["monthly_direction"]=direction(monthly_change) if monthly_change is not None else None
    rules=[]
    if abs(change)>=config.price_alert_medium:
        rules.append("weekly_"+direction(change))
    if monthly_change is not None and abs(monthly_change)>=config.monthly_alert_pct:
        rules.append("monthly_"+direction(monthly_change))
    result["triggered_rules"]=rules
    result["is_alert"]=bool(rules)
    result["requires_impact_analysis"]=any(r.endswith("_increase") for r in rules)
    result["severity"]=config.price_severity(max(abs(change),abs(monthly_change or 0)),bool(rules))
    return result
