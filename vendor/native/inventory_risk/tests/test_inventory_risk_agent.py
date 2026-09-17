from copy import deepcopy
from datetime import date
import pytest
from adapters.bundle import AdapterBundle
from agents.inventory_risk import analyze_inventory_and_risk
from config import RiskConfig
from schemas.risk_report import RiskReport
from schemas.event import Event
from schemas.models import InventoryLot, Menu, Recipe, IngredientAmount, PriceTrend
from tools.events import parse_event
from tools.inventory import allocate
from tools.nutrition import check
from tools.pricing import analyze_price

@pytest.fixture
def adapters():
    return AdapterBundle.demo()

def run(adapters,event=None,**kwargs):
    return analyze_inventory_and_risk({"as_of":"2026-09-17","adapters":adapters,**kwargs},event)

def test_case1_expiry(adapters):
    r=run(adapters)
    alert=next(x for x in r["alerts"] if x["type"]=="expiry_risk" and x["ingredient"]=="두부")
    assert "현재 재고 8.0kg" in alert["evidence"]
    assert "유통기한 D-1" in alert["evidence"]
    assert any("두부조림" in x for x in alert["evidence"])
    assert alert["candidate_action"]=="기존 재고 우선 사용 검토"

def test_case2_price(adapters):
    r=run(adapters)
    p=next(x for x in r["price_risks"] if x["ingredient"]=="계란")
    assert p["price_change_pct"]==22
    assert p["severity"]=="HIGH"
    assert {x["menu_name"] for x in r["affected_menus"] if x["affected_ingredient"]=="계란"}=={"계란찜","계란말이"}
    options=[x for x in r["substitute_candidates"] if x["original_menu"]=="계란찜" and x["candidate_menu"]=="두부조림"]
    assert options and options[0]["nutrition_check"]=="PASS"
    assert options[0]["inventory_available"]
    assert options[0]["price_effect"]=="lower"
    assert r["nutrition_results"] and r["cost_impacts"]

def test_case3_supply(adapters):
    r=run(adapters)
    assert {x["ingredient"] for x in r["supply_risks"]}=={"계란","닭고기"}
    assert all(x["source_type"]=="simulation" and x["severity"]=="HIGH" for x in r["supply_risks"])
    assert all(x["inventory_context"] for x in r["supply_risks"])
    assert any(x["original_menu"]=="닭갈비" for x in r["substitute_candidates"])

def test_case4_restriction_is_date_scoped(adapters):
    r=run(adapters,"내일 닭고기 쓰지 말아주세요.")
    e=r["detected_events"][0]
    assert e["event_type"]=="ingredient_restriction_event" and e["date"]=="2026-09-18"
    conflicts=[x for x in r["affected_menus"] if x["cause"]=="ingredient_restriction_event"]
    assert len(conflicts)==1 and conflicts[0]["date"]=="2026-09-18"
    assert any(x["original_menu"]=="닭갈비" for x in r["substitute_candidates"])

def test_case5_attendance_no_forecast_or_mutation(adapters):
    before=deepcopy(adapters.inventory.menus)
    r=run(adapters,"내일 외부 손님 35명 추가됩니다.")
    e=r["detected_events"][0]
    assert e["event_type"]=="attendance_event" and e["attendance_delta"]==35
    assert "demand_forecast" in r["recommended_rechecks"]
    assert before==adapters.inventory.menus
    assert "final_decision" not in r and "predicted_diners" not in r

@pytest.mark.parametrize("text",["내일 외부 인원 추가됩니다.","내일 외부 인원 30~35명 추가됩니다.","내일 외부 인원 약 35명 추가됩니다.","내일 외부 인원 35.5명 추가됩니다.","내일 외부 인원 35명 추가 10명 감소됩니다.","내일 외부 인원 30-35명 추가됩니다.","내일 외부 인원 1,035명 추가됩니다."])
def test_ambiguous_count(text):
    e=parse_event(text,date(2026,9,17),set())[0]
    assert e.needs_clarification and e.attendance_delta is None

def test_nutrition_rejection_and_allergy(adapters):
    r=run(adapters,prohibited_allergens=["대두"])
    tofu=[x for x in r["substitute_candidates"] if x["candidate_menu"]=="두부조림"]
    assert tofu and all(x["nutrition_check"]=="FAIL" and not x["eligible_for_review"] for x in tofu)
    assert any("sodium_limit" in x["violations"] for x in r["nutrition_results"])
    assert any("minimum_protein" in x["violations"] for x in r["nutrition_results"])

def test_unknown_nutrition_is_not_pass(adapters):
    del adapters.nutrition.rows["두부"]
    r=run(adapters)
    assert all(x["nutrition_check"]=="UNKNOWN" for x in r["substitute_candidates"] if x["candidate_menu"]=="두부조림")

def test_expired_lots_cannot_supply_later_candidates(adapters):
    for lot in adapters.inventory.inventory:
        if lot.ingredient=="두부": lot.expiry_date=date(2026,9,18)
    r=run(adapters)
    assert all(not x["inventory_available"] for x in r["substitute_candidates"] if x["candidate_menu"]=="두부조림")

def test_expiry_input_is_snapshot_only(adapters):
    old=deepcopy(adapters.inventory.inventory)
    r=run(adapters,"두부가 내일까지예요.")
    assert r["detected_events"][0]["event_type"]=="expiry_event"
    assert all(not x["inventory_available"] for x in r["substitute_candidates"] if x["candidate_menu"]=="두부조림")
    assert old==adapters.inventory.inventory

