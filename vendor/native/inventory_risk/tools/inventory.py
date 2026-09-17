from collections import defaultdict
from .units import grams
from .usable_stock import usable_stock
from .events import applies
from .recipe import menu_key
from .alerts import make_alert
from .identity import stable_id, deduplicate
from schemas.event import Event

def allocate(inventory, menus, recipes, restrictions=(), with_audit=False, required_totals=None):
    """FEFO across chronological meals; expired lots never satisfy later demand."""
    remaining = [grams(x.current_stock, x.unit) for x in inventory]
    needed, missing = defaultdict(float), defaultdict(float)
    audit=[]
    weights={}; distributed=defaultdict(float); occurrences=defaultdict(int)
    if required_totals is not None:
        from schemas.errors import input_error
        from math import isfinite
        if len({(m.date,m.meal_type) for m in menus})!=1:
            raise input_error('Operation totals require one service scope','required_totals')
        # Reuse the existing native quantity calculation, without duplicating trim loss/rounding.
        weights,_,_,original=allocate(inventory,menus,recipes,restrictions,with_audit=True)
        if set(required_totals)!=set(weights) or any(not isfinite(v) or v<0 for v in required_totals.values()):
            raise input_error('Operation requirement coverage/values mismatch','required_totals')
        for row in original: occurrences[row['ingredient']]+=1
    for menu in sorted(menus, key=lambda m:(m.date, m.meal_type, m.menu_name)):
        for item in recipes[menu_key(menu)].ingredients:
            amount = grams(item.amount_per_serving, item.unit) * menu.expected_max_diners
            edible=amount
            if required_totals is not None:
                occurrences[item.ingredient]-=1
                # Transport an aggregate Operation total across menus by original edible contribution.
                # The last share keeps the aggregate exact; no procurement formula is reimplemented.
                amount=(required_totals[item.ingredient]-distributed[item.ingredient] if occurrences[item.ingredient]==0 else
                        required_totals[item.ingredient]*amount/weights[item.ingredient] if weights[item.ingredient] else 0)
                distributed[item.ingredient]+=amount
            needed[item.ingredient] += amount
            required=amount
            lots_used=[]
            restricted = any(e.ingredient == item.ingredient and applies(e, menu.date) for e in restrictions)
            for index in sorted(range(len(inventory)), key=lambda i:inventory[i].expiry_date):
                lot = inventory[index]
                if restricted or lot.ingredient != item.ingredient:
                    continue
                take = min(amount, usable_stock(remaining[index], lot.expiry_date, menu.date))
                remaining[index] -= take
                amount -= take
                if take:
                    lots_used.append({"lot_index":index,"quantity_g":take})
            missing[item.ingredient] += amount
            audit.append(dict(date=menu.date.isoformat(),meal_type=menu.meal_type,menu_name=menu.menu_name,ingredient=item.ingredient,required_g=required,shortage_g=amount,allocations=lots_used,restricted=restricted))
            if required_totals is not None: audit[-1].update(edible_required_g=edible,quantity_basis='operation_cooking_raw_g')
    result=(dict(needed), dict(missing), remaining)
    return (*result,audit) if with_audit else result

