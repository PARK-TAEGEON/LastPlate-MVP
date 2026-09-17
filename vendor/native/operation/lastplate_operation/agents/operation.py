"""Shared deterministic stages for the callable API and LangGraph subgraph."""
from decimal import Decimal, localcontext, DecimalException, Context
from fractions import Fraction
import json
from pydantic import ValidationError
from ..schemas.operation_input import OperationInput
from ..schemas.operation_output import OperationOutput
from ..tools.serving import calculate_servings
from ..tools.procurement import aggregate, purchase_details, ceil_fraction, review_order
from ..tools.unit_conversion import UnitError, assert_same_unit, normalize
from ..tools.constraints import check_constraints
from ..tools.evidence import assess_evidence


STATUS_RANK = {"ok": 0, "review": 1, "needs_clarification": 2, "invalid_input": 3}


def require_status(ctx, status):
    if STATUS_RANK[status] > STATUS_RANK[ctx.get("status_floor", "ok")]:
        ctx["status_floor"] = status


def add_trace(ctx, trace):
    trace_id = f"trace-{len(ctx['report']['decision_trace']) + 1:04d}"
    ctx["report"]["decision_trace"].append({**trace, "trace_id": trace_id})
    return trace_id


def alert(ctx, kind, message, severity="MEDIUM", evidence=None, *, trace_refs=None, **extra):
    ctx["report"]["alerts"].append(dict(type=kind, message=message, severity=severity,
        evidence={} if evidence is None else evidence,
        trace_refs=[] if trace_refs is None else list(trace_refs), **extra))


def initialize(payload):
    report = OperationOutput(status="ok").model_dump()
    ctx = {"report": report, "halt": False}
    try:
        data = OperationInput.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        missing_recipe = all(e["type"] == "missing" and e["loc"] and e["loc"][0] == "recipe_data" for e in errors)
        report["status"] = "needs_clarification" if missing_recipe else "invalid_input"
        for error in errors:
            alert(ctx, "MISSING_RECIPE" if missing_recipe else "INVALID_INPUT", error["msg"], "HIGH",
                  field=".".join(map(str, error["loc"])))
        ctx["halt"] = True
        return ctx
    ctx["data"] = data
    ctx["nutrition_evidence_valid"] = True
    report.update(data_mode=data.config.data_mode,
        policy=json.loads(json.dumps(data.config.model_dump(), default=float)),
        source=json.loads(json.dumps(data.demand_result.model_dump(), default=float)),
        provenance=data.config.provenance.model_dump(mode="json"))
    report["decision_trace"].append(dict(step="demand_source", inputs=report["source"], result="preserved"))
    maximum = data.config.maximum_input_servings
    values = [data.demand_result.prediction]
    if data.demand_result.prediction_interval:
        values += [data.demand_result.prediction_interval.lower, data.demand_result.prediction_interval.upper]
    if max(values) > maximum:
        report["status"] = "invalid_input"
        ctx["halt"] = True
        alert(ctx, "INPUT_DEMAND_OUT_OF_RANGE", "Demand가 설정된 입력 적용 범위를 초과했습니다.", "HIGH",
              evidence={"maximum_input_servings": maximum, "received_max": float(max(values))})
    if data.config.data_mode == "UNSPECIFIED":
        alert(ctx, "DATA_MODE_UNSPECIFIED", "입력 데이터의 DEMO/REAL 출처를 지정하세요.")
    return ctx


def evidence_stage(ctx):
    for issue in assess_evidence(ctx["data"]):
        status = issue.pop("status")
        invalid_nutrition = issue.pop("invalid_nutrition", False)
        if invalid_nutrition:
            ctx["nutrition_evidence_valid"] = False
        require_status(ctx, status)
        trace_id = add_trace(ctx, dict(step="evidence_check",
            inputs={"alert_type":issue["kind"], "evidence":issue["evidence"]},
            result={"status":status, "invalid_nutrition":invalid_nutrition}))
        alert(ctx, trace_refs=[trace_id], **issue)
    add_trace(ctx, dict(step="evidence_gate",
        inputs={"provenance": ctx["report"]["provenance"], "execution_mode": ctx["data"].config.execution_mode},
        result={"status_floor":ctx.get("status_floor", "ok"), "nutrition_evidence_valid":ctx["nutrition_evidence_valid"]}))


