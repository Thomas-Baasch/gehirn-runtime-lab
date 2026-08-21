from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, FrozenSet

ALLOWED_ACTIONS = frozenset({"INTERNAL_CONTINUE", "INTERNAL_RECOVERY"})
OWNER_ACTIONS = frozenset({"MERGE", "EXTERNAL_SEND", "PAYMENT", "PERMISSION_CHANGE", "POLICY_CHANGE", "PRODUCTION_PUBLISH"})
FORBIDDEN_ACTIONS = OWNER_ACTIONS | frozenset({"DELETE"})


@dataclass(frozen=True)
class WorkItem:
    work_id: str
    home_system: str
    state: str
    continuation_policy: str
    source_health: str
    runtime_status: str
    safe_internal_next: bool
    safe_recovery: bool
    action_class: str
    reversible: bool
    external_effect: bool
    owner_gate: bool
    stop_latch: bool
    dedupe_key: str
    retry_count: int
    retry_limit: int
    circuit_open: bool
    requested_permissions: FrozenSet[str] = field(default_factory=frozenset)
    minimum_permissions: FrozenSet[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ExecutionDecision:
    outcome: str
    dispatch: bool
    reason: str


class SafeContinuationExecutor:
    """Fail-closed, product-neutral continuation decision/execution core.

    V1 has no real external dispatch. A caller-provided callback represents the
    already-authorized Home-System adapter in tests. This class never creates
    authority from a watcher signal.
    """

    def __init__(self, dispatch_callback: Callable[[WorkItem], bool], *, permission_allowlist: FrozenSet[str] = frozenset({"actions:write", "contents:read", "issues:write"})) -> None:
        self.dispatch_callback = dispatch_callback
        self.permission_allowlist = permission_allowlist
        self.completed_dedupe_keys: set[str] = set()
        self.audit: list[dict] = []

    def decide(self, item: WorkItem) -> ExecutionDecision:
        # 1) STOPP / owner gate
        if item.stop_latch:
            return ExecutionDecision("STOPPED", False, "stop_latch_active")
        if item.owner_gate:
            return ExecutionDecision("OWNER_REQUIRED", False, "explicit_owner_gate")

        # 2) source health/freshness
        if item.source_health != "FRESH":
            return ExecutionDecision("SOURCE_RECONCILE", False, "source_not_fresh_or_conflicting")

        # 3) state + continuation policy
        if item.state == "DONE":
            return ExecutionDecision("NOOP_DONE", False, "work_already_done")
        if item.state != "ACTIVE":
            return ExecutionDecision("FAIL_CLOSED", False, "work_state_not_active")
        if item.continuation_policy == "PARKED":
            return ExecutionDecision("NOOP_PARKED", False, "parked")
        if item.continuation_policy == "WAITING_EXTERNAL":
            return ExecutionDecision("NOOP_WAITING_EXTERNAL", False, "waiting_external")
        if item.continuation_policy == "MANUAL_ON_DEMAND":
            return ExecutionDecision("NOOP_MANUAL", False, "manual_on_demand")
        if item.continuation_policy == "OWNER_REQUIRED":
            return ExecutionDecision("OWNER_REQUIRED", False, "continuation_policy_owner_required")
        if item.continuation_policy != "AUTONOMOUS_EXPECTED":
            return ExecutionDecision("FAIL_CLOSED", False, "continuation_policy_unknown")

        # 4) runtime status
        if item.runtime_status == "RUNNING":
            return ExecutionDecision("NOOP_RUNNING", False, "active_runtime_exists")
        if item.runtime_status == "UNKNOWN":
            return ExecutionDecision("SOURCE_RECONCILE", False, "runtime_unknown")
        if item.runtime_status not in {"IDLE", "FAILED", "STALE"}:
            return ExecutionDecision("FAIL_CLOSED", False, "runtime_status_not_allowlisted")

        # 5) dedupe/idempotency
        if item.dedupe_key in self.completed_dedupe_keys:
            return ExecutionDecision("NOOP_DUPLICATE", False, "dedupe_key_already_completed")

        # 6) action allowlist
        if item.action_class in OWNER_ACTIONS:
            return ExecutionDecision("OWNER_REQUIRED", False, "action_requires_owner")
        if item.action_class == "DELETE":
            return ExecutionDecision("FAIL_CLOSED", False, "delete_never_auto")
        if item.action_class not in ALLOWED_ACTIONS:
            return ExecutionDecision("FAIL_CLOSED", False, "action_not_allowlisted")
        if item.runtime_status in {"FAILED", "STALE"}:
            if item.action_class != "INTERNAL_RECOVERY" or not item.safe_recovery:
                return ExecutionDecision("FAIL_CLOSED", False, "safe_recovery_missing")
        else:
            if item.action_class != "INTERNAL_CONTINUE" or not item.safe_internal_next:
                return ExecutionDecision("FAIL_CLOSED", False, "safe_internal_next_missing")

        # 7) reversible / no outside effect
        if not item.reversible or item.external_effect:
            return ExecutionDecision("OWNER_REQUIRED", False, "irreversible_or_external_effect")

        # 8) least privilege
        if not item.requested_permissions.issubset(item.minimum_permissions):
            return ExecutionDecision("FAIL_CLOSED_LEAST_PRIVILEGE", False, "requested_permissions_exceed_minimum")
        if not item.minimum_permissions.issubset(self.permission_allowlist):
            return ExecutionDecision("FAIL_CLOSED_LEAST_PRIVILEGE", False, "minimum_permissions_outside_allowlist")

        # 9) retry / circuit breaker
        if item.circuit_open or item.retry_count >= item.retry_limit:
            return ExecutionDecision("CIRCUIT_OPEN", False, "retry_limit_or_circuit_open")

        return ExecutionDecision("DISPATCH_CONTINUE" if item.action_class == "INTERNAL_CONTINUE" else "DISPATCH_RECOVERY", True, "all_fail_closed_gates_passed")

    def execute(self, item: WorkItem) -> ExecutionDecision:
        decision = self.decide(item)
        self.audit.append({"event": "decision", "work_id": item.work_id, "dedupe_key": item.dedupe_key, "outcome": decision.outcome, "dispatch": decision.dispatch})
        if not decision.dispatch:
            return decision

        # Durable audit claim conceptually precedes the callback. The lab uses an
        # in-memory append-only list; real adapters need their own durable audit.
        self.audit.append({"event": "dispatch_attempt", "work_id": item.work_id, "dedupe_key": item.dedupe_key, "action": item.action_class, "retry_count": item.retry_count})
        try:
            success = bool(self.dispatch_callback(item))
        except Exception as exc:
            self.audit.append({"event": "dispatch_failure", "work_id": item.work_id, "dedupe_key": item.dedupe_key, "error": repr(exc)})
            return ExecutionDecision("DISPATCH_FAILED_RETRYABLE", False, "callback_exception")
        if success:
            self.completed_dedupe_keys.add(item.dedupe_key)
            self.audit.append({"event": "dispatch_success", "work_id": item.work_id, "dedupe_key": item.dedupe_key, "action": item.action_class})
            return decision
        self.audit.append({"event": "dispatch_failure", "work_id": item.work_id, "dedupe_key": item.dedupe_key, "error": "callback_returned_false"})
        return ExecutionDecision("DISPATCH_FAILED_RETRYABLE", False, "callback_returned_false")
