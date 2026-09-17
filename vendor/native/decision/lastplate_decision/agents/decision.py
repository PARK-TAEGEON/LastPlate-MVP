"""Pure, deterministic recommendation; no I/O and no operational side effects."""
from lastplate_decision.config.decision_policy import DecisionPolicy, HARD_CONSTRAINTS
from lastplate_decision.schemas.decision_input import DecisionInput
from lastplate_decision.schemas.decision_output import Action, DecisionOutput
from lastplate_decision.schemas.decision_trace import TraceStep
from lastplate_decision.schemas.context import AnalysisScope, MenuScope, RecheckRequest, ScopeSelector
from lastplate_decision.evidence import selector, relation, evidence_issues
from lastplate_decision.quality import collect_quality, finalize_quality, quality_notes, confidence_assessment
from lastplate_decision.rechecks import request, reconcile, agent_name, fingerprint

ALERT_CONSTRAINT = {
    "shortage_risk": "shortage", "ingredient_shortage": "shortage", "expired_inventory": "expiry", "menu_conflict": "restriction", "expiry_expired": "expiry", "expired": "expiry",
    "allergy": "allergy", "nutrition_violation": "nutrition",
    "ingredient_restriction": "restriction", "supply_unavailable": "supply",
}


def make_final_recommendation(demand_result, operation_result, inventory_risk_result,
                              user_events=None, *, input_revision=None, policy=None, recheck_state=None, run_id=None, workflow_notes=None):
    """Accept upstream dicts; return JSON-compatible validated recommendation.

    Invalid structure raises pydantic.ValidationError; missing evidence produces
    NEEDS_CONFIRMATION. Events must be structured, not natural-language strings.
    """
    policy = policy or DecisionPolicy()
    events = [user_events] if isinstance(user_events, dict) else (user_events or [])
    payload = DecisionInput.model_validate(dict(
        demand_result=demand_result or {}, operation_result=operation_result or {},
        inventory_risk_result=inventory_risk_result or {}, user_events=events, input_revision=input_revision))
    d, o, r = payload.demand_result, payload.operation_result, payload.inventory_risk_result
    trace, notes, generated = [], [], []

    def log(source, rule, finding, evidence=None, decision=None):
        trace.append(TraceStep(step=len(trace)+1, source=source, rule=rule,
                               finding=finding, evidence=evidence or {}, decision=decision))

    def recheck(*names, reason="상위 결과 재검증", source_agent="decision", source_revision=None):
        for name in names:
            q = request(name, reason, payload, source_agent=source_agent, source_revision=source_revision, policy=policy)
            if q.request_id not in {v.request_id for v in generated}:
                generated.append(q)

    quality_records = collect_quality(payload.model_dump(mode="json"))
    issues = evidence_issues(payload, policy)
    for agent, code, note in issues:
        notes.append(note)
        recheck(agent, reason=code)
        log(agent, "provenance_gate", note)
    pending_attendance = False
    for e in payload.user_events:
        event_scope = selector(e)
        if (event_scope.target_date or event_scope.meal_type) and relation(event_scope, o.current_plan, o.current_plan, policy) == "unrelated":
            log("User", "event_out_of_scope", "현재 운영안 범위 밖 이벤트", e.model_dump())
            continue
        if e.needs_clarification:
            notes.append("사용자 이벤트 needs_clarification: " + str(e.event_id))
            recheck("user_confirmation", reason="event_clarification:" + str(e.event_id))
            continue
        if e.event_type == "attendance_event":
            applied = (e.event_id is not None and e.event_id in d.applied_event_ids
                       and e.event_id in o.applied_event_ids)
            if not applied:
                pending_attendance = True
                recheck("demand_forecast", "operation", reason="attendance:" + str(e.event_id))
            log("User", "attendance_event", "인원 변경 반영 확인", e.model_dump(),
                "이미 반영됨" if applied else "예측·운영 재실행 필요")
        elif e.event_type in {"expiry_event", "price_event", "supply_event", "ingredient_restriction_event", "inventory_shortage_event"}:
            # The parent workflow routes these events before decision. Standalone calls
            # need an explicit upstream acknowledgement to avoid accepting stale evidence.
            applied_ids = r.applied_event_ids
            if not e.event_id or e.event_id not in applied_ids:
                recheck("inventory_risk", reason="event:" + str(e.event_id))
            if e.event_type != "expiry_event" and (
                not e.event_id or e.event_id not in o.applied_event_ids
            ):
                recheck("operation", reason="event:" + str(e.event_id))
        else:
            notes.append(f"지원하지 않는 이벤트: {e.event_type}; 운영자 확인 필요")
            recheck("unknown_event")
    if r.status != "ok":
        recheck("inventory_risk")
    for item in r.recommended_rechecks:
        if isinstance(item, str):
            name = agent_name(item)
            recheck(name, reason="upstream_request:" + name, source_agent="inventory_risk",
                    source_revision=r.provenance.result_revision)
        else:
            generated.append(item.model_copy(update={"agent":agent_name(item.agent), "status":"pending", "result_revision":None}))
            if item.input_revision != payload.input_revision:
                recheck("inventory_risk", reason="upstream_request_revision_mismatch")
            name = agent_name(item.agent)
        if name == "demand_forecast":
            recheck("operation", reason="demand_dependency", source_agent="inventory_risk",
                    source_revision=r.provenance.result_revision)
    previous = [RecheckRequest.model_validate(x) for x in (recheck_state or [])]
    rechecks, history = reconcile(generated, previous, payload, policy)
    log("Demand Forecast", "upstream_prediction", "상위 Agent 예측 보존", d.model_dump())
    log("Operation Agent", "upstream_servings", "상위 Agent 조리량 보존", o.model_dump())
    log("Inventory & Risk", "upstream_report", "위험 보고서 및 원본 trace 보존", r.model_dump())

    def evaluate(checks, ingredient=None, menu=None, candidate_id=None, days=None, scope=None):
        values = checks.model_dump()
        # Evaluate the selected service against all scoped evidence, not a null menu.
        if candidate_id is None and ingredient is None and menu is None:
            target = o.current_plan
        else:
            target = AnalysisScope(target_date=(scope.target_date if scope else None) or o.current_plan.target_date,
                meal_type=(scope.meal_type if scope else None) or o.current_plan.meal_type,
                menus=[MenuScope(menu=menu or "unknown", ingredients=[ingredient] if ingredient else [],
                                 ingredients_complete=ingredient is not None)],
                menus_complete=menu is not None, coverage="full")
        for event in payload.user_events:
            if event.event_type != "ingredient_restriction_event":
                continue
            match = relation(selector(event), target, o.current_plan, policy, candidate_id)
            if match == "matched":
                values["restriction"] = "FAIL"
            elif match == "unknown" and values["restriction"] != "FAIL":
                values["restriction"] = "UNKNOWN"
        if days is not None and days < 0:
            values["expiry"] = "FAIL"
        if o.nutrition_constraints.status == "FAIL" and (candidate_id is None or days is not None):
            values["nutrition"] = "FAIL"
        elif candidate_id is None and values["nutrition"] == "UNKNOWN":
            values["nutrition"] = o.nutrition_constraints.status
        for result in r.nutrition_results:
            match = relation(selector(result), target, r.provenance.analysis_scope, policy, candidate_id)
            if match == "matched" and (result.status == "FAIL" or values["nutrition"] != "FAIL"):
                values["nutrition"] = result.status
            elif match == "unknown" and result.status != "PASS" and values["nutrition"] != "FAIL":
                values["nutrition"] = "UNKNOWN"
        for risk in r.supply_risks:
            match = relation(selector(risk), target, r.provenance.analysis_scope, policy, candidate_id)
            if risk.unavailable and match != "unrelated" and values["supply"] != "FAIL":
                values["supply"] = "FAIL" if match == "matched" else "UNKNOWN"
        for alert in r.alerts:
            constraint = ALERT_CONSTRAINT.get(alert.type)
            if not constraint:
                continue
            match = relation(selector(alert), target, r.provenance.analysis_scope, policy, candidate_id)
            if match == "matched":
                values[constraint] = "FAIL"
            elif match == "unknown" and values[constraint] != "FAIL":
                values[constraint] = "UNKNOWN"
            log("Inventory & Risk", "scope_match", f"{alert.type}: {match}",
                {"selector":selector(alert).model_dump(), "target":target.model_dump(), "candidate_id":candidate_id})
        failed = [k for k in HARD_CONSTRAINTS if values[k] == "FAIL"]
        unknown = [k for k in HARD_CONSTRAINTS if values[k] == "UNKNOWN"]
        return failed, unknown

    def action(action_id, checks, text, reason, desired="ADJUST", **fields):
        target_scope = fields.get("target_scope")
        fields["scope"] = {
            "target_date": (target_scope.target_date if target_scope else None) or o.current_plan.target_date,
            "meal_type": (target_scope.meal_type if target_scope else None) or o.current_plan.meal_type,
            "menu": fields.get("menu"), "ingredient": fields.get("ingredient")}
        failed, unknown = evaluate(checks, fields.get("ingredient"), fields.get("menu"),
                                   fields.get("candidate_id"), fields.pop("days", None), fields.pop("target_scope", None))
        decision = "BLOCK" if failed else "NEEDS_CONFIRMATION" if unknown else desired
        detail = reason
        if failed:
            detail += "; Hard Constraint 위반: " + ", ".join(failed)
        if unknown:
            detail += "; 검증 누락: " + ", ".join(unknown)
        result = Action(action_id=action_id, decision=decision, action=text, reason=detail,
                        failed_constraints=failed, unknown_constraints=unknown, **fields)
        log("Decision", "hard_constraint_gate", detail, result.model_dump(), decision)
        return result

    serving = action("servings", o.constraints, "상위 Operation 조리량 유지 검토",
                     "Demand·Operation 결과와 제약 검증", desired="KEEP")
    extra_fail = []
    if d.prediction is not None and o.recommended_servings is not None and o.recommended_servings < d.prediction:
        extra_fail.append("shortage")
    if o.shortage_probability is not None and o.shortage_probability > policy.max_shortage_probability:
        extra_fail.append("shortage")
    if extra_fail:
        serving.decision = "BLOCK"
        serving.failed_constraints = sorted(set(serving.failed_constraints + extra_fail))
        serving.reason += "; 예측 식수 또는 허용 부족확률 기준 위반"
        recheck("operation")
    if d.prediction is None or o.recommended_servings is None:
        if serving.decision != "BLOCK":
            serving.decision = "NEEDS_CONFIRMATION"
        serving.reason += "; 필수 예측·조리량 누락"
        if d.prediction is None:
            recheck("demand_forecast")
        recheck("operation")
    if pending_attendance or rechecks or r.status != "ok":
        if serving.decision != "BLOCK":
            serving.decision = "NEEDS_CONFIRMATION"
        serving.reason += "; 상위 결과 갱신/확인 필요"
    rechecks, history = reconcile(generated, previous, payload, policy)
    if rechecks and serving.decision != "BLOCK":
        serving.decision = "NEEDS_CONFIRMATION"
    servings = o.recommended_servings if serving.decision == "KEEP" else None
    log("Decision", "serving_resolution", serving.reason, serving.model_dump(), serving.decision)

    procurement = []
    for index, order in enumerate(o.order_recommendations):
        desired = "ADJUST" if order.status in {"OVER", "UNDER"} else "KEEP"
        item = action(f"order-{index}", order.constraints, "발주 범위 검토",
                      "Operation 제공 범위를 그대로 사용", desired=desired,
                      ingredient=order.ingredient, menu=order.menu, target_scope=order.scope, current_plan=order.planned_order, unit=order.unit)
        if None in (order.planned_order, order.recommended_min, order.recommended_max, order.unit) or order.status == "UNKNOWN":
            if item.decision != "BLOCK":
                item.decision = "NEEDS_CONFIRMATION"
            item.reason += "; 발주 수량·단위·상태 확인 필요"
        elif item.decision in {"KEEP", "ADJUST"}:
            actual_status = ("OVER" if order.planned_order > order.recommended_max else
                             "UNDER" if order.planned_order < order.recommended_min else "OK")
            if actual_status != order.status:
                item.decision = "NEEDS_CONFIRMATION"
                item.reason += "; 발주 상태와 수량 범위 불일치"
            else:
                item.recommended = {"min": order.recommended_min, "max": order.recommended_max}
        procurement.append(item)

    inventory, candidates, menus = [], [], []
    for candidate in r.inventory_recommendations:
        item = action(f"inventory-{candidate.candidate_id}", candidate.constraints,
                      "기존 재고 우선 사용 검토", candidate.reason,
                      ingredient=candidate.ingredient, menu=candidate.menu,
                      candidate_id=candidate.candidate_id, days=candidate.days_to_expiry,
                      unit=candidate.unit, target_scope=candidate.scope)
        if candidate.quantity is None or candidate.unit is None or candidate.days_to_expiry is None:
            if item.decision != "BLOCK":
                item.decision = "NEEDS_CONFIRMATION"
            item.reason += "; 수량·단위·사용일 기준 유통기한 확인 필요"
        if item.decision == "ADJUST":
            item.recommended = {"quantity": candidate.quantity}
        inventory.append(item)
    for index, alert in enumerate(r.alerts):
        if alert.type == "expiry_risk" and not any(
            alert.ingredient and policy.normalize(c.ingredient) == policy.normalize(alert.ingredient)
            for c in r.inventory_recommendations
        ):
            inventory.append(Action(action_id=f"expiry-alert-{index}", ingredient=alert.ingredient,
                decision="NEEDS_CONFIRMATION", action="기존 재고 우선 사용 가능 여부 확인",
                reason=alert.message + "; 구조화된 수량·사용일·영양·안전 검증 필요"))

    ranked = sorted(r.substitute_candidates,
                    key=lambda c: tuple(-c.soft_scores.get(k, 0) for k in policy.priorities) + (c.candidate_id,))
    for candidate in ranked:
        candidates.append(action(f"candidate-{candidate.candidate_id}", candidate.constraints,
                          "대체 후보 검토", candidate.reason, desired="REVIEW",
                          ingredient=candidate.ingredient, menu=candidate.candidate_menu or candidate.menu,
                          candidate_id=candidate.candidate_id, target_scope=candidate.scope))
    log("Decision", "soft_objective_order", "검증 통과 후보만 메뉴 검토에 포함; 제공 점수의 사전식 순위",
        {"priorities": list(policy.priorities), "ranked": [c.candidate_id for c in ranked],
         "cost_impacts": r.cost_impacts})
    cards = {}
    for risk in r.price_risks + r.supply_risks:
        impacts = []
        for entry in risk.affected_menus:
            impacts.append({"menu_name":entry} if isinstance(entry,str) else entry)
        for entry in r.affected_menus:
            if isinstance(entry,dict) and policy.normalize(entry.get("ingredient") or entry.get("affected_ingredient") or "") == policy.normalize(risk.ingredient):
                impacts.append(entry)
        if not impacts:
            # Derive only from a complete, explicit ingredient membership; no global fan-out.
            impacts = [{"menu_name":m.menu} for m in o.current_plan.menus if risk.ingredient in m.ingredients]
        for impact in impacts:
            menu = impact.get("menu_name") or impact.get("menu")
            if not menu:
                continue
            day = impact.get("date") or risk.scope.target_date or o.current_plan.target_date
            meal = impact.get("meal_type") or risk.scope.meal_type or o.current_plan.meal_type
            key = (day, meal, menu)
            eligible = []
            for c, evaluated in ((c, next(a for a in candidates if a.candidate_id == c.candidate_id)) for c in ranked):
                same_scope = (not c.scope.target_date or c.scope.target_date == day) and (not c.scope.meal_type or c.scope.meal_type == meal)
                linked = (c.menu == menu and (c.kind == "menu_substitution" or c.replaces is not None and policy.normalize(c.replaces) == policy.normalize(risk.ingredient)))
                if same_scope and linked and evaluated.decision == "REVIEW":
                    eligible.append(c.candidate_id)
            existing = risk.inventory_sufficient is True and not risk.unavailable
            reason = risk.message + ("; 재고 충분: 기존 재고·신규 발주 축소 검토" if existing else "; 영양·안전 검증 후 운영자 판단")
            if key not in cards:
                cards[key] = Action(action_id="menu-"+fingerprint(key), menu=menu, decision="REVIEW",
                    action="영향 메뉴·대체 후보 검토", reason=reason,
                    scope={"target_date":day,"meal_type":meal,"menu":menu}, candidates=eligible)
            else:
                if reason not in cards[key].reason:
                    cards[key].reason += "; " + reason
                cards[key].candidates = list(dict.fromkeys(cards[key].candidates + eligible))
    menus = list(cards.values())

    # Stale/partial reports must not leave executable-looking numerical adjustments.
    if rechecks or r.status != "ok":
        for item in procurement + inventory + candidates:
            if item.decision in {"ADJUST", "KEEP", "REVIEW"}:
                item.decision = "NEEDS_CONFIRMATION"
                item.recommended = None
                item.reason += "; 상위 결과 갱신 필요"
        for item in menus:
            item.candidates = []
    all_actions = [serving] + procurement + inventory + menus + candidates
    critical = [dict(a.model_dump(), scope_relation=relation(selector(a), o.current_plan, r.provenance.analysis_scope, policy))
                for a in r.alerts if a.severity in {"HIGH", "CRITICAL"}]
    for risk in r.supply_risks:
        if risk.severity in {"HIGH", "CRITICAL"} or risk.unavailable:
            critical.append(dict(type="supply_risk", severity=risk.severity, scope_relation=relation(selector(risk), o.current_plan, r.provenance.analysis_scope, policy), **risk.model_dump(exclude={"severity"})))
    for item in all_actions:
        if item.failed_constraints:
            critical.append(dict(type="constraint_violation", severity="HIGH", action_id=item.action_id,
                                 message=item.reason, constraints=item.failed_constraints, candidate_id=item.candidate_id))
    critical.sort(key=lambda a: (0 if a.get("type") in ALERT_CONSTRAINT or a.get("type") == "constraint_violation" else 1,
                                 0 if a.get("severity") == "CRITICAL" else 1))
    # The approval covers the current safe plan plus explicitly selected valid actions.
    # Rejected/unknown independent alternatives remain visible but are not selected.
    serving.selected = True
    for item in procurement + inventory:
        match = relation(ScopeSelector.model_validate(item.scope), o.current_plan, o.current_plan, policy)
        item.selected = item.decision in {"KEEP", "ADJUST"} and match == "matched"
    selected = [a for a in all_actions if a.selected]
    blocked = any(a.decision == "BLOCK" for a in selected)
    uncertain = any(a.decision == "NEEDS_CONFIRMATION" for a in selected) or bool(issues) or bool(rechecks) or r.status != "ok"
    status = "blocked" if blocked else "needs_confirmation" if uncertain else "ok"
    excluded = [f"input.inventory_risk_result.substitute_candidates[{i}]" for i,_ in enumerate(r.substitute_candidates)]
    for group,rows in (("alerts",r.alerts),("nutrition_results",r.nutrition_results),("price_risks",r.price_risks),("supply_risks",r.supply_risks)):
        for i,row in enumerate(rows):
            if relation(selector(row),o.current_plan,r.provenance.analysis_scope,policy)=="unrelated":
                excluded.append(f"input.inventory_risk_result.{group}[{i}]")
    for i,item in enumerate(inventory[:len(r.inventory_recommendations)]):
        if not item.selected:excluded.append(f"input.inventory_risk_result.inventory_recommendations[{i}]")
    for note in notes:
        quality_records.append(dict(kind="VALIDATION",message=note,path="decision",warning=True,affects_confidence=True))
    quality_records=finalize_quality(quality_records,excluded,workflow_notes or [])
    confidence,reasons,confidence_evidence=confidence_assessment(status,selected,critical,quality_records)
    notes=quality_notes(quality_records)
    if any(q['kind'] in {'DEMO','SIMULATION'} and q['warning'] and q['affects_confidence'] for q in quality_records):
        for item in all_actions:
            item.action = "[DEMO 검토용] " + item.action
    for item in all_actions:
        log("Decision", "final_action", item.reason, item.model_dump(), item.decision)
    log("Human Approval", "approval_required", "권고만 반환; 발주·메뉴·재고 실행 기능 없음")
    revision = "rec-" + fingerprint({"input":payload.model_dump(mode="json"), "policy":policy.model_dump(mode="json"),
                                    "rechecks":[q.model_dump() for q in history], "workflow_notes":workflow_notes or []})
    return DecisionOutput(run_id=run_id, recommendation_revision=revision,
        selected_action_ids=[a.action_id for a in selected],
        rejected_candidate_ids=[a.candidate_id for a in candidates + inventory if a.decision == "BLOCK" and a.candidate_id],
        recheck_history=history,
        upstream_traces={"demand_forecast": d.model_extra.get("decision_trace", []),
                         "operation": o.model_extra.get("decision_trace", []),
                         "inventory_risk": r.decision_trace},
        status=status,
        provenance_notes=list(dict.fromkeys(q['message'] for q in quality_records if not q['warning'])),
        source_provenance=[q for q in quality_records if q['kind'] in {'REAL','DEMO','SIMULATION','UNKNOWN','INFO'}],
        quality_records=quality_records, confidence_evidence=confidence_evidence,
        critical_alerts=critical, recommended_servings=servings, serving_action=serving,
        procurement_actions=procurement, inventory_actions=inventory, menu_actions=menus,
        candidate_evaluations=candidates, confidence=confidence, confidence_reasons=reasons,
        recommended_rechecks=rechecks, decision_trace=trace,
        data_quality_notes=list(dict.fromkeys(notes))).model_dump(mode="json")

