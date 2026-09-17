from dataclasses import asdict, is_dataclass
from uuid import uuid4
from contextlib import contextmanager

from .connection import connect
from .schema import TABLES, SOURCE_TYPES, RECORD_STATUSES, initialize_schema
from .models import ValidationError, utc_now, to_json, from_json, number, validate_date, normalize_timestamp
from .deployments import DeploymentMixin, nonempty
from .snapshots import FeatureSchemaMixin, validate_input_snapshot
from .lineage import TrainingLineageMixin


class Repository(DeploymentMixin, FeatureSchemaMixin, TrainingLineageMixin):
    """One connection per instance. Context manager closes it; each write is atomic."""
    def __init__(self, path=None):
        self.connection = connect(path)
        try:
            initialize_schema(self.connection)
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        """Atomic multi-call unit; nested calls use savepoints, never commit the parent."""
        nested = self.connection.in_transaction
        savepoint = "sp_" + uuid4().hex
        self.connection.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
        try:
            yield self
            if nested:
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                self.connection.commit()
        except BaseException:
            if nested:
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                self.connection.rollback()
            raise

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        return {key: from_json(value) if key.endswith("_json") else value for key, value in dict(row).items()}

    def _one(self, sql, args=()):
        return self._decode(self.connection.execute(sql, args).fetchone())

    def _many(self, sql, args=()):
        return [self._decode(row) for row in self.connection.execute(sql, args)]

    def _data(self, record, kwargs):
        if record is None:
            return dict(kwargs)
        if is_dataclass(record) and not isinstance(record, type):
            record = asdict(record)
        if not isinstance(record, dict):
            raise ValidationError("Record must be a dict or dataclass instance")
        if set(record) & set(kwargs):
            raise ValidationError("Duplicate fields in record and keyword arguments")
        return {**record, **kwargs}

    def _validate(self, table, data):
        fields = TABLES[table][1]
        unknown = set(data) - set(fields)
        if unknown:
            raise ValidationError(f"Unknown {table} fields: {sorted(unknown)}")
        result = {}
        for name, spec in fields.items():
            value = data.get(name)
            if value is None:
                if spec.endswith("!"):
                    raise ValidationError(f"{table}.{name} is required")
                result[name] = None
                continue
            kind = spec.rstrip("!")
            try:
                if kind in ("real", "int"):
                    value = number(value, integer=kind == "int")
                elif kind == "bool":
                    if not isinstance(value, (bool, int)) or value not in (0, 1):
                        raise ValidationError("Expected boolean or 0/1")
                    value = int(value)
                elif kind == "date":
                    value = validate_date(value)
                elif kind == "time":
                    value = normalize_timestamp(value)
                elif kind == "json":
                    value = to_json(from_json(value) if isinstance(value, str) else value)
                elif not isinstance(value, str) or not value.strip():
                    raise ValidationError("Expected nonempty text")
            except ValidationError as exc:
                raise ValidationError(f"{table}.{name}: {exc}") from exc
            result[name] = value
        if table == "predictions" and result["lower_bound"] is not None and result["upper_bound"] is not None:
            if not result["lower_bound"] <= result["predicted_diners"] <= result["upper_bound"]:
                raise ValidationError("Expected lower_bound <= predicted_diners <= upper_bound")
        if result["source_type"] not in SOURCE_TYPES:
            raise ValidationError(f"source_type must be one of {SOURCE_TYPES}")
        if result["record_status"] not in RECORD_STATUSES:
            raise ValidationError(f"record_status must be one of {RECORD_STATUSES}")
        if result["source_type"] == "DEMO" and not result["is_demo"]:
            raise ValidationError("source_type DEMO requires is_demo=True")
        if table == "model_versions" and result["status"] not in (None, "candidate", "current", "archived", "rejected"):
            raise ValidationError("Invalid model status")
        if table == "model_versions" and result["status"] == "current":
            if result["source_type"] == "DEMO" or result["is_demo"] or result["record_status"] == "INVALID":
                raise ValidationError("current model cannot be DEMO or INVALID")
        if table == "inventory_snapshots" and result["source"] is not None:
            source_code = result["source"].strip(" ").upper()
            if source_code in SOURCE_TYPES:
                if source_code != result["source_type"]:
                    raise ValidationError("inventory source/source_type contradiction")
                result["source"] = source_code
        return result

    def _save(self, table, record=None, **kwargs):
        data = self._data(record, kwargs)
        pk = TABLES[table][0]
        if pk != "model_version":
            data.setdefault(pk, str(uuid4()))
        data.setdefault("created_at", utc_now())
        # A reserved legacy source value is an alias for the canonical source_type.
        if table == "inventory_snapshots" and "source_type" not in data:
            source = data.get("source")
            if isinstance(source, str) and source.strip(" ").upper() in SOURCE_TYPES:
                data["source_type"] = source.strip(" ").upper()
        data.setdefault("source_type", "UNKNOWN")
        data.setdefault("is_demo", data["source_type"] == "DEMO")
        data.setdefault("record_status", "UNVALIDATED")
        if "requires_human_approval" in TABLES[table][1]:
            data.setdefault("requires_human_approval", True)
        if table == "actual_results":
            data.setdefault("shortage", False)
        data = self._validate(table, data)
        if table == "predictions":
            # Persist diagnostics, but extraction recomputes them against the immutable contract.
            data["snapshot_validation_json"] = to_json(validate_input_snapshot(self, data))
        columns = list(data)
        # No silent overwrite: duplicate IDs/request IDs raise sqlite3.IntegrityError.
        with self.transaction():
            self.connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(data.values()))
        return self._one(f"SELECT * FROM {table} WHERE {pk} = ?", (data[pk],))

    def create_site(self, record=None, **kwargs):
        return self._save("sites", record, **kwargs)

    def get_site(self, site_id):
        return self._one("SELECT * FROM sites WHERE site_id=?", (site_id,))

    def list_sites(self):
        return self._many("SELECT * FROM sites ORDER BY created_at,rowid")

    def update_site(self, site_id, record=None, **kwargs):
        changes = self._data(record, kwargs)
        forbidden = {"site_id", "created_at", "updated_at"} & set(changes)
        if forbidden:
            raise ValidationError(f"Immutable or managed fields: {sorted(forbidden)}")
        with self.transaction():
            current = self.get_site(site_id)
            if current is None:
                raise ValidationError("Site not found")
            data = self._validate("sites", {**current, **changes, "updated_at": utc_now()})
            names = list(changes) + ["updated_at"]
            self.connection.execute(f"UPDATE sites SET {','.join(n+'=?' for n in names)} WHERE site_id=?",
                                    [data[n] for n in names] + [site_id])
        return self.get_site(site_id)

    def save_prediction(self, record=None, **kwargs):
        return self._save("predictions", record, **kwargs)

    def get_prediction(self, prediction_id):
        return self._one("SELECT * FROM predictions WHERE prediction_id=?", (prediction_id,))

    def get_predictions_by_site(self, site_id, start_date=None, end_date=None):
        sql, args = "SELECT * FROM predictions WHERE site_id=?", [site_id]
        for value, operator in ((start_date, ">="), (end_date, "<=")):
            if value is not None:
                sql += f" AND target_date {operator} ?"
                args.append(validate_date(value))
        if start_date and end_date and start_date > end_date:
            raise ValidationError("start_date must not exceed end_date")
        return self._many(sql + " ORDER BY target_date,created_at,rowid", args)

    def save_operation_plan(self, record=None, **kwargs):
        return self._save("operation_plans", record, **kwargs)

    def get_operation_plan(self, plan_id):
        return self._one("SELECT * FROM operation_plans WHERE plan_id=?", (plan_id,))

    def get_operation_plan_by_prediction(self, prediction_id):
        return self._one("SELECT * FROM operation_plans WHERE prediction_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (prediction_id,))

    def save_actual_result(self, record=None, **kwargs):
        return self._save("actual_results", record, **kwargs)

    def get_actual_result(self, site_id, target_date):
        return self._one("SELECT * FROM actual_results WHERE site_id=? AND target_date=?", (site_id, validate_date(target_date)))

    def update_actual_result(self, site_id, target_date, record=None, *, actor="LEGACY_API",
                             correction_source="UNKNOWN", reason="Legacy update_actual_result call", **kwargs):
        actor, reason = nonempty(actor, "actor"), nonempty(reason, "reason")
        if correction_source not in SOURCE_TYPES:
            raise ValidationError("Invalid correction_source")
        changes = self._data(record, kwargs)
        forbidden = {"result_id", "site_id", "target_date", "created_at", "updated_at"} & set(changes)
        if forbidden:
            raise ValidationError(f"Immutable or managed fields: {sorted(forbidden)}")
        # IMMEDIATE prevents a read/modify/write race with another connection.
        with self.transaction():
            current = self.get_actual_result(site_id, target_date)
            if current is None:
                raise ValidationError("Actual result not found")
            data = self._validate("actual_results", {**current, **changes, "updated_at": utc_now()})
            names = list(changes) + ["updated_at"]
            self.connection.execute("INSERT INTO actual_correction_context VALUES (?,?,?,?)",
                                    (current["result_id"],actor,correction_source,reason))
            self.connection.execute(f"UPDATE actual_results SET {','.join(n+'=?' for n in names)} WHERE result_id=?", [data[n] for n in names] + [current["result_id"]])
            self.connection.execute("DELETE FROM actual_correction_context WHERE result_id=?", (current["result_id"],))
        return self.get_actual_result(site_id, target_date)

    def get_actual_corrections(self, site_id, target_date):
        return self._many("SELECT * FROM actual_corrections WHERE site_id=? AND target_date=? ORDER BY correction_id",
                          (site_id,validate_date(target_date)))

    def save_inventory_snapshot(self, record=None, **kwargs):
        return self._save("inventory_snapshots", record, **kwargs)

    def get_inventory_by_site(self, site_id, snapshot_date=None):
        sql, args = "SELECT * FROM inventory_snapshots WHERE site_id=?", [site_id]
        if snapshot_date is not None:
            sql += " AND snapshot_date=?"
            args.append(validate_date(snapshot_date))
        return self._many(sql + " ORDER BY snapshot_date,created_at,rowid", args)

    def save_model_version(self, record=None, **kwargs):
        return self._save("model_versions", record, **kwargs)

    def get_current_model(self):
        return self._one("SELECT * FROM model_versions WHERE status='current'")

    def list_model_versions(self):
        return self._many("SELECT * FROM model_versions ORDER BY created_at,rowid")

    def set_current_model(self, model_version):
        with self.transaction():
            target = self._one("SELECT * FROM model_versions WHERE model_version=?", (model_version,))
            if target is None:
                raise ValidationError("Model version not found")
            # Validate before archiving the existing current model.
            self._validate("model_versions", {**target, "status": "current"})
            self.connection.execute("UPDATE model_versions SET status='archived' WHERE status='current'")
            self.connection.execute("UPDATE model_versions SET status='current' WHERE model_version=?", (model_version,))
        return self.get_current_model()

    def save_decision(self, record=None, **kwargs):
        return self._save("decision_logs", record, **kwargs)

    def get_decision(self, decision_id):
        return self._one("SELECT * FROM decision_logs WHERE decision_id=?", (decision_id,))
