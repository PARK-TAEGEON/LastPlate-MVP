from copy import deepcopy
from pathlib import Path
import shutil
import pytest
from openpyxl import load_workbook, Workbook
from adapters.bundle import AdapterBundle
from adapters.local import DEMO_DIR
from adapters.recipe_adapter import DemoRecipeAdapter
from adapters.nutrition_adapter import DemoNutritionAdapter
from adapters.price_trend_adapter import DemoPriceTrendAdapter
from adapters.monthly_price_adapter import DemoMonthlyPriceAdapter
from adapters.supply_risk_adapter import DemoSupplyRiskAdapter
from adapters.inventory_adapter import DemoInventoryAdapter
from schemas.errors import DataQualityError
from schemas.risk_report import RiskReport
from examples.forecast_wrapper import analyze_with_forecast
from examples.streamlit_app import validated_analysis

CSV_ADAPTERS=[
    (DemoRecipeAdapter,"demo_recipe_ingredients.csv"),
    (DemoNutritionAdapter,"demo_nutrition.csv"),
    (DemoPriceTrendAdapter,"demo_price_trend.csv"),
    (DemoMonthlyPriceAdapter,"demo_monthly_price.csv"),
    (DemoSupplyRiskAdapter,"demo_risk_events.csv"),
]

@pytest.mark.parametrize("factory,filename",CSV_ADAPTERS)
@pytest.mark.parametrize("fault",["empty","missing_column","corrupt","header_only"])
def test_csv_errors_have_file_row_field(tmp_path,factory,filename,fault):
    path=tmp_path/filename
    original=(DEMO_DIR/filename).read_text(encoding="utf-8-sig")
    values={"empty":"", "missing_column":"unexpected\nvalue\n", "corrupt":"\"unterminated", "header_only":original.splitlines()[0]+"\n"}
    path.write_text(values[fault],encoding="utf-8")
    with pytest.raises(DataQualityError) as error:factory(path)
    detail=error.value.detail
    assert detail.code=="data_quality_error" and detail.file==str(path)
    assert detail.row>=1 and detail.field

def test_csv_invalid_number_preserves_exact_location(tmp_path):
    path=tmp_path/"prices.csv"
    text=(DEMO_DIR/"demo_price_trend.csv").read_text(encoding="utf-8-sig")
    lines=text.splitlines()
    row=lines[1].split(",");row[2]="not-a-number";lines[1]=",".join(row)
    path.write_text("\n".join(lines),encoding="utf-8")
    with pytest.raises(DataQualityError) as error:DemoPriceTrendAdapter(path)
    assert error.value.detail.row==2 and error.value.detail.field=="current_price"

@pytest.mark.parametrize("factory,filename,field",[
    (DemoRecipeAdapter,"demo_recipe_ingredients.csv","amount_per_serving"),
    (DemoNutritionAdapter,"demo_nutrition.csv","protein"),
    (DemoMonthlyPriceAdapter,"demo_monthly_price.csv","average_price"),
    (DemoSupplyRiskAdapter,"demo_risk_events.csv","date"),
])
def test_other_csv_field_errors_preserve_exact_location(tmp_path,factory,filename,field):
    import csv,io
    rows=list(csv.reader(io.StringIO((DEMO_DIR/filename).read_text(encoding="utf-8-sig"))))
    rows[1][rows[0].index(field)]="invalid"
    path=tmp_path/filename
    with path.open("w",encoding="utf-8",newline="") as stream:csv.writer(stream).writerows(rows)
    with pytest.raises(DataQualityError) as error:factory(path)
    assert error.value.detail.row==2 and error.value.detail.field==field

