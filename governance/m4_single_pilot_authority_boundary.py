from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import re


class AuthorityStatus(str, Enum):
    AUTHORIZATION_EVIDENCE_VALID_FOR_SEPARATE_SINGLE_DISPATCH = "AUTHORIZATION_EVIDENCE_VALID_FOR_SEPARATE_SINGLE_DISPATCH"
    BLOCKED_PREFLIGHT = "BLOCKED_PREFLIGHT"
    BLOCKED_AUTHENTICITY = "BLOCKED_AUTHENTICITY"
    BLOCKED_REVOKED = "BLOCKED_REVOKED"
    BLOCKED_TEMPORAL = "BLOCKED_TEMPORAL"
    BLOCKED_NOT_SINGLE_USE = "BLOCKED_NOT_SINGLE_USE"
    BLOCKED_ALREADY_CONSUMED = "BLOCKED_ALREADY_CONSUMED"
    BLOCKED_SCOPE_MISMATCH = "BLOCKED_SCOPE_MISMATCH"
    BLOCKED_WILDCARD_SCOPE = "BLOCKED_WILDCARD_SCOPE"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class PilotIntent:
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    target_adapter: str
    adapter_contract_drive_id: str
    adapter_contract_sha256: str
    action_class: str
    expected_repository: str
    expected_workflow_id: int
    expected_event: str
    expected_ref: str
    expected_head_sha: str
    exact_run_name_token: str
    outcome_contract_drive_id: str
    outcome_contract_sha256: str
    expected_artifact_name: str
    expected_outcome_path: str
    outcome_schema: str
    preflight_contract_drive_id: str
    preflight_contract_sha256: str


@dataclass(frozen=True)
class PreflightEvidence:
    status: str
    observed_at: datetime
    source_health: str
    preflight_contract_drive_id: str
    preflight_contract_sha256: str
    snapshot_sha256: str


@dataclass(frozen=True)
class OwnerAuthorizationEvidence:
    source_kind: str
    authority_level: str
    verification_state: str
    source_health: str
    source_ref: str
    source_evidence_sha256: str
    source_verified_at: datetime
    grant_id: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool
    max_dispatches: int
    used_dispatches: int
    preflight_snapshot_sha256: str
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    target_adapter: str
    adapter_contract_drive_id: str
    adapter_contract_sha256: str
    action_class: str
    expected_repository: str
    expected_workflow_id: int
    expected_event: str
    expected_ref: str
    expected_head_sha: str
    exact_run_name_token: str
    outcome_contract_drive_id: str
    outcome_contract_sha256: str
    expected_artifact_name: str
    expected_outcome_path: str
    outcome_schema: str
    preflight_contract_drive_id: str
    preflight_contract_sha256: str


@dataclass(frozen=True)
class AuthorityDecision:
    status: AuthorityStatus
    reason: str
    valid: bool = False
    dispatch_executed: bool = False
    claim_executed: bool = False
    retry_executed: bool = False
    write_executed: bool = False
    authority_created: bool = False
    real_dispatch_authority: str = "NOT_GRANTED"


_PREFLIGHT_STATUS = "READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT"
_PREFLIGHT_CONTRACT_ID = "1pOcZzNBuEZwIFpAPc3JCduv27RsvL1P2P3-Bwc2kDrM"
_PREFLIGHT_CONTRACT_SHA = "0e05fb767927a72508556363a507a6261ddf0bc5c1c4b655c4d16953f4362c11"
_ALLOWED_ACTIONS = frozenset({"INTERNAL_CONTINUE", "INTERNAL_RECOVERY"})
_REQUIRED_SOURCE_KIND = "EXPLICIT_THOMAS_OWNER_AUTHORIZATION"
_REQUIRED_AUTHORITY_LEVEL = "A5_OWNER_EXPLICIT_SINGLE_PILOT"
_REQUIRED_VERIFICATION_STATE = "VERIFIED_OWNER_SOURCE"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_CLOCK_SKEW = timedelta(seconds=30)
_MAX_PREFLIGHT_AGE = timedelta(minutes=10)
_MAX_AUTH_SOURCE_AGE = timedelta(minutes=5)
_MAX_GRANT_TTL = timedelta(minutes=30)


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value))


def _wild(value: str) -> bool:
    stripped = value.strip()
    upper = stripped.upper()
    return "*" in stripped or "?" in stripped or upper in {"ANY", "ALL", "WILDCARD"}


