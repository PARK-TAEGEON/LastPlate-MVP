"""Additive v4 contracts, deployment guards and automatic append-only correction log."""
CONTRACT_COLUMNS = {
    "feature_schema_version": "TEXT",
    "observed_at": "TEXT",
    "source_lineage_id": "TEXT",
    "snapshot_validation_json": "TEXT",
}


def v4_statements(actual_fields):
    from .schema import provenance_columns
    provenance = ",".join(provenance_columns().values())
    yield '''CREATE TABLE IF NOT EXISTS feature_schemas (
        feature_schema_version TEXT NOT NULL PRIMARY KEY,
        required_features_json TEXT NOT NULL CHECK(json_valid(required_features_json) AND json_type(required_features_json)='object'),
        description TEXT, created_at TEXT NOT NULL)'''
    yield f'''CREATE TABLE IF NOT EXISTS model_deployments (
        deployment_id TEXT NOT NULL PRIMARY KEY,
        site_id TEXT NOT NULL REFERENCES sites(site_id),
        model_version TEXT NOT NULL REFERENCES model_versions(model_version),
        model_role TEXT NOT NULL CHECK(length(trim(model_role))>0),
        status TEXT NOT NULL CHECK(status IN ('current','retired')),
        effective_at TEXT NOT NULL CHECK(effective_at GLOB '????-??-??T??:??:??.??????+00:00' AND julianday(effective_at) IS NOT NULL),
        retired_at TEXT CHECK(retired_at IS NULL OR (retired_at GLOB '????-??-??T??:??:??.??????+00:00' AND julianday(retired_at) IS NOT NULL)),
        created_at TEXT NOT NULL, actor TEXT NOT NULL CHECK(length(trim(actor))>0),
        reason TEXT NOT NULL CHECK(length(trim(reason))>0),
        audit_metadata_json TEXT CHECK(audit_metadata_json IS NULL OR json_valid(audit_metadata_json)),
        retired_by TEXT, retirement_reason TEXT,
        {provenance},
        CHECK(source_type!='DEMO' AND is_demo=0 AND record_status='VALIDATED'),
        CHECK((status='current' AND retired_at IS NULL AND retired_by IS NULL AND retirement_reason IS NULL)
           OR (status='retired' AND retired_at IS NOT NULL AND retired_at>=effective_at
               AND retired_by IS NOT NULL AND length(trim(retired_by))>0
               AND retirement_reason IS NOT NULL AND length(trim(retirement_reason))>0)))'''
    yield "CREATE UNIQUE INDEX IF NOT EXISTS one_site_role_deployment ON model_deployments(site_id,model_role) WHERE status='current'"
    yield "CREATE INDEX IF NOT EXISTS ix_deployment_history ON model_deployments(site_id,model_role,effective_at)"
    yield '''CREATE TRIGGER IF NOT EXISTS deployment_insert_guard BEFORE INSERT ON model_deployments
        BEGIN
          SELECT CASE WHEN EXISTS(SELECT 1 FROM model_deployments WHERE deployment_id=NEW.deployment_id)
            THEN RAISE(ABORT,'deployment history is immutable') END;
          SELECT CASE WHEN NEW.status!='current' THEN RAISE(ABORT,'insert a current deployment; retire explicitly') END;
          SELECT CASE WHEN substr(NEW.effective_at,1,19)>strftime('%Y-%m-%dT%H:%M:%S','now') THEN RAISE(ABORT,'future deployment scheduling unsupported') END;
          SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM sites WHERE site_id=NEW.site_id)
            THEN RAISE(ABORT,'deployment site does not exist') END;
          SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM model_versions WHERE model_version=NEW.model_version
            AND record_status='VALIDATED' AND is_demo=0 AND source_type!='DEMO' AND (status IS NULL OR status!='rejected'))
            THEN RAISE(ABORT,'deployment requires a VALIDATED non-DEMO non-rejected model') END;
          SELECT CASE WHEN EXISTS(SELECT 1 FROM model_deployments WHERE site_id=NEW.site_id AND model_role=NEW.model_role
            AND status='retired' AND retired_at>NEW.effective_at)
            THEN RAISE(ABORT,'deployment overlaps retired history') END;
        END'''
    immutable = ("deployment_id", "site_id", "model_version", "model_role", "effective_at", "created_at", "actor", "reason",
                 "audit_metadata_json", "source_type", "is_demo", "record_status")
    conditions = " OR ".join(f"NEW.{key} IS NOT OLD.{key}" for key in immutable)
    yield f'''CREATE TRIGGER IF NOT EXISTS deployment_update_guard BEFORE UPDATE ON model_deployments
        WHEN OLD.status!='current' OR NEW.status!='retired' OR substr(NEW.retired_at,1,19)>strftime('%Y-%m-%dT%H:%M:%S','now') OR {conditions}
        BEGIN SELECT RAISE(ABORT,'deployment history is immutable; only current to retired allowed'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS deployment_delete_guard BEFORE DELETE ON model_deployments
        BEGIN SELECT RAISE(ABORT,'deployment history is immutable'); END'''
    for event in ("INSERT", "UPDATE"):
        identity = "NEW.model_version" if event == "INSERT" else "OLD.model_version"
        invalid = "NEW.record_status!='VALIDATED' OR NEW.is_demo=1 OR NEW.source_type='DEMO' OR NEW.status='rejected'"
        if event == "UPDATE":
            invalid += " OR NEW.model_version IS NOT OLD.model_version"
        yield f'''CREATE TRIGGER IF NOT EXISTS deployed_model_{event.lower()}_guard BEFORE {event} ON model_versions
            WHEN EXISTS(SELECT 1 FROM model_deployments WHERE model_version={identity} AND status='current')
              AND ({invalid})
            BEGIN SELECT RAISE(ABORT,'cannot invalidate a currently deployed model'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS deployed_model_delete_guard BEFORE DELETE ON model_versions
        WHEN EXISTS(SELECT 1 FROM model_deployments WHERE model_version=OLD.model_version)
        BEGIN SELECT RAISE(ABORT,'model referenced by deployment history'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS deployed_model_replace_guard BEFORE INSERT ON model_versions
        WHEN EXISTS(SELECT 1 FROM model_versions WHERE model_version=NEW.model_version)
         AND EXISTS(SELECT 1 FROM model_deployments WHERE model_version=NEW.model_version)
        BEGIN SELECT RAISE(ABORT,'cannot replace a model referenced by deployment history'); END'''

    yield '''CREATE TABLE IF NOT EXISTS actual_correction_context (
        result_id TEXT NOT NULL PRIMARY KEY REFERENCES actual_results(result_id),
        actor TEXT NOT NULL CHECK(length(trim(actor))>0),
        source_type TEXT NOT NULL CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')),
        reason TEXT NOT NULL CHECK(length(trim(reason))>0))'''
    yield '''CREATE TABLE IF NOT EXISTS actual_corrections (
        correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_id TEXT NOT NULL UNIQUE,
        result_id TEXT NOT NULL REFERENCES actual_results(result_id),
        site_id TEXT NOT NULL, target_date TEXT NOT NULL,
        old_values_json TEXT NOT NULL CHECK(json_valid(old_values_json)),
        new_values_json TEXT NOT NULL CHECK(json_valid(new_values_json)),
        actor TEXT NOT NULL, source_type TEXT NOT NULL, reason TEXT NOT NULL,
        corrected_at TEXT NOT NULL)'''
    yield "CREATE INDEX IF NOT EXISTS ix_actual_corrections ON actual_corrections(result_id,correction_id)"
    for table in ("actual_corrections", "feature_schemas"):
        for event in ("UPDATE", "DELETE"):
            yield f'''CREATE TRIGGER IF NOT EXISTS {table}_{event.lower()}_guard BEFORE {event} ON {table}
                BEGIN SELECT RAISE(ABORT,'immutable history or versioned contract'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS correction_replace_guard BEFORE INSERT ON actual_corrections
        WHEN EXISTS(SELECT 1 FROM actual_corrections WHERE audit_id=NEW.audit_id OR correction_id=NEW.correction_id)
        BEGIN SELECT RAISE(ABORT,'immutable correction history'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS feature_schema_replace_guard BEFORE INSERT ON feature_schemas
        WHEN EXISTS(SELECT 1 FROM feature_schemas WHERE feature_schema_version=NEW.feature_schema_version)
        BEGIN SELECT RAISE(ABORT,'immutable feature schema version'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS actual_identity_guard BEFORE UPDATE ON actual_results
        WHEN NEW.result_id IS NOT OLD.result_id OR NEW.site_id IS NOT OLD.site_id
          OR NEW.target_date IS NOT OLD.target_date OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT,'actual identity and created_at are immutable'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS actual_delete_guard BEFORE DELETE ON actual_results
        BEGIN SELECT RAISE(ABORT,'actual history cannot be deleted'); END'''
    yield '''CREATE TRIGGER IF NOT EXISTS actual_replace_guard BEFORE INSERT ON actual_results
        WHEN EXISTS(SELECT 1 FROM actual_results WHERE result_id=NEW.result_id
                    OR (site_id=NEW.site_id AND target_date=NEW.target_date))
        BEGIN SELECT RAISE(ABORT,'actual already exists; use audited UPDATE'); END'''
    old_json = "json_object(" + ",".join(f"'{key}',OLD.{key}" for key in actual_fields) + ")"
    new_json = "json_object(" + ",".join(f"'{key}',NEW.{key}" for key in actual_fields) + ")"
    yield f'''CREATE TRIGGER IF NOT EXISTS actual_correction_capture AFTER UPDATE ON actual_results
        BEGIN
          INSERT INTO actual_corrections(audit_id,result_id,site_id,target_date,old_values_json,new_values_json,
                                        actor,source_type,reason,corrected_at)
          VALUES(lower(hex(randomblob(16))),OLD.result_id,OLD.site_id,OLD.target_date,{old_json},{new_json},
            COALESCE((SELECT actor FROM actual_correction_context WHERE result_id=OLD.result_id),'UNKNOWN_RAW_SQL'),
            COALESCE((SELECT source_type FROM actual_correction_context WHERE result_id=OLD.result_id),'UNKNOWN'),
            COALESCE((SELECT reason FROM actual_correction_context WHERE result_id=OLD.result_id),'Unattributed raw SQL update'),
            strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00');
        END'''