@pytest.mark.parametrize("filename",["food_inventory.xlsx","weekly_menu.xlsx"])
@pytest.mark.parametrize("fault",["empty","missing_column","corrupt","header_only","bad_value","missing_sheet"])
def test_excel_errors_have_file_row_field(tmp_path,filename,fault):
    for name in ("food_inventory.xlsx","weekly_menu.xlsx"):
        shutil.copyfile(DEMO_DIR/name,tmp_path/name)
    path=tmp_path/filename
    if fault=="empty":path.write_bytes(b"")
    elif fault=="corrupt":path.write_bytes(b"not an XLSX archive")
    else:
        # Deliberately malformed test fixtures, not user-facing workbook authoring.
        book=load_workbook(path)
        sheet=book["DEMO"]
        if fault=="missing_column":sheet.cell(1,1,"wrong_column")
        elif fault=="missing_sheet":sheet.title="wrong_sheet"
        elif fault=="header_only":sheet.delete_rows(2,sheet.max_row)
        elif fault=="bad_value":sheet.cell(2,2 if filename=="food_inventory.xlsx" else 5,"not-a-number")
        book.save(path);book.close()
    with pytest.raises(DataQualityError) as error:DemoInventoryAdapter(tmp_path)
    detail=error.value.detail
    assert detail.file==str(path) and detail.row>=1 and detail.field
    if fault=="bad_value":
        assert detail.row==2
        assert detail.field==("current_stock" if filename=="food_inventory.xlsx" else "serving_amount")

def test_ui_adapter_failure_never_falls_back_to_demo(tmp_path):
    def broken():return DemoInventoryAdapter(tmp_path)
    report=validated_analysis({"as_of":"2026-09-17"},adapter_factory=broken)
    assert report["status"]=="error"
    assert not report["inventory_status"] and not report["substitute_candidates"]
    assert report["errors"][0]["file"].endswith("food_inventory.xlsx")
    assert report["data_sources"]=={}
    RiskReport.model_validate(report)

def forecast_for(bundle):
    keys={(m.date.isoformat(),m.meal_type) for m in bundle.inventory.menus}
    return {"forecast_version":"test-forecast-v2","input_snapshot_id":"input-42",
            "rows":[dict(date=d,meal_type=m,expected_max_diners=135) for d,m in sorted(keys)]}

def test_forecast_injection_changes_analysis_not_original_menu():
    bundle=AdapterBundle.demo()
    before=deepcopy(bundle.inventory.menus)
    report=analyze_with_forecast(bundle,{"as_of":"2026-09-17"},forecast_for(bundle))
    assert report["status"]=="ok"
    eggs=next(x for x in report["inventory_status"] if x["ingredient"]=="계란")
    assert eggs["required_g"]==20250
    assert report["forecast_version"]=="test-forecast-v2" and report["input_snapshot_id"]=="input-42"
    assert bundle.inventory.menus==before
    assert "forecast=test-forecast-v2" in report["data_sources"]["weekly_menu"]

@pytest.mark.parametrize("fault",["missing_meal","duplicate_meal","bool_count","negative_count"])
def test_forecast_wrapper_rejects_bad_inputs(fault):
    bundle=AdapterBundle.demo()
    forecast=forecast_for(bundle)
    if fault=="missing_meal":forecast["rows"].pop()
    elif fault=="duplicate_meal":forecast["rows"].append(forecast["rows"][0])
    elif fault=="bool_count":forecast["rows"][0]["expected_max_diners"]=True
    else:forecast["rows"][0]["expected_max_diners"]=-1
    report=analyze_with_forecast(bundle,{"as_of":"2026-09-17"},forecast)
    assert report["status"]=="error" and report["errors"]
    RiskReport.model_validate(report)

def test_streamlit_boundary_invalid_date():
    report=validated_analysis({"as_of":"2026-02-30"})
    assert report["status"]=="error" and report["errors"][0]["field"]=="as_of"

@pytest.mark.parametrize("case",["normal","clarification","invalid"])
def test_streamlit_actual_app(case):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"examples"/"streamlit_app.py"),default_timeout=20).run()
    assert not app.exception
    assert "DEMO / SIMULATION" in app.warning[0].value
    if case=="clarification":
        app.selectbox[0].select("event")
        app.text_area[0].input("내일 사람이 좀 많이 올 것 같아요.")
    elif case=="invalid":
        app.text_input[0].input("2026-02-30")
    app.button[0].click().run()
    assert not app.exception
    if case=="invalid":assert len(app.error)==1
    if case=="clarification":assert any("차단" in warning.value for warning in app.warning)
