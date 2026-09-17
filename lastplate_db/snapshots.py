"""Versioned top-level feature contracts and explicit extraction diagnostics."""
import math
from .models import ValidationError, to_json, from_json, utc_now, normalize_timestamp
from .deployments import nonempty
from .feature_rules import validate_rules, evaluate_rules

FEATURE_TYPES = ("number", "integer", "string", "boolean", "object", "array")


def validate_definition(required_features, *, allow_empty=False):
    if not isinstance(required_features, dict) or (not required_features and not allow_empty):
        raise ValidationError("required_features must be a nonempty {feature_name: type} mapping")
    for name, kind in required_features.items():
        nonempty(name, "feature name")
        if kind not in FEATURE_TYPES:
            raise ValidationError(f"Unsupported feature type for {name}")
    return required_features


class FeatureSchemaMixin:
    def register_feature_schema(self, feature_schema_version, required_features, *, description=None,
                                rule_language_version=None, rules=None):
        version = nonempty(feature_schema_version, "feature_schema_version")
        checked_rules = validate_rules(rule_language_version, rules)
        encoded = to_json(validate_definition(required_features, allow_empty=bool(checked_rules)))
        if description is not None:
            nonempty(description, "description")
        with self.transaction():
            self.connection.execute("INSERT INTO feature_schemas(feature_schema_version,required_features_json,description,created_at,rule_language_version,rules_json) "
                                    "VALUES (?,?,?,?,?,?)", (version,encoded,description,utc_now(),rule_language_version,to_json(rules) if rules is not None else None))
        return self.get_feature_schema(version)

    def get_feature_schema(self, feature_schema_version):
        return self._one("SELECT * FROM feature_schemas WHERE feature_schema_version=?", (feature_schema_version,))

    def list_feature_schemas(self):
        return self._many("SELECT * FROM feature_schemas ORDER BY created_at,rowid")


def validate_input_snapshot(repository, prediction):
    """Recompute; never trust a caller-provided/stored validation report."""
    errors, missing, type_errors = [], [], []
    version = prediction.get("feature_schema_version")
    schema = repository.get_feature_schema(version) if version else None
    if not version:
        errors.append("missing feature_schema_version")
    elif schema is None:
        errors.append("unknown feature_schema_version")
    if not isinstance(prediction.get("source_lineage_id"), str) or not prediction["source_lineage_id"].strip():
        errors.append("missing source_lineage_id")
    try:
        observed = normalize_timestamp(prediction.get("observed_at"))
        if observed > normalize_timestamp(prediction.get("created_at")):
            errors.append("observed_at is after prediction created_at")
    except ValidationError:
        errors.append("missing or invalid observed_at/created_at")
    snapshot = prediction.get("input_snapshot_json")
    if isinstance(snapshot, str):
        try:
            snapshot = from_json(snapshot)
        except ValidationError:
            snapshot = None
    if not isinstance(snapshot, dict):
        errors.append("input_snapshot_json must be an object")
        snapshot = {}
    definitions, rule_errors = {}, []
    if schema is not None:
        try:
            rules = validate_rules(schema.get("rule_language_version"), schema.get("rules_json"))
            definitions = validate_definition(schema["required_features_json"], allow_empty=bool(rules))
            rule_errors = evaluate_rules(snapshot, rules)
        except ValidationError:
            errors.append("invalid feature schema definition")
    for name, kind in definitions.items():
        value = snapshot.get(name)
        if value is None:
            missing.append(name)
            continue
        matches = {"integer": type(value) is int, "string": isinstance(value, str) and bool(value.strip()),
                   "boolean": type(value) is bool, "object": isinstance(value, dict), "array": isinstance(value, list)}
        try:
            matches["number"] = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            matches["number"] = False
        if not matches[kind]:
            type_errors.append({"feature": name, "expected": kind})
    missing.extend(item["path"] for item in rule_errors if item["error"] == "missing_required")
    return {"valid": not (errors or missing or type_errors or rule_errors), "feature_schema_version": version,
            "missing_required_features": sorted(missing), "type_errors": type_errors, "metadata_errors": errors,
            "rule_errors": rule_errors}