def _intent_strings(intent: PilotIntent) -> tuple[str, ...]:
    return (
        intent.home_system,
        intent.work_id,
        intent.dedupe_key,
        intent.target,
        intent.target_adapter,
        intent.adapter_contract_drive_id,
        intent.adapter_contract_sha256,
        intent.action_class,
        intent.expected_repository,
        intent.expected_event,
        intent.expected_ref,
        intent.expected_head_sha,
        intent.exact_run_name_token,
        intent.outcome_contract_drive_id,
        intent.outcome_contract_sha256,
        intent.expected_artifact_name,
        intent.expected_outcome_path,
        intent.outcome_schema,
        intent.preflight_contract_drive_id,
        intent.preflight_contract_sha256,
    )


def _scope_pairs(intent: PilotIntent, grant: OwnerAuthorizationEvidence) -> tuple[tuple[object, object], ...]:
    return (
        (intent.home_system, grant.home_system),
        (intent.work_id, grant.work_id),
        (intent.dedupe_key, grant.dedupe_key),
        (intent.target, grant.target),
        (intent.target_adapter, grant.target_adapter),
        (intent.adapter_contract_drive_id, grant.adapter_contract_drive_id),
        (intent.adapter_contract_sha256, grant.adapter_contract_sha256),
        (intent.action_class, grant.action_class),
        (intent.expected_repository, grant.expected_repository),
        (intent.expected_workflow_id, grant.expected_workflow_id),
        (intent.expected_event, grant.expected_event),
        (intent.expected_ref, grant.expected_ref),
        (intent.expected_head_sha, grant.expected_head_sha),
        (intent.exact_run_name_token, grant.exact_run_name_token),
        (intent.outcome_contract_drive_id, grant.outcome_contract_drive_id),
        (intent.outcome_contract_sha256, grant.outcome_contract_sha256),
        (intent.expected_artifact_name, grant.expected_artifact_name),
        (intent.expected_outcome_path, grant.expected_outcome_path),
        (intent.outcome_schema, grant.outcome_schema),
        (intent.preflight_contract_drive_id, grant.preflight_contract_drive_id),
        (intent.preflight_contract_sha256, grant.preflight_contract_sha256),
    )


