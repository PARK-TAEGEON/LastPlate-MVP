"""v0.2.3: narrow intent polarity and residual regressions."""
from datetime import date
import pytest
from tools.events import parse_event_result, applies
from adapters.bundle import AdapterBundle
from agents.inventory_risk import analyze_inventory_and_risk
from schemas.event import Event
from schemas.risk_report import RiskReport

BAN="ingredient_restriction_event"
RELEASE="ingredient_restriction_release_event"

def parse(text):
    return parse_event_result(text,date(2026,9,17),{"닭고기","계란","두부"})

def test_1_spaced_exclusion():
    result=parse("내일 닭고기 쓰지 말아주세요 계란도 빼 주세요.")
    assert result.status=="ok"
    assert [(e.ingredient,e.event_type) for e in result.parsed_events]==[("닭고기",BAN),("계란",BAN)]

def test_2_exclude_conjunction():
    result=parse("닭고기 제외하고 계란도 제외해주세요.")
    assert len(result.parsed_events)==2
    assert all(e.event_type==BAN for e in result.parsed_events)
    assert result.status=="needs_clarification"  # Preserve missing-date policy.

def test_3_release_is_not_ban():
    result=parse("닭고기 쓰지 말아주세요 계란은 사용 금지 해제해주세요.")
    assert [(e.ingredient,e.event_type) for e in result.parsed_events]==[("닭고기",BAN),("계란",RELEASE)]

def test_4_standalone_release():
    event=parse("계란 금지 해제해주세요.").parsed_events[0]
    assert event.event_type==RELEASE and event.action=="release_restriction"

def test_5_do_not_remove():
    assert parse("계란 빼지 마세요.").parsed_events[0].event_type==RELEASE

def test_6_connector_not_partial():
    result=parse("닭고기 쓰지 말아주세요. 그리고 계란도 빼 주세요.")
    assert len(result.parsed_events)==2 and not result.unparsed_segments
    assert result.status=="needs_clarification"
    assert parse("내일 닭고기 쓰지 말아주세요. 그리고 계란도 빼 주세요.").status=="ok"

def test_7_meaningful_residual():
    result=parse("닭고기 쓰지 말아주세요. 그리고 재고도 알아서 처리해 주세요.")
    assert result.parsed_events[0].event_type==BAN
    assert result.status=="partial" and "재고" in result.unparsed_segments[-1]

def test_8_last_explicit_intent_and_trace():
    result=parse("계란 쓰지 마세요. 아니요 계란 금지는 해제해주세요.")
    assert [e.event_type for e in result.parsed_events]==[BAN,RELEASE]
    assert result.parsed_events[0].superseded
    assert not result.parsed_events[1].superseded
    assert any(BAN+" -> "+RELEASE in line for line in result.decision_trace)

@pytest.mark.parametrize("phrase",["쓰지 말아주세요","사용하지 말아주세요","사용하지 마세요","빼 주세요","빼주세요","제외해 주세요","제외해주세요","사용 금지","금지"])
def test_all_exclusion_synonyms(phrase):
    result=parse("내일 계란 "+phrase+".")
    assert result.status=="ok" and len(result.parsed_events)==1
    assert result.parsed_events[0].event_type==BAN

@pytest.mark.parametrize("phrase",["금지 해제","사용 금지 해제","제외 취소","금지 취소","다시 사용","사용 가능","빼지 마세요","제외하지 마세요"])
def test_release_priority(phrase):
    result=parse("내일 계란 "+phrase+".")
    assert result.status=="ok" and len(result.parsed_events)==1
    assert result.parsed_events[0].event_type==RELEASE
    assert result.parsed_events[0].restriction is None

@pytest.mark.parametrize("connector",["그리고","또","또한","및","그리고요",",",".","/"])
def test_standalone_connectors(connector):
    result=parse("내일 계란 금지. "+connector+". 두부 금지.")
    assert result.status=="ok" and len(result.parsed_events)==2

@pytest.mark.parametrize("text",[
    "내일 계란 금지 재고도 알아서 처리해 주세요.",
    "내일 계란 금지 해제해주세요 재고도 알아서 처리해 주세요.",
    "내일 손님 35명 추가됩니다 재고도 알아서 처리해 주세요.",
    "두부가 내일까지예요 재고도 알아서 처리해 주세요.",
    "내일 계란 금지. 그리고요 재고도 알아서 처리해 주세요.",
    "내일 계란 금지. 또한 재고도 알아서 처리해 주세요.",
])
def test_meaningful_tail_never_ok(text):
    result=parse(text)
    assert result.status in {"partial","needs_clarification"}
    assert result.unparsed_segments

