"""Contract checks only: no eligibility inference, nutrition estimation or remote calls."""


def assess_evidence(data):
    issues = []
    demand, config = data.demand_result, data.config

    def add(kind, status, message, evidence, invalid_nutrition=False, severity="HIGH"):
        issues.append(dict(kind=kind, status=status, message=message, evidence=evidence,
                           invalid_nutrition=invalid_nutrition, severity=severity))

    applicability = demand.applicability.status
    if applicability in {"OOD", "NOT_APPLICABLE"}:
        add("DEMAND_OOD" if applicability == "OOD" else "DEMAND_NOT_APPLICABLE", "review",
            "Demand 적용 가능성 검토가 필요합니다.", demand.applicability.model_dump())
    elif applicability == "UNKNOWN":
        add("DEMAND_EVIDENCE_UNKNOWN", "needs_clarification", "Demand 적용 가능성 근거가 미확인입니다.",
            demand.applicability.model_dump())
    if demand.operational_eligible is False:
        add("DEMAND_NOT_APPLICABLE", "review", "Demand가 operational_eligible=false를 반환했습니다.",
            {"operational_eligible":False, "availability_status":demand.availability_status})
    if demand.availability_status == "historical_unknown":
        add("DEMAND_EVIDENCE_UNKNOWN", "needs_clarification", "Demand 가용성 근거가 historical_unknown입니다.",
            {"availability_status":demand.availability_status})
    for warning in demand.warnings:
        status = "needs_clarification" if warning.category == "EVIDENCE_UNKNOWN" else (
            "review" if warning.category in {"OOD", "NOT_APPLICABLE"} or warning.severity == "HIGH" else "ok")
        add("DEMAND_WARNING", status, warning.message, warning.model_dump(), severity=warning.severity)

    refs = config.provenance
    supplied = {name: getattr(refs, name) for name in ("recipe", "nutrition", "inventory", "policy") if getattr(refs, name)}
    meal_ids = {ref.meal_id for ref in supplied.values()}
    if len(meal_ids) > 1:
        add("PROVENANCE_MISMATCH", "needs_clarification", "데이터 근거의 meal_id가 서로 다릅니다.",
            {name:ref.meal_id for name, ref in supplied.items()}, invalid_nutrition=True)
    if refs.nutrition:
        valid = refs.recipe and refs.nutrition.recipe_version == refs.recipe.version and (
            refs.nutrition.recipe_snapshot_id == refs.recipe.snapshot_id)
        if not valid:
            add("NUTRITION_VERSION_MISMATCH", "needs_clarification", "영양 근거가 레시피 버전/스냅샷과 일치하지 않습니다.",
                {"recipe":refs.recipe.model_dump() if refs.recipe else None, "nutrition":refs.nutrition.model_dump()},
                invalid_nutrition=True)

    if config.execution_mode == "operation":
        missing = []
        if not config.policy_acknowledged:
            missing.append("policy_acknowledged=true")
        if config.capacity_servings is None:
            missing.append("capacity_servings")
        missing += ["provenance." + name for name in ("recipe", "nutrition", "inventory", "policy") if not getattr(refs, name)]
        rules = config.constraints
        for name in ("minimum_protein", "calorie_range", "sodium_max", "allergy_restriction"):
            if getattr(rules, name) is None:
                missing.append("constraints." + name)
        if not rules.minimum_serving_amount:
            missing.append("constraints.minimum_serving_amount")
        nutrition = config.nutrition_per_serving
        for name in ("protein", "calories", "sodium", "allergens"):
            if nutrition is None or getattr(nutrition, name) is None:
                missing.append("nutrition_per_serving." + name)
        if demand.model_version is None:
            missing.append("demand_result.model_version")
        if demand.input_snapshot_id is None:
            missing.append("demand_result.input_snapshot_id")
        if missing:
            add("OPERATION_EVIDENCE_MISSING", "needs_clarification", "운영 모드 필수 정책·근거를 보완해야 합니다.",
                {"missing":missing, "data_mode":config.data_mode, "real_label_is_certification":False},
                invalid_nutrition=any("nutrition" in name or "constraints" in name for name in missing))
    return issues
