"""Narrow v0.2.1 regressions: compound input, names, duplicate weekly rows."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import shutil
import pytest
from openpyxl import load_workbook
from adapters.bundle import AdapterBundle
from adapters.inventory_adapter import DemoInventoryAdapter
from adapters.local import DEMO_DIR
from agents.inventory_risk import analyze_inventory_and_risk
from schemas.errors import DataQualityError
from schemas.models import IngredientAmount, InventoryLot, Menu, Recipe
from schemas.risk_report import RiskReport
from tools.events import parse_event_result
from tools.ingredients import IngredientRegistry, normalize_ingredient

@pytest.fixture
def bundle():
    return AdapterBundle.demo()

def run(bundle,event=None,mode="event"):
    return analyze_inventory_and_risk({"as_of":"2026-09-17","mode":mode,"adapters":bundle},event)

def user_events(report):
    return [e for e in report["detected_events"] if e["source_type"]=="user"]

@pytest.mark.parametrize("mode",["full","event"])
@pytest.mark.parametrize("text,delta,kind,ingredient,status",[
    ("내일 손님 35명 추가하고 닭고기 쓰지 말아주세요.",35,"ingredient_restriction_event","닭고기","ok"),
    ("내일 회식으로 40명 빠지고 두부가 내일까지예요.",-40,"expiry_event","두부","ok"),
    ("외부 인원 20명 추가되고 계란 쓰지 말아주세요.",20,"ingredient_restriction_event","계란","needs_clarification"),
])
def test_compound_cases_abc(bundle,mode,text,delta,kind,ingredient,status):
    before=deepcopy(bundle.inventory.menus)
    report=run(bundle,text,mode)
    events=user_events(report)
    assert len(events)==2
    assert {e["event_type"] for e in events}=={"attendance_event",kind}
    assert next(e for e in events if e["event_type"]=="attendance_event")["attendance_delta"]==delta
    target=next(e for e in events if e["event_type"]==kind)
    assert target["ingredient"]==ingredient
    assert target["matched_sources"]==["inventory","recipe","weekly_menu"]
    assert all(e["source_text"] and e["source_text"] in text for e in events)
    assert report["status"]==status
    if status=="ok":
        assert all(e["date"]=="2026-09-18" for e in events)
        assert "inventory_analyzer" in report["execution"]["executed_nodes"]
        assert "demand_forecast" in report["recommended_rechecks"]
    else:
        assert not report["recommended_rechecks"]
    assert before==bundle.inventory.menus
    RiskReport.model_validate(report)

def test_compound_partial_is_visible_and_blocks_rechecks(bundle):
    text="내일 손님 35명 추가하고 냉장고 청소도 해주세요."
    report=run(bundle,text)
    assert report["status"]=="partial"
    parsed=report["parsing_result"]
    assert len(parsed["parsed_events"])==1
    assert parsed["unparsed_segments"]==["냉장고 청소도 해주세요."]
    assert "demand_forecast" not in report["recommended_rechecks"]
    assert report["recheck_status"]["demand_forecast"]["status"]=="blocked_clarification"

def test_unsplit_ingredient_intents_are_not_reported_complete(bundle):
    report=run(bundle,"내일 닭고기 쓰지 말아주세요 두부가 내일까지예요")
    assert report["status"]=="partial"
    assert report["parsing_result"]["unparsed_segments"]

def test_multiple_spaces_in_restriction_marker(bundle):
    report=run(bundle,"내일 닭 고기 사용  금지")
    assert user_events(report)[0]["ingredient"]=="닭고기"
    assert report["status"]=="ok"

@pytest.mark.parametrize("input_name,expected",[("닭 고기","닭고기"),(" 두   부 ","두부"),(" 계 란 ","계란"),("달걀","계란")])
def test_whitespace_and_aliases_reach_impacts(bundle,input_name,expected):
    report=run(bundle,f"내일 {input_name} 사용하지 말아주세요.")
    event=user_events(report)[0]
    assert event["ingredient"]==expected and event["matched_sources"]
    assert not event["needs_clarification"]
    assert any(i["cause"]=="ingredient_restriction_event" for i in report["affected_menus"]) if expected!="계란" else event["date"]=="2026-09-18"

def test_normalization_casefold():
    registry=IngredientRegistry({"inventory":{"Milk"}})
    result=parse_event_result("내일 m I L k 쓰지 말아주세요.",date(2026,9,17),registry)
    assert result.status=="ok" and result.parsed_events[0].ingredient=="Milk"
    assert normalize_ingredient(" \t CHICK EN \n")=="chicken"

@pytest.mark.parametrize("value",["내일 타조고기 쓰지 말아주세요.",{"event_type":"ingredient_restriction_event","ingredient":"타조고기","date":"2026-09-18","restriction":"do_not_use"}])
def test_unregistered_ingredient_never_guessed(bundle,value):
    report=run(bundle,value)
    assert report["status"]=="needs_clarification"
    event=user_events(report)[0]
    assert event["ingredient"]=="타조고기" and event["reason"]=="unregistered_ingredient"
    assert event["matched_sources"]==[]
    warning=report["validation_warnings"][0]
    assert warning["type"]=="unregistered_ingredient" and warning["ingredient"]=="타조고기"
    assert not report["substitute_candidates"]

@pytest.mark.parametrize("source",["inventory","recipe","weekly_menu"])
def test_registration_in_any_one_source_is_sufficient(bundle,source):
    name="등록전용재료"
    amount=IngredientAmount(ingredient=name,amount_per_serving=10,unit="g")
    if source=="inventory":
        bundle.inventory.inventory.append(InventoryLot(ingredient=name,current_stock=1,unit="kg",expiry_date="2026-09-30",unit_price=10,minimum_stock=0,planned_order=0,storage_type="cold"))
    elif source=="recipe":
        bundle.recipe.recipes["별도메뉴"]=Recipe(recipe_id="only",menu_name="별도메뉴",category="side",ingredients=[amount])
    else:
        bundle.inventory.menus.append(Menu(date="2026-09-18",meal_type="lunch",menu_name="별도메뉴",expected_max_diners=1,ingredients=[amount]))
    report=run(bundle,f"내일 {name} 쓰지 말아주세요.")
    event=user_events(report)[0]
    assert not event["needs_clarification"] and event["matched_sources"]==[source]

def test_alias_does_not_register_nonexistent_food():
    result=parse_event_result("내일 달걀 쓰지 말아주세요.",date(2026,9,17),IngredientRegistry({}, {"계란":["달걀"]}))
    assert result.status=="needs_clarification" and result.validation_warnings

def test_registered_name_ending_in_particle_is_not_trimmed():
    result=parse_event_result("내일 오이 쓰지 말아주세요.",date(2026,9,17),{"오이"})
    assert result.parsed_events[0].ingredient=="오이" and result.status=="ok"

@pytest.mark.parametrize("value",["",12,"2026-02-30 닭고기 쓰지 말아주세요."])
def test_parser_invalid_input_contract(value):
    result=parse_event_result(value,date(2026,9,17),{"닭고기"})
    assert result.status=="invalid_input" and result.errors

@pytest.fixture
def demo_copy(tmp_path):
    for filename in ("food_inventory.xlsx","weekly_menu.xlsx"):
        shutil.copyfile(DEMO_DIR/filename,tmp_path/filename)
    return tmp_path

def duplicate_row(directory,change=None):
    path=directory/"weekly_menu.xlsx"
    book=load_workbook(path)
    sheet=book["DEMO"]
    row=[c.value for c in sheet[2]]
    if change:
        headers=[c.value for c in sheet[1]]
        row[headers.index(change[0])]=change[1]
    sheet.append(row)
    book.save(path);book.close()
    return path

def test_duplicate_row_excluded_with_warning_and_original_unchanged(bundle,demo_copy):
    path=duplicate_row(demo_copy)
    before=path.read_bytes()
    baseline=run(bundle,None,"full")
    bundle.inventory=DemoInventoryAdapter(demo_copy)
    report=run(bundle,None,"full")
    assert report["inventory_status"]==baseline["inventory_status"]
    assert next(x for x in report["inventory_status"] if x["ingredient"]=="두부")["required_g"]==8000
    warning=next(w for w in report["validation_warnings"] if w["type"]=="duplicate_menu_rows")
    assert warning["duplicate_count"]==1 and warning["keys"][0]["ingredient"]=="두부"
    assert warning["rows"][0]["original_row"]==2 and warning["severity"]=="HIGH"
    assert any(a["type"]=="duplicate_menu_rows" for a in report["alerts"])
    assert path.read_bytes()==before

def test_same_menu_different_ingredients_retained(demo_copy):
    adapter=DemoInventoryAdapter(demo_copy)
    tofu=next(m for m in adapter.menus if m.menu_name=="두부조림")
    assert {i.ingredient for i in tofu.ingredients}=={"두부","간장"}
    assert not adapter.get_validation_warnings()

@pytest.mark.parametrize("field,value",[("date",date(2026,9,19)),("meal_type","breakfast"),("ingredient","새로운재료")])
def test_legitimate_repeated_menu_rows_not_duplicates(demo_copy,field,value):
    duplicate_row(demo_copy,(field,value))
    adapter=DemoInventoryAdapter(demo_copy)
    assert not adapter.get_validation_warnings()
    assert sum(len(m.ingredients) for m in adapter.menus)==11

@pytest.mark.parametrize("field,value",[("serving_amount",90),("expected_max_diners",200),("unit","kg")])
def test_conflicting_duplicate_is_error_not_silent_sum(demo_copy,field,value):
    path=duplicate_row(demo_copy,(field,value))
    with pytest.raises(DataQualityError) as error:DemoInventoryAdapter(demo_copy)
    assert error.value.detail.file==str(path) and error.value.detail.row==12

def test_target_group_not_silently_merged(demo_copy):
    path=demo_copy/"weekly_menu.xlsx"
    book=load_workbook(path);sheet=book["DEMO"]
    sheet.cell(1,sheet.max_column+1,"target_group")
    sheet.cell(2,sheet.max_column,"staff")
    book.save(path);book.close()
    with pytest.raises(DataQualityError) as error:DemoInventoryAdapter(demo_copy)
    assert error.value.detail.field=="target_group"

def test_duplicate_warning_survives_forecast_wrapper(bundle,demo_copy):
    from examples.forecast_wrapper import analyze_with_forecast
    duplicate_row(demo_copy);bundle.inventory=DemoInventoryAdapter(demo_copy)
    keys={(m.date.isoformat(),m.meal_type) for m in bundle.inventory.menus}
    forecast={"forecast_version":"v","input_snapshot_id":"s","rows":[dict(date=d,meal_type=m,expected_max_diners=100) for d,m in sorted(keys)]}
    report=analyze_with_forecast(bundle,{"as_of":"2026-09-17"},forecast)
    assert report["validation_warnings"][0]["type"]=="duplicate_menu_rows"

def test_compound_streamlit_integration():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"examples/streamlit_app.py"),default_timeout=20).run()
    app.selectbox[0].select("event")
    app.text_area[0].input("내일 손님 35명 추가하고 냉장고 청소도 해주세요.")
    app.button[0].click().run()
    assert not app.exception and any("일부 입력" in w.value for w in app.warning)

def test_compound_parent_graph_integration(bundle):
    from langgraph.graph import StateGraph,START,END
    from graph.inventory_risk_workflow import build_inventory_risk_subgraph,InventoryRiskState
    from config import RiskConfig
    parent=StateGraph(InventoryRiskState)
    parent.add_node("risk",build_inventory_risk_subgraph(bundle,RiskConfig()))
    parent.add_edge(START,"risk");parent.add_edge("risk",END)
    result=parent.compile().invoke({"request":{"as_of":"2026-09-17","mode":"event"},"user_event":"내일 손님 35명 추가하고 닭고기 쓰지 말아주세요."})["report"]
    assert len(user_events(result))==2 and result["status"]=="ok"
