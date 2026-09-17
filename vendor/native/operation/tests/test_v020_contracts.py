from copy import deepcopy
from decimal import Decimal, Overflow, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import pytest
from lastplate_operation import generate_operation_plan
from lastplate_operation.graph.operation_workflow import build_operation_subgraph
from lastplate_operation.schemas.operation_input import OperationInput
from lastplate_operation.schemas.operation_output import OperationOutput
from lastplate_operation.schemas.operation_trace import Alert, AlertType
from lastplate_operation.integration import to_inventory_forecast


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parents[1]/"examples/demo_input.json").read_text(encoding="utf-8"))


def run(payload):
    result = generate_operation_plan(**payload)
    OperationOutput.model_validate(result)
    json.dumps(result, allow_nan=False)
    assert result["advisory_only"] and result["requires_human_approval"]
    return result


def pork(report):
    return next(row for row in report["ingredient_requirements"] if row["ingredient"] == "돼지고기")


def codes(report):
    return {a["type"] for a in report["alerts"]}


def operational(payload):
    config = payload["config"]
    config.update(execution_mode="operation", policy_acknowledged=True, capacity_servings=1000)
    refs = {name:dict(source="DEMO:"+name, version=name+"-v1", snapshot_id=name+"-001", meal_id="meal-001")
            for name in ("recipe", "inventory", "nutrition", "policy")}
    refs["nutrition"].update(recipe_version="recipe-v1", recipe_snapshot_id="recipe-001")
    config["provenance"] = refs
    return payload


@pytest.mark.parametrize("state,expected,code", [("IN_DOMAIN","ok",None), ("OOD","review","DEMAND_OOD"),
    ("NOT_APPLICABLE","review","DEMAND_NOT_APPLICABLE"), ("UNKNOWN","needs_clarification","DEMAND_EVIDENCE_UNKNOWN")])
def test_applicability(payload, state, expected, code):
    payload["demand_result"]["applicability"] = {"status":state,"reasons":["test reason"]}
    result = run(payload)
    assert result["status"] == expected
    assert result["source"]["applicability"] == payload["demand_result"]["applicability"]
    source_trace = next(t for t in result["decision_trace"] if t["step"] == "demand_source")
    for key in ("applicability","model_version","input_snapshot_id"):
        assert source_trace["inputs"][key] == payload["demand_result"][key]
    if code: assert code in codes(result)


@pytest.mark.parametrize("category,severity,expected", [("OOD","INFO","review"),
    ("NOT_APPLICABLE","MEDIUM","review"), ("EVIDENCE_UNKNOWN","INFO","needs_clarification"),
    ("OTHER","HIGH","review"), ("OTHER","INFO","ok")])
def test_warnings_retained(payload, category, severity, expected):
    warning = dict(code="UPSTREAM-123", category=category, severity=severity, message="upstream message")
    payload["demand_result"]["warnings"] = [warning]
    result = run(payload)
    assert result["status"] == expected and result["source"]["warnings"] == [warning]
    assert next(a for a in result["alerts"] if a["type"] == "DEMAND_WARNING")["evidence"] == warning


def test_native_demand_receipt_names(payload):
    native = dict(prediction_id="native-id", created_at="2026-09-17T00:00:00+09:00", target_date="2026-09-18",
        deadline_at="2026-09-17T18:00:00+09:00", timezone="Asia/Seoul", mode="operation",
        input_data={"staff":100}, availability=[{"field":"staff","source":"declared"}], weather=None,
        policy={"deadline_hour":18}, operational_eligible=True, availability_status="validated_declared_receipts")
    payload["demand_result"].update(native)
    result = run(payload)
    for name, value in native.items(): assert result["source"][name] == value
    payload["demand_result"]["operational_eligible"] = False
    assert "DEMAND_NOT_APPLICABLE" in codes(run(payload))
    payload["demand_result"]["availability_status"] = "historical_unknown"
    assert run(payload)["status"] == "needs_clarification"


def test_unknown_contract_is_not_silently_dropped(payload):
    payload["demand_result"]["warnings"] = [{"unrecognized":"cannot discard"}]
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("prediction,capacity,minimum,required,excess", [
    (0,0,0,0,0),(500,500,0,500,0),(501,500,0,501,1),(0,500,600,600,100)])
def test_capacity(payload, prediction, capacity, minimum, required, excess):
    payload["demand_result"].update(prediction=prediction, prediction_interval=None)
    payload["config"].update(safety_margin_pct=0, capacity_servings=capacity, minimum_servings=minimum)
    result = run(payload)
    assert result["required_servings"] == result["recommended_servings"] == required
    assert result["capacity_servings"] == capacity and result["capacity_excess"] == excess
    if excess:
        assert result["status"] == "review" and "CAPACITY_EXCEEDED" in codes(result)
    else:
        assert "CAPACITY_EXCEEDED" not in codes(result)


