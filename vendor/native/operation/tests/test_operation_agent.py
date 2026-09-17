from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import pytest
from lastplate_operation import generate_operation_plan
from lastplate_operation.schemas.operation_output import OperationOutput
from lastplate_operation.graph.operation_workflow import build_operation_subgraph
from lastplate_operation.integration import to_inventory_forecast


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parents[1] / "examples/demo_input.json").read_text(encoding="utf-8"))


def run(p):
    result = generate_operation_plan(**p)
    OperationOutput.model_validate(result)
    json.dumps(result, allow_nan=False)
    assert result["requires_human_approval"] is True
    assert result["advisory_only"] is True
    return result


def pork(result):
    return next(r for r in result["ingredient_requirements"] if r["ingredient"] == "돼지고기")


def types(result):
    return {a["type"] for a in result["alerts"]}


def test_reference_arithmetic(payload):
    result = run(payload)
    assert result["recommended_servings"] == 523
    assert result["constraints"]["status"] == "PASS"
    row = pork(result)
    assert row["gross_required"] == 62760
    assert row["adjusted_required"] == 66064
    assert row["stock"] == 6000
    assert row["purchase_need"] == row["recommended_min"] == 60064
    assert row["recommended_max"] == 63068
    review = next(r for r in result["order_reviews"] if r["ingredient"] == "돼지고기")
    assert (review["status"], review["difference"]) == ("OVER", 41932)


@pytest.mark.parametrize("planned,status,difference", [(60063,"UNDER",1), (60064,"OK",0), (63068,"OK",0), (63069,"OVER",1)])
def test_order_boundaries(payload, planned, status, difference):
    payload["planned_orders"][0]["planned_order"] = planned
    result = run(payload)
    review = next(r for r in result["order_reviews"] if r["ingredient"] == "돼지고기")
    assert (review["status"], review["difference"]) == (status, difference)
    if status != "OK":
        assert status + "_ORDER" in types(result)


def test_excess_stock_zero_order(payload):
    payload["inventory_data"][0]["stock"] = 100
    payload["planned_orders"][0]["planned_order"] = 0
    row = pork(run(payload))
    assert row["purchase_need"] == row["recommended_min"] == row["recommended_max"] == 0


@pytest.mark.parametrize("recipe_unit,recipe_amount,stock_unit,stock_amount,canonical", [
    ("kg", .12, "g", 6000, "g"), ("g",120,"kg",6,"g"),
    ("l", .12,"ml",6000,"ml"), ("ml",120,"l",6,"ml"), ("ea",120,"ea",6000,"ea")])
def test_unit_normalization(payload, recipe_unit, recipe_amount, stock_unit, stock_amount, canonical):
    payload["recipe_data"][0].update(unit=recipe_unit, amount_per_serving=recipe_amount)
    payload["inventory_data"][0].update(unit=stock_unit, stock=stock_amount)
    payload["planned_orders"][0]["unit"] = canonical
    payload["config"]["constraints"] = {}
    row = pork(run(payload))
    assert row["unit"] == canonical and row["stock"] == 6000 and row["gross_required"] == 62760


@pytest.mark.parametrize("table,unit", [("recipe_data","bag"),("inventory_data","box"),("planned_orders","oz"),("inventory_data","ml"),("planned_orders","ea")])
def test_bad_units_fail_closed(payload, table, unit):
    payload[table][0]["unit"] = unit
    result = run(payload)
    assert result["status"] == "invalid_input" and "UNIT_MISMATCH" in types(result)
    assert not result["ingredient_requirements"] and result["recommended_servings"] is None


@pytest.mark.parametrize("field", ["ingredient", "amount_per_serving", "unit", "menu_name"])
def test_missing_recipe_fields(payload, field):
    del payload["recipe_data"][0][field]
    assert run(payload)["status"] == "needs_clarification"


def test_empty_and_missing_menu(payload):
    payload["config"]["required_menus"] = ["누락메뉴"]
    assert run(payload)["status"] == "needs_clarification"
    payload["recipe_data"] = []
    assert "MISSING_RECIPE" in types(run(payload))


@pytest.mark.parametrize("value", [-1, True, "487", float("nan"), float("inf"), None])
def test_invalid_prediction(payload, value):
    payload["demand_result"]["prediction"] = value
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("interval", [{"lower":508,"upper":507},{"lower":490,"upper":507},{"lower":0,"upper":400},{"upper":507}])
def test_invalid_interval(payload, interval):
    payload["demand_result"]["prediction_interval"] = interval
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("config", [
    {"safety_margin_pct":-1}, {"safety_margin_pct":True}, {"trim_loss_pct":{"돼지고기":100}},
    {"trim_loss_pct":{"돼지고기":-1}}, {"minimum_servings":1.5}, {"shortage_policy":"guess"},
    {"quantity_quantum":{"g":0,"ml":1,"ea":1}}, {"quantity_quantum":{"g":1}},
    {"quantity_quantum":{"g":1,"ml":1,"ea":.5}}, {"order_tolerance_pct":-1},
    {"unknown_setting":1}, {"constraints":{"calorie_range":[900,500]}},
    {"safety_margin_pct":101}, {"order_tolerance_pct":101}])
