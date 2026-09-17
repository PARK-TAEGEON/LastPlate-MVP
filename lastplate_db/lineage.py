"""Freeze export/run metadata and accepted rows; never execute training or fetch artifacts."""
import hashlib
import json
from uuid import uuid4
from .models import ValidationError, normalize_timestamp, utc_now, to_json
from .deployments import nonempty


def manifest_digest(payload):
    content = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class TrainingLineageMixin:
    def create_training_manifest(self, model_version, feature_schema_version, *, data_cutoff,
                                 code_artifact_id, data_artifact_id, site_id=None,
                                 selection_policy="latest_pre_actual", prediction_ids=None,
                                 training_run_id=None, run_status="EXPORTED", actor="LOCAL"):
        from .queries import get_training_dataset
        cutoff = normalize_timestamp(data_cutoff)
        if cutoff > utc_now():
            raise ValidationError("data_cutoff cannot be in the future")
        if run_status not in ("EXPORTED", "COMPLETED", "FAILED"):
            raise ValidationError("run_status must be EXPORTED, COMPLETED or FAILED")
        nonempty(code_artifact_id, "code_artifact_id")
        nonempty(data_artifact_id, "data_artifact_id")
        nonempty(actor, "actor")
        run_id = str(uuid4()) if training_run_id is None else nonempty(training_run_id, "training_run_id")
        with self.transaction():
            if self.get_feature_schema(feature_schema_version) is None:
                raise ValidationError("Feature schema not found")
            if self._one("SELECT model_version FROM model_versions WHERE model_version=?", (model_version,)) is None:
                raise ValidationError("Model version not found")
            extraction = get_training_dataset(self, site_id, selection_policy=selection_policy,
                                              prediction_ids=prediction_ids, data_cutoff=cutoff)
            records, rejected = [], list(extraction["rejected_records"])
            for row in extraction["records"]:
                if row["feature_schema_version"] == feature_schema_version:
                    records.append(row)
                else:
                    rejected.append({"prediction_id": row["prediction_id"], "site_id": row["site_id"], "target_date": row["target_date"],
                                     "validation_result": {"valid": False, "metadata_errors": ["feature schema differs from requested manifest version"]}})
            payload = dict(training_run_id=run_id, model_version=model_version, feature_schema_version=feature_schema_version,
                data_cutoff=cutoff, code_artifact_id=code_artifact_id, data_artifact_id=data_artifact_id,
                row_selection_policy_json={"policy": selection_policy, "site_id": site_id,
                    "prediction_ids": sorted(set(prediction_ids)) if prediction_ids is not None else None,
                    "cutoff_policy": "inclusive actual creation/update and audit timestamps; safe eligible pre-actual predictions"},
                candidate_count=extraction["candidate_count"], accepted_count=len(records), rejected_count=len(rejected),
                run_status=run_status, created_at=utc_now(), actor=actor,
                manifest_json={"records": records, "rejected_records": rejected})
            payload["manifest_sha256"] = manifest_digest(payload)
            values = [to_json(value) if name.endswith("_json") else value for name,value in payload.items()]
            self.connection.execute(f"INSERT INTO training_runs({','.join(payload)}) VALUES ({','.join('?' for _ in payload)})", values)
        return self.get_training_run(run_id)

    def get_training_run(self, training_run_id):
        return self._one("SELECT * FROM training_runs WHERE training_run_id=?", (training_run_id,))

    def list_training_runs(self, model_version=None):
        return self._many("SELECT * FROM training_runs WHERE (? IS NULL OR model_version=?) ORDER BY created_at,rowid", (model_version,model_version))

    def get_training_manifest_rows(self, training_run_id):
        return self._many("SELECT * FROM training_manifest_rows WHERE training_run_id=? ORDER BY row_index", (training_run_id,))

    def verify_training_manifest(self, training_run_id):
        payload = self.get_training_run(training_run_id)
        if payload is None:
            raise ValidationError("Training run not found")
        return payload["manifest_sha256"] == manifest_digest(payload)
