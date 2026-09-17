import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from lastplate_db import (Repository, ValidationError, get_training_dataset, get_dashboard_readiness,
    get_site_role_deployment_report, AuthenticatedIntegration, VerifiedActor, AuthenticationError,
    get_integration_actor_events, RULE_LANGUAGE_VERSION)


def setup_rows(repo, *, site="s", version="features-1", snapshot=None):
    if repo.get_feature_schema(version) is None:
        repo.register_feature_schema(version, {"population": "number"})
    p = repo.save_prediction(site_id=site,target_date="2026-01-02",predicted_diners=100,
        source_type="MODEL",record_status="VALIDATED",feature_schema_version=version,
        observed_at="2026-01-02T09:00:00Z",created_at="2026-01-02T10:00:00Z",source_lineage_id="upload-1",
        input_snapshot_json={"population": 200} if snapshot is None else snapshot)
    a = repo.save_actual_result(site_id=site,target_date="2026-01-02",actual_diners=95,
        source_type="USER_UPLOAD",record_status="VALIDATED",created_at="2026-01-02T12:00:00Z")
    return p, a


def model(repo, version="model-1", **kwargs):
    return repo.save_model_version(model_version=version,model_type="x",source_type="MODEL",record_status="VALIDATED",**kwargs)


def manifest(repo, **kwargs):
    options = dict(data_cutoff="2026-01-03T00:00:00Z",code_artifact_id="git:abc",data_artifact_id="export:123")
    options.update(kwargs)
    return repo.create_training_manifest("model-1","features-1",**options)


def test_training_manifest_freezes_rows_counts_artifacts_and_digest(repo):
    p, a = setup_rows(repo)
    model(repo)
    run = manifest(repo)
    assert run["run_status"] == "EXPORTED"
    assert (run["candidate_count"],run["accepted_count"],run["rejected_count"]) == (1,1,0)
    assert run["code_artifact_id"] == "git:abc" and run["data_artifact_id"] == "export:123"
    rows = repo.get_training_manifest_rows(run["training_run_id"])
    assert rows[0]["prediction_id"] == p["prediction_id"] and rows[0]["actual_result_id"] == a["result_id"]
    assert rows[0]["row_json"]["actual_diners"] == 95
    assert repo.verify_training_manifest(run["training_run_id"])
    repo.update_actual_result("s","2026-01-02",actual_diners=99)
    assert repo.get_training_manifest_rows(run["training_run_id"])[0]["row_json"]["actual_diners"] == 95
    assert repo.verify_training_manifest(run["training_run_id"])
    assert manifest(repo)["accepted_count"] == 0  # A later correction cannot be exported as a past label.


def test_manifest_cutoff_selection_and_rejected_snapshot_counts(repo):
    p, _ = setup_rows(repo,snapshot={})
    model(repo)
    run = manifest(repo,selection_policy="explicit",prediction_ids={p["prediction_id"]})
    assert run["accepted_count"] == 0 and run["rejected_count"] == 1
    assert run["manifest_json"]["rejected_records"][0]["validation_result"]["missing_required_features"] == ["population"]
    assert run["row_selection_policy_json"]["prediction_ids"] == [p["prediction_id"]]
    assert manifest(repo,data_cutoff="2026-01-02T11:00:00Z")["candidate_count"] == 0


def test_manifest_immutability_raw_sql_and_references(repo):
    setup_rows(repo)
    model(repo)
    run = manifest(repo)
    for sql in ("UPDATE training_runs SET run_status='COMPLETED'", "DELETE FROM training_runs",
        "INSERT OR REPLACE INTO training_runs SELECT * FROM training_runs", "DELETE FROM training_manifest_rows",
        "UPDATE training_manifest_rows SET row_json='{}'", "DELETE FROM predictions", "DELETE FROM model_versions"):
        with pytest.raises(sqlite3.DatabaseError):
            with repo.transaction():
                repo.connection.execute(sql)
    assert repo.get_training_run(run["training_run_id"]) == run
    with pytest.raises(sqlite3.IntegrityError):
        manifest(repo,training_run_id=run["training_run_id"])