def validate_materials(ctx):
    data = ctx["data"]
    for row in data.inventory_data:
        if row.unit == "ea" and row.stock != row.stock.to_integral_value() and not data.config.fractional_ea_inventory:
            ctx["report"]["status"] = "invalid_input"
            ctx["halt"] = True
            alert(ctx, "FRACTIONAL_EA_INVENTORY", "분할 ea 재고는 명시적으로 허용해야 합니다.", "HIGH",
                  ingredient=row.ingredient, evidence={"stock":float(row.stock), "fractional_ea_inventory":False})
            return
    menus = {row.menu_name for row in data.recipe_data}
    if not data.recipe_data or set(data.config.required_menus) - menus:
        ctx["report"]["status"] = "needs_clarification"
        alert(ctx, "MISSING_RECIPE", "필수 메뉴의 레시피가 누락되었습니다.", "HIGH")
        ctx["halt"] = True
        return
    keys = [(r.menu_name, r.ingredient) for r in data.recipe_data]
    if len(keys) != len(set(keys)):
        ctx["report"]["status"] = "invalid_input"
        alert(ctx, "DUPLICATE_RECIPE", "동일 메뉴·식재료 행은 합쳐서 입력하세요.", "HIGH")
        ctx["halt"] = True
        return
    ctx["recipes"] = aggregate(data.recipe_data, "amount_per_serving")
    ctx["stocks"] = aggregate(data.inventory_data, "stock")
    ctx["orders"] = aggregate(data.planned_orders, "planned_order")
    for label, rows, field in [("recipe", data.recipe_data, "amount_per_serving"),
                               ("inventory", data.inventory_data, "stock"),
                               ("planned_order", data.planned_orders, "planned_order")]:
        for index, row in enumerate(rows):
            amount, unit = normalize(getattr(row, field), row.unit)
            ctx["report"]["decision_trace"].append(dict(step="unit_normalization",
                formula="canonical_amount = input_amount * unit_factor",
                inputs=dict(source=label, row=index, ingredient=row.ingredient,
                            amount=float(getattr(row, field)), unit=row.unit),
                result=dict(amount=float(amount), unit=unit)))
    # Validate all dimensions before emitting any actionable quantities.
    dimensions = {}
    for table in (ctx["recipes"], ctx["stocks"], ctx["orders"]):
        for name, (_, unit) in table.items():
            if name in dimensions:
                assert_same_unit(dimensions[name], unit, name)
            dimensions[name] = unit
    for name, amount in data.config.constraints.minimum_serving_amount.items():
        _, unit = normalize(amount.amount, amount.unit)
        if name in dimensions:
            assert_same_unit(dimensions[name], unit, name)
    unused_loss = set(data.config.trim_loss_pct) - set(ctx["recipes"])
    if unused_loss:
        alert(ctx, "UNUSED_TRIM_POLICY", "레시피에 없는 손실률 설정: " + ", ".join(sorted(unused_loss)))
    missing_stock = set(ctx["recipes"]) - set(ctx["stocks"])
    if missing_stock:
        ctx["report"]["status"] = "needs_clarification"
        alert(ctx, "MISSING_INVENTORY", "재고 미확인 품목은 stock=0과 구분합니다: " + ", ".join(sorted(missing_stock)), "HIGH")
        ctx["halt"] = True


def serving_stage(ctx):
    data, report = ctx["data"], ctx["report"]
    base, count, trace = calculate_servings(data.demand_result, data.config)
    report.update(predicted_diners=float(data.demand_result.prediction), base_demand=float(base),
        safety_margin_pct=float(data.config.safety_margin_pct), recommended_servings=count)
    trace["inputs"].update(capacity_servings=data.config.capacity_servings, planned_servings=data.config.planned_servings)
    serving_trace_id = add_trace(ctx, trace)
    capacity = data.config.capacity_servings
    report.update(required_servings=count, capacity_servings=capacity,
                  capacity_excess=max(0, count-capacity) if capacity is not None else None)
    if capacity is not None and count > capacity:
        require_status(ctx, "review")
        alert(ctx, "CAPACITY_EXCEEDED", "요구 조리량이 설비 capacity를 초과합니다. 요구량은 잘라내지 않았습니다.", "HIGH",
              evidence={"required_servings":count, "capacity_servings":capacity, "excess":count-capacity,
                        "minimum_servings":data.config.minimum_servings}, trace_refs=[serving_trace_id])
    elif capacity is None:
        alert(ctx, "CAPACITY_UNSPECIFIED", "설비 capacity가 제공되지 않았습니다.", evidence={"capacity_servings":None})
    planned = data.config.planned_servings
    if planned is not None and planned != count:
        kind = "UNDER_PREPARATION" if planned < count else "OVER_PREPARATION"
        alert(ctx, kind, f"예정 조리량 {planned}인분 / 권장 {count}인분", "HIGH" if planned < count else "MEDIUM", evidence={"planned_servings":planned,"required_servings":count}, trace_refs=[serving_trace_id])