def test_invalid_config(payload, config):
    payload["config"].update(config)
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("field,value", [("stock",-1),("stock",True),("planned_order",-1),("amount_per_serving",0)])
def test_invalid_quantities(payload, field, value):
    table = {"stock":"inventory_data", "planned_order":"planned_orders", "amount_per_serving":"recipe_data"}[field]
    payload[table][0][field] = value
    assert run(payload)["status"] == "invalid_input"


def test_fallback_and_expected_policy(payload):
    payload["demand_result"].pop("prediction_interval")
    assert run(payload)["recommended_servings"] == 502
    payload["demand_result"]["prediction_interval"] = {"lower":469,"upper":507}
    payload["config"]["shortage_policy"] = "expected"
    assert run(payload)["recommended_servings"] == 502


def test_minimum_and_zero(payload):
    payload["config"]["minimum_servings"] = 600
    assert run(payload)["recommended_servings"] == 600
    payload["config"]["minimum_servings"] = 0
    payload["demand_result"] = {"prediction":0}
    assert run(payload)["recommended_servings"] == 0
    assert pork(run(payload))["purchase_need"] == 0


@pytest.mark.parametrize("nutrition", [{"protein":19},{"calories":499},{"calories":901},{"sodium":1501},{"allergens":["땅콩"]}])
def test_hard_constraints(payload, nutrition):
    payload["config"]["nutrition_per_serving"].update(nutrition)
    result = run(payload)
    assert result["constraints"]["status"] == "FAIL" and result["status"] == "review"
    assert "HARD_CONSTRAINT_VIOLATION" in types(result)


def test_minimum_portion_and_dimension(payload):
    payload["config"]["constraints"]["minimum_serving_amount"]["돼지고기"]["amount"] = 121
    assert run(payload)["constraints"]["status"] == "FAIL"
    payload["config"]["constraints"]["minimum_serving_amount"]["돼지고기"]["unit"] = "ml"
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("field", ["protein","calories","sodium","allergens"])
def test_missing_nutrition_is_unknown(payload, field):
    del payload["config"]["nutrition_per_serving"][field]
    result = run(payload)
    assert result["constraints"]["status"] == "UNKNOWN" and result["status"] == "needs_clarification"


def test_constraints_not_configured(payload):
    payload["config"]["constraints"] = {}
    assert run(payload)["constraints"]["status"] == "NOT_CONFIGURED"


def test_reforecast_only_no_double_delta(payload):
    old = run(payload)
    payload["demand_result"] = {"prediction":522,"prediction_interval":{"lower":504,"upper":542}}
    new = run(payload)
    assert new["recommended_servings"] == 559 > old["recommended_servings"]
    payload["demand_result"]["attendance_delta"] = 35
    assert run(payload)["status"] == "invalid_input"


def test_missing_inventory_not_zero(payload):
    payload["inventory_data"] = []
    result = run(payload)
    assert result["status"] == "needs_clarification" and not result["ingredient_requirements"]


def test_missing_order_not_zero(payload):
    payload["planned_orders"] = []
    result = run(payload)
    assert result["status"] == "needs_clarification" and not result["order_reviews"]
    assert "UNDER_ORDER" not in types(result)


def test_unknown_order(payload):
    payload["planned_orders"].append({"ingredient":"추가품목","planned_order":100,"unit":"g"})
    result = run(payload)
    assert result["status"] == "needs_clarification" and "UNMATCHED_ORDER" in types(result)


def test_duplicate_lots_orders_and_cross_menu_ingredient(payload):
    payload["inventory_data"].append({"ingredient":"돼지고기","stock":1,"unit":"kg"})
    payload["planned_orders"].append({"ingredient":"돼지고기","planned_order":1,"unit":"kg"})
    row = deepcopy(payload["recipe_data"][0]); row["menu_name"] = "두번째메뉴"
    payload["recipe_data"].append(row)
    result = run(payload)
    assert pork(result)["gross_required"] == 125520 and pork(result)["stock"] == 7000
    assert next(r for r in result["order_reviews"] if r["ingredient"] == "돼지고기")["planned_order"] == 106000
    payload["recipe_data"].append(row)
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("count,kind", [(500,"UNDER_PREPARATION"),(600,"OVER_PREPARATION")])
def test_preparation_alerts(payload, count, kind):
    payload["config"]["planned_servings"] = count
    assert kind in types(run(payload))


