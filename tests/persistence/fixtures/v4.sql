CREATE TABLE IF NOT EXISTS sites (site_id TEXT NOT NULL PRIMARY KEY, site_name TEXT NOT NULL, site_type TEXT, registered_population INTEGER CHECK (registered_population IS NULL OR (typeof(registered_population) IN ('integer') AND registered_population >= 0 AND registered_population <= 1.7976931348623157e308)), meal_capacity INTEGER CHECK (meal_capacity IS NULL OR (typeof(meal_capacity) IN ('integer') AND meal_capacity >= 0 AND meal_capacity <= 1.7976931348623157e308)), created_at TEXT NOT NULL, updated_at TEXT, source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')), is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1), record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')));
CREATE TABLE IF NOT EXISTS predictions (prediction_id TEXT NOT NULL PRIMARY KEY, site_id TEXT NOT NULL, target_date TEXT NOT NULL, predicted_diners REAL NOT NULL CHECK (predicted_diners IS NULL OR (typeof(predicted_diners) IN ('integer','real') AND predicted_diners >= 0 AND predicted_diners <= 1.7976931348623157e308)), lower_bound REAL CHECK (lower_bound IS NULL OR (typeof(lower_bound) IN ('integer','real') AND lower_bound >= 0 AND lower_bound <= 1.7976931348623157e308)), upper_bound REAL CHECK (upper_bound IS NULL OR (typeof(upper_bound) IN ('integer','real') AND upper_bound >= 0 AND upper_bound <= 1.7976931348623157e308)), predicted_rate REAL CHECK (predicted_rate IS NULL OR (typeof(predicted_rate) IN ('integer','real') AND predicted_rate >= 0 AND predicted_rate <= 1.7976931348623157e308)), available_population REAL CHECK (available_population IS NULL OR (typeof(available_population) IN ('integer','real') AND available_population >= 0 AND available_population <= 1.7976931348623157e308)), model_version TEXT, model_type TEXT, applicability TEXT, confidence TEXT, created_at TEXT NOT NULL, request_id TEXT, input_snapshot_json TEXT, source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')), is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1), record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')), feature_schema_version TEXT, observed_at TEXT, source_lineage_id TEXT, snapshot_validation_json TEXT, FOREIGN KEY(site_id) REFERENCES sites(site_id), UNIQUE(request_id), UNIQUE(prediction_id, site_id, target_date), CHECK(lower_bound IS NULL OR upper_bound IS NULL OR (lower_bound <= predicted_diners AND predicted_diners <= upper_bound)));
CREATE TABLE IF NOT EXISTS operation_plans (plan_id TEXT NOT NULL PRIMARY KEY, prediction_id TEXT NOT NULL, site_id TEXT NOT NULL, target_date TEXT NOT NULL, recommended_servings INTEGER NOT NULL CHECK (recommended_servings IS NULL OR (typeof(recommended_servings) IN ('integer') AND recommended_servings >= 0 AND recommended_servings <= 1.7976931348623157e308)), base_demand REAL CHECK (base_demand IS NULL OR (typeof(base_demand) IN ('integer','real') AND base_demand >= 0 AND base_demand <= 1.7976931348623157e308)), safety_margin REAL CHECK (safety_margin IS NULL OR (typeof(safety_margin) IN ('integer','real') AND safety_margin >= 0 AND safety_margin <= 1.7976931348623157e308)), status TEXT, ingredient_requirements_json TEXT, order_reviews_json TEXT, alerts_json TEXT, constraints_json TEXT, requires_human_approval INTEGER NOT NULL DEFAULT 1 CHECK (requires_human_approval IS NULL OR requires_human_approval IN (0,1)), created_at TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')), is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1), record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')), idempotency_key TEXT, FOREIGN KEY(site_id) REFERENCES sites(site_id), UNIQUE(prediction_id, idempotency_key), FOREIGN KEY(prediction_id, site_id, target_date) REFERENCES predictions(prediction_id, site_id, target_date));
CREATE TABLE IF NOT EXISTS actual_results (result_id TEXT NOT NULL PRIMARY KEY, site_id TEXT NOT NULL, target_date TEXT NOT NULL, actual_diners INTEGER NOT NULL CHECK (actual_diners IS NULL OR (typeof(actual_diners) IN ('integer') AND actual_diners >= 0 AND actual_diners <= 1.7976931348623157e308)), prepared_servings INTEGER CHECK (prepared_servings IS NULL OR (typeof(prepared_servings) IN ('integer') AND prepared_servings >= 0 AND prepared_servings <= 1.7976931348623157e308)), unserved_leftover_kg REAL CHECK (unserved_leftover_kg IS NULL OR (typeof(unserved_leftover_kg) IN ('integer','real') AND unserved_leftover_kg >= 0 AND unserved_leftover_kg <= 1.7976931348623157e308)), plate_waste_kg REAL CHECK (plate_waste_kg IS NULL OR (typeof(plate_waste_kg) IN ('integer','real') AND plate_waste_kg >= 0 AND plate_waste_kg <= 1.7976931348623157e308)), ingredient_waste_kg REAL CHECK (ingredient_waste_kg IS NULL OR (typeof(ingredient_waste_kg) IN ('integer','real') AND ingredient_waste_kg >= 0 AND ingredient_waste_kg <= 1.7976931348623157e308)), shortage INTEGER NOT NULL DEFAULT 0 CHECK (shortage IS NULL OR shortage IN (0,1)), actual_food_cost REAL CHECK (actual_food_cost IS NULL OR (typeof(actual_food_cost) IN ('integer','real') AND actual_food_cost >= 0 AND actual_food_cost <= 1.7976931348623157e308)), notes TEXT, created_at TEXT NOT NULL, updated_at TEXT, source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')), is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1), record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')), FOREIGN KEY(site_id) REFERENCES sites(site_id), UNIQUE(site_id, target_date));
CREATE TABLE IF NOT EXISTS inventory_snapshots (inventory_id TEXT NOT NULL PRIMARY KEY, site_id TEXT NOT NULL, snapshot_date TEXT NOT NULL, ingredient_name TEXT NOT NULL, normalized_ingredient_name TEXT, quantity REAL NOT NULL CHECK (quantity IS NULL OR (typeof(quantity) IN ('integer','real') AND quantity >= 0 AND quantity <= 1.7976931348623157e308)), unit TEXT NOT NULL, expiry_date TEXT, lot_id TEXT, source TEXT, created_at TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')), is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1), record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')), FOREIGN KEY(site_id) REFERENCES sites(site_id));
CREATE TABLE IF NOT EXISTS model_versions (model_version TEXT NOT NULL PRIMARY KEY, model_type TEXT NOT NULL, trained_at TEXT, training_rows INTEGER CHECK (training_rows IS NULL OR (typeof(training_rows) IN ('integer') AND training_rows >= 0 AND training_rows <= 1.7976931348623157e308)), validation_rows INTEGER CHECK (validation_rows IS NULL OR (typeof(validation_rows) IN ('integer') AND validation_rows >= 0 AND validation_rows <= 1.7976931348623157e308)), validation_mae REAL CHECK (validation_mae IS NULL OR (typeof(validation_mae) IN ('integer','real') AND validation_mae >= 0 AND validation_mae <= 1.7976931348623157e308)), validation_rmse REAL CHECK (validation_rmse IS NULL OR (typeof(validation_rmse) IN ('integer','real') AND validation_rmse >= 0 AND validation_rmse <= 1.7976931348623157e308)), validation_mape REAL CHECK (validation_mape IS NULL OR (typeof(validation_mape) IN ('integer','real') AND validation_mape >= 0 AND validation_mape <= 1.7976931348623157e308)), status TEXT, parent_version TEXT, notes TEXT, created_at TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')), is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1), record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')));
CREATE TABLE IF NOT EXISTS decision_logs (decision_id TEXT NOT NULL PRIMARY KEY, site_id TEXT NOT NULL, target_date TEXT NOT NULL, decision_type TEXT, recommendation_json TEXT, critical_alerts_json TEXT, confidence TEXT, requires_human_approval INTEGER NOT NULL DEFAULT 1 CHECK (requires_human_approval IS NULL OR requires_human_approval IN (0,1)), approved INTEGER CHECK (approved IS NULL OR approved IN (0,1)), approved_at TEXT, created_at TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')), is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1), record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')), FOREIGN KEY(site_id) REFERENCES sites(site_id));
CREATE UNIQUE INDEX IF NOT EXISTS one_current_model ON model_versions(status) WHERE status = 'current';
CREATE INDEX IF NOT EXISTS ix_predictions ON predictions(site_id,target_date);
CREATE INDEX IF NOT EXISTS ix_operation_plans ON operation_plans(prediction_id,created_at);
CREATE INDEX IF NOT EXISTS ix_inventory_snapshots ON inventory_snapshots(site_id,snapshot_date);
CREATE INDEX IF NOT EXISTS ix_decision_logs ON decision_logs(site_id,target_date);
CREATE TRIGGER IF NOT EXISTS guard_model_versions_insert BEFORE INSERT ON model_versions WHEN NEW.status='current' AND (NEW.source_type='DEMO' OR NEW.is_demo=1 OR NEW.record_status='INVALID') BEGIN SELECT RAISE(ABORT, 'current model cannot be DEMO or INVALID'); END;
CREATE TRIGGER IF NOT EXISTS guard_inventory_snapshots_insert BEFORE INSERT ON inventory_snapshots WHEN UPPER(TRIM(NEW.source)) IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT') AND UPPER(TRIM(NEW.source)) != NEW.source_type BEGIN SELECT RAISE(ABORT, 'inventory source/source_type contradiction'); END;
CREATE TRIGGER IF NOT EXISTS guard_model_versions_update BEFORE UPDATE ON model_versions WHEN NEW.status='current' AND (NEW.source_type='DEMO' OR NEW.is_demo=1 OR NEW.record_status='INVALID') BEGIN SELECT RAISE(ABORT, 'current model cannot be DEMO or INVALID'); END;
CREATE TRIGGER IF NOT EXISTS guard_inventory_snapshots_update BEFORE UPDATE ON inventory_snapshots WHEN UPPER(TRIM(NEW.source)) IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT') AND UPPER(TRIM(NEW.source)) != NEW.source_type BEGIN SELECT RAISE(ABORT, 'inventory source/source_type contradiction'); END;
CREATE TABLE IF NOT EXISTS feature_schemas (
        feature_schema_version TEXT NOT NULL PRIMARY KEY,
        required_features_json TEXT NOT NULL CHECK(json_valid(required_features_json) AND json_type(required_features_json)='object'),
        description TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_deployments (
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
        source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')),is_demo INTEGER NOT NULL DEFAULT 0 CHECK(typeof(is_demo)='integer' AND is_demo IN (0,1)) CHECK(source_type != 'DEMO' OR is_demo=1),record_status TEXT NOT NULL DEFAULT 'UNVALIDATED' CHECK(record_status IN ('UNVALIDATED','VALIDATED','INVALID')),
        CHECK(source_type!='DEMO' AND is_demo=0 AND record_status='VALIDATED'),
        CHECK((status='current' AND retired_at IS NULL AND retired_by IS NULL AND retirement_reason IS NULL)
           OR (status='retired' AND retired_at IS NOT NULL AND retired_at>=effective_at
               AND retired_by IS NOT NULL AND length(trim(retired_by))>0
               AND retirement_reason IS NOT NULL AND length(trim(retirement_reason))>0)));
CREATE UNIQUE INDEX IF NOT EXISTS one_site_role_deployment ON model_deployments(site_id,model_role) WHERE status='current';
CREATE INDEX IF NOT EXISTS ix_deployment_history ON model_deployments(site_id,model_role,effective_at);
CREATE TRIGGER IF NOT EXISTS deployment_insert_guard BEFORE INSERT ON model_deployments
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
        END;
CREATE TRIGGER IF NOT EXISTS deployment_update_guard BEFORE UPDATE ON model_deployments
        WHEN OLD.status!='current' OR NEW.status!='retired' OR substr(NEW.retired_at,1,19)>strftime('%Y-%m-%dT%H:%M:%S','now') OR NEW.deployment_id IS NOT OLD.deployment_id OR NEW.site_id IS NOT OLD.site_id OR NEW.model_version IS NOT OLD.model_version OR NEW.model_role IS NOT OLD.model_role OR NEW.effective_at IS NOT OLD.effective_at OR NEW.created_at IS NOT OLD.created_at OR NEW.actor IS NOT OLD.actor OR NEW.reason IS NOT OLD.reason OR NEW.audit_metadata_json IS NOT OLD.audit_metadata_json OR NEW.source_type IS NOT OLD.source_type OR NEW.is_demo IS NOT OLD.is_demo OR NEW.record_status IS NOT OLD.record_status
        BEGIN SELECT RAISE(ABORT,'deployment history is immutable; only current to retired allowed'); END;
CREATE TRIGGER IF NOT EXISTS deployment_delete_guard BEFORE DELETE ON model_deployments
        BEGIN SELECT RAISE(ABORT,'deployment history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS deployed_model_insert_guard BEFORE INSERT ON model_versions
            WHEN EXISTS(SELECT 1 FROM model_deployments WHERE model_version=NEW.model_version AND status='current')
              AND (NEW.record_status!='VALIDATED' OR NEW.is_demo=1 OR NEW.source_type='DEMO' OR NEW.status='rejected')
            BEGIN SELECT RAISE(ABORT,'cannot invalidate a currently deployed model'); END;
CREATE TRIGGER IF NOT EXISTS deployed_model_update_guard BEFORE UPDATE ON model_versions
            WHEN EXISTS(SELECT 1 FROM model_deployments WHERE model_version=OLD.model_version AND status='current')
              AND (NEW.record_status!='VALIDATED' OR NEW.is_demo=1 OR NEW.source_type='DEMO' OR NEW.status='rejected' OR NEW.model_version IS NOT OLD.model_version)
            BEGIN SELECT RAISE(ABORT,'cannot invalidate a currently deployed model'); END;
CREATE TRIGGER IF NOT EXISTS deployed_model_delete_guard BEFORE DELETE ON model_versions
        WHEN EXISTS(SELECT 1 FROM model_deployments WHERE model_version=OLD.model_version)
        BEGIN SELECT RAISE(ABORT,'model referenced by deployment history'); END;
CREATE TRIGGER IF NOT EXISTS deployed_model_replace_guard BEFORE INSERT ON model_versions
        WHEN EXISTS(SELECT 1 FROM model_versions WHERE model_version=NEW.model_version)
         AND EXISTS(SELECT 1 FROM model_deployments WHERE model_version=NEW.model_version)
        BEGIN SELECT RAISE(ABORT,'cannot replace a model referenced by deployment history'); END;
CREATE TABLE IF NOT EXISTS actual_correction_context (
        result_id TEXT NOT NULL PRIMARY KEY REFERENCES actual_results(result_id),
        actor TEXT NOT NULL CHECK(length(trim(actor))>0),
        source_type TEXT NOT NULL CHECK(source_type IN ('UNKNOWN','MODEL','DEMO','USER_UPLOAD','PUBLIC_API','MANUAL','AGENT')),
        reason TEXT NOT NULL CHECK(length(trim(reason))>0));
CREATE TABLE IF NOT EXISTS actual_corrections (
        correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_id TEXT NOT NULL UNIQUE,
        result_id TEXT NOT NULL REFERENCES actual_results(result_id),
        site_id TEXT NOT NULL, target_date TEXT NOT NULL,
        old_values_json TEXT NOT NULL CHECK(json_valid(old_values_json)),
        new_values_json TEXT NOT NULL CHECK(json_valid(new_values_json)),
        actor TEXT NOT NULL, source_type TEXT NOT NULL, reason TEXT NOT NULL,
        corrected_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_actual_corrections ON actual_corrections(result_id,correction_id);
CREATE TRIGGER IF NOT EXISTS actual_corrections_update_guard BEFORE UPDATE ON actual_corrections
                BEGIN SELECT RAISE(ABORT,'immutable history or versioned contract'); END;
CREATE TRIGGER IF NOT EXISTS actual_corrections_delete_guard BEFORE DELETE ON actual_corrections
                BEGIN SELECT RAISE(ABORT,'immutable history or versioned contract'); END;
CREATE TRIGGER IF NOT EXISTS feature_schemas_update_guard BEFORE UPDATE ON feature_schemas
                BEGIN SELECT RAISE(ABORT,'immutable history or versioned contract'); END;
CREATE TRIGGER IF NOT EXISTS feature_schemas_delete_guard BEFORE DELETE ON feature_schemas
                BEGIN SELECT RAISE(ABORT,'immutable history or versioned contract'); END;
CREATE TRIGGER IF NOT EXISTS correction_replace_guard BEFORE INSERT ON actual_corrections
        WHEN EXISTS(SELECT 1 FROM actual_corrections WHERE audit_id=NEW.audit_id OR correction_id=NEW.correction_id)
        BEGIN SELECT RAISE(ABORT,'immutable correction history'); END;
CREATE TRIGGER IF NOT EXISTS feature_schema_replace_guard BEFORE INSERT ON feature_schemas
        WHEN EXISTS(SELECT 1 FROM feature_schemas WHERE feature_schema_version=NEW.feature_schema_version)
        BEGIN SELECT RAISE(ABORT,'immutable feature schema version'); END;
CREATE TRIGGER IF NOT EXISTS actual_identity_guard BEFORE UPDATE ON actual_results
        WHEN NEW.result_id IS NOT OLD.result_id OR NEW.site_id IS NOT OLD.site_id
          OR NEW.target_date IS NOT OLD.target_date OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT,'actual identity and created_at are immutable'); END;
CREATE TRIGGER IF NOT EXISTS actual_delete_guard BEFORE DELETE ON actual_results
        BEGIN SELECT RAISE(ABORT,'actual history cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS actual_replace_guard BEFORE INSERT ON actual_results
        WHEN EXISTS(SELECT 1 FROM actual_results WHERE result_id=NEW.result_id
                    OR (site_id=NEW.site_id AND target_date=NEW.target_date))
        BEGIN SELECT RAISE(ABORT,'actual already exists; use audited UPDATE'); END;
CREATE TRIGGER IF NOT EXISTS actual_correction_capture AFTER UPDATE ON actual_results
        BEGIN
          INSERT INTO actual_corrections(audit_id,result_id,site_id,target_date,old_values_json,new_values_json,
                                        actor,source_type,reason,corrected_at)
          VALUES(lower(hex(randomblob(16))),OLD.result_id,OLD.site_id,OLD.target_date,json_object('result_id',OLD.result_id,'site_id',OLD.site_id,'target_date',OLD.target_date,'actual_diners',OLD.actual_diners,'prepared_servings',OLD.prepared_servings,'unserved_leftover_kg',OLD.unserved_leftover_kg,'plate_waste_kg',OLD.plate_waste_kg,'ingredient_waste_kg',OLD.ingredient_waste_kg,'shortage',OLD.shortage,'actual_food_cost',OLD.actual_food_cost,'notes',OLD.notes,'created_at',OLD.created_at,'updated_at',OLD.updated_at,'source_type',OLD.source_type,'is_demo',OLD.is_demo,'record_status',OLD.record_status),json_object('result_id',NEW.result_id,'site_id',NEW.site_id,'target_date',NEW.target_date,'actual_diners',NEW.actual_diners,'prepared_servings',NEW.prepared_servings,'unserved_leftover_kg',NEW.unserved_leftover_kg,'plate_waste_kg',NEW.plate_waste_kg,'ingredient_waste_kg',NEW.ingredient_waste_kg,'shortage',NEW.shortage,'actual_food_cost',NEW.actual_food_cost,'notes',NEW.notes,'created_at',NEW.created_at,'updated_at',NEW.updated_at,'source_type',NEW.source_type,'is_demo',NEW.is_demo,'record_status',NEW.record_status),
            COALESCE((SELECT actor FROM actual_correction_context WHERE result_id=OLD.result_id),'UNKNOWN_RAW_SQL'),
            COALESCE((SELECT source_type FROM actual_correction_context WHERE result_id=OLD.result_id),'UNKNOWN'),
            COALESCE((SELECT reason FROM actual_correction_context WHERE result_id=OLD.result_id),'Unattributed raw SQL update'),
            strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00');
        END;
PRAGMA user_version=4;