def recipe_stage(ctx):
    ctx["required"] = {name: amount * ctx["report"]["recommended_servings"]
                       for name, (amount, _) in ctx["recipes"].items()}
    for name, (amount, unit) in sorted(ctx["recipes"].items()):
        ctx["report"]["decision_trace"].append(dict(step="recipe_requirement", formula="servings * per_serving",
            inputs=dict(ingredient=name, amount_per_serving=float(amount), unit=unit,
                        servings=ctx["report"]["recommended_servings"]), result=float(ctx["required"][name])))


def inventory_stage(ctx):
    policy, report = ctx["data"].config, ctx["report"]
    ctx["ranges"] = {}
    if policy.rounding_policy == "legacy_combined":
        alert(ctx, "LEGACY_ROUNDING_POLICY", "호환 정책: quantity_quantum을 조리와 구매에 함께 적용합니다.",
              evidence={"rounding_policy":"legacy_combined", "quantity_quantum":report["policy"]["quantity_quantum"]})
    for name, (_, unit) in sorted(ctx["recipes"].items()):
        required, stock = ctx["required"][name], ctx["stocks"][name][0]
        loss = policy.trim_loss_pct.get(name, Decimal(0))
        purchase_q = (policy.quantity_quantum if policy.rounding_policy == "legacy_combined" else policy.purchase_quantum)[unit]
        cooking_q = (policy.quantity_quantum[unit] if policy.rounding_policy == "legacy_combined" else
                     policy.cooking_quantum[unit] if policy.rounding_policy == "cooking_and_purchase" else None)
        raw, cooking, need, upper = purchase_details(required, stock, loss, cooking_q, purchase_q, policy.order_tolerance_pct)
        # Finite JSON numbers remain meaningful at the selected precision.
        outputs = [required, stock, cooking, need, upper]
        if any(abs(v) > 10**12 for v in outputs) or any(Decimal(str(float(v))) != v for v in (required, stock, need, upper)):
            ctx["halt"] = True
            report["status"] = "invalid_input"
            report["ingredient_requirements"] = []
            report["order_reviews"] = []
            alert(ctx, "OUTPUT_PRECISION_LIMIT", "계산 결과가 지원하는 JSON 수량 정밀도를 초과했습니다.", "HIGH", ingredient=name)
            return
        ctx["ranges"][name] = (need, upper, unit)
        row = dict(ingredient=name, edible_required=float(required), raw_required=float(raw),
            raw_required_exact={"numerator":str(raw.numerator), "denominator":str(raw.denominator)},
            cooking_required=float(cooking), cooking_extra=float(cooking-raw), rounding_policy=policy.rounding_policy,
            gross_required=float(required), trim_loss_pct=float(loss), adjusted_required=float(cooking),
            stock=float(stock), purchase_need=float(need), unit=unit, recommended_min=float(need), recommended_max=float(upper))
        report["ingredient_requirements"].append(row)
        inventory_trace_id = add_trace(ctx, dict(step="inventory_offset_and_range",
            formula="raw=edible/(1-loss/100); cooking=raw or ceil_c(raw); need=ceil_p(max(0,cooking-stock)); max=ceil_p(need*(1+tolerance/100))",
            inputs=dict(ingredient=name, edible_required=float(required), trim_loss_pct=float(loss), stock=float(stock),
                        cooking_quantum=float(cooking_q) if cooking_q else None, purchase_quantum=float(purchase_q),
                        tolerance_pct=float(policy.order_tolerance_pct), rounding_policy=policy.rounding_policy, unit=unit),
            result=row))
        if cooking > raw:
            purchase_without_cooking = ceil_fraction(max(0, raw-Fraction(stock)), purchase_q)
            alert(ctx, "COOKING_ROUNDING_EXTRA", "조리 계량 올림으로 보수적 추가량이 생겼습니다.", "INFO", ingredient=name,
                  evidence={"cooking_extra":float(cooking-raw), "extra_purchase":float(need-purchase_without_cooking),
                            "purchase_without_cooking_rounding":float(purchase_without_cooking), "unit":unit}, trace_refs=[inventory_trace_id])
        if stock < cooking:
            alert(ctx, "STOCK_SHORTAGE", "사용 가능 원물 재고만으로는 요구 조리량을 충족하지 못합니다.", ingredient=name,
                  evidence={"stock":float(stock), "raw_required":float(raw), "cooking_required":float(cooking), "unit":unit}, trace_refs=[inventory_trace_id])