def test_ban_release_ban_preserves_order():
    result=parse("내일 계란 금지. 계란 금지 해제. 계란 금지.")
    assert [e.event_type for e in result.parsed_events]==[BAN,RELEASE,BAN]
    assert [e.superseded for e in result.parsed_events]==[True,True,False]
    assert applies(result.parsed_events[-1],date(2026,9,18))

def test_different_date_release_does_not_override():
    result=parse("오늘 계란 금지. 내일 계란 금지 해제.")
    assert not any(e.superseded for e in result.parsed_events)

def test_unknown_release_stays_unregistered():
    result=parse("내일 타조고기 금지 해제.")
    assert result.status=="needs_clarification"
    assert result.parsed_events[0].event_type==RELEASE
    assert result.validation_warnings[0]["type"]=="unregistered_ingredient"

@pytest.mark.parametrize("mode",["full","event"])
def test_report_release_has_no_restriction_impact(mode):
    bundle=AdapterBundle.demo()
    bundle.supply_risk.rows=[]
    for menu in bundle.inventory.menus:
        if menu.menu_name=="계란찜": menu.date=date(2026,9,18)
    report=analyze_inventory_and_risk({"as_of":"2026-09-17","mode":mode,"adapters":bundle},"내일 계란 쓰지 마세요. 아니요 계란 금지는 해제해주세요.")
    RiskReport.model_validate(report)
    assert report["status"]=="ok"
    assert not [i for i in report["affected_menus"] if i["cause"]==BAN]
    assert any(BAN+" -> "+RELEASE in line for line in report["decision_trace"])
    assert report["advisory_only"]
    # Isolated inventory allocation matches the same analysis with release only.
    baseline=analyze_inventory_and_risk({"as_of":"2026-09-17","mode":mode,"adapters":bundle},"내일 계란 금지 해제.")
    assert report["inventory_status"]==baseline["inventory_status"]
    assert report["substitute_candidates"]==baseline["substitute_candidates"]

def test_structured_release_contract():
    result=parse_event_result({"event_type":RELEASE,"ingredient":"계란","date":"2026-09-18"},date(2026,9,17),{"계란"})
    assert result.status=="ok" and result.parsed_events[0].action=="release_restriction"
    with pytest.raises(ValueError):
        Event(event_type=RELEASE,ingredient="계란",restriction="do_not_use")

def test_existing_event_identity_unchanged():
    from tools.identity import event_id,stable_id
    event=Event(event_type=BAN,ingredient="계란",date=date(2026,9,18),restriction="do_not_use")
    old_body=event.model_dump(mode="json",exclude={"event_id","source_text","matched_sources","reason","action","superseded"})
    assert event_id(event)==stable_id("event",old_body)

def test_release_through_parent_graph():
    from langgraph.graph import StateGraph,START,END
    from graph.inventory_risk_workflow import InventoryRiskState,build_inventory_risk_subgraph
    from config import RiskConfig
    parent=StateGraph(InventoryRiskState)
    parent.add_node("risk",build_inventory_risk_subgraph(AdapterBundle.demo(),RiskConfig()))
    parent.add_edge(START,"risk");parent.add_edge("risk",END)
    report=parent.compile().invoke({"request":{"as_of":"2026-09-17","mode":"event"},"user_event":"내일 계란 금지. 아니요 계란 금지 해제."})["report"]
    assert report["status"]=="ok"
    assert report["parsing_result"]["parsed_events"][0]["superseded"]
    assert any("last explicit intent wins" in line for line in report["decision_trace"])

def test_release_in_existing_streamlit_ui():
    from pathlib import Path
    import json
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"examples/streamlit_app.py"),default_timeout=20).run()
    app.selectbox[0].select("event")
    app.text_area[0].input("내일 계란 금지. 그리고 계란 금지 해제.")
    app.button[0].click().run()
    assert not app.exception and not app.error
    result=next(json.loads(j.value)["parsing_result"] for j in app.json if "parsing_result" in json.loads(j.value))
    assert result["status"]=="ok"
    assert [e["event_type"] for e in result["parsed_events"]]==[BAN,RELEASE]