def test_raw_manifest_insert_checks_counts_and_eligibility(repo):
    setup_rows(repo)
    model(repo)
    run = manifest(repo)
    for change in ({"accepted_count": 2}, {"model_version": "absent"}, {"feature_schema_version": "absent"},
        {"data_cutoff": "2026-01-02T11:00:00.000000+00:00"}):
        data = {**run, "training_run_id": "forged", **change}
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction():
                repo.connection.execute(f"INSERT INTO training_runs({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
                    [json.dumps(v) if k.endswith("_json") else v for k,v in data.items()])
    forged = json.loads(json.dumps(run))
    forged["training_run_id"] = "false-label"
    forged["manifest_json"]["records"][0]["actual_diners"] = 999
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute(f"INSERT INTO training_runs({','.join(forged)}) VALUES ({','.join('?' for _ in forged)})",
                [json.dumps(v) if k.endswith("_json") else v for k,v in forged.items()])


def test_manifest_and_schema_version_mismatch_is_reported(repo):
    setup_rows(repo,version="other")
    repo.register_feature_schema("features-1", {"population": "number"})
    model(repo)
    run = manifest(repo)
    assert run["rejected_count"] == 1
    assert "differs" in run["manifest_json"]["rejected_records"][0]["validation_result"]["metadata_errors"][0]
    with pytest.raises(RuntimeError):
        with repo.transaction():
            manifest(repo,training_run_id="rollback")
            raise RuntimeError("abort")
    assert repo.get_training_run("rollback") is None


RULES = [
    {"path": "/weather/temperature", "type": "number", "minimum": -50, "maximum": 60},
    {"path": "/menu/category", "type": "string", "enum": ["A", "B"]},
    {"path": "/optional_note", "type": "string", "required": False, "nullable": True},
    {"path": "/items/0/quantity", "type": "integer", "minimum": 0},
]
VALID = {"weather": {"temperature": 20}, "menu": {"category": "A"}, "items": [{"quantity": 1}], "optional_note": None}


def rule_prediction(repo, snapshot):
    return repo.save_prediction(site_id="s",target_date="2026-01-02",predicted_diners=100,
        feature_schema_version="nested",observed_at="2026-01-02T09:00:00Z",created_at="2026-01-02T10:00:00Z",
        source_lineage_id="feed",input_snapshot_json=snapshot,source_type="MODEL",record_status="VALIDATED")


def test_nested_rules_nullable_range_vocabulary_and_legacy(repo):
    repo.register_feature_schema("nested", {},rule_language_version=RULE_LANGUAGE_VERSION,rules=RULES)
    assert rule_prediction(repo,VALID)["snapshot_validation_json"]["valid"]
    without_note = {k:v for k,v in VALID.items() if k != "optional_note"}
    assert rule_prediction(repo,without_note)["snapshot_validation_json"]["valid"]
    repo.register_feature_schema("old", {"x": "integer"})
    assert repo.get_feature_schema("old")["rules_json"] is None
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute("UPDATE feature_schemas SET rules_json='[]'")


@pytest.mark.parametrize("snapshot,error", [
    ({**VALID, "weather": {}}, "missing_required"),
    ({**VALID, "weather": {"temperature": None}}, "null_not_allowed"),
    ({**VALID, "weather": {"temperature": -51}}, "below_minimum"),
    ({**VALID, "weather": {"temperature": 61}}, "above_maximum"),
    ({**VALID, "weather": {"temperature": True}}, "type_mismatch"),
    ({**VALID, "menu": {"category": "C"}}, "not_in_vocabulary"),
    ({**VALID, "items": []}, "missing_required"),
])
def test_rule_diagnostics(repo,snapshot,error):
    repo.register_feature_schema("nested", {},rule_language_version=RULE_LANGUAGE_VERSION,rules=RULES)
    report = rule_prediction(repo,snapshot)["snapshot_validation_json"]
    assert not report["valid"]
    assert error in [r["error"] for r in report["rule_errors"]]


@pytest.mark.parametrize("rules,version", [
    (RULES, "unknown/v2"), ([], RULE_LANGUAGE_VERSION),
    ([{"path":"x","type":"number"}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x~2","type":"number"}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x","type":"number","minimum":2,"maximum":1}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x","type":"string","minimum":1}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x","type":"number","nullable":"yes"}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x","type":"number","enum":["bad"]}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x","type":"string","enum":[None]}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x","type":"string","execute":"x"}], RULE_LANGUAGE_VERSION),
    ([{"path":"/x","type":"string"}]*2, RULE_LANGUAGE_VERSION),
])
def test_rule_registration_rejects_invalid_language(repo,rules,version):
    with pytest.raises(ValidationError):
        repo.register_feature_schema("bad",{},rule_language_version=version,rules=rules)