def test_missing_price_and_stale_price(adapters):
    for p in adapters.price_trend.rows: p.date=date(2026,1,1)
    r=run(adapters)
    assert not r["price_risks"]
    assert all(c["delta_total"] is None for c in r["cost_impacts"])

def test_price_drop_and_unit_normalization():
    p=PriceTrend(date="2026-09-17",ingredient="x",current_price=0.7,price_1w_ago=1,price_2w_ago=1,price_3w_ago=1,price_4w_ago=1,unit="g")
    r=analyze_price(p,[],RiskConfig())
    assert r["price_change_pct"]==-30 and r["direction"]=="decrease"
    with pytest.raises(ValueError): PriceTrend(**{**p.model_dump(),"price_1w_ago":0})

def test_fefo_does_not_double_count():
    a=IngredientAmount(ingredient="x",amount_per_serving=100,unit="g")
    recipe=Recipe(recipe_id="r",menu_name="m",category="main",ingredients=[a])
    menus=[Menu(date=day,meal_type="lunch",menu_name="m",expected_max_diners=10,ingredients=[a]) for day in ["2026-09-18","2026-09-19"]]
    lot=InventoryLot(ingredient="x",current_stock=1,unit="kg",expiry_date="2026-09-20",unit_price=1,minimum_stock=0,planned_order=0,storage_type="cold")
    from tools.recipe import menu_key
    needed,missing,_=allocate([lot],menus,{menu_key(m):recipe for m in menus})
    assert needed["x"]==2000 and missing["x"]==1000

def test_future_price_and_completed_supply_excluded(adapters):
    for p in adapters.price_trend.rows:p.date=date(2027,1,1)
    for e in adapters.supply_risk.rows:e.end_date=date(2026,9,16)
    r=run(adapters)
    assert not r["price_risks"] and not r["supply_risks"]

def test_report_schema_sources_and_trace(adapters):
    r=run(adapters)
    assert RiskReport.model_validate(r).advisory_only
    assert len(r["decision_trace"])>=8
    assert all("DEMO" in v for v in r["data_sources"].values())
    with pytest.raises(ValueError):RiskReport.model_validate({**r,"final_decision":{}})

def test_adapter_replacement_no_file_access(adapters):
    class MemoryInventory:
        source="TEST_MEMORY"
        menu_source="TEST_MEMORY"
        def get_inventory(self):return []
        def get_weekly_menu(self):return []
    adapters.inventory=MemoryInventory()
    adapters.supply_risk.rows=[]
    r=run(adapters)
    assert r["inventory_status"]==[] and r["data_sources"]["inventory"]=="TEST_MEMORY"

def test_graph_can_be_composed(adapters):
    from langgraph.graph import StateGraph,START,END
    from graph.inventory_risk_workflow import build_inventory_risk_subgraph, InventoryRiskState
    parent=StateGraph(InventoryRiskState)
    parent.add_node("inventory_risk",build_inventory_risk_subgraph(adapters,RiskConfig()))
    parent.add_edge(START,"inventory_risk");parent.add_edge("inventory_risk",END)
    assert parent.compile().invoke({"request":{"as_of":"2026-09-17"}})["report"]["advisory_only"]

def test_invalid_config_and_event():
    with pytest.raises(ValueError):RiskConfig(price_alert_high=5)
    with pytest.raises(ValueError):Event(event_type="attendance_event")
    with pytest.raises(ValueError):Event(event_type="ingredient_restriction_event",ingredient="x")

def test_same_menu_different_day_quantities(adapters):
    chicken=[m for m in adapters.inventory.menus if m.menu_name=="닭갈비"]
    chicken[0].ingredients[0].amount_per_serving=50
    r=run(adapters)
    stock=next(x for x in r["inventory_status"] if x["ingredient"]=="닭고기")
    assert stock["required_g"]==12500

def test_reserved_stock_not_reused_for_candidate(adapters):
    from tools.substitute import inventory_feasibility
    from tools.recipe import scheduled_recipe,menu_key
    target=next(m for m in adapters.inventory.menus if m.menu_name=="계란찜")
    inventory=[x for x in adapters.inventory.inventory if not(x.ingredient=="두부" and x.current_stock==30)]
    for lot in inventory:
        if lot.ingredient=="두부":lot.expiry_date=date(2026,9,30)
    menus=adapters.inventory.menus
    recipes={menu_key(m):scheduled_recipe(m,adapters.recipe) for m in menus}
    r=inventory_feasibility(adapters.recipe.get_recipe("두부조림"),target,menus,recipes,inventory,[])
    assert not r["inventory_available"] and r["shortages_g"]["두부"]==8000

def test_order_is_not_excess_when_stock_expires_before_service(adapters):
    from tools.inventory import analyze
    from tools.recipe import menu_key,scheduled_recipe
    target=next(m for m in adapters.inventory.menus if m.menu_name=="계란찜")
    lot=next(x for x in adapters.inventory.inventory if x.ingredient=="계란")
    lot.current_stock=7;lot.planned_order=7;lot.minimum_stock=0;lot.expiry_date=date(2026,9,18)
    _,alerts=analyze([lot],[target],{menu_key(target):scheduled_recipe(target,adapters.recipe)},date(2026,9,17),RiskConfig(),[])
    assert not any(a["type"]=="excess_order" and a["ingredient"]=="계란" for a in alerts)

def test_html_escapes_operator_content(adapters):
    from tools.report_html import render_report
    r=run(adapters,"<script>alert(1)</script>")
    page=render_report(r)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "DEMO / SIMULATION" in page
