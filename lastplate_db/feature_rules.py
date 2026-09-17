"""Optional declarative rules: JSON Pointer paths, no code execution."""
import math
import re
from .models import ValidationError, to_json

RULE_LANGUAGE_VERSION = "lastplate-rules/v1"
TYPES = ("number", "integer", "string", "boolean", "object", "array")
MISSING = object()


def matches_type(value, kind):
    if kind == "number":
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    return {"integer": type(value) is int, "string": isinstance(value, str) and bool(value.strip()),
            "boolean": type(value) is bool, "object": isinstance(value, dict), "array": isinstance(value, list)}.get(kind, False)


def pointer_parts(path):
    if not isinstance(path, str) or not path.startswith("/") or re.search(r"~(?![01])", path):
        raise ValidationError("rule path must be an RFC 6901 JSON Pointer beginning with /")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def validate_rules(version, rules):
    if version is None and rules is None:
        return []
    if version != RULE_LANGUAGE_VERSION or not isinstance(rules, list) or not rules:
        raise ValidationError("rules require lastplate-rules/v1 and a nonempty rule list")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - {"path", "type", "required", "nullable", "minimum", "maximum", "enum"}:
            raise ValidationError("Invalid or unknown rule fields")
        path, kind = rule.get("path"), rule.get("type")
        pointer_parts(path)
        if path in seen or kind not in TYPES:
            raise ValidationError("Duplicate rule path or unsupported rule type")
        seen.add(path)
        for option in ("required", "nullable"):
            if option in rule and type(rule[option]) is not bool:
                raise ValidationError(f"{option} must be bool")
        for option in ("minimum", "maximum"):
            if option in rule and (kind not in ("number", "integer") or not matches_type(rule[option], "number")):
                raise ValidationError("Numeric ranges require finite numeric bounds and a numeric type")
        if "minimum" in rule and "maximum" in rule and rule["minimum"] > rule["maximum"]:
            raise ValidationError("minimum exceeds maximum")
        if "enum" in rule:
            vocabulary = rule["enum"]
            if not isinstance(vocabulary, list) or not vocabulary or kind in ("object", "array"):
                raise ValidationError("enum requires a nonempty scalar vocabulary")
            for value in vocabulary:
                if value is None:
                    if not rule.get("nullable", False):
                        raise ValidationError("null vocabulary item requires nullable")
                elif not matches_type(value, kind):
                    raise ValidationError("enum value does not match declared type")
            to_json(vocabulary)
    return rules


def evaluate_rules(snapshot, rules):
    errors = []
    for rule in rules:
        value = snapshot
        for part in pointer_parts(rule["path"]):
            if isinstance(value, dict):
                value = value.get(part, MISSING)
            elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
                index = int(part)
                value = value[index] if index < len(value) else MISSING
            else:
                value = MISSING
            if value is MISSING:
                break
        problem = None
        if value is MISSING:
            if rule.get("required", True):
                problem = "missing_required"
        elif value is None:
            if not rule.get("nullable", False):
                problem = "null_not_allowed"
            elif "enum" in rule and None not in rule["enum"]:
                problem = "not_in_vocabulary"
        elif not matches_type(value, rule["type"]):
            problem = "type_mismatch"
        elif "minimum" in rule and value < rule["minimum"]:
            problem = "below_minimum"
        elif "maximum" in rule and value > rule["maximum"]:
            problem = "above_maximum"
        elif "enum" in rule and value not in rule["enum"]:
            problem = "not_in_vocabulary"
        if problem:
            errors.append({"path": rule["path"], "error": problem})
    return errors