def validate_single_pilot_authority(
    intent: PilotIntent,
    preflight: PreflightEvidence,
    grant: OwnerAuthorizationEvidence,
    *,
    as_of: datetime,
) -> AuthorityDecision:
    """Validate evidence of a separately-issued exact owner grant.

    This function cannot create authority or perform a dispatch. A VALID result
    only permits a separate one-shot dispatcher layer to continue its own gates.
    """
    if not _aware(as_of):
        return AuthorityDecision(AuthorityStatus.FAIL_CLOSED, "as_of_timezone_required")

    if not all(_nonblank(v) for v in _intent_strings(intent)):
        return AuthorityDecision(AuthorityStatus.FAIL_CLOSED, "intent_field_missing")
    if not isinstance(intent.expected_workflow_id, int) or isinstance(intent.expected_workflow_id, bool) or intent.expected_workflow_id <= 0:
        return AuthorityDecision(AuthorityStatus.FAIL_CLOSED, "workflow_id_invalid")
    if intent.action_class not in _ALLOWED_ACTIONS:
        return AuthorityDecision(AuthorityStatus.BLOCKED_SCOPE_MISMATCH, "intent_action_not_internal")
    if not _sha(intent.adapter_contract_sha256) or not _sha(intent.outcome_contract_sha256) or not _sha(intent.preflight_contract_sha256):
        return AuthorityDecision(AuthorityStatus.FAIL_CLOSED, "intent_contract_hash_invalid")

    if any(_wild(v) for v in _intent_strings(intent)):
        return AuthorityDecision(AuthorityStatus.BLOCKED_WILDCARD_SCOPE, "intent_contains_wildcard_scope")

    if preflight.status != _PREFLIGHT_STATUS or preflight.source_health != "FRESH":
        return AuthorityDecision(AuthorityStatus.BLOCKED_PREFLIGHT, "preflight_not_ready_or_fresh")
    if (
        preflight.preflight_contract_drive_id != _PREFLIGHT_CONTRACT_ID
        or preflight.preflight_contract_sha256 != _PREFLIGHT_CONTRACT_SHA
        or intent.preflight_contract_drive_id != _PREFLIGHT_CONTRACT_ID
        or intent.preflight_contract_sha256 != _PREFLIGHT_CONTRACT_SHA
    ):
        return AuthorityDecision(AuthorityStatus.BLOCKED_SCOPE_MISMATCH, "preflight_contract_mismatch")
    if not _sha(preflight.snapshot_sha256) or not _aware(preflight.observed_at):
        return AuthorityDecision(AuthorityStatus.BLOCKED_PREFLIGHT, "preflight_evidence_invalid")
    preflight_age = as_of - preflight.observed_at
    if preflight_age > _MAX_PREFLIGHT_AGE or preflight_age < -_CLOCK_SKEW:
        return AuthorityDecision(AuthorityStatus.BLOCKED_PREFLIGHT, "preflight_not_fresh_at_authority_check")

    if (
        grant.source_kind != _REQUIRED_SOURCE_KIND
        or grant.authority_level != _REQUIRED_AUTHORITY_LEVEL
        or grant.verification_state != _REQUIRED_VERIFICATION_STATE
        or grant.source_health != "FRESH"
    ):
        return AuthorityDecision(AuthorityStatus.BLOCKED_AUTHENTICITY, "owner_single_pilot_source_not_verified")
    if not _nonblank(grant.source_ref) or not _sha(grant.source_evidence_sha256) or not _nonblank(grant.grant_id):
        return AuthorityDecision(AuthorityStatus.BLOCKED_AUTHENTICITY, "owner_evidence_identity_missing")
    if _wild(grant.source_ref) or _wild(grant.grant_id):
        return AuthorityDecision(AuthorityStatus.BLOCKED_WILDCARD_SCOPE, "grant_identity_contains_wildcard")
    if not _aware(grant.source_verified_at) or not _aware(grant.issued_at) or not _aware(grant.expires_at):
        return AuthorityDecision(AuthorityStatus.BLOCKED_TEMPORAL, "authorization_time_timezone_required")
    source_age = as_of - grant.source_verified_at
    if source_age > _MAX_AUTH_SOURCE_AGE or source_age < -_CLOCK_SKEW:
        return AuthorityDecision(AuthorityStatus.BLOCKED_AUTHENTICITY, "authorization_source_not_fresh")

    if grant.revoked:
        return AuthorityDecision(AuthorityStatus.BLOCKED_REVOKED, "grant_revoked")
    if not isinstance(grant.max_dispatches, int) or isinstance(grant.max_dispatches, bool) or grant.max_dispatches != 1:
        return AuthorityDecision(AuthorityStatus.BLOCKED_NOT_SINGLE_USE, "max_dispatches_must_equal_one")
    if not isinstance(grant.used_dispatches, int) or isinstance(grant.used_dispatches, bool) or grant.used_dispatches < 0:
        return AuthorityDecision(AuthorityStatus.FAIL_CLOSED, "used_dispatches_invalid")
    if grant.used_dispatches >= 1:
        return AuthorityDecision(AuthorityStatus.BLOCKED_ALREADY_CONSUMED, "single_use_grant_already_consumed")

    if grant.expires_at <= grant.issued_at or grant.expires_at - grant.issued_at > _MAX_GRANT_TTL:
        return AuthorityDecision(AuthorityStatus.BLOCKED_TEMPORAL, "grant_ttl_invalid")
    if grant.issued_at < preflight.observed_at - _CLOCK_SKEW:
        return AuthorityDecision(AuthorityStatus.BLOCKED_TEMPORAL, "grant_predates_exact_preflight")
    if grant.issued_at > as_of + _CLOCK_SKEW:
        return AuthorityDecision(AuthorityStatus.BLOCKED_TEMPORAL, "grant_issued_in_future")
    if as_of < grant.issued_at - _CLOCK_SKEW or as_of > grant.expires_at:
        return AuthorityDecision(AuthorityStatus.BLOCKED_TEMPORAL, "grant_not_currently_valid")

    grant_scope_strings = tuple(
        value
        for pair in _scope_pairs(intent, grant)
        for value in pair
        if isinstance(value, str)
    )
    if any(_wild(v) for v in grant_scope_strings):
        return AuthorityDecision(AuthorityStatus.BLOCKED_WILDCARD_SCOPE, "grant_scope_contains_wildcard")

    if any(left != right for left, right in _scope_pairs(intent, grant)):
        return AuthorityDecision(AuthorityStatus.BLOCKED_SCOPE_MISMATCH, "grant_scope_not_exact")
    if grant.action_class not in _ALLOWED_ACTIONS:
        return AuthorityDecision(AuthorityStatus.BLOCKED_SCOPE_MISMATCH, "grant_action_not_internal")
    if grant.preflight_snapshot_sha256 != preflight.snapshot_sha256 or not _sha(grant.preflight_snapshot_sha256):
        return AuthorityDecision(AuthorityStatus.BLOCKED_SCOPE_MISMATCH, "grant_not_bound_to_exact_preflight_snapshot")

    return AuthorityDecision(
        AuthorityStatus.AUTHORIZATION_EVIDENCE_VALID_FOR_SEPARATE_SINGLE_DISPATCH,
        "exact_verified_single_use_owner_authorization_evidence_matches_ready_preflight",
        valid=True,
        real_dispatch_authority="NOT_GRANTED",
    )
