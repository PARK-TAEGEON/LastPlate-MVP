"""Deployment metadata only: no serving, routing, model execution or scheduling."""
from uuid import uuid4
from .models import ValidationError, normalize_timestamp, utc_now, to_json
from .schema import SOURCE_TYPES


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be nonempty text")
    return value


class DeploymentMixin:
    def get_deployment(self, deployment_id):
        return self._one("SELECT * FROM model_deployments WHERE deployment_id=?", (deployment_id,))

    def get_current_deployment(self, site_id, model_role="demand"):
        return self._one("SELECT * FROM model_deployments WHERE site_id=? AND model_role=? AND status='current'",
                         (site_id, model_role))

    def list_model_deployments(self, site_id=None, model_role=None):
        return self._many("SELECT * FROM model_deployments WHERE (? IS NULL OR site_id=?) "
                          "AND (? IS NULL OR model_role=?) ORDER BY effective_at,rowid",
                          (site_id, site_id, model_role, model_role))

    def deploy_model(self, site_id, model_version, model_role="demand", *, actor, reason,
                     effective_at=None, source_type="MANUAL", audit_metadata=None,
                     training_run_id=None, training_data_cutoff=None):
        actor, reason = nonempty(actor, "actor"), nonempty(reason, "reason")
        role = nonempty(model_role, "model_role")
        if source_type not in SOURCE_TYPES or source_type == "DEMO":
            raise ValidationError("deployment source_type must be non-DEMO")
        metadata = to_json(audit_metadata) if audit_metadata is not None else None
        with self.transaction():
            cutoff = normalize_timestamp(training_data_cutoff) if training_data_cutoff is not None else None
            if training_run_id is not None:
                run = self.get_training_run(training_run_id)
                if run is None or run["model_version"] != model_version:
                    raise ValidationError("deployment training lineage mismatch")
                if cutoff is not None and cutoff != run["data_cutoff"]:
                    raise ValidationError("deployment cutoff differs from training manifest")
                cutoff = run["data_cutoff"]
            effective = normalize_timestamp(effective_at) if effective_at is not None else utc_now()
            if effective > utc_now():
                raise ValidationError("Future deployment scheduling is not supported")
            model = self._one("SELECT * FROM model_versions WHERE model_version=?", (model_version,))
            if model is None or model["record_status"] != "VALIDATED" or model["is_demo"] or model["source_type"] == "DEMO" or model["status"] == "rejected":
                raise ValidationError("deployment requires a VALIDATED non-DEMO non-rejected model")
            if self.get_site(site_id) is None:
                raise ValidationError("Deployment site not found")
            current = self.get_current_deployment(site_id, role)
            if current is not None:
                if effective < current["effective_at"]:
                    raise ValidationError("Deployment precedes current effective_at")
                self.retire_deployment(current["deployment_id"], actor=actor, reason=reason, retired_at=effective)
            deployment_id = str(uuid4())
            self.connection.execute('''INSERT INTO model_deployments
                (deployment_id,site_id,model_version,model_role,status,effective_at,created_at,actor,reason,
                 audit_metadata_json,source_type,is_demo,record_status,training_run_id,training_data_cutoff)
                VALUES (?,?,?,?,'current',?,?,?,?,?,?,0,'VALIDATED',?,?)''',
                (deployment_id,site_id,model_version,role,effective,utc_now(),actor,reason,metadata,source_type,training_run_id,cutoff))
        return self.get_deployment(deployment_id)

    def retire_deployment(self, deployment_id, *, actor, reason, retired_at=None):
        actor, reason = nonempty(actor, "actor"), nonempty(reason, "reason")
        with self.transaction():
            retired = normalize_timestamp(retired_at) if retired_at is not None else utc_now()
            if retired > utc_now():
                raise ValidationError("Future retirement scheduling is not supported")
            current = self.get_deployment(deployment_id)
            if current is None or current["status"] != "current":
                raise ValidationError("Current deployment not found")
            if retired < current["effective_at"]:
                raise ValidationError("retired_at precedes effective_at")
            self.connection.execute("UPDATE model_deployments SET status='retired',retired_at=?,retired_by=?,retirement_reason=? "
                                    "WHERE deployment_id=?", (retired,actor,reason,deployment_id))
        return self.get_deployment(deployment_id)
