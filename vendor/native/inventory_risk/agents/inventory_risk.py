"""Advisory analysis stages: no menu/order mutation or forecast execution."""
from datetime import date
from schemas.event import Event
from schemas.request import AnalysisRequest
from schemas.risk_report import RiskReport
from schemas.errors import input_error
from tools.events import parse_event_result, events_from_result, applies
from tools.ingredients import IngredientRegistry, ingredient_intent
from tools.identity import stable_id, deduplicate
from tools.alerts import make_alert
from tools.recipe import scheduled_recipe, menu_key
from tools.inventory import analyze_details, allocate
from tools.active_evidence import active_events, project_active
from tools.pricing import analyze_price
from tools.nutrition import check
from tools.substitute import candidates, inventory_feasibility, cost

STAGES = [
    "event_parser", "inventory_analyzer", "price_risk_analyzer",
    "supply_risk_analyzer", "impact_analyzer", "substitute_candidate_generator",
    "nutrition_constraint_checker", "risk_report_builder",
]

class InventoryRiskAgent:
    def __init__(self, adapters, config):
        self.a, self.c = adapters, config

    def event_parser(self, state):
        request = AnalysisRequest.model_validate(state["request"])
        value = state.get("user_event")
        if request.mode == "event" and value is None:
            raise input_error("event mode requires user_event", "user_event")
        # Pure attendance retains the no-inventory-read path; compounds do not.
        sources={}
        if ingredient_intent(value):
            sources={"inventory":{x.ingredient for x in self.a.inventory.get_inventory()},
                     "recipe":{i.ingredient for r in self.a.recipe.list_recipes() for i in r.ingredients},
                     "weekly_menu":{i.ingredient for m in self.a.inventory.get_weekly_menu() for i in m.ingredients}}
        parsed=parse_event_result(value,request.as_of,IngredientRegistry(sources,self.c.ingredient_aliases))
        events=events_from_result(parsed)
        warnings=parsed.validation_warnings+getattr(self.a.inventory,"get_validation_warnings",lambda:[])()
        warnings=[{**w,"severity":self.c.severity(w["type"])} for w in warnings]
        plan = STAGES[1:-1]
        if request.mode == "event":
            if any(e.needs_clarification for e in events) or all(e.event_type=="attendance_event" for e in events):
                plan = []
            elif any(e.event_type=="price_event" for e in events):
                plan = STAGES[1:-1]
            else:
                plan = [n for n in STAGES[1:-1] if n != "price_risk_analyzer"]
        alerts = [make_alert(self.c,"clarification_required","입력 확인이 필요합니다",[e.description or "Missing event date or attendance number"],cause_event_ids=[e.event_id]) for e in events if e.needs_clarification]
        return dict(
            request=request.model_dump(mode="json"), as_of=request.as_of,
            horizon_start=request.horizon_start,horizon_end=request.horizon_end,
            menus=[], inventory=[], recipes={}, events=events, alerts=alerts, plan=plan,
            trace=[f"Event Parser: mode={request.mode}, status={parsed.status}, {len(events)} events; selected={plan}"]+parsed.decision_trace,
            inventory_status=[], inventory_impacts=[], priority_use_candidates=[],
            price_risks=[], supply_risks=[], affected=[], candidate_work=[], candidates=[],
            nutrition_results=[],cost_impacts=[],errors=parsed.errors,
            parsing_result=parsed.model_dump(mode="json"),validation_warnings=warnings,
        )

    def inventory_analyzer(self,s):
        inventory=self.a.inventory.get_inventory()
        menus=[m for m in self.a.inventory.get_weekly_menu() if s["horizon_start"]<=m.date<=s["horizon_end"]]
        recipes={menu_key(m):scheduled_recipe(m,self.a.recipe) for m in menus}
        for event in s["events"]:
            if event.event_type=="expiry_event" and not event.needs_clarification and not event.superseded:
                inventory=[lot.model_copy(update={"expiry_date":min(lot.expiry_date,event.date)}) if lot.ingredient==event.ingredient else lot for lot in inventory]
        restrictions=[e for e in s["events"] if e.event_type=="ingredient_restriction_event"]
        totals=getattr(self.a.inventory,'get_requirement_totals',lambda:None)()
        status,alerts,impacts,events,priority=analyze_details(inventory,menus,recipes,s["as_of"],self.c,restrictions,totals)
        _,_,_,allocation_audit=allocate(inventory,menus,recipes,restrictions,with_audit=True,required_totals=totals)
        warnings=[{**w,"severity":self.c.severity(w["type"])} for w in getattr(self.a.inventory,"get_validation_warnings",lambda:[])()]
        alerts += [make_alert(self.c,w["type"],w["message"],[f"duplicate_count={w['duplicate_count']}",f"keys={w['keys']}",f"rows={w['rows']}"],**{k:v for k,v in w.items() if k not in {"type","message"}}) for w in warnings]
        return dict(inventory=inventory,menus=menus,recipes=recipes,inventory_status=status,allocation_audit=allocation_audit,
                    alerts=s["alerts"]+alerts,inventory_impacts=impacts,
                    events=deduplicate(s["events"]+events),priority_use_candidates=priority,
                    validation_warnings=s.get("validation_warnings",[])+[w for w in warnings if w not in s.get("validation_warnings",[])],
                    trace=s["trace"]+[f"Inventory Analyzer: {len(status)} ingredients; {len(impacts)} impacts; {len(priority)} priority-use candidates"]+
                    [f"Inventory: {r['ingredient']} current={r['current_stock_g']}g, required={r['required_g']}g, service shortage={r['shortage_at_service_g']}g, planned={r['planned_order_g']}g" for r in status])

    def price_risk_analyzer(self,s):
        risks,events,alerts=[],list(s["events"]),list(s["alerts"])
        for name in sorted({x["ingredient"] for x in s["inventory_status"]}):
            trend=self.a.price_trend.get_price_trend(name,s["as_of"])
            if trend is None or (s["as_of"]-trend.date).days>self.c.price_max_age_days:
                alerts.append(make_alert(self.c,"price_data_unavailable",f"{name} 가격 확인 필요",["Missing or stale price; no price inference"],ingredient=name))
                continue
            r=analyze_price(trend,self.a.monthly_price.get_monthly_history(name,s["as_of"]),self.c)
            if not r["is_alert"]:
                continue
            risks.append(r)
            cause_ids=[]
            if r["requires_impact_analysis"]:
                event=deduplicate([Event(event_type="price_event",ingredient=name,date=s["as_of"],end_date=s["horizon_end"],severity=r["severity"],source_type=self.a.price_trend.source+";"+self.a.monthly_price.source,description=f"weekly={r['price_change_pct']}%, monthly={r['long_term_change_pct']}%; rules={r['triggered_rules']}")])[0]
                events.append(event)
                cause_ids=[event.event_id]
            alerts.append(make_alert(self.c,"price_risk",f"{name} 가격 이상",[
                f"weekly {r['price_change_pct']}% ({r['weekly_direction']})",
                f"monthly {r['long_term_change_pct']}% ({r['monthly_direction']})",
                f"triggered_rules={r['triggered_rules']}"],severity=r["severity"],ingredient=name,
                cause_event_ids=cause_ids,price_analysis=r))
        return dict(price_risks=risks,events=deduplicate(events),alerts=alerts,
                    trace=s["trace"]+[f"Price Risk Analyzer: {r['ingredient']} weekly={r['price_change_pct']}%, monthly={r['long_term_change_pct']}%, rules={r['triggered_rules']}" for r in risks])

    def supply_risk_analyzer(self,s):
        incoming=self.a.supply_risk.get_events(s["as_of"],s["horizon_end"])
        events=deduplicate(s["events"]+incoming)
        supply=[e for e in active_events(events) if e.event_type=="supply_risk" and not e.needs_clarification and e.date and e.date<=s["horizon_end"] and (e.end_date or e.date)>=s["horizon_start"]]
        risks=[]
        for e in supply:
            status=next((x for x in s["inventory_status"] if x["ingredient"]==e.ingredient),{})
            risks.append({**e.model_dump(mode="json"),"inventory_context":status})
        alerts=[make_alert(self.c,"supply_risk",f"{r['ingredient']} 공급 위험",[
            r["description"] or "Supply risk event",f"period={r['date']}..{r['end_date'] or r['date']}",
            f"inventory={r['inventory_context']}"],severity=r["severity"],ingredient=r["ingredient"],cause_event_ids=[r["event_id"]]) for r in risks]
        return dict(events=events,supply_risks=risks,alerts=s["alerts"]+alerts,
                    trace=s["trace"]+[f"Supply Risk Analyzer: {len(incoming)} observations, {len(supply)} unique active events"])

    def impact_analyzer(self,s):
        affected=list(s["inventory_impacts"])
        for event in s["events"]:
            if event.event_type not in {"price_event","supply_risk","ingredient_restriction_event","expiry_event"} or event.needs_clarification or event.superseded:
                continue
            for menu in s["menus"]:
                match=applies(event,menu.date) if event.event_type!="expiry_event" else True
                if match and any(i.ingredient==event.ingredient for i in s["recipes"][menu_key(menu)].ingredients):
                    affected.append(dict(affected_ingredient=event.ingredient,ingredient=event.ingredient,
                        menu_name=menu.menu_name,date=menu.date.isoformat(),meal_type=menu.meal_type,
                        cause=event.event_type,cause_event_id=event.event_id))
        affected=list({stable_id("impact",r):r for r in affected}.values())
        alerts=s["alerts"]+[make_alert(self.c,"menu_conflict",f"{r['menu_name']} 사용 제한 충돌",
            [f"{r['date']} {r['meal_type']}: {r['affected_ingredient']}"],ingredient=r["affected_ingredient"],cause_event_ids=[r["cause_event_id"]]) for r in affected if r["cause"]=="ingredient_restriction_event"]
        return dict(affected=affected,alerts=alerts,trace=s["trace"]+[
            f"Impact Analyzer: {r['cause_event_id']} -> {r['date']} {r['menu_name']}/{r['affected_ingredient']} ({r['cause']})" for r in affected])

    def substitute_candidate_generator(self,s):
        work={}
        for impact in s["affected"]:
            if impact["cause"] in {"expiry_event","inventory_expiry_event"}:
                continue
            menu=next(m for m in s["menus"] if menu_key(m)==(impact["date"],impact["meal_type"],impact["menu_name"]))
            blocked={e.ingredient for e in s["events"] if applies(e,menu.date) and (
                e.event_type=="ingredient_restriction_event" or e.event_type=="supply_risk" and e.severity=="HIGH")}
            original=s["recipes"][menu_key(menu)]
            for candidate in candidates(original,impact["affected_ingredient"],self.a.recipe.list_recipes(),blocked):
                key=(*menu_key(menu),candidate.menu_name)
                option=work.setdefault(key,dict(menu=menu,original=original,candidate=candidate,
                    candidate_id=stable_id("candidate",key),cause_event_ids=[]))
                if impact["cause_event_id"] not in option["cause_event_ids"]:
                    option["cause_event_ids"].append(impact["cause_event_id"])
        return dict(candidate_work=list(work.values()),trace=s["trace"]+[
            f"Substitute Candidate Generator: {len(work)} independent alternatives; cause IDs retained"])

    def nutrition_constraint_checker(self,s):
        results,options,costs,alerts=[],[],[],list(s["alerts"])
        restrictions=[e for e in s["events"] if e.event_type=="ingredient_restriction_event"]
        for w in s["candidate_work"]:
            cid=w["candidate_id"]
            menu,original,candidate=w["menu"],w["original"],w["candidate"]
            causes=sorted(w["cause_event_ids"])
            result=check(original,candidate,self.a.nutrition,self.c,s["request"].get("prohibited_allergens",[]))
            results.append(dict(candidate_id=cid,cause_event_ids=causes,**result))
            feasible=inventory_feasibility(candidate,menu,s["menus"],s["recipes"],s["inventory"],restrictions)
            old=cost(original,self.a.price_trend,s["as_of"],self.c.price_max_age_days)
            new=cost(candidate,self.a.price_trend,s["as_of"],self.c.price_max_age_days)
            delta=round(new-old,4) if old is not None and new is not None else None
            effect="unknown" if delta is None else "lower" if delta<0 else "higher" if delta>0 else "same"
            costs.append(dict(candidate_id=cid,cause_event_ids=causes,currency="KRW",
                original_per_serving=old,candidate_per_serving=new,delta_per_serving=delta,
                delta_total=round(delta*menu.expected_max_diners,4) if delta is not None else None,
                basis="current price estimate; excludes labor, waste and delivery; not an order"))
            names={i.ingredient for i in candidate.ingredients}
            options.append(dict(candidate_id=cid,cause_event_ids=causes,kind="menu_substitution",
                original_menu=original.menu_name,candidate_menu=candidate.menu_name,date=menu.date.isoformat(),
                meal_type=menu.meal_type,nutrition_check=result["status"],**feasible,price_effect=effect,
                supply_risks=[e.model_dump(mode="json") for e in s["events"] if e.event_type=="supply_risk" and e.ingredient in names and applies(e,menu.date)],
                price_risks=[r for r in s["price_risks"] if r["ingredient"] in names],
                eligible_for_review=result["status"]=="PASS" and feasible["inventory_available"],
                reason="동일 메뉴 분류의 독립 후보; 영양·알레르기·재고 검증 결과 확인",requires_approval=True))
            if result["status"]!="PASS":
                alerts.append(make_alert(self.c,"nutrition_violation" if result["status"]=="FAIL" else "nutrition_data_unavailable",
                    f"{candidate.menu_name} 영양 검증 {result['status']}",result["violations"],candidate_id=cid,cause_event_ids=causes))
        return dict(candidates=options,nutrition_results=results,cost_impacts=costs,alerts=alerts,
                    trace=s["trace"]+[f"Nutrition Constraint Checker: {r['candidate_id']} {r['status']} {r['violations']}" for r in results]+
                    [f"Candidate cost: {c['candidate_id']} delta={c['delta_per_serving']} KRW/serving" for c in costs])

    def risk_report_builder(self,s):
        request=s.get("request",{})
        errors=s.get("errors",[])
        if errors:
            from schemas.errors import ErrorDetail
            report=error_report(ErrorDetail.model_validate(errors[0]),request,self.a.sources())
            executed=s.get("executed_nodes",[])+["risk_report_builder"]
            report["execution"].update(executed_nodes=executed,skipped_nodes=[n for n in STAGES if n not in executed])
            report["decision_trace"]=s.get("trace",[])+[f"SKIP {n}: upstream_error" for n in STAGES if n not in executed]+["Risk Report Builder: error; no operational action"]
            return {"report":RiskReport.model_validate(report).model_dump(mode="json")}
        events=s.get("events",[])
        pending=[e.event_id for e in active_events(events) if e.needs_clarification]
        attendance=[e for e in active_events(events) if e.event_type=="attendance_event"]
        forecast_state=("blocked_error" if errors else "blocked_clarification" if attendance and pending
                        else "requested" if attendance else "not_requested")
        rechecks=[]
        if forecast_state=="requested":
            rechecks.append("demand_forecast")
        if not errors and (s.get("alerts") or s.get("candidates") or s.get("priority_use_candidates")) and not pending:
            rechecks.append("operation_agent")
        executed=s.get("executed_nodes",[])+["risk_report_builder"]
        skipped=[n for n in STAGES if n not in executed]
        reason="upstream_error" if errors else "not_selected_for_event" if request.get("mode")=="event" else "no_relevant_impacts_or_candidates"
        trace=s.get("trace",[])+[f"SKIP {n}: {reason}" for n in skipped]+[
            f"Risk Report Builder: {len(s.get('candidates',[]))} menu alternatives, {len(s.get('priority_use_candidates',[]))} priority-use candidates; approval required"]
        sources=self.a.sources()
        snapshot=request.get("input_snapshot_id") or stable_id("snapshot",{
            "request":request,"inventory":[x.model_dump(mode="json") for x in s.get("inventory",[])],
            "menus":[x.model_dump(mode="json") for x in s.get("menus",[])],
            "events":[x.model_dump(mode="json") for x in events],
            "prices":s.get("price_risks",[]),"nutrition":s.get("nutrition_results",[]),"sources":sources})
        report=RiskReport(
            as_of=s.get("as_of"),analysis_mode=request.get("mode","full"),
            status="partial" if s.get("parsing_result",{}).get("status")=="partial" else "needs_clarification" if pending else "ok",
            parsing_result=s.get("parsing_result"),validation_warnings=s.get("validation_warnings",[]),
            period={"start":str(s["horizon_start"]) if s.get("horizon_start") else None,
                    "end":str(s["horizon_end"]) if s.get("horizon_end") else None},
            forecast_version=request.get("forecast_version"),input_snapshot_id=snapshot,
            clarification={"status":"required" if pending else "not_required","event_ids":pending},
            recheck_status={"demand_forecast":{"status":forecast_state,"execute_allowed":forecast_state=="requested","executed":False},
                            "operation_agent":{"status":"requested" if "operation_agent" in rechecks else "blocked" if errors or pending else "not_requested","executed":False}},
            execution={"executed_nodes":executed,"skipped_nodes":skipped,"scope":"full" if request.get("mode","full")=="full" else "event_scoped","previous_report_reused":False},
            errors=errors,inventory_status=s.get("inventory_status",[]),allocation_audit=s.get('allocation_audit',[]),
            detected_events=[e.model_dump(mode="json") for e in events],alerts=s.get("alerts",[]),
            price_risks=s.get("price_risks",[]),supply_risks=s.get("supply_risks",[]),
            affected_menus=s.get("affected",[]),
            affected_ingredients=sorted({r["affected_ingredient"] for r in s.get("affected",[])} |
                                        {r["ingredient"] for r in s.get("alerts",[]) if r.get("ingredient")}),
            substitute_candidates=s.get("candidates",[]),priority_use_candidates=s.get("priority_use_candidates",[]),
            nutrition_results=s.get("nutrition_results",[]),cost_impacts=s.get("cost_impacts",[]),
            recommended_rechecks=rechecks,decision_trace=trace,data_sources=sources,
            limitations=[
                "DEMO dish-level constraints, not official institutional standards or whole-meal validation.",
                "Independent candidates require reallocation before joint selection. No automatic operational action.",
                "Planned orders are not available stock; arrival dates are unknown.",
                "Declared allergen exclusions only; missing nutrition/allergens cannot PASS.",
                "Event-scoped reports omit skipped analyses; empty skipped results do not mean no risk.",
                "Generated snapshot ID fingerprints observed inputs; production should provide its authoritative snapshot ID.",
            ])
        raw=report.model_dump(mode="json")
        active=project_active(raw)
        # Public event history remains complete; all derived current evidence is active-only.
        active['detected_events']=raw['detected_events']
        active['parsing_result']=raw['parsing_result']
        return {"report":RiskReport.model_validate(active).model_dump(mode='json')}

