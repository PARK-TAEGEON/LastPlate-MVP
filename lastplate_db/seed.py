"""Synthetic DEMO data, never eligible for default learning extraction."""
def seed_demo(repository):
    provenance = dict(source_type="DEMO", is_demo=True, record_status="VALIDATED")
    with repository.transaction():
        site = repository.create_site(site_name="라플 데모 구내식당", site_type="company",
            registered_population=600, meal_capacity=550, **provenance)
        sid = site["site_id"]
        prediction = repository.save_prediction(site_id=sid, target_date="2026-09-17",
            predicted_diners=487, lower_bound=469, upper_bound=507, model_version="demo-v1",
            available_population=580, predicted_rate=487 / 580, model_type="demo",
            applicability="demo_only", confidence="DEMO", input_snapshot_json={"demo": True},
            created_at="2026-09-17T00:00:00+00:00", **provenance)
        repository.save_operation_plan(site_id=sid, prediction_id=prediction["prediction_id"],
            target_date="2026-09-17", recommended_servings=523, safety_margin=0.03,
            created_at="2026-09-17T00:01:00+00:00", idempotency_key="demo-initial",
            ingredient_requirements_json=[{"ingredient": "쌀", "quantity": 50, "unit": "kg"}], **provenance)
        repository.save_actual_result(site_id=sid, target_date="2026-09-17", actual_diners=495,
            prepared_servings=523, unserved_leftover_kg=8.5, plate_waste_kg=12.1,
            ingredient_waste_kg=1.4, shortage=False, notes="DEMO synthetic data",
            created_at="2026-09-17T04:00:00+00:00", **provenance)
        repository.save_inventory_snapshot(site_id=sid, snapshot_date="2026-09-17",
            ingredient_name="쌀", quantity=80, unit="kg", lot_id="DEMO-LOT-1", source="DEMO", **provenance)
        model = repository._one("SELECT * FROM model_versions WHERE model_version='demo-v1'")
        if model is None:
            repository.save_model_version(model_version="demo-v1", model_type="demo", status="candidate",
                notes="DEMO only; not a trained model", **provenance)
        elif model["source_type"] != "DEMO" or not model["is_demo"]:
            from .models import ValidationError
            raise ValidationError("demo-v1 exists without DEMO provenance; use a separate demo database")
        repository.save_decision(site_id=sid, target_date="2026-09-17", decision_type="REVIEW",
            recommendation_json={"demo": True}, requires_human_approval=True, **provenance)
    return site
