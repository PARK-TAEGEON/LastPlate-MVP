"""Fail-closed integration boundary with an application-supplied trusted identity verifier.

No credentials, signing keys or token contents are persisted. This is not an auth server.
"""
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4
from .models import normalize_timestamp, utc_now, to_json
from .deployments import nonempty


class AuthenticationError(PermissionError):
    pass


@dataclass(frozen=True)
class VerifiedActor:
    subject: str
    issuer: str
    verification_id: str
    authenticated_at: str
    expires_at: str
    allowed_sites: frozenset[str]
    permissions: frozenset[str]


class ActorVerifier(Protocol):
    def verify(self, credentials: object) -> VerifiedActor:
        """Authenticate with the trusted external system; raise on invalid credentials."""
        ...


def _check(actor, action, site_id):
    if not isinstance(actor, VerifiedActor):
        raise AuthenticationError("Verifier must return VerifiedActor")
    try:
        for name in ("subject", "issuer", "verification_id"):
            nonempty(getattr(actor, name), name)
        start, end = normalize_timestamp(actor.authenticated_at), normalize_timestamp(actor.expires_at)
        now = utc_now()
        if start > now or end <= now or start >= end:
            raise ValueError("expired or future assertion")
        if not isinstance(actor.allowed_sites, frozenset) or not isinstance(actor.permissions, frozenset):
            raise ValueError("immutable scopes required")
        if any(not isinstance(value, str) or not value.strip() for value in actor.allowed_sites | actor.permissions):
            raise ValueError("invalid scope values")
        if site_id not in actor.allowed_sites or action not in actor.permissions:
            raise ValueError("scope denied")
    except (ValueError, TypeError):
        raise AuthenticationError("Invalid, expired or unauthorized actor assertion") from None


class AuthenticatedIntegration:
    def __init__(self, repository, verifier: ActorVerifier):
        if verifier is None or not callable(getattr(verifier, "verify", None)):
            raise AuthenticationError("A trusted ActorVerifier is required")
        self.repository, self.verifier = repository, verifier

    def _actor(self, credentials, action, site_id):
        try:
            actor = self.verifier.verify(credentials)
        except Exception:
            raise AuthenticationError("Identity verification failed") from None
        _check(actor, action, site_id)
        return actor

    def _record(self, actor, action, site_id, target_id):
        _check(actor, action, site_id)
        attestation = {"allowed_sites": sorted(actor.allowed_sites), "permissions": sorted(actor.permissions)}
        self.repository.connection.execute('''INSERT INTO integration_actor_events
            (event_id,action,site_id,target_id,subject,issuer,verification_id,authenticated_at,expires_at,recorded_at,attestation_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (str(uuid4()),action,site_id,target_id,actor.subject,actor.issuer,actor.verification_id,
                normalize_timestamp(actor.authenticated_at),normalize_timestamp(actor.expires_at),utc_now(),to_json(attestation)))

    def update_actual_result(self, credentials, site_id, target_date, record=None, *, reason,
                             correction_source="USER_UPLOAD", **changes):
        if "actor" in changes:
            raise AuthenticationError("Actor override is not permitted")
        principal = self._actor(credentials, "correction:write", site_id)
        with self.repository.transaction():
            _check(principal, "correction:write", site_id)
            row = self.repository.update_actual_result(site_id,target_date,record,actor=principal.subject,
                reason=reason,correction_source=correction_source,**changes)
            event = self.repository.get_actual_corrections(site_id,target_date)[-1]
            self._record(principal,"correction:write",site_id,event["audit_id"])
        return row

    def deploy_model(self, credentials, site_id, model_version, model_role="demand", *, reason, **options):
        if "actor" in options:
            raise AuthenticationError("Actor override is not permitted")
        principal = self._actor(credentials, "deployment:write", site_id)
        with self.repository.transaction():
            _check(principal, "deployment:write", site_id)
            row = self.repository.deploy_model(site_id,model_version,model_role,actor=principal.subject,reason=reason,**options)
            self._record(principal,"deployment:write",site_id,row["deployment_id"])
        return row

    def retire_deployment(self, credentials, deployment_id, *, reason, retired_at=None):
        row = self.repository.get_deployment(deployment_id)
        if row is None:
            raise AuthenticationError("Deployment unavailable")
        site_id = row["site_id"]
        principal = self._actor(credentials,"deployment:retire",site_id)
        with self.repository.transaction():
            _check(principal,"deployment:retire",site_id)
            row = self.repository.retire_deployment(deployment_id,actor=principal.subject,reason=reason,retired_at=retired_at)
            self._record(principal,"deployment:retire",site_id,deployment_id)
        return row


def get_integration_actor_events(repository, site_id=None):
    return repository._many("SELECT * FROM integration_actor_events WHERE (? IS NULL OR site_id=?) ORDER BY recorded_at,rowid", (site_id,site_id))
