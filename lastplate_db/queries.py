"""Read-only evaluation queries. No prediction, planning or retraining occurs."""
from .models import ValidationError, normalize_timestamp


def get_learning_dataset(repository, site_id=None, *, include_demo=False,
                         include_unvalidated=False, selection_policy="latest_pre_actual",
                         prediction_ids=None, data_cutoff=None):
    """Select eligible pre-outcome rows. INVALID is always excluded.

    latest_pre_actual selects one prediction per site/date; explicit selects IDs.
    Both policies require prediction/plan created_at < actual created_at.
    """
    if type(include_demo) is not bool or type(include_unvalidated) is not bool:
        raise ValidationError("include_demo/include_unvalidated must be bool")
    if selection_policy not in ("latest_pre_actual", "explicit"):
        raise ValidationError("selection_policy must be latest_pre_actual or explicit")
    if selection_policy == "latest_pre_actual" and prediction_ids is not None:
        raise ValidationError("prediction_ids requires selection_policy='explicit'")
    ids = None
    if selection_policy == "explicit":
        if not isinstance(prediction_ids, (list, tuple, set, frozenset)):
            raise ValidationError("explicit policy requires a prediction_id collection")
        if any(not isinstance(value, str) or not value.strip() for value in prediction_ids):
            raise ValidationError("prediction_ids must contain nonempty strings")
        ids = sorted(set(prediction_ids))
        if not ids:
            return []

    def eligible(alias):
        status = f"{alias}.record_status IN ('VALIDATED','UNVALIDATED')" if include_unvalidated else f"{alias}.record_status='VALIDATED'"
        demo = "1=1" if include_demo else f"{alias}.is_demo=0 AND {alias}.source_type != 'DEMO'"
        return f"({status} AND {demo})"

    args = [site_id, site_id]
    cutoff_filter = "1=1"
    if data_cutoff is not None:
        cutoff = normalize_timestamp(data_cutoff)
        cutoff_filter = "a.created_at<=? AND COALESCE(a.updated_at,a.created_at)<=? AND NOT EXISTS(SELECT 1 FROM actual_corrections c WHERE c.result_id=a.result_id AND c.corrected_at>?)"
        args.extend([cutoff, cutoff, cutoff])
    selection = "p.selection_rank=1"
    if ids is not None:
        selection = f"p.prediction_id IN ({','.join('?' for _ in ids)})"
        args.extend(ids)
    # Filter before ranking: an excluded newer row cannot mask eligible history.
    return repository._many(f'''
        WITH candidates AS (
            SELECT p.*, p.rowid AS prediction_rowid,
                   ROW_NUMBER() OVER (PARTITION BY p.site_id,p.target_date
                                      ORDER BY p.created_at DESC,p.rowid DESC) AS selection_rank
            FROM predictions p
            JOIN actual_results a ON a.site_id=p.site_id AND a.target_date=p.target_date
            WHERE (? IS NULL OR p.site_id=?)
              AND {eligible('p')} AND {eligible('a')}
              AND p.created_at < a.created_at
              AND {cutoff_filter}
        )
        SELECT p.prediction_id,p.site_id,p.target_date,p.predicted_diners,
               p.lower_bound,p.upper_bound,p.model_version,p.input_snapshot_json,
               p.available_population,p.predicted_rate,p.model_type,p.applicability,p.confidence,
               p.feature_schema_version,p.observed_at,p.source_lineage_id,p.snapshot_validation_json,
               p.source_type,p.is_demo,p.record_status,p.created_at AS prediction_created_at,
               a.result_id AS actual_result_id,a.source_type AS actual_source_type,a.is_demo AS actual_is_demo,
               a.record_status AS actual_record_status,a.created_at AS actual_created_at,
               o.plan_id,o.recommended_servings,o.safety_margin,
               o.source_type AS plan_source_type,o.is_demo AS plan_is_demo,
               o.record_status AS plan_record_status,o.created_at AS plan_created_at,
               a.actual_diners,a.prepared_servings,a.unserved_leftover_kg,
               a.plate_waste_kg,a.ingredient_waste_kg,a.shortage
        FROM candidates p
        JOIN actual_results a ON a.site_id=p.site_id AND a.target_date=p.target_date
        LEFT JOIN operation_plans o ON o.rowid=(
            SELECT latest.rowid FROM operation_plans latest
            WHERE latest.prediction_id=p.prediction_id AND {eligible('latest')}
              AND latest.created_at < a.created_at
            ORDER BY latest.created_at DESC,latest.rowid DESC LIMIT 1)
        WHERE {selection}
        ORDER BY p.site_id,p.target_date,p.created_at,p.prediction_rowid
    ''', args)


def _eligible_sql(alias):
    """Shared safe actual/prediction policy; caller supplies only static SQL aliases."""
    return f"{alias}.record_status='VALIDATED' AND {alias}.is_demo=0 AND {alias}.source_type!='DEMO'"