def test_capacity_includes_margin(payload):
    payload["config"]["capacity_servings"] = 507
    result = run(payload)
    assert result["required_servings"] == 523 and result["capacity_excess"] == 16


@pytest.mark.parametrize("prediction,maximum,expected", [(100000,100000,"review"),(100001,100000,"invalid_input"),
    (1000001,1000000,"invalid_input"),(10**12,1000000,"invalid_input")])
def test_demand_range(payload, prediction, maximum, expected):
    payload["demand_result"].update(prediction=prediction, prediction_interval=None)
    payload["config"]["maximum_input_servings"] = maximum
    assert run(payload)["status"] == expected


def test_purchase_only_sufficient_inventory(payload):
    payload["inventory_data"][0]["stock"] = 66.0632
    payload["config"].update(rounding_policy="purchase_only", purchase_quantum={"g":100,"ml":1,"ea":1})
    row = pork(run(payload))
    assert row["purchase_need"] == row["recommended_max"] == row["cooking_extra"] == 0
    assert row["raw_required"] < row["stock"]
    exact = row["raw_required_exact"]
    assert Fraction(int(exact["numerator"]),int(exact["denominator"])) == Fraction(6276000,95)


def test_explicit_cooking_rounding_conservative_extra(payload):
    payload["inventory_data"][0]["stock"] = 66.0632
    payload["config"].update(rounding_policy="cooking_and_purchase", cooking_quantum={"g":100,"ml":1,"ea":.5},
        purchase_quantum={"g":100,"ml":1,"ea":1})
    result = run(payload); row = pork(result)
    assert row["purchase_need"] == 100 and row["cooking_required"] == 66100
    assert row["cooking_extra"] == pytest.approx(36.84210526315789)
    alert = next(a for a in result["alerts"] if a["type"] == "COOKING_ROUNDING_EXTRA" and a["ingredient"] == "돼지고기")
    assert alert["evidence"]["extra_purchase"] == 100


@pytest.mark.parametrize("rounding", ["legacy_combined","purchase_only","cooking_and_purchase"])
def test_normal_fixture_unchanged_across_rounding(payload, rounding):
    payload["config"]["rounding_policy"] = rounding
    if rounding != "legacy_combined": payload["config"]["purchase_quantum"] = {"g":1,"ml":1,"ea":1}
    if rounding == "cooking_and_purchase": payload["config"]["cooking_quantum"] = {"g":1,"ml":1,"ea":1}
    row = pork(run(payload))
    assert row["edible_required"] == row["gross_required"] == 62760
    assert row["purchase_need"] == 60064 and row["recommended_max"] == 63068
    assert row["adjusted_required"] == row["cooking_required"]


def ea_payload(payload):
    payload["recipe_data"] = [{"menu_name":"egg","ingredient":"egg","amount_per_serving":.5,"unit":"ea"}]
    payload["inventory_data"] = [{"ingredient":"egg","stock":0,"unit":"ea"}]
    payload["planned_orders"] = [{"ingredient":"egg","planned_order":1,"unit":"ea"}]
    payload["demand_result"].update(prediction=1, prediction_interval=None)
    payload["config"].update(safety_margin_pct=0, constraints={}, trim_loss_pct={})
    return payload


def test_fractional_recipe_whole_order(payload):
    result = run(ea_payload(payload))
    assert result["ingredient_requirements"][0]["edible_required"] == .5
    assert result["ingredient_requirements"][0]["purchase_need"] == 1
    payload["planned_orders"][0]["planned_order"] = 1.5
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("allowed,expected", [(False,"invalid_input"),(True,"ok")])
def test_fractional_ea_stock_policy(payload, allowed, expected):
    ea_payload(payload)
    payload["inventory_data"][0]["stock"] = .5
    payload["config"]["fractional_ea_inventory"] = allowed
    assert run(payload)["status"] == expected


@pytest.mark.parametrize("quantum", [Decimal("1e-1000000"),1e-300,.0001,0,Decimal("0.1234567"),1000001])
def test_quantum_numeric_limits(payload, quantum):
    payload["config"]["quantity_quantum"] = {"g":quantum,"ml":1,"ea":1}
    assert run(payload)["status"] == "invalid_input"