def analyze(inventory, menus, recipes, as_of, config, restrictions, required_totals=None):
    needed, missing, _ = allocate(inventory, menus, recipes, restrictions,required_totals=required_totals)
    names = sorted(set(needed) | {x.ingredient for x in inventory})
    statuses, alerts = [], []
    def alert(kind, ingredient, evidence, severity=None, action=None):
        alerts.append(make_alert(config,kind,f"{ingredient}: {kind}",evidence,severity=severity,ingredient=ingredient,candidate_action=action))
    for name in names:
        lots = [x for x in inventory if x.ingredient == name]
        current = sum(grams(x.current_stock,x.unit) for x in lots)
        valid = sum(usable_stock(grams(x.current_stock,x.unit),x.expiry_date,as_of) for x in lots)
        order = sum(grams(x.planned_order,x.unit) for x in lots)
        minimum = sum(grams(x.minimum_stock,x.unit) for x in lots)
        demand = needed.get(name,0)
        deficit = missing.get(name,0)
        statuses.append(dict(ingredient=name, current_stock_g=current, usable_today_g=valid, required_g=demand, shortage_at_service_g=deficit, planned_order_g=order, uncovered_order_g=max(0,deficit-order), order_arrival_verified=False))
        if valid < minimum:
            alert("low_stock",name,[f"usable {valid}g < minimum {minimum}g"])
        if deficit:
            alert("ingredient_shortage",name,[f"service-date shortage {deficit}g"])
        if deficit > order:
            alert("insufficient_order",name,[f"shortage {deficit}g; planned order {order}g"])
        if valid > max(demand, minimum) * config.excess_factor and valid:
            alert("excess_inventory",name,[f"usable {valid}g; demand {demand}g"])
        if order > deficit + minimum and order:
            alert("excess_order",name,[f"usable {valid}g; demand {demand}g; planned {order}g"],action="예정 발주량 재검토 후보")
        for lot in lots:
            days = (lot.expiry_date-as_of).days
            if lot.current_stock > 0 and days <= config.expiry_days:
                usable_menus = [m.menu_name for m in menus if as_of <= m.date <= lot.expiry_date and any(i.ingredient == name for i in recipes[menu_key(m)].ingredients) and not any(e.ingredient == name and applies(e,m.date) for e in restrictions)]
                alert("expired_inventory" if days < 0 else "expiry_risk",name,[f"현재 재고 {lot.current_stock}{lot.unit}",f"유통기한 D-{days}",f"기한 내 메뉴: {', '.join(usable_menus) or '없음'}"],config.severity("urgent_expiry" if days<=config.expiry_high_days else "expiry_risk"),"기존 재고 우선 사용 검토" if usable_menus else "사용 가능 여부 검토")
            if lot.last_used_date and (as_of-lot.last_used_date).days >= config.unused_days and lot.current_stock:
                alert("long_unused_inventory",name,[f"last used {lot.last_used_date}"])
    return statuses, alerts

def analyze_details(inventory,menus,recipes,as_of,config,restrictions,required_totals=None):
    statuses,alerts=analyze(inventory,menus,recipes,as_of,config,restrictions,required_totals)
    _,_,_,audit=allocate(inventory,menus,recipes,restrictions,with_audit=True,required_totals=required_totals)
    impacts,events,priority=[],[],[]
    for record in audit:
        base={k:record[k] for k in ("date","meal_type","menu_name")}
        base.update(ingredient=record["ingredient"],affected_ingredient=record["ingredient"])
        if record["shortage_g"]:
            event=deduplicate([Event(event_type="inventory_shortage_event",ingredient=record["ingredient"],date=record["date"],severity=config.severity("ingredient_shortage"),source_type="inventory_analysis",description=f"{record['meal_type']} {record['menu_name']}: shortage {record['shortage_g']}g")])[0]
            events.append(event)
            impacts.append(dict(**base,cause="inventory_shortage_event",cause_event_id=event.event_id,shortage_g=record["shortage_g"]))
        for index,lot in enumerate(inventory):
            if lot.ingredient!=record["ingredient"] or not lot.current_stock or (lot.expiry_date-as_of).days>config.expiry_days:
                continue
            lot_id=stable_id("lot",[index,lot.model_dump(mode="json")])
            event=deduplicate([Event(event_type="inventory_expiry_event",ingredient=lot.ingredient,date=as_of,end_date=lot.expiry_date if lot.expiry_date>=as_of else as_of,severity=config.severity("expiry_risk"),source_type="inventory_analysis",description=f"{lot_id} expiry={lot.expiry_date}")])[0]
            events.append(event)
            impacts.append(dict(**base,cause="inventory_expiry_event",cause_event_id=event.event_id,lot_id=lot_id,expiry_date=lot.expiry_date.isoformat(),expired_before_service=lot.expiry_date.isoformat()<record["date"]))
            quantity=sum(x["quantity_g"] for x in record["allocations"] if x["lot_index"]==index)
            if quantity:
                priority.append(dict(candidate_id=stable_id("priority",[base,lot_id]),kind="priority_inventory_use",**base,lot_id=lot_id,expiry_date=lot.expiry_date.isoformat(),quantity_g=quantity,cause_event_ids=[event.event_id],requires_approval=True,reason="기존 식단의 FEFO 배분량 내 임박 재고 우선 사용 검토; 자동 적용 없음"))
    for alert in alerts:
        alert["cause_event_ids"]=sorted({i["cause_event_id"] for i in impacts if i["ingredient"]==alert["ingredient"] and (i["cause"]=="inventory_shortage_event" if alert["type"] in {"ingredient_shortage","insufficient_order"} else i["cause"]=="inventory_expiry_event" if alert["type"] in {"expiry_risk","expired_inventory"} else False)})
    return statuses,alerts,impacts,deduplicate(events),priority
