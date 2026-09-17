"""v0.2.2: repeated restrictions only; keep the original 169 tests unchanged."""
from datetime import date
from pathlib import Path
import pytest
from adapters.bundle import AdapterBundle
from agents.inventory_risk import analyze_inventory_and_risk
from config import RiskConfig
from schemas.risk_report import RiskReport
from tools.events import parse_event_result

NAMES={"닭고기","계란","두부"}

def parse(text):
    return parse_event_result(text,date(2026,9,17),NAMES,RiskConfig().ingredient_aliases)

def restrictions(result):
    return [e for e in result.parsed_events if e.event_type=="ingredient_restriction_event"]

def test_1_consecutive_restrictions_have_complete_status():
    result=parse("내일 닭고기 쓰지 말아주세요 계란 쓰지 말아주세요.")
    assert result.status=="ok"
    assert {e.ingredient for e in restrictions(result)}=={"닭고기","계란"}
    assert len(result.parsed_events)==2
    assert all(e.date==date(2026,9,18) for e in result.parsed_events)

def test_2_malgo_and_particle_do():
    result=parse("닭고기 쓰지 말고 계란도 쓰지 말아주세요.")
    assert {e.ingredient for e in restrictions(result)}=={"닭고기","계란"}
    assert all(e.reason!="unregistered_ingredient" for e in result.parsed_events)
    assert result.status=="needs_clarification"  # Missing date remains missing.

def test_3_list_shares_predicate():
    result=parse("닭고기, 계란, 두부 사용하지 말아주세요.")
    assert len(restrictions(result))==3
    assert {e.ingredient for e in restrictions(result)}==NAMES

def test_4_attendance_and_two_restrictions():
    result=parse("내일 손님 35명 추가하고 닭고기 쓰지 말고 계란도 쓰지 말아주세요.")
    assert result.status=="ok" and len(result.parsed_events)==3
    assert next(e for e in result.parsed_events if e.event_type=="attendance_event").attendance_delta==35
    assert {e.ingredient for e in restrictions(result)}=={"닭고기","계란"}

def test_5_normalized_names_in_repeated_predicates():
    result=parse("닭 고기 쓰지 말아주세요 계 란 쓰지 말아주세요.")
    assert {e.ingredient for e in restrictions(result)}=={"닭고기","계란"}

def test_6_unregistered_second_item_not_dropped():
    result=parse("닭고기 쓰지 말고 타조고기도 쓰지 말아주세요.")
    assert len(restrictions(result))==2 and result.status!="ok"
    unknown=next(e for e in restrictions(result) if e.ingredient=="타조고기")
    assert unknown.needs_clarification and unknown.reason=="unregistered_ingredient"
    assert result.validation_warnings[0]["ingredient"]=="타조고기"

def test_7_semantic_duplicates_keep_source_phrases():
    text="닭고기 쓰지 말고 닭고기는 꼭 빼주세요."
    result=parse(text)
    assert len(restrictions(result))==1
    event=result.parsed_events[0]
    assert event.ingredient=="닭고기"
    assert "닭고기 쓰지 말고" in event.source_text
    assert "닭고기는 꼭 빼주세요" in event.source_text
    assert not result.unparsed_segments

@pytest.mark.parametrize("text,names",[
    ("닭고기 쓰지 말아주세요 계란 쓰지 말아주세요.",{"닭고기","계란"}),
    ("닭고기, 계란 사용하지 말아주세요.",{"닭고기","계란"}),
    ("닭고기 금지, 계란 금지, 두부 금지",NAMES),
    ("닭 고기 쓰지 말아주세요. 계 란도 쓰지 말아주세요.",{"닭고기","계란"}),
    ("계란 사용 금지, 두부 사용  금지",{"계란","두부"}),
])
def test_representative_patterns_with_and_without_date(text,names):
    unknown_date=parse(text)
    known_date=parse("내일 "+text)
    assert {e.ingredient for e in restrictions(unknown_date)}==names
    assert {e.ingredient for e in restrictions(known_date)}==names
    assert len(restrictions(known_date))==len(names)
    assert known_date.status=="ok" and unknown_date.status=="needs_clarification"

def test_each_repeated_event_has_local_source():
    text="내일 닭고기 쓰지 말아주세요 계란 쓰지 말아주세요."
    events=restrictions(parse(text))
    assert all(e.source_text in text for e in events)
    assert "계란" not in events[0].source_text and "닭고기" not in events[1].source_text

