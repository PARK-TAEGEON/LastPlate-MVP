"""Each review defect has isolated evidence; price/supply cannot mask stock bugs."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import pytest
from pydantic import ValidationError
from adapters.bundle import AdapterBundle
from adapters.local import DEMO_DIR
from schemas.alert import Alert, ALERT_ALIASES
from schemas.event import Event
from schemas.risk_report import RiskReport
from schemas.errors import DataQualityError
from config import RiskConfig
from agents.inventory_risk import analyze_inventory_and_risk, InventoryRiskAgent, STAGES
from tools.events import parse_event
from tools.pricing import analyze_price

@pytest.fixture
def isolated():
    bundle=AdapterBundle.demo()
    bundle.supply_risk.rows=[]
    for p in bundle.price_trend.rows:
        for field in ("price_1w_ago","price_2w_ago","price_3w_ago","price_4w_ago"):
            setattr(p,field,p.current_price)
    prices={p.ingredient:p.current_price for p in bundle.price_trend.rows}
    for p in bundle.monthly_price.rows:
        p.average_price=prices[p.ingredient]
    for lot in bundle.inventory.inventory:
        lot.current_stock=100
        lot.minimum_stock=0
        lot.planned_order=0
        lot.expiry_date=date(2026,12,31)
        lot.last_used_date=date(2026,9,16)
    return bundle

def run(bundle,event=None,**values):
    return analyze_inventory_and_risk({"as_of":"2026-09-17","adapters":bundle,**values},event)

def assert_contract(report):
    RiskReport.model_validate(report)
    assert report["advisory_only"]
    assert not {"final_decision","final_menu","approved_order","auto_commit_change"}&report.keys()
    assert {"period","forecast_version","input_snapshot_id","clarification","recheck_status","execution","errors"}<=report.keys()
    for alert in report["alerts"]:
        Alert.model_validate(alert)
        assert alert["message"] and alert["evidence"]
    assert not report["recheck_status"]["demand_forecast"]["executed"]

@pytest.mark.parametrize("missing",["type","severity","message","evidence"])
def test_alert_fields_required(missing):
    payload=dict(type="low_stock",severity="HIGH",message="risk",evidence=["stock=0"])
    del payload[missing]
    with pytest.raises(ValidationError):Alert(**payload)

@pytest.mark.parametrize("old,new",list(ALERT_ALIASES.items()))
def test_alert_names_normalized(old,new):
    assert Alert(type=old,severity="HIGH",message="risk",evidence=["fact"]).type==new

def test_every_emitted_alert_has_contract():
    report=run(AdapterBundle.demo(),"내일 닭고기 쓰지 말아주세요.")
    assert_contract(report)
    assert not {a["type"] for a in report["alerts"]}&ALERT_ALIASES.keys()

def test_severity_is_configurable(isolated):
    for lot in isolated.inventory.inventory:
        if lot.ingredient=="계란":lot.current_stock=0
    policy=dict(RiskConfig().severity_policy)
    policy["ingredient_shortage"]="LOW"
    r=run(isolated,config=RiskConfig(severity_policy=policy))
    assert all(a["severity"]=="LOW" for a in r["alerts"] if a["type"]=="ingredient_shortage")

def test_shortage_alone_reaches_impacts_and_alternatives(isolated):
    for lot in isolated.inventory.inventory:
        if lot.ingredient=="계란":lot.current_stock=0
    r=run(isolated)
    assert not r["price_risks"] and not r["supply_risks"]
    impacts=[i for i in r["affected_menus"] if i["cause"]=="inventory_shortage_event"]
    assert {i["menu_name"] for i in impacts}=={"계란찜","계란말이"}
    assert all({"date","meal_type","ingredient","cause_event_id"}<=i.keys() for i in impacts)
    ids={i["cause_event_id"] for i in impacts}
    assert r["substitute_candidates"]
    assert all(set(c["cause_event_ids"])<=ids for c in r["substitute_candidates"])

def test_expiry_alone_yields_separate_priority_candidate(isolated):
    tofu=next(l for l in isolated.inventory.inventory if l.ingredient=="두부")
    tofu.current_stock=8;tofu.expiry_date=date(2026,9,18)
    r=run(isolated)
    assert not r["price_risks"] and not r["supply_risks"] and not r["substitute_candidates"]
    assert any(i["cause"]=="inventory_expiry_event" for i in r["affected_menus"])
    candidates=r["priority_use_candidates"]
    assert len(candidates)==1
    assert candidates[0]["quantity_g"]==8000
    assert candidates[0]["date"]=="2026-09-18" and candidates[0]["menu_name"]=="두부조림"
    assert candidates[0]["requires_approval"] and candidates[0]["cause_event_ids"]

def test_expired_lot_never_creates_priority_candidate(isolated):
    isolated.inventory.inventory[0].expiry_date=date(2026,9,16)
    r=run(isolated)
    assert not r["priority_use_candidates"]

def test_priority_allocation_respects_restriction(isolated):
    isolated.inventory.inventory[0].expiry_date=date(2026,9,18)
    r=run(isolated,"내일 두부 쓰지 말아주세요.")
    assert not r["priority_use_candidates"]

@pytest.mark.parametrize("mode",["full","event"])
def test_vague_attendance_never_requests_forecast(isolated,mode):
    r=run(isolated,"내일 사람이 좀 많이 올 것 같아요.",mode=mode)
    e=r["detected_events"][0]
    assert e["event_type"]=="attendance_event" and e["date"]=="2026-09-18"
    assert e["attendance_delta"] is None and e["needs_clarification"]
    assert r["recheck_status"]["demand_forecast"]["status"]=="blocked_clarification"
    assert not r["recheck_status"]["demand_forecast"]["execute_allowed"]
    assert "demand_forecast" not in r["recommended_rechecks"]
    assert_contract(r)

@pytest.mark.parametrize("text",[
    "오늘 내일 손님 35명 추가", "2026-09-18 2026-09-19 손님 35명 추가",
    "2026-09-19 내일 손님 35명 추가", "내일 모레 닭고기 쓰지 마세요",
    "내일 내일 손님 35명 추가", "2026-09-18 내일 손님 35명 추가",
])
def test_multiple_dates_require_clarification(isolated,text):
    r=run(isolated,text,mode="event")
    assert r["status"]=="needs_clarification"
    assert r["detected_events"][0]["date"] is None
    assert r["execution"]["executed_nodes"]==["event_parser","risk_report_builder"]

def test_invalid_natural_date_returns_error(isolated):
    r=run(isolated,"2026-02-30 손님 35명 추가",mode="event")
    assert r["status"]=="error" and r["errors"][0]["field"]=="user_event.date"
    assert_contract(r)

@pytest.mark.parametrize("bad",[True,False,35.0,"35",35.5])
def test_attendance_delta_strict_integer(isolated,bad):
    payload=dict(event_type="attendance_event",date="2026-09-18",attendance_delta=bad)
    with pytest.raises(ValidationError):Event(**payload)
    r=run(isolated,payload,mode="event")
    assert r["status"]=="error" and r["errors"][0]["field"]=="user_event.attendance_delta"
    assert_contract(r)

def test_weekly_down_monthly_up_isolated_regression(isolated):
    p=next(p for p in isolated.price_trend.rows if p.ingredient=="계란")
    p.current_price=100
    p.price_1w_ago=p.price_2w_ago=p.price_3w_ago=p.price_4w_ago=105
    for monthly in isolated.monthly_price.rows:
        if monthly.ingredient=="계란":monthly.average_price=50
    r=run(isolated)
    risk=r["price_risks"][0]
    assert risk["price_change_pct"]==-4.7619 and risk["long_term_change_pct"]==100
    assert risk["weekly_direction"]=="decrease" and risk["monthly_direction"]=="increase"
    assert risk["triggered_rules"]==["monthly_increase"]
    assert not r["supply_risks"]
    assert {x["cause"] for x in r["affected_menus"]}=={"price_event"}
    assert r["substitute_candidates"]

def test_supply_duplicate_observations_idempotent(isolated):
    event=Event(event_type="supply_risk",ingredient="계란",date="2026-09-18",end_date="2026-09-24",severity="HIGH",source_type="simulation",description="same observation")
    isolated.supply_risk.rows=[event,event.model_copy(deep=True)]
    first=run(isolated,event)
    second=run(isolated,event)
    assert first==second
    assert len(first["supply_risks"])==1
    assert len([e for e in first["detected_events"] if e["event_type"]=="supply_risk"])==1
    assert len([a for a in first["alerts"] if a["type"]=="supply_risk"])==1
    assert all(len(c["cause_event_ids"])==1 for c in first["substitute_candidates"])

def test_candidate_keeps_multiple_causes(isolated):
    for lot in isolated.inventory.inventory:
        if lot.ingredient=="계란":lot.current_stock=0
    isolated.supply_risk.rows=[Event(event_type="supply_risk",ingredient="계란",date="2026-09-18",end_date="2026-09-24",severity="HIGH",source_type="simulation")]
    r=run(isolated)
    events={e["event_id"]:e for e in r["detected_events"]}
    for candidate in r["substitute_candidates"]:
        assert {events[e]["event_type"] for e in candidate["cause_event_ids"]}=={"supply_risk","inventory_shortage_event"}

def test_event_attendance_skips_real_nodes(isolated,monkeypatch):
    def forbidden(*args):raise AssertionError("unselected node called")
    for name in STAGES[1:-1]:monkeypatch.setattr(InventoryRiskAgent,name,forbidden)
    r=run(isolated,"내일 손님 35명 추가",mode="event")
    assert r["execution"]["executed_nodes"]==["event_parser","risk_report_builder"]
    assert r["execution"]["skipped_nodes"]==STAGES[1:-1]
    assert all(any(f"SKIP {name}:" in line for line in r["decision_trace"]) for name in STAGES[1:-1])
    assert r["recheck_status"]["demand_forecast"]["status"]=="requested"
    assert r["inventory_status"]==[]

def test_restriction_event_skips_price_node(isolated,monkeypatch):
    def forbidden(*args):raise AssertionError("price node called")
    monkeypatch.setattr(InventoryRiskAgent,"price_risk_analyzer",forbidden)
    r=run(isolated,"내일 닭고기 쓰지 말아주세요.",mode="event")
    assert "supply_risk_analyzer" in r["execution"]["executed_nodes"]
    assert "price_risk_analyzer" in r["execution"]["skipped_nodes"]
    assert r["substitute_candidates"]

def test_no_impacts_skips_candidate_and_nutrition(isolated):
    r=run(isolated)
    assert not r["affected_menus"]
    assert r["execution"]["skipped_nodes"]==["substitute_candidate_generator","nutrition_constraint_checker"]

def test_no_recipe_candidate_skips_nutrition(isolated):
    isolated.recipe.recipes={k:v for k,v in isolated.recipe.recipes.items() if v.menu_name=="닭갈비"}
    r=run(isolated,"내일 닭고기 쓰지 말아주세요.",mode="event")
    assert "substitute_candidate_generator" in r["execution"]["executed_nodes"]
    assert "nutrition_constraint_checker" in r["execution"]["skipped_nodes"]

@pytest.mark.parametrize("event",[
    "내일 손님 35명 추가", "내일 사람이 좀 많이 올 것 같아요.",
    "내일 닭고기 쓰지 말아주세요.", "두부가 내일까지예요.", "이해 불가",
    {"event_type":"price_event","date":"2026-09-21","ingredient":"계란"},
    {"event_type":"supply_risk","date":"2026-09-21","ingredient":"계란","severity":"HIGH"},
    "2026-99-99 인원 35명 추가",None,
])
def test_all_event_routes_return_report_contract(isolated,event):
    assert_contract(run(isolated,event,mode="event"))

def test_graph_has_conditional_edges_and_actual_stream(isolated):
    from graph.inventory_risk_workflow import build_inventory_risk_subgraph
    graph=build_inventory_risk_subgraph(isolated,RiskConfig())
    assert any(e.conditional for e in graph.get_graph().edges)
    outputs=list(graph.stream({"request":{"as_of":"2026-09-17","mode":"event"},"user_event":"내일 손님 35명 추가"},stream_mode="updates"))
    assert [next(iter(x)) for x in outputs]==["event_parser","risk_report_builder"]

def test_metadata_and_no_source_mutation(isolated):
    before=deepcopy(isolated.inventory.inventory)
    r=run(isolated,"두부가 내일까지예요.",mode="event",forecast_version="forecast-v2",input_snapshot_id="snapshot-42")
    assert r["forecast_version"]=="forecast-v2" and r["input_snapshot_id"]=="snapshot-42"
    assert r["period"]=={"start":"2026-09-17","end":"2026-09-24"}
    assert before==isolated.inventory.inventory

def test_graph_data_error_returns_contract(isolated,monkeypatch):
    def broken():raise DataQualityError("broken",file="inventory.xlsx",row=4,field="unit")
    monkeypatch.setattr(isolated.inventory,"get_inventory",broken)
    r=run(isolated)
    assert r["status"]=="error"
    assert r["errors"][0]["row"]==4
    assert_contract(r)

@pytest.mark.parametrize("state",[{}, {"as_of":"invalid"}, {"as_of":"2026-09-17","mode":"bad"}, {"as_of":"2026-09-17","forecast_version":12}, {"as_of":"2026-09-17","horizon_end":"2026-01-01"}])
def test_invalid_request_returns_contract(state):
    r=analyze_inventory_and_risk(state)
    assert r["status"]=="error"
    assert_contract(r)

@pytest.mark.parametrize("state",[{"as_of":False},{"as_of":12345},{"as_of":"2026-09-17","mode":[]}])
def test_invalid_request_types_do_not_escape_error_boundary(state):
    report=analyze_inventory_and_risk(state)
    assert report["status"]=="error"
    assert_contract(report)

def test_graph_reinvocation_resets_selected_nodes(isolated):
    from graph.inventory_risk_workflow import build_inventory_risk_subgraph
    graph=build_inventory_risk_subgraph(isolated,RiskConfig())
    first=graph.invoke({"request":{"as_of":"2026-09-17"}})
    first["request"]["mode"]="event"
    first["user_event"]="내일 닭고기 쓰지 말아주세요."
    second=graph.invoke(first)["report"]
    assert second["execution"]["executed_nodes"].count("inventory_analyzer")==1
    assert "price_risk_analyzer" in second["execution"]["skipped_nodes"]
    assert second["substitute_candidates"]

def test_monthly_decrease_does_not_create_substitution_impacts(isolated):
    price=next(p for p in isolated.price_trend.rows if p.ingredient=="계란")
    for row in isolated.monthly_price.rows:
        if row.ingredient=="계란":row.average_price=price.current_price*2
    report=run(isolated)
    assert report["price_risks"][0]["triggered_rules"]==["monthly_decrease"]
    assert not report["affected_menus"] and not report["substitute_candidates"]