def test_json_pointer_escapes_and_nullable_required(repo):
    repo.register_feature_schema("nested",{},rule_language_version=RULE_LANGUAGE_VERSION,
        rules=[{"path":"/a~1b/~0key","type":"number","nullable":True}])
    assert rule_prediction(repo,{"a/b":{"~key":None}})["snapshot_validation_json"]["valid"]
    assert not rule_prediction(repo,{"a/b":{}})["snapshot_validation_json"]["valid"]


def test_raw_rule_pair_validation(repo):
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute("INSERT INTO feature_schemas(feature_schema_version,required_features_json,created_at,rule_language_version,rules_json) VALUES ('bad','{}','now','unknown','[]')")


def test_multisite_cutoff_report_keeps_readiness_trained_at_semantics(repo):
    setup_rows(repo)
    repo.create_site(site_id="b",site_name="B")
    setup_rows(repo,site="b")
    model(repo,trained_at="2026-01-04T00:00:00Z")
    run = manifest(repo)
    repo.deploy_model("s","model-1",actor="local",reason="release",effective_at="2026-01-05T00:00:00Z",training_run_id=run["training_run_id"])
    repo.deploy_model("b","model-1",actor="local",reason="release",effective_at="2026-01-06T00:00:00Z",training_data_cutoff="2026-01-01T00:00:00Z")
    first,second = [get_site_role_deployment_report(repo,site) for site in ("s","b")]
    assert first["model_trained_at"].startswith("2026-01-04")
    assert first["deployment_effective_at"].startswith("2026-01-05")
    assert first["training_data_cutoff"].startswith("2026-01-03")
    assert first["training_cutoff_source"] == "manifest"
    assert second["training_data_cutoff"].startswith("2026-01-01") and second["training_cutoff_source"] == "explicit"
    assert not get_dashboard_readiness(repo,"s",1)["ready"] and not get_dashboard_readiness(repo,"b",1)["ready"]
    assert get_site_role_deployment_report(repo,"s","other")["training_data_cutoff"] is None
    with pytest.raises(ValidationError):
        repo.deploy_model("s","model-1",actor="x",reason="bad",training_run_id=run["training_run_id"],training_data_cutoff="2026-01-01T00:00:00Z")
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction():
            repo.connection.execute("UPDATE model_deployments SET training_data_cutoff='2026-01-01T00:00:00.000000+00:00' WHERE site_id='s'")


def principal(**extra):
    now = datetime.now(timezone.utc)
    values = dict(subject="verified-subject",issuer="test-idp",verification_id="check-123",
        authenticated_at=(now-timedelta(minutes=1)).isoformat(),expires_at=(now+timedelta(minutes=10)).isoformat(),
        allowed_sites=frozenset({"s"}),permissions=frozenset({"correction:write","deployment:write","deployment:retire"}))
    values.update(extra)
    return VerifiedActor(**values)


class FakeTrustedVerifier:
    def __init__(self, actor):
        self.actor = actor
    def verify(self, credentials):
        if credentials != "valid-secret":
            raise ValueError("SECRET must not be exposed")
        return self.actor


def test_authenticated_hooks_use_verified_actor_and_preserve_offline_calls(repo):
    setup_rows(repo)
    model(repo)
    api = AuthenticatedIntegration(repo,FakeTrustedVerifier(principal()))
    api.update_actual_result("valid-secret","s","2026-01-02",actual_diners=96,reason="review")
    deployed = api.deploy_model("valid-secret","s","model-1",reason="reviewed")
    api.retire_deployment("valid-secret",deployed["deployment_id"],reason="withdraw")
    events = get_integration_actor_events(repo,"s")
    assert len(events) == 3 and all(e["subject"] == "verified-subject" for e in events)
    assert "valid-secret" not in json.dumps(events)
    assert repo.get_actual_corrections("s","2026-01-02")[0]["actor"] == "verified-subject"
    repo.update_actual_result("s","2026-01-02",actual_diners=97,actor="offline",reason="local")
    assert len(get_integration_actor_events(repo)) == 3
    for sql in ("UPDATE integration_actor_events SET subject='fake'", "DELETE FROM integration_actor_events",
                "INSERT OR REPLACE INTO integration_actor_events SELECT * FROM integration_actor_events"):
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction():
                repo.connection.execute(sql)


