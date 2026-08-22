from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet


class CompositeStatus(str, Enum):
    READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT = "READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT"
    BLOCKED_SOURCE = "BLOCKED_SOURCE"
    BLOCKED_STATE = "BLOCKED_STATE"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    BLOCKED_EXPECTED_WAIT = "BLOCKED_EXPECTED_WAIT"
    BLOCKED_OWNER_OR_REVIEW = "BLOCKED_OWNER_OR_REVIEW"
    BLOCKED_RUNTIME = "BLOCKED_RUNTIME"
    BLOCKED_SAFE_ACTION = "BLOCKED_SAFE_ACTION"
    BLOCKED_OWNER_OR_EFFECT = "BLOCKED_OWNER_OR_EFFECT"
    BLOCKED_RIGHTS = "BLOCKED_RIGHTS"
    BLOCKED_CIRCUIT = "BLOCKED_CIRCUIT"
    BLOCKED_DURABILITY = "BLOCKED_DURABILITY"
    FAIL_CLOSED_IDENTITY = "FAIL_CLOSED_IDENTITY"
    BLOCKED_ADAPTER_AUTHORITY = "BLOCKED_ADAPTER_AUTHORITY"
    BLOCKED_RUN_BINDING = "BLOCKED_RUN_BINDING"
    BLOCKED_DURABLE_CLAIM = "BLOCKED_DURABLE_CLAIM"
    BLOCKED_DUPLICATE_DONE = "BLOCKED_DUPLICATE_DONE"
    BLOCKED_OUTCOME_PROOF = "BLOCKED_OUTCOME_PROOF"
    BLOCKED_EXECUTOR = "BLOCKED_EXECUTOR"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class CompositePilotSnapshot:
    home_system: str
    work_id: str
    dedupe_key: str
    target_adapter: str
    target: str
    source_health: str
    state: str
    continuation_policy: str
    runtime_status: str
    safe_internal_next: bool
    safe_recovery: bool
    action_class: str
    reversible: bool
    external_effect: bool
    protected_effects_allowed: bool
    owner_gate: bool
    review_gate: bool
    stop_latch: bool
    waiting_expected: bool
    requested_permissions: FrozenSet[str] = field(default_factory=frozenset)
    minimum_permissions: FrozenSet[str] = field(default_factory=frozenset)
    permission_allowlist: FrozenSet[str] = field(default_factory=frozenset)
    retry_count: int = 0
    retry_limit: int = 1
    circuit_open: bool = False
    durable_claim_state: str = "NONE"
    negative_tests_passed: bool = False
    audit_present: bool = False
    rollback_present: bool = False
    durable_dedupe_passed: bool = False
    expected_repository: str = ""
    expected_workflow_id: int = 0
    expected_event: str = ""
    expected_ref: str = ""
    expected_head_sha: str = ""
    exact_run_name_token: str = ""
    outcome_contract_drive_id: str = ""
    outcome_contract_sha256: str = ""
    expected_artifact_name: str = ""
    expected_outcome_path: str = ""
    outcome_schema: str = ""
    provider_digest_required: bool = False
    live_executor_enabled: bool = False


@dataclass(frozen=True)
class CompositeDecision:
    status: CompositeStatus
    reason: str
    ready: bool = False
    dispatch_executed: bool = False
    retry_executed: bool = False
    claim_executed: bool = False
    write_executed: bool = False
    real_dispatch_authority: str = "NOT_GRANTED"