@pytest.mark.parametrize("value", [Decimal("1.1234567"),Decimal("999999999.1234567"),10**9+1,Decimal("1e-1000000")])
def test_precision_inputs_rejected(payload, value):
    payload["inventory_data"][0]["stock"] = value
    assert run(payload)["status"] == "invalid_input"


def test_supported_precision_json_roundtrip(payload):
    payload["inventory_data"][0]["stock"] = Decimal("66.0632")
    payload["config"]["quantity_quantum"] = {"g":.001,"ml":.001,"ea":1}
    model = OperationInput.model_validate(payload)
    assert OperationInput.model_validate_json(model.model_dump_json()) == model
    result = run(payload)
    assert result["policy"]["quantity_quantum"]["g"] == .001
    with localcontext() as ctx:
        ctx.prec=6;ctx.Emin=-6;ctx.Emax=6
        assert run(payload) == result


def test_arithmetic_failure_structured_and_bug_not_hidden(payload, monkeypatch):
    from lastplate_operation.agents import operation
    def overflow(*args): raise Overflow("test decimal error")
    monkeypatch.setattr(operation,"purchase_details",overflow)
    result=run(payload)
    assert result["status"] == "invalid_input" and "NUMERIC_ERROR" in codes(result)
    assert result["ingredient_requirements"] == result["order_reviews"] == []
    def programming_error(*args): raise TypeError("programming error")
    monkeypatch.setattr(operation,"purchase_details",programming_error)
    with pytest.raises(TypeError, match="programming error"): run(payload)


def test_output_range_fails_structurally(payload):
    payload["recipe_data"][0]["amount_per_serving"] = 10**9
    payload["recipe_data"][0]["unit"] = "kg"
    result = run(payload)
    assert result["status"] == "invalid_input" and "OUTPUT_PRECISION_LIMIT" in codes(result)
    assert result["ingredient_requirements"] == []


@pytest.mark.parametrize("field", ["recipe_version","recipe_snapshot_id","meal_id"])
def test_nutrition_version_mismatch(payload, field):
    operational(payload)
    payload["config"]["provenance"]["nutrition"][field] = "wrong"
    result = run(payload)
    assert result["status"] == "needs_clarification" and result["constraints"]["status"] == "UNKNOWN"


def test_operating_mode_complete_evidence(payload):
    result = run(operational(payload))
    assert result["status"] == "ok" and result["constraints"]["status"] == "PASS"
    assert result["provenance"] == payload["config"]["provenance"]


@pytest.mark.parametrize("missing", ["capacity_servings","policy_acknowledged","recipe","nutrition","inventory","policy",
    "minimum_protein","calorie_range","sodium_max","allergy_restriction","minimum_serving_amount"])
def test_operational_requirements(payload, missing):
    operational(payload); config = payload["config"]
    if missing in config["provenance"]: config["provenance"].pop(missing)
    elif missing in config["constraints"]: config["constraints"].pop(missing)
    else: config.pop(missing)
    config["data_mode"] = "REAL"
    result = run(payload)
    assert result["status"] == "needs_clarification" and "OPERATION_EVIDENCE_MISSING" in codes(result)


def test_real_label_not_operating_authorization(payload):
    payload["config"].update(data_mode="REAL",execution_mode="operation")
    result=run(payload)
    assert result["status"] == "needs_clarification"
    assert result["advisory_only"] and result["requires_human_approval"]


def test_alert_enum_evidence_and_trace_references(payload):
    result=run(payload)
    ids={t["trace_id"] for t in result["decision_trace"]}
    for alert in result["alerts"]:
        assert AlertType(alert["type"]) and alert["evidence"]
        assert set(alert["trace_refs"]) <= ids
    order=next(a for a in result["alerts"] if a["type"] == "OVER_ORDER")
    assert order["evidence"]["difference"] == 41932
    with pytest.raises(ValueError): Alert(type="free text",severity="HIGH",message="bad")


@pytest.mark.parametrize("fault", ["ood","capacity","purchase","ea","precision","nutrition","operating","warning"])
def test_new_graph_paths_identical(payload, fault):
    if fault=="ood": payload["demand_result"]["applicability"]["status"]="OOD"
    if fault=="capacity": payload["config"]["capacity_servings"]=500
    if fault=="purchase":
        payload["inventory_data"][0]["stock"]=66.0632
        payload["config"].update(rounding_policy="purchase_only",purchase_quantum={"g":100,"ml":1,"ea":1})
    if fault=="ea": ea_payload(payload);payload["planned_orders"][0]["planned_order"]=1.5
    if fault=="precision": payload["config"]["quantity_quantum"]={"g":Decimal("1e-1000000"),"ml":1,"ea":1}
    if fault=="nutrition": operational(payload);payload["config"]["provenance"]["nutrition"]["recipe_version"]="wrong"
    if fault=="operating": payload["config"]["execution_mode"]="operation"
    if fault=="warning": payload["demand_result"]["warnings"]=[dict(code="OOD",category="OOD",severity="HIGH",message="OOD")]
    before=deepcopy(payload)
    graph=build_operation_subgraph().invoke({"payload":payload})
    assert graph["operation_report"]==run(payload) and before==payload
    assert graph["route"]==graph["operation_report"]["status"]