def test_determinism_no_mutation_and_context_independence(payload):
    before = deepcopy(payload)
    first = run(payload)
    with localcontext() as context:
        context.prec = 6
        assert run(payload) == first
    assert payload == before
    payload["config"] = first["policy"]
    payload["demand_result"] = first["source"]
    assert run(payload) == first


@pytest.mark.parametrize("fault", ["none","unit","recipe","nutrition","missing_evidence","under"])
def test_real_langgraph_matches_api(payload, fault):
    if fault == "unit": payload["inventory_data"][0]["unit"] = "ml"
    if fault == "recipe": payload["recipe_data"] = []
    if fault == "nutrition": payload["config"]["nutrition_per_serving"]["protein"] = 0
    if fault == "missing_evidence": payload["config"].pop("nutrition_per_serving")
    if fault == "under": payload["planned_orders"][0]["planned_order"] = 0
    before = deepcopy(payload)
    graph = build_operation_subgraph()
    state = graph.invoke({"payload":payload})
    assert state["operation_report"] == run(payload)
    assert state["route"] == state["operation_report"]["status"] and before == payload


def test_graph_invalid_input():
    state = build_operation_subgraph().invoke({"payload":{}})
    assert state["route"] == "invalid_input"


def test_bridge(payload):
    report = run(payload)
    meals = [{"date":"2026-09-17","meal_type":"lunch","operation_report":report}]
    kwargs = {"forecast_version":"operation-0.1.0","input_snapshot_id":"meal-1"}
    snapshot = to_inventory_forecast(meals, **kwargs)
    assert snapshot["rows"][0]["expected_max_diners"] == 523
    with pytest.raises(ValueError): to_inventory_forecast(meals + meals, **kwargs)
    report["constraints"]["status"] = "FAIL"
    with pytest.raises(ValueError): to_inventory_forecast(meals, **kwargs)


def test_monotonic_purchase_property(payload):
    for loss in [0, 5, 50, 99]:
        payload["config"]["trim_loss_pct"]["돼지고기"] = loss
        previous = None
        for stock in [0, 1, 6, 100, 10000]:
            payload["inventory_data"][0]["stock"] = stock
            row = pork(run(payload))
            assert 0 <= row["purchase_need"] <= row["recommended_max"]
            assert row["purchase_need"] + row["stock"] >= row["gross_required"] / (1 - loss / 100) - 1e-5
            if previous is not None: assert row["purchase_need"] <= previous
            previous = row["purchase_need"]


def test_streamlit_demo_and_invalid_json():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(Path(__file__).parents[1] / "examples/streamlit_app.py"), default_timeout=20).run()
    app.button[0].click().run()
    assert not app.exception and app.metric[1].value == "523"
    app.text_area[0].input("{broken").run()
    app.button[0].click().run()
    assert not app.exception and len(app.error) == 1


def test_configured_rounding_and_range(payload):
    payload["config"]["quantity_quantum"] = {"g":100,"ml":1,"ea":1}
    payload["config"]["order_tolerance_pct"] = 0
    row = pork(run(payload))
    assert row["adjusted_required"] == 66100
    assert row["purchase_need"] == row["recommended_max"] == 60100


def test_nutrition_exact_boundaries(payload):
    payload["config"]["nutrition_per_serving"].update(protein=20, calories=500, sodium=1500)
    assert run(payload)["constraints"]["status"] == "PASS"
    payload["config"]["nutrition_per_serving"]["calories"] = 900
    assert run(payload)["constraints"]["status"] == "PASS"


def test_conversion_evidence(payload):
    trace = run(payload)["decision_trace"]
    conversion = next(t for t in trace if t["step"] == "unit_normalization" and t["inputs"]["source"] == "inventory")
    assert conversion["inputs"]["amount"] == 6 and conversion["inputs"]["unit"] == "kg"
    assert conversion["result"] == {"amount":6000,"unit":"g"}


def test_invalid_error_contains_field(payload):
    payload["inventory_data"][0]["stock"] = "6"
    result = run(payload)
    assert result["alerts"][0]["field"] == "inventory_data.0.stock"


def test_json_schema_matches_numeric_contract():
    from lastplate_operation.schemas.operation_input import OperationInput
    schema = OperationInput.model_json_schema()
    amount = schema["$defs"]["RecipeRow"]["properties"]["amount_per_serving"]
    margin = schema["$defs"]["OperationPolicy"]["properties"]["safety_margin_pct"]
    assert amount["type"] == "number" and amount["exclusiveMinimum"] == 0
    assert margin["maximum"] == 100
