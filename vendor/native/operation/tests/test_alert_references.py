from copy import deepcopy
import json
from pathlib import Path
import pytest
from lastplate_operation import generate_operation_plan
from lastplate_operation.agents.operation import alert
from lastplate_operation.graph.operation_workflow import build_operation_subgraph


def payload():
    return json.loads((Path(__file__).parents[1]/"examples/demo_input.json").read_text(encoding="utf-8"))


def test_alert_without_evidence_does_not_invent_last_trace_reference():
    ctx={"report":{"alerts":[],"decision_trace":[{"trace_id":"trace-0001","step":"unrelated"}]}}
    alert(ctx,"MISSING_RECIPE","missing",ingredient="pork")
    assert ctx["report"]["alerts"][0]["trace_refs"] == []
    assert ctx["report"]["alerts"][0]["evidence"] == {}


@pytest.mark.parametrize("case,code,step",[
    ("recipe","MISSING_RECIPE",None),
    ("duplicate","DUPLICATE_RECIPE",None),
    ("missing_stock","MISSING_INVENTORY",None),
    ("missing_order","MISSING_PLANNED_ORDER",None),
    ("unknown_order","UNMATCHED_ORDER",None),
    ("unit","UNIT_MISMATCH",None),
    ("ood","DEMAND_OOD","evidence_check"),
    ("warning","DEMAND_WARNING","evidence_check"),
    ("operation","OPERATION_EVIDENCE_MISSING","evidence_check"),
    ("capacity","CAPACITY_EXCEEDED","serving_calculator"),
    ("prepare","UNDER_PREPARATION","serving_calculator"),
    ("over","OVER_ORDER","order_review"),
    ("under","UNDER_ORDER","order_review"),
    ("stock","STOCK_SHORTAGE","inventory_offset_and_range"),
    ("rounding","COOKING_ROUNDING_EXTRA","inventory_offset_and_range"),
    ("constraint","HARD_CONSTRAINT_VIOLATION","constraint_check"),
    ("nutrition","MISSING_CONSTRAINT_EVIDENCE","constraint_check"),
    ("no_rules","CONSTRAINTS_NOT_CONFIGURED","constraint_check"),
])
def test_alert_references_match_check_ingredient_and_evidence(case,code,step):
    data=payload()
    if case=="recipe": data["recipe_data"]=[]
    if case=="duplicate": data["recipe_data"].append(deepcopy(data["recipe_data"][0]))
    if case=="missing_stock": data["inventory_data"]=[]
    if case=="missing_order": data["planned_orders"]=[]
    if case=="unknown_order": data["planned_orders"].append(dict(ingredient="unknown",planned_order=1,unit="g"))
    if case=="unit": data["inventory_data"][0]["unit"]="ml"
    if case=="ood": data["demand_result"]["applicability"]["status"]="OOD"
    if case=="warning": data["demand_result"]["warnings"]=[dict(code="OOD1",category="OOD",severity="HIGH",message="OOD")]
    if case=="operation": data["config"]["execution_mode"]="operation"
    if case=="capacity": data["config"]["capacity_servings"]=500
    if case=="prepare": data["config"]["planned_servings"]=500
    if case=="under": data["planned_orders"][0]["planned_order"]=0
    if case=="constraint": data["config"]["nutrition_per_serving"]["protein"]=0
    if case=="nutrition": data["config"].pop("nutrition_per_serving")
    if case=="no_rules": data["config"]["constraints"]={}
    report=generate_operation_plan(**data)
    traces={t["trace_id"]:t for t in report["decision_trace"]}
    matches=[a for a in report["alerts"] if a["type"]==code]
    assert matches
    for item in matches:
        if step is None:
            assert item["trace_refs"]==[] and item["evidence"]=={}
            continue
        assert len(item["trace_refs"])==1
        trace=traces[item["trace_refs"][0]]
        assert trace["step"]==step
        if step=="evidence_check":
            assert trace["inputs"]["alert_type"]==code
            assert trace["inputs"]["evidence"]==item["evidence"]
        if step in {"order_review","inventory_offset_and_range"}:
            assert trace["inputs"]["ingredient"]==item["ingredient"]
            if step=="order_review": assert trace["inputs"]==item["evidence"]
            else:
                for key in ("stock","raw_required","cooking_required","cooking_extra","unit"):
                    if key in item["evidence"]: assert trace["result"][key]==item["evidence"][key]
        if step=="constraint_check": assert trace["result"]==item["evidence"]
        if step=="serving_calculator":
            assert trace["result"]==item["evidence"]["required_servings"]
    assert build_operation_subgraph().invoke({"payload":data})["operation_report"]==report