@pytest.mark.parametrize("bad", [None,[],"invalid"])
def test_graph_malformed_payload(bad):
    assert build_operation_subgraph().invoke({"payload":bad})["route"]=="invalid_input"


def test_bridge_is_not_final_approval(payload):
    payload["config"]["capacity_servings"]=500
    report=run(payload)
    result=to_inventory_forecast([dict(date="2026-09-17",meal_type="lunch",operation_report=report)],
                                forecast_version="operation-0.2.0",input_snapshot_id="test")
    assert result["rows"][0]["expected_max_diners"]==523
    assert report["status"]=="review" and report["requires_human_approval"]


def test_json_parser_preserves_precision_until_validation(payload):
    from lastplate_operation.tools.json_input import load_operation_json
    text=json.dumps(payload)
    text=text.replace('"stock": 6', '"stock": 6.000000000000000001', 1)
    parsed=load_operation_json(text)
    assert parsed["inventory_data"][0]["stock"] == Decimal("6.000000000000000001")
    assert run(parsed)["status"] == "invalid_input"
    for bad in ('{"prediction":NaN}', '[1]', '{broken'):
        with pytest.raises(ValueError): load_operation_json(bad)


def test_full_decision_transport_keeps_warnings_and_risk_history(payload):
    from lastplate_operation.integration import to_decision_payload
    payload["demand_result"]["applicability"]["status"]="OOD"
    report=run(payload)
    risk={"events":[{"type":"restriction","superseded":True},{"type":"release"}]}
    envelope=to_decision_payload(report,risk)
    assert envelope["operation_report"] == report and envelope["inventory_risk_report"] == risk
    envelope["inventory_risk_report"]["events"].clear()
    assert len(risk["events"]) == 2


def test_schema_includes_numeric_quantum_and_alias_contract():
    schema=OperationInput.model_json_schema()
    quantum=schema["$defs"]["OperationPolicy"]["properties"]["quantity_quantum"]["additionalProperties"]
    assert quantum["minimum"] == .001 and quantum["maximum"] == 1000000
    requirement=OperationOutput.model_json_schema()["$defs"]["Requirement"]["properties"]
    assert requirement["gross_required"]["deprecated"] is True
    assert requirement["adjusted_required"]["deprecated"] is True


def test_native_json_decimal_metadata(payload):
    from lastplate_operation.tools.json_input import load_operation_json
    payload["demand_result"].update(input_data={"staff":487.0},weather={"temperature":-12.5})
    result=run(load_operation_json(json.dumps(payload)))
    assert result["source"]["input_data"] == {"staff":487.0}
    assert result["source"]["weather"] == {"temperature":-12.5}
    payload["demand_result"]["weather"]["temperature"] = float("nan")
    assert run(payload)["status"] == "invalid_input"


def test_generated_contracts_and_demo_are_current():
    from jsonschema import Draft202012Validator
    root=Path(__file__).parents[1]
    for name,model in (("operation_input",OperationInput),("operation_output",OperationOutput)):
        schema=json.loads((root/"contracts"/(name+".schema.json")).read_text(encoding="utf-8"))
        assert schema==model.model_json_schema()
        Draft202012Validator.check_schema(schema)
    for prefix in ("demo","purchase_only","cooking_and_purchase"):
        from lastplate_operation.tools.json_input import load_operation_json
        data=load_operation_json((root/"examples"/(prefix+"_input.json")).read_text(encoding="utf-8"))
        output=json.loads((root/"examples"/(prefix+"_output.json")).read_text(encoding="utf-8"))
        assert output==generate_operation_plan(**data)


def test_later_constraint_failure_does_not_erase_missing_order(payload):
    payload["planned_orders"] = []
    payload["config"]["nutrition_per_serving"]["protein"] = 0
    result = run(payload)
    assert result["status"] == "needs_clarification"
    assert result["constraints"]["status"] == "FAIL"
    assert {"MISSING_PLANNED_ORDER", "HARD_CONSTRAINT_VIOLATION"} <= codes(result)
    assert build_operation_subgraph().invoke({"payload":payload})["operation_report"] == result