def order_stage(ctx):
    report = ctx["report"]
    for name, (lower, upper, unit) in sorted(ctx["ranges"].items()):
        if name not in ctx["orders"]:
            alert(ctx, "MISSING_PLANNED_ORDER", "예정 발주량이 없어 검수하지 않았습니다. 미발주는 0을 명시하세요.", ingredient=name)
            if report["status"] == "ok":
                report["status"] = "needs_clarification"
            continue
        planned = ctx["orders"][name][0]
        status, difference = review_order(planned, lower, upper)
        row = dict(ingredient=name, planned_order=float(planned), recommended_min=float(lower),
                   recommended_max=float(upper), status=status, difference=float(difference), unit=unit)
        report["order_reviews"].append(row)
        order_trace_id = add_trace(ctx, dict(step="order_review", formula="UNDER if planned<min; OVER if planned>max; else OK",
                                              inputs=row, result=status))
        if status != "OK":
            alert(ctx, status + "_ORDER", "예정 발주량이 권장 범위를 벗어났습니다.",
                  "HIGH" if status == "UNDER" else "MEDIUM", ingredient=name, evidence=row, trace_refs=[order_trace_id])
    for name in sorted(set(ctx["orders"]) - set(ctx["recipes"])):
        alert(ctx, "UNMATCHED_ORDER", "레시피에 없는 발주 품목으로 범위 검수가 불가능합니다.", ingredient=name)
        if report["status"] == "ok":
            report["status"] = "needs_clarification"


def constraint_stage(ctx):
    report = ctx["report"]
    result = check_constraints(ctx["data"].config, ctx["recipes"])
    if not ctx["nutrition_evidence_valid"]:
        result["checks"].append({"constraint":"nutrition_provenance", "status":"UNKNOWN"})
        if result["status"] != "FAIL":
            result["status"] = "UNKNOWN"
    report["constraints"] = result
    constraint_trace_id = add_trace(ctx, dict(step="constraint_check", result=result))
    if result["status"] == "FAIL":
        alert(ctx, "HARD_CONSTRAINT_VIOLATION", "Hard Constraint 위반: 해당 계획은 실행 가능한 권고가 아닙니다.", "HIGH", evidence=result, trace_refs=[constraint_trace_id])
        report["status"] = "review"
    elif result["status"] == "UNKNOWN":
        alert(ctx, "MISSING_CONSTRAINT_EVIDENCE", "영양/알레르기/최소 제공량 검증에 필요한 근거가 없습니다.", "HIGH", evidence=result, trace_refs=[constraint_trace_id])
        report["status"] = "needs_clarification"
    elif result["status"] == "NOT_CONFIGURED":
        alert(ctx, "CONSTRAINTS_NOT_CONFIGURED", "영양 제약이 설정되지 않아 영양 적합성을 검증하지 않았습니다.", evidence=result, trace_refs=[constraint_trace_id])


STAGES = (evidence_stage, validate_materials, serving_stage, recipe_stage, inventory_stage, order_stage, constraint_stage)


def run_stage(ctx, stage):
    if ctx["halt"]:
        return ctx
    previous_status = ctx["report"]["status"]
    try:
        ctx["stage"] = stage.__name__
        with localcontext(Context(prec=50, Emin=-999, Emax=999)) as decimal_context:
            stage(ctx)
    except UnitError as exc:
        ctx["report"]["status"] = "invalid_input"
        alert(ctx, "UNIT_MISMATCH", str(exc), "HIGH")
        ctx["halt"] = True
    except DecimalException as exc:
        ctx["report"]["status"] = "invalid_input"
        ctx["report"]["ingredient_requirements"] = []
        ctx["report"]["order_reviews"] = []
        alert(ctx, "NUMERIC_ERROR", "지원 수치 연산을 완료할 수 없습니다.", "HIGH",
              evidence={"exception":type(exc).__name__, "stage":stage.__name__})
        ctx["halt"] = True
    ctx["report"]["status"] = max((previous_status, ctx["report"]["status"]), key=STATUS_RANK.get)
    return ctx


def build_report(ctx):
    report = ctx["report"]
    if report["status"] == "ok" and any(a["severity"] == "HIGH" for a in report["alerts"]):
        report["status"] = "review"
    report["status"] = max((report["status"], ctx.get("status_floor", "ok")), key=STATUS_RANK.get)
    for index, trace in enumerate(report["decision_trace"], 1):
        trace["trace_id"] = f"trace-{index:04d}"
    return OperationOutput.model_validate(report).model_dump(mode="json")


def generate_operation_plan(demand_result, recipe_data, inventory_data, planned_orders, config=None):
    ctx = initialize(dict(demand_result=demand_result, recipe_data=recipe_data,
        inventory_data=inventory_data, planned_orders=planned_orders, config={} if config is None else config))
    for stage in STAGES:
        run_stage(ctx, stage)
    return build_report(ctx)
