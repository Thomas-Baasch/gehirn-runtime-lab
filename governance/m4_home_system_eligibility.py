from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Eligibility(str, Enum):
    ELIGIBLE_FOR_SINGLE_LIVE_PILOT = "ELIGIBLE_FOR_SINGLE_LIVE_PILOT"
    OWNER_REVIEW_GATE = "OWNER_REVIEW_GATE"
    ACTIVE_RUN_NOOP = "ACTIVE_RUN_NOOP"
    WAITING_EXPECTED = "WAITING_EXPECTED"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    SAFE_NEXT_BLOCKED = "SAFE_NEXT_BLOCKED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    DURABILITY_BLOCKED = "DURABILITY_BLOCKED"
    TESTS_BLOCKED = "TESTS_BLOCKED"
    LIVE_EXECUTOR_BLOCKED = "LIVE_EXECUTOR_BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HomeSystemSnapshot:
    home_system: str
    source_health: str
    continuation_policy: str
    work_id: str
    dedupe_key: str
    safe_internal_next: bool
    safe_recovery: bool
    allowlisted_target: str | None
    stop_latch: bool
    owner_gate: bool
    review_gate: bool
    waiting_expected: bool
    active_run: bool
    action_class: str
    reversible: bool
    external_effect: bool
    minimum_permissions_proven: bool
    retry_limit_present: bool
    circuit_breaker_present: bool
    audit_present: bool
    rollback_present: bool
    negative_tests_passed: bool
    durable_dedupe_passed: bool
    live_executor_enabled: bool
    protected_effects_allowed: bool = False


@dataclass(frozen=True)
class EligibilityDecision:
    status: Eligibility
    reason: str
    eligible: bool = False
    dispatch_executed: bool = False


_ALLOWED_ACTIONS = {"INTERNAL_CONTINUE", "INTERNAL_RECOVERY"}


def _nonblank(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def evaluate_m4_eligibility(snapshot: HomeSystemSnapshot) -> EligibilityDecision:
    """Read-only evaluator for the frozen M4 eligibility contract.

    It never performs a dispatch. ELIGIBLE means only that a separate, already
    authorized single-pilot executor may proceed after its own final freshness
    and idempotency checks.
    """
    if not _nonblank(snapshot.home_system):
        return EligibilityDecision(Eligibility.UNKNOWN, "home_system_missing")

    if snapshot.waiting_expected:
        return EligibilityDecision(Eligibility.WAITING_EXPECTED, "home_system_waiting_expected")

    if snapshot.stop_latch or snapshot.owner_gate or snapshot.review_gate:
        return EligibilityDecision(Eligibility.OWNER_REVIEW_GATE, "stop_owner_or_review_gate_active")

    if snapshot.active_run:
        return EligibilityDecision(Eligibility.ACTIVE_RUN_NOOP, "active_relevant_run_exists")

    if snapshot.source_health != "FRESH":
        return EligibilityDecision(Eligibility.SOURCE_BLOCKED, "source_not_fresh_or_conflicting")

    if snapshot.continuation_policy != "AUTONOMOUS_EXPECTED":
        return EligibilityDecision(Eligibility.POLICY_BLOCKED, "continuation_policy_not_autonomous_expected")

    if not _nonblank(snapshot.work_id) or not _nonblank(snapshot.dedupe_key):
        return EligibilityDecision(Eligibility.POLICY_BLOCKED, "work_id_or_dedupe_key_missing")

    if not (snapshot.safe_internal_next or snapshot.safe_recovery):
        return EligibilityDecision(Eligibility.SAFE_NEXT_BLOCKED, "no_allowlisted_safe_next_or_recovery")

    if not _nonblank(snapshot.allowlisted_target):
        return EligibilityDecision(Eligibility.SAFE_NEXT_BLOCKED, "concrete_allowlisted_target_missing")

    if snapshot.action_class not in _ALLOWED_ACTIONS or not snapshot.reversible or snapshot.external_effect:
        return EligibilityDecision(Eligibility.ACTION_BLOCKED, "action_not_internal_reversible_or_has_external_effect")

    if snapshot.protected_effects_allowed:
        return EligibilityDecision(Eligibility.ACTION_BLOCKED, "protected_effects_must_remain_false")

    if not snapshot.minimum_permissions_proven:
        return EligibilityDecision(Eligibility.RIGHTS_BLOCKED, "least_privilege_not_proven")

    durability = (
        snapshot.retry_limit_present
        and snapshot.circuit_breaker_present
        and snapshot.audit_present
        and snapshot.rollback_present
        and snapshot.durable_dedupe_passed
    )
    if not durability:
        return EligibilityDecision(Eligibility.DURABILITY_BLOCKED, "retry_circuit_audit_rollback_or_dedupe_missing")

    if not snapshot.negative_tests_passed:
        return EligibilityDecision(Eligibility.TESTS_BLOCKED, "negative_tests_not_proven")

    if not snapshot.live_executor_enabled:
        return EligibilityDecision(Eligibility.LIVE_EXECUTOR_BLOCKED, "live_executor_still_disabled")

    return EligibilityDecision(
        Eligibility.ELIGIBLE_FOR_SINGLE_LIVE_PILOT,
        "all_frozen_m4_eligibility_gates_pass",
        eligible=True,
        dispatch_executed=False,
    )