def get_site_kpis(repository, site_id, *, eligible_only=True):
    """Safe KPIs by default; eligible_only=False explicitly restores all-row v0.1.1."""
    if type(eligible_only) is not bool:
        raise ValidationError("eligible_only must be bool")
    actual_filter = _eligible_sql("a") if eligible_only else "1=1"
    prediction_filter = (_eligible_sql("latest") + " AND latest.created_at<a.created_at") if eligible_only else "1=1"
    # Operational averages use actuals only; repeated forecasts cannot reweight days.
    result = repository._one(f'''
        SELECT AVG(unserved_leftover_kg) AS average_leftover_kg,
               AVG(plate_waste_kg) AS average_plate_waste_kg,
               AVG(shortage) AS shortage_rate,
               AVG(CASE WHEN prepared_servings IS NOT NULL
                        THEN MAX(prepared_servings-actual_diners,0) END) AS average_overprep_servings
        FROM actual_results a WHERE site_id=? AND {actual_filter}
    ''', (site_id,))
    result.update(repository._one(f'''
        SELECT AVG(ABS(p.predicted_diners-a.actual_diners)) AS prediction_mae
        FROM actual_results a
        JOIN predictions p ON p.rowid=(
            SELECT latest.rowid FROM predictions latest
            WHERE latest.site_id=a.site_id AND latest.target_date=a.target_date
              AND {prediction_filter}
            ORDER BY latest.created_at DESC,latest.rowid DESC LIMIT 1)
        WHERE a.site_id=? AND {actual_filter}
    ''', (site_id,)))
    return result


def get_retraining_readiness(repository, site_id, min_new_records=30, *, since=None,
                             legacy_all_rows=False):
    """Count eligible new actuals; all-row threshold behavior requires explicit opt-in.

    Both counts are returned. new_actual_records follows the selected count mode.
    Eligibility does not require a matching prediction and never runs retraining.
    """
    if isinstance(min_new_records, bool) or not isinstance(min_new_records, int) or min_new_records < 1:
        raise ValidationError("min_new_records must be a positive integer")
    if type(legacy_all_rows) is not bool:
        raise ValidationError("legacy_all_rows must be bool")
    if since is None:
        current = repository.get_current_model()
        since = current["trained_at"] if current else None
    if since is not None:
        since = normalize_timestamp(since)
    return _readiness_counts(repository, site_id, min_new_records, since, legacy_all_rows)


def _readiness_counts(repository, site_id, min_new_records, since, legacy_all_rows=False):
    counts = repository._one(f'''
        SELECT COUNT(*) AS all_new_actual_records,
               COALESCE(SUM(CASE WHEN {_eligible_sql('a')} THEN 1 ELSE 0 END),0)
                   AS eligible_new_actual_records
        FROM actual_results a WHERE site_id=? AND (? IS NULL OR created_at>?)
    ''', (site_id, since, since))
    count = counts["all_new_actual_records" if legacy_all_rows else "eligible_new_actual_records"]
    return {"site_id": site_id, "new_actual_records": count,
            **counts, "required_records": min_new_records, "ready": count >= min_new_records}


def get_dashboard_kpis(repository, site_id):
    """Named safe-only KPI API. No legacy switches."""
    return get_site_kpis(repository, site_id, eligible_only=True)


def get_dashboard_readiness(repository, site_id, min_new_records=30, *, model_role="demand", since=None):
    """Safe actual count; cutoff comes from this site's role deployment, never global current."""
    from .deployments import nonempty
    nonempty(model_role, "model_role")
    if type(min_new_records) is not int or min_new_records < 1:
        raise ValidationError("min_new_records must be a positive integer")
    deployment = repository.get_current_deployment(site_id, model_role)
    if since is None and deployment is not None:
        model = repository._one("SELECT trained_at FROM model_versions WHERE model_version=?", (deployment["model_version"],))
        since = model["trained_at"]
    if since is not None:
        since = normalize_timestamp(since)
    result = _readiness_counts(repository, site_id, min_new_records, since)
    return {**result, "model_role": model_role, "deployment_id": deployment["deployment_id"] if deployment else None,
            "cutoff": since}


def get_training_dataset(repository, site_id=None, *, selection_policy="latest_pre_actual", prediction_ids=None, data_cutoff=None):
    """Safe extraction with explicit per-candidate snapshot diagnostics; never silently fill features."""
    from .snapshots import validate_input_snapshot
    candidates = get_learning_dataset(repository, site_id, selection_policy=selection_policy, prediction_ids=prediction_ids, data_cutoff=data_cutoff)
    records, rejected = [], []
    for row in candidates:
        report = validate_input_snapshot(repository, {**row, "created_at": row["prediction_created_at"]})
        if report["valid"]:
            records.append({**row, "snapshot_validation_json": report})
        else:
            rejected.append({"prediction_id": row["prediction_id"], "site_id": row["site_id"],
                             "target_date": row["target_date"], "validation_result": report})
    return {"records": records, "rejected_records": rejected, "candidate_count": len(candidates),
            "accepted_count": len(records), "rejected_count": len(rejected)}


def get_site_role_deployment_report(repository, site_id, model_role="demand"):
    """Separate training, deployment and explicit data cutoff; does not change readiness."""
    from .deployments import nonempty
    nonempty(model_role, "model_role")
    deployment = repository.get_current_deployment(site_id, model_role)
    model = repository._one("SELECT * FROM model_versions WHERE model_version=?", (deployment["model_version"],)) if deployment else None
    return {"site_id": site_id, "model_role": model_role,
            "deployment_id": deployment["deployment_id"] if deployment else None,
            "model_version": model["model_version"] if model else None,
            "model_trained_at": model["trained_at"] if model else None,
            "deployment_effective_at": deployment["effective_at"] if deployment else None,
            "training_data_cutoff": deployment["training_data_cutoff"] if deployment else None,
            "training_run_id": deployment["training_run_id"] if deployment else None,
            "training_cutoff_source": ("manifest" if deployment["training_run_id"] else "explicit") if deployment and deployment["training_data_cutoff"] else None,
            "dashboard_readiness_default_cutoff": model["trained_at"] if model else None,
            "readiness_semantics": "deployment model trained_at; explicit since overrides; no cutoff means all time"}