@pytest.mark.parametrize("identity", [None, "claimed-actor", principal(allowed_sites=frozenset({"other"})),
    principal(permissions=frozenset()), principal(expires_at="2020-01-01T00:00:00Z")])
def test_authentication_fail_closed_without_mutation(repo,identity):
    _,original = setup_rows(repo)
    api = AuthenticatedIntegration(repo,FakeTrustedVerifier(identity))
    with pytest.raises(AuthenticationError):
        api.update_actual_result("valid-secret","s","2026-01-02",actual_diners=99,reason="bad")
    assert repo.get_actual_result("s","2026-01-02") == original
    assert repo.get_actual_corrections("s","2026-01-02") == []


def test_auth_failure_and_override_do_not_expose_credentials(repo):
    setup_rows(repo)
    api = AuthenticatedIntegration(repo,FakeTrustedVerifier(principal()))
    with pytest.raises(AuthenticationError,match="Identity verification failed") as error:
        api.update_actual_result("invalid-secret","s","2026-01-02",reason="test",actual_diners=1)
    assert "SECRET" not in str(error.value)
    with pytest.raises(AuthenticationError,match="override"):
        api.update_actual_result("valid-secret","s","2026-01-02",reason="test",actor="spoof",actual_diners=1)


def test_auth_event_failure_rolls_back_correction_and_audit(repo):
    _,original = setup_rows(repo)
    api = AuthenticatedIntegration(repo,FakeTrustedVerifier(principal()))
    repo.connection.execute("CREATE TRIGGER fail_attestation BEFORE INSERT ON integration_actor_events BEGIN SELECT RAISE(ABORT,'attestation storage failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        api.update_actual_result("valid-secret","s","2026-01-02",reason="test",actual_diners=99)
    assert repo.get_actual_result("s","2026-01-02") == original
    assert repo.get_actual_corrections("s","2026-01-02") == []


def test_raw_deployment_training_reference_mismatch_and_no_mutation(repo):
    setup_rows(repo)
    model(repo)
    model(repo,"other")
    run = manifest(repo)
    first = repo.deploy_model("s","model-1",actor="local",reason="first",training_run_id=run["training_run_id"])
    with pytest.raises(sqlite3.IntegrityError,match="lineage mismatch"):
        with repo.transaction():
            repo.connection.execute('''INSERT INTO model_deployments
                (deployment_id,site_id,model_version,model_role,status,effective_at,created_at,actor,reason,source_type,is_demo,record_status,training_run_id,training_data_cutoff)
                VALUES ('bad','s','other','different','current','2026-01-05T00:00:00.000000+00:00','2026-01-05T00:00:00.000000+00:00','x','bad','MANUAL',0,'VALIDATED',?,?)''',
                (run["training_run_id"],run["data_cutoff"]))
    assert repo.get_current_deployment("s") == first


def test_auth_deployment_event_failure_restores_previous_deployment(repo):
    model(repo)
    model(repo,"other")
    original = repo.deploy_model("s","model-1",actor="offline",reason="first")
    api = AuthenticatedIntegration(repo,FakeTrustedVerifier(principal()))
    repo.connection.execute("CREATE TRIGGER fail_attestation BEFORE INSERT ON integration_actor_events BEGIN SELECT RAISE(ABORT,'event failed'); END")
    with pytest.raises(sqlite3.IntegrityError):
        api.deploy_model("valid-secret","s","other",reason="replace")
    assert repo.get_current_deployment("s") == original
    assert len(repo.list_model_deployments()) == 1


def test_manifest_export_and_correction_concurrency_never_mix_labels(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path = tmp_path/"concurrent-manifest.db"
    with Repository(path) as r:
        r.create_site(site_id="s",site_name="S")
        setup_rows(r)
        model(r)
    cutoff = datetime.now(timezone.utc).isoformat()
    barrier = Barrier(2)
    def worker(export):
        with Repository(path) as r:
            barrier.wait(timeout=10)
            if export:
                return manifest(r,data_cutoff=cutoff)
            r.update_actual_result("s","2026-01-02",actual_diners=999,reason="new label")
    with ThreadPoolExecutor(max_workers=2) as pool:
        run,_ = list(pool.map(worker,(True,False)))
    assert run["accepted_count"] in (0,1)
    assert all(row["actual_diners"] == 95 for row in run["manifest_json"]["records"])
    with Repository(path) as r:
        assert r.verify_training_manifest(run["training_run_id"])