def error_report(detail, request=None, sources=None):
    request=request if isinstance(request,dict) else {}
    report=RiskReport(status="error",errors=[detail],parsing_result={"status":"invalid_input","errors":[detail.model_dump(mode="json")]} if detail.code=="input_validation_error" else None,
        analysis_mode=request.get("mode") if isinstance(request.get("mode"),str) and request.get("mode") in {"full","event"} else "full",
        period={"start":None,"end":None},
        forecast_version=request.get("forecast_version") if isinstance(request.get("forecast_version"),str) else None,
        input_snapshot_id=request.get("input_snapshot_id") if isinstance(request.get("input_snapshot_id"),str) else None,
        clarification={"status":"not_evaluated","event_ids":[]},
        recheck_status={"demand_forecast":{"status":"blocked_error","execute_allowed":False,"executed":False},
                        "operation_agent":{"status":"blocked","executed":False}},
        execution={"executed_nodes":[],"skipped_nodes":STAGES,"scope":"not_started","previous_report_reused":False},
        decision_trace=[f"Input/adapter error: {detail.message}"]+[f"SKIP {n}: initialization_error" for n in STAGES],
        data_sources=sources or {})
    return report.model_dump(mode="json")

def analyze_inventory_and_risk(state,user_event=None):
    from pydantic import ValidationError
    from schemas.errors import DataQualityError,validation_error
    from adapters.bundle import AdapterBundle
    from config import RiskConfig
    from graph.inventory_risk_workflow import build_inventory_risk_subgraph
    request={}
    try:
        if not isinstance(state,dict):
            raise input_error("state must be an object","state")
        request={k:v for k,v in state.items() if k not in {"adapters","config"}}
        # Validate before constructing eager local adapters.
        request=AnalysisRequest.model_validate(request).model_dump(mode="json")
        adapters=state.get("adapters")
        if adapters is None:
            adapters=AdapterBundle.demo()
        config=state.get("config") or RiskConfig()
        return build_inventory_risk_subgraph(adapters,config).invoke({"request":request,"user_event":user_event})["report"]
    except DataQualityError as exc:
        return error_report(exc.detail,request)
    except ValidationError as exc:
        return error_report(validation_error(exc).detail,request)
