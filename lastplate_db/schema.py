"""Version 5 schema. Package v0.3.0 uses database user_version=5."""
SCHEMA_VERSION = 5
SOURCE_TYPES = ("UNKNOWN", "MODEL", "DEMO", "USER_UPLOAD", "PUBLIC_API", "MANUAL", "AGENT")
RECORD_STATUSES = ("UNVALIDATED", "VALIDATED", "INVALID")


def current_model_forbidden_sql(alias):
    return (f"{alias}.status='current' AND ({alias}.source_type='DEMO' "
            f"OR {alias}.is_demo=1 OR {alias}.record_status='INVALID')")


def inventory_source_conflict_sql(alias):
    sources = ",".join(repr(v) for v in SOURCE_TYPES)
    return (f"UPPER(TRIM({alias}.source)) IN ({sources}) "
            f"AND UPPER(TRIM({alias}.source)) != {alias}.source_type")


def policy_statements():
    """SQLite guards cover raw INSERT and UPDATE, including metadata-only updates."""
    for event in ("INSERT", "UPDATE"):
        for table, predicate, message in (
            ("model_versions", current_model_forbidden_sql("NEW"), "current model cannot be DEMO or INVALID"),
            ("inventory_snapshots", inventory_source_conflict_sql("NEW"), "inventory source/source_type contradiction"),
        ):
            yield (f"CREATE TRIGGER IF NOT EXISTS guard_{table}_{event.lower()} "
                   f"BEFORE {event} ON {table} WHEN {predicate} "
                   f"BEGIN SELECT RAISE(ABORT, '{message}'); END")
# kind: text, date, time, real, int, bool, json; ! means NOT NULL.
TABLES = {
    "sites": ("site_id", {
        "site_id": "text!", "site_name": "text!", "site_type": "text",
        "registered_population": "int", "meal_capacity": "int",
        "created_at": "time!", "updated_at": "time"}),
    "predictions": ("prediction_id", {
        "prediction_id": "text!", "site_id": "text!", "target_date": "date!",
        "predicted_diners": "real!", "lower_bound": "real", "upper_bound": "real",
        "predicted_rate": "real", "available_population": "real", "model_version": "text",
        "model_type": "text", "applicability": "text", "confidence": "text",
        "created_at": "time!", "request_id": "text", "input_snapshot_json": "json"}),
    "operation_plans": ("plan_id", {
        "plan_id": "text!", "prediction_id": "text!", "site_id": "text!", "target_date": "date!",
        "recommended_servings": "int!", "base_demand": "real", "safety_margin": "real",
        "status": "text", "ingredient_requirements_json": "json", "order_reviews_json": "json",
        "alerts_json": "json", "constraints_json": "json", "requires_human_approval": "bool!",
        "created_at": "time!"}),
    "actual_results": ("result_id", {
        "result_id": "text!", "site_id": "text!", "target_date": "date!",
        "actual_diners": "int!", "prepared_servings": "int", "unserved_leftover_kg": "real",
        "plate_waste_kg": "real", "ingredient_waste_kg": "real", "shortage": "bool!",
        "actual_food_cost": "real", "notes": "text", "created_at": "time!", "updated_at": "time"}),
    "inventory_snapshots": ("inventory_id", {
        "inventory_id": "text!", "site_id": "text!", "snapshot_date": "date!",
        "ingredient_name": "text!", "normalized_ingredient_name": "text", "quantity": "real!",
        "unit": "text!", "expiry_date": "date", "lot_id": "text", "source": "text", "created_at": "time!"}),
    "model_versions": ("model_version", {
        "model_version": "text!", "model_type": "text!", "trained_at": "time",
        "training_rows": "int", "validation_rows": "int", "validation_mae": "real",
        "validation_rmse": "real", "validation_mape": "real", "status": "text",
        "parent_version": "text", "notes": "text", "created_at": "time!"}),
    "decision_logs": ("decision_id", {
        "decision_id": "text!", "site_id": "text!", "target_date": "date!",
        "decision_type": "text", "recommendation_json": "json", "critical_alerts_json": "json",
        "confidence": "text", "requires_human_approval": "bool!", "approved": "bool",
        "approved_at": "time", "created_at": "time!"}),
}

# Uniform provenance also covers demo sites, inventory and model metadata.
for _, fields in TABLES.values():
    fields.update(source_type="text!", is_demo="bool!", record_status="text!")
TABLES["operation_plans"][1]["idempotency_key"] = "text"
TABLES["predictions"][1].update(feature_schema_version="text", observed_at="time",
                              source_lineage_id="text", snapshot_validation_json="json")


def provenance_columns():
    sources = ",".join(repr(v) for v in SOURCE_TYPES)
    statuses = ",".join(repr(v) for v in RECORD_STATUSES)
    return {
        "source_type": f"source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ({sources}))",
        "is_demo": "is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1)",
        "record_status": f"record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ({statuses}))",
    }


def schema_statements():
    for table, (pk, fields) in TABLES.items():
        columns = []
        for name, spec in fields.items():
            if name in provenance_columns():
                columns.append(provenance_columns()[name])
                continue
            kind = spec.rstrip("!")
            sql_type = {"int": "INTEGER", "bool": "INTEGER", "real": "REAL"}.get(kind, "TEXT")
            col = f"{name} {sql_type}"
            if spec.endswith("!"):
                col += " NOT NULL"
            if name == pk:
                col += " PRIMARY KEY"
            if kind in ("int", "real"):
                types = "'integer'" if kind == "int" else "'integer','real'"
                col += f" CHECK ({name} IS NULL OR (typeof({name}) IN ({types}) AND {name} >= 0 AND {name} <= 1.7976931348623157e308))"
            if kind == "bool":
                if name != "approved":
                    col += " DEFAULT " + ("0" if name == "shortage" else "1")
                col += f" CHECK ({name} IS NULL OR {name} IN (0,1))"
            columns.append(col)
        if table not in ("sites", "model_versions"):
            columns.append("FOREIGN KEY(site_id) REFERENCES sites(site_id)")
        if table == "predictions":
            columns += ["UNIQUE(request_id)", "UNIQUE(prediction_id, site_id, target_date)",
                        "CHECK(lower_bound IS NULL OR upper_bound IS NULL OR (lower_bound <= predicted_diners AND predicted_diners <= upper_bound))"]
        if table == "operation_plans":
            columns.append("UNIQUE(prediction_id, idempotency_key)")
            columns.append("FOREIGN KEY(prediction_id, site_id, target_date) REFERENCES predictions(prediction_id, site_id, target_date)")
        if table == "actual_results":
            columns.append("UNIQUE(site_id, target_date)")
        yield f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(columns)})"
    yield "CREATE UNIQUE INDEX IF NOT EXISTS one_current_model ON model_versions(status) WHERE status = 'current'"
    for table, cols in (("predictions", "site_id,target_date"), ("operation_plans", "prediction_id,created_at"),
                        ("inventory_snapshots", "site_id,snapshot_date"), ("decision_logs", "site_id,target_date")):
        yield f"CREATE INDEX IF NOT EXISTS ix_{table} ON {table}({cols})"
    yield from policy_statements()
    from .schema_v4 import v4_statements
    yield from v4_statements(TABLES["actual_results"][1])
    from .schema_v5 import v5_statements
    yield from v5_statements()


def initialize_schema(connection):
    from .migrations import migrate
    migrate(connection)