def test_list_unknown_member_keeps_known_members():
    result=parse("내일 닭고기, 타조고기, 계란 사용하지 말아주세요.")
    assert len(result.parsed_events)==3 and result.status=="needs_clarification"
    assert {e.ingredient for e in restrictions(result) if not e.needs_clarification}=={"닭고기","계란"}

def test_alias_duplicate_merges_after_normalization():
    result=parse("내일 계 란 금지, 달걀 금지")
    assert result.status=="ok" and len(restrictions(result))==1
    assert result.parsed_events[0].ingredient=="계란"
    assert "계 란" in result.parsed_events[0].source_text and "달걀" in result.parsed_events[0].source_text

def test_different_dates_are_not_merged():
    result=parse("오늘 닭고기 금지. 내일 닭고기 금지.")
    assert len(restrictions(result))==2
    assert {e.date for e in restrictions(result)}=={date(2026,9,17),date(2026,9,18)}

def test_missing_ingredient_is_partial_instead_of_ok():
    result=parse("내일 쓰지 말아주세요 계란 쓰지 말아주세요.")
    assert result.status=="partial" and result.unparsed_segments
    assert any(e.ingredient=="계란" for e in restrictions(result))

@pytest.mark.parametrize("mode",["full","event"])
def test_report_preserves_three_events_and_existing_routing(mode):
    bundle=AdapterBundle.demo()
    text="내일 손님 35명 추가하고 닭고기 쓰지 말고 계란도 쓰지 말아주세요."
    report=analyze_inventory_and_risk({"as_of":"2026-09-17","mode":mode,"adapters":bundle},text)
    RiskReport.model_validate(report)
    events=[e for e in report["detected_events"] if e["source_type"]=="user"]
    assert len(events)==3 and report["status"]=="ok"
    assert "inventory_analyzer" in report["execution"]["executed_nodes"]
    assert report["recheck_status"]["demand_forecast"]["executed"] is False
    assert report["advisory_only"] and "final_decision" not in report

def test_second_restriction_reaches_impact_analysis():
    bundle=AdapterBundle.demo()
    bundle.supply_risk.rows=[]
    for m in bundle.inventory.menus:
        if m.menu_name=="계란찜":m.date=date(2026,9,18)
    report=analyze_inventory_and_risk({"as_of":"2026-09-17","mode":"event","adapters":bundle},"내일 닭고기 쓰지 말아주세요 계란 쓰지 말아주세요.")
    assert {i["ingredient"] for i in report["affected_menus"] if i["cause"]=="ingredient_restriction_event"}=={"닭고기","계란"}
    assert not report["supply_risks"] and not report["price_risks"]

def test_unknown_second_item_blocks_report_rechecks():
    report=analyze_inventory_and_risk({"as_of":"2026-09-17","mode":"event"},"내일 닭고기 쓰지 말고 타조고기도 쓰지 말아주세요.")
    assert report["status"]=="needs_clarification"
    assert report["validation_warnings"][0]["ingredient"]=="타조고기"
    assert not report["recommended_rechecks"]

def test_repeated_restrictions_through_parent_graph():
    from langgraph.graph import StateGraph,START,END
    from graph.inventory_risk_workflow import InventoryRiskState,build_inventory_risk_subgraph
    parent=StateGraph(InventoryRiskState)
    parent.add_node("risk",build_inventory_risk_subgraph(AdapterBundle.demo(),RiskConfig()))
    parent.add_edge(START,"risk");parent.add_edge("risk",END)
    report=parent.compile().invoke({"request":{"as_of":"2026-09-17","mode":"event"},"user_event":"내일 닭고기 금지, 계란 금지"})["report"]
    assert report["status"]=="ok" and len(report["parsing_result"]["parsed_events"])==2

def test_existing_streamlit_renders_repeated_restriction_result():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"examples/streamlit_app.py"),default_timeout=20).run()
    app.selectbox[0].select("event")
    app.text_area[0].input("내일 닭고기 쓰지 말아주세요 계란 쓰지 말아주세요.")
    app.button[0].click().run()
    assert not app.exception and not app.error
    import json
    parsing=next(json.loads(j.value)["parsing_result"] for j in app.json if "parsing_result" in json.loads(j.value))
    assert parsing["status"]=="ok" and len(parsing["parsed_events"])==2
