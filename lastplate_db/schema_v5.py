"""Immutable run manifests, optional feature rules and authenticated actor attestations."""


def v5_statements():
    yield "ALTER TABLE feature_schemas ADD COLUMN rule_language_version TEXT"
    yield "ALTER TABLE feature_schemas ADD COLUMN rules_json TEXT"
    yield "ALTER TABLE model_deployments ADD COLUMN training_run_id TEXT REFERENCES training_runs(training_run_id)"
    yield "ALTER TABLE model_deployments ADD COLUMN training_data_cutoff TEXT"
    yield '''CREATE TABLE training_runs (
        training_run_id TEXT NOT NULL PRIMARY KEY,
        model_version TEXT NOT NULL REFERENCES model_versions(model_version),
        feature_schema_version TEXT NOT NULL REFERENCES feature_schemas(feature_schema_version),
        data_cutoff TEXT NOT NULL CHECK(data_cutoff GLOB '????-??-??T??:??:??.??????+00:00' AND julianday(data_cutoff) IS NOT NULL),
        code_artifact_id TEXT NOT NULL CHECK(length(trim(code_artifact_id))>0),
        data_artifact_id TEXT NOT NULL CHECK(length(trim(data_artifact_id))>0),
        row_selection_policy_json TEXT NOT NULL CHECK(json_valid(row_selection_policy_json)),
        candidate_count INTEGER NOT NULL CHECK(typeof(candidate_count)='integer' AND candidate_count>=0),
        accepted_count INTEGER NOT NULL CHECK(typeof(accepted_count)='integer' AND accepted_count>=0),
        rejected_count INTEGER NOT NULL CHECK(typeof(rejected_count)='integer' AND rejected_count>=0),
        run_status TEXT NOT NULL CHECK(run_status IN ('EXPORTED','COMPLETED','FAILED')),
        created_at TEXT NOT NULL, actor TEXT NOT NULL CHECK(length(trim(actor))>0),
        manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)
            AND json_type(manifest_json,'$.records') IS 'array'
            AND json_type(manifest_json,'$.rejected_records') IS 'array'),
        manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'),
        CHECK(candidate_count=accepted_count+rejected_count),
        CHECK(accepted_count=json_array_length(manifest_json,'$.records')),
        CHECK(rejected_count=json_array_length(manifest_json,'$.rejected_records')))'''
    yield '''CREATE VIEW training_manifest_rows AS
        SELECT r.training_run_id,CAST(j.key AS INTEGER) AS row_index,
          json_extract(j.value,'$.prediction_id') AS prediction_id,
          json_extract(j.value,'$.actual_result_id') AS actual_result_id,
          json_extract(j.value,'$.site_id') AS site_id,j.value AS row_json
        FROM training_runs r,json_each(r.manifest_json,'$.records') j'''
    yield '''CREATE TRIGGER training_run_insert_guard BEFORE INSERT ON training_runs BEGIN
        SELECT CASE WHEN EXISTS(SELECT 1 FROM training_runs WHERE training_run_id=NEW.training_run_id)
          THEN RAISE(ABORT,'immutable training run') END;
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM model_versions WHERE model_version=NEW.model_version)
          OR NOT EXISTS(SELECT 1 FROM feature_schemas WHERE feature_schema_version=NEW.feature_schema_version)
          THEN RAISE(ABORT,'training run requires model and feature schema') END;
        SELECT CASE WHEN NEW.accepted_count!=(SELECT COUNT(DISTINCT json_extract(value,'$.prediction_id'))
          FROM json_each(NEW.manifest_json,'$.records')) THEN RAISE(ABORT,'duplicate or missing manifest prediction') END;
        SELECT CASE WHEN EXISTS(
          SELECT 1 FROM json_each(NEW.manifest_json,'$.records') j
          LEFT JOIN predictions p ON p.prediction_id=json_extract(j.value,'$.prediction_id')
          LEFT JOIN actual_results a ON a.result_id=json_extract(j.value,'$.actual_result_id')
          WHERE p.prediction_id IS NULL OR a.result_id IS NULL OR p.site_id!=a.site_id OR p.target_date!=a.target_date
            OR p.site_id IS NOT json_extract(j.value,'$.site_id')
            OR p.target_date IS NOT json_extract(j.value,'$.target_date')
            OR p.predicted_diners IS NOT json_extract(j.value,'$.predicted_diners')
            OR a.actual_diners IS NOT json_extract(j.value,'$.actual_diners')
            OR p.feature_schema_version IS NOT json_extract(j.value,'$.feature_schema_version')
            OR p.source_lineage_id IS NOT json_extract(j.value,'$.source_lineage_id')
            OR json_extract(j.value,'$.snapshot_validation_json.valid') IS NOT 1
            OR p.feature_schema_version IS NOT NEW.feature_schema_version
            OR p.record_status!='VALIDATED' OR p.is_demo!=0 OR p.source_type='DEMO'
            OR a.record_status!='VALIDATED' OR a.is_demo!=0 OR a.source_type='DEMO'
            OR p.created_at>=a.created_at OR a.created_at>NEW.data_cutoff
            OR COALESCE(a.updated_at,a.created_at)>NEW.data_cutoff
            OR EXISTS(SELECT 1 FROM actual_corrections c WHERE c.result_id=a.result_id AND c.corrected_at>NEW.data_cutoff)
          ) THEN RAISE(ABORT,'manifest row is not eligible at cutoff') END;
        END'''
    yield '''CREATE TRIGGER feature_rule_pair_guard BEFORE INSERT ON feature_schemas
        WHEN (NEW.rule_language_version IS NULL)!=(NEW.rules_json IS NULL)
          OR (NEW.rule_language_version IS NOT NULL AND (NEW.rule_language_version!='lastplate-rules/v1'
              OR CASE WHEN json_valid(NEW.rules_json) THEN json_type(NEW.rules_json)!='array' OR json_array_length(NEW.rules_json)=0 ELSE 1 END))
        BEGIN SELECT RAISE(ABORT,'invalid feature rule language or rules'); END'''
    yield '''CREATE TRIGGER deployment_lineage_insert_guard BEFORE INSERT ON model_deployments BEGIN
        SELECT CASE WHEN NEW.training_data_cutoff IS NOT NULL AND
          (NEW.training_data_cutoff NOT GLOB '????-??-??T??:??:??.??????+00:00' OR julianday(NEW.training_data_cutoff) IS NULL)
          THEN RAISE(ABORT,'invalid training data cutoff') END;
        SELECT CASE WHEN NEW.training_run_id IS NOT NULL AND NOT EXISTS(
          SELECT 1 FROM training_runs WHERE training_run_id=NEW.training_run_id AND model_version=NEW.model_version
            AND data_cutoff=NEW.training_data_cutoff)
          THEN RAISE(ABORT,'deployment training lineage mismatch') END;
        END'''
    yield '''CREATE TRIGGER deployment_lineage_update_guard BEFORE UPDATE ON model_deployments
        WHEN NEW.training_run_id IS NOT OLD.training_run_id OR NEW.training_data_cutoff IS NOT OLD.training_data_cutoff
        BEGIN SELECT RAISE(ABORT,'immutable deployment training lineage'); END'''

    yield '''CREATE TABLE integration_actor_events (
        event_id TEXT NOT NULL PRIMARY KEY,
        action TEXT NOT NULL CHECK(action IN ('correction:write','deployment:write','deployment:retire')),
        site_id TEXT NOT NULL REFERENCES sites(site_id), target_id TEXT NOT NULL,
        subject TEXT NOT NULL, issuer TEXT NOT NULL, verification_id TEXT NOT NULL,
        authenticated_at TEXT NOT NULL, expires_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
        attestation_json TEXT NOT NULL CHECK(json_valid(attestation_json)))'''
    yield '''CREATE TRIGGER actor_event_insert_guard BEFORE INSERT ON integration_actor_events BEGIN
        SELECT CASE WHEN EXISTS(SELECT 1 FROM integration_actor_events WHERE event_id=NEW.event_id)
          THEN RAISE(ABORT,'immutable actor event') END;
        SELECT CASE WHEN (NEW.action='correction:write' AND NOT EXISTS(
          SELECT 1 FROM actual_corrections WHERE audit_id=NEW.target_id AND site_id=NEW.site_id AND actor=NEW.subject))
          OR (NEW.action='deployment:write' AND NOT EXISTS(
          SELECT 1 FROM model_deployments WHERE deployment_id=NEW.target_id AND site_id=NEW.site_id AND actor=NEW.subject))
          OR (NEW.action='deployment:retire' AND NOT EXISTS(
          SELECT 1 FROM model_deployments WHERE deployment_id=NEW.target_id AND site_id=NEW.site_id AND retired_by=NEW.subject))
          THEN RAISE(ABORT,'actor event target mismatch') END;
        END'''
    for table in ("training_runs", "integration_actor_events"):
        for action in ("UPDATE", "DELETE"):
            yield f"CREATE TRIGGER {table}_{action.lower()}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable lineage'); END"
    for table, key, link_table in (("predictions", "prediction_id", "training_manifest_rows"), ("model_versions", "model_version", "training_runs")):
        for action in ("DELETE", "UPDATE", "INSERT"):
            identity = f"NEW.{key}" if action == "INSERT" else f"OLD.{key}"
            when = f"EXISTS(SELECT 1 FROM {link_table} WHERE {key}={identity})"
            if action == "UPDATE":
                when += f" AND NEW.{key} IS NOT OLD.{key}"
            if action == "INSERT":
                when += f" AND EXISTS(SELECT 1 FROM {table} WHERE {key}=NEW.{key})"
            yield f"CREATE TRIGGER lineage_{table}_{action.lower()} BEFORE {action} ON {table} WHEN {when} BEGIN SELECT RAISE(ABORT,'record referenced by immutable training lineage'); END"