_ALLOWED_ACTIONS = frozenset({"INTERNAL_CONTINUE", "INTERNAL_RECOVERY"})
_ALLOWED_ADAPTERS_V1 = frozenset({"SYNTHETIC_SINGLE_PILOT_ADAPTER_V1"})
_OUTCOME_CONTRACT_ID = "15JeNfaaHDAn4a9znqAvkB7DyOLbOGXHs7gbMs4V9e54"
_OUTCOME_CONTRACT_SHA256 = "d150621ba21b77f5251d343b5876f81ff63749410c2628c57a3ccf8ea30575fb"
_OUTCOME_PATH = "safe-continuation-outcome.json"
_OUTCOME_SCHEMA = "safe-continuation-outcome.v1"


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def evaluate_single_pilot_preflight(snapshot: CompositePilotSnapshot) -> CompositeDecision:
    """Pure read-only M4 preflight.

    READY means only that a separate authority layer may consider a single pilot.
    This function cannot dispatch, claim, retry or write.
    """
    identity = (
        snapshot.home_system,
        snapshot.work_id,
        snapshot.dedupe_key,
        snapshot.target_adapter,
        snapshot.target,
    )
    if not all(_nonblank(v) for v in identity):
        return CompositeDecision(CompositeStatus.FAIL_CLOSED_IDENTITY, "core_identity_missing")

    if snapshot.source_health != "FRESH":
        return CompositeDecision(CompositeStatus.BLOCKED_SOURCE, "source_not_fresh")

    if snapshot.waiting_expected:
        return CompositeDecision(CompositeStatus.BLOCKED_EXPECTED_WAIT, "waiting_expected_is_binding")

    if snapshot.owner_gate or snapshot.review_gate or snapshot.stop_latch:
        return CompositeDecision(CompositeStatus.BLOCKED_OWNER_OR_REVIEW, "owner_review_or_stop_gate")

    if snapshot.state != "ACTIVE":
        return CompositeDecision(CompositeStatus.BLOCKED_STATE, "work_state_not_active")

    if snapshot.continuation_policy != "AUTONOMOUS_EXPECTED":
        return CompositeDecision(CompositeStatus.BLOCKED_POLICY, "continuation_not_autonomous_expected")

    if snapshot.runtime_status in {"RUNNING", "UNKNOWN"}:
        return CompositeDecision(CompositeStatus.BLOCKED_RUNTIME, "active_or_unknown_runtime")

    if snapshot.action_class not in _ALLOWED_ACTIONS:
        return CompositeDecision(CompositeStatus.BLOCKED_SAFE_ACTION, "action_class_not_allowlisted")

    if snapshot.action_class == "INTERNAL_CONTINUE":
        if snapshot.runtime_status != "IDLE" or not snapshot.safe_internal_next:
            return CompositeDecision(CompositeStatus.BLOCKED_SAFE_ACTION, "safe_internal_continue_not_proven")
    elif snapshot.action_class == "INTERNAL_RECOVERY":
        if snapshot.runtime_status not in {"FAILED", "STALE"} or not snapshot.safe_recovery:
            return CompositeDecision(CompositeStatus.BLOCKED_SAFE_ACTION, "safe_internal_recovery_not_proven")

    if not snapshot.reversible or snapshot.external_effect or snapshot.protected_effects_allowed:
        return CompositeDecision(CompositeStatus.BLOCKED_OWNER_OR_EFFECT, "action_not_reversible_internal_only")

    try:
        rights_ok = (
            snapshot.requested_permissions.issubset(snapshot.minimum_permissions)
            and snapshot.minimum_permissions.issubset(snapshot.permission_allowlist)
        )
    except AttributeError:
        return CompositeDecision(CompositeStatus.FAIL_CLOSED, "permission_sets_invalid")
    if not rights_ok:
        return CompositeDecision(CompositeStatus.BLOCKED_RIGHTS, "least_privilege_not_proven")

    if (
        not isinstance(snapshot.retry_count, int)
        or isinstance(snapshot.retry_count, bool)
        or snapshot.retry_count < 0
        or not isinstance(snapshot.retry_limit, int)
        or isinstance(snapshot.retry_limit, bool)
        or snapshot.retry_limit <= 0
    ):
        return CompositeDecision(CompositeStatus.FAIL_CLOSED, "retry_values_invalid")
    if snapshot.circuit_open or snapshot.retry_count >= snapshot.retry_limit:
        return CompositeDecision(CompositeStatus.BLOCKED_CIRCUIT, "retry_limit_or_circuit_open")

    if not (
        snapshot.negative_tests_passed
        and snapshot.audit_present
        and snapshot.rollback_present
        and snapshot.durable_dedupe_passed
    ):
        return CompositeDecision(CompositeStatus.BLOCKED_DURABILITY, "durability_or_negative_tests_missing")

    if snapshot.durable_claim_state == "SUCCEEDED":
        return CompositeDecision(CompositeStatus.BLOCKED_DUPLICATE_DONE, "durable_success_already_recorded")
    if snapshot.durable_claim_state != "NONE":
        return CompositeDecision(CompositeStatus.BLOCKED_DURABLE_CLAIM, "durable_claim_not_clean")

    if snapshot.target_adapter not in _ALLOWED_ADAPTERS_V1:
        return CompositeDecision(CompositeStatus.BLOCKED_ADAPTER_AUTHORITY, "target_adapter_not_v1_allowlisted")

    run_fields_ok = (
        _nonblank(snapshot.expected_repository)
        and isinstance(snapshot.expected_workflow_id, int)
        and not isinstance(snapshot.expected_workflow_id, bool)
        and snapshot.expected_workflow_id > 0
        and _nonblank(snapshot.expected_event)
        and _nonblank(snapshot.expected_ref)
        and _nonblank(snapshot.expected_head_sha)
        and _nonblank(snapshot.exact_run_name_token)
        and snapshot.work_id in snapshot.exact_run_name_token
        and snapshot.dedupe_key in snapshot.exact_run_name_token
    )
    if not run_fields_ok:
        return CompositeDecision(CompositeStatus.BLOCKED_RUN_BINDING, "exact_run_binding_incomplete")

    outcome_ok = (
        snapshot.outcome_contract_drive_id == _OUTCOME_CONTRACT_ID
        and snapshot.outcome_contract_sha256 == _OUTCOME_CONTRACT_SHA256
        and _nonblank(snapshot.expected_artifact_name)
        and snapshot.work_id in snapshot.expected_artifact_name
        and snapshot.dedupe_key in snapshot.expected_artifact_name
        and snapshot.expected_outcome_path == _OUTCOME_PATH
        and snapshot.outcome_schema == _OUTCOME_SCHEMA
        and snapshot.provider_digest_required is True
    )
    if not outcome_ok:
        return CompositeDecision(CompositeStatus.BLOCKED_OUTCOME_PROOF, "outcome_proof_capability_missing_or_weaker")

    if not snapshot.live_executor_enabled:
        return CompositeDecision(CompositeStatus.BLOCKED_EXECUTOR, "live_executor_not_enabled")

    return CompositeDecision(
        CompositeStatus.READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT,
        "all_frozen_composite_preflight_gates_pass",
        ready=True,
        real_dispatch_authority="NOT_GRANTED",
    )
