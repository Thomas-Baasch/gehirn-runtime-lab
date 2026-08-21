from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sqlite3
from typing import Iterable, Mapping, Any

from governance.durable_continuation_ledger import DurableContinuationLedger
from governance.safe_continuation_executor import WorkItem


class ReconcileStatus(str, Enum):
    RECONCILED_SUCCEEDED = "RECONCILED_SUCCEEDED"
    WAIT_DOWNSTREAM = "WAIT_DOWNSTREAM"
    RECONCILED_FAILED_RETRYABLE = "RECONCILED_FAILED_RETRYABLE"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    OWNER_GATE_BLOCKED = "OWNER_GATE_BLOCKED"
    FAIL_CLOSED = "FAIL_CLOSED"
    NOOP_ALREADY_SUCCEEDED = "NOOP_ALREADY_SUCCEEDED"


@dataclass(frozen=True)
class DownstreamEvidence:
    source_health: str
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    downstream_id: str
    state: str
    external_effect_proven: bool
    external_effect_possible: bool
    evidence_source_ref: str


@dataclass(frozen=True)
class ReconcileDecision:
    status: ReconcileStatus
    reason: str
    ledger_updated: bool = False
    dispatch_executed: bool = False


def parse_evidence(payload: Mapping[str, Any]) -> DownstreamEvidence:
    required = ("source_health","home_system","work_id","dedupe_key","target","downstream_id","state","external_effect_proven","external_effect_possible","evidence_source_ref")
    if not all(key in payload for key in required):
        raise ValueError("evidence_missing_required_field")
    strings = {key: str(payload[key]).strip() for key in ("source_health","home_system","work_id","dedupe_key","target","downstream_id","state","evidence_source_ref")}
    if not all(strings.values()):
        raise ValueError("evidence_blank_required_field")
    if not isinstance(payload["external_effect_proven"], bool) or not isinstance(payload["external_effect_possible"], bool):
        raise ValueError("evidence_effect_flags_invalid")
    return DownstreamEvidence(
        **strings,
        external_effect_proven=payload["external_effect_proven"],
        external_effect_possible=payload["external_effect_possible"],
    )


class DownstreamReconciler:
    def __init__(self, ledger: DurableContinuationLedger) -> None:
        self.ledger = ledger

    def _set_state(self, item: WorkItem, *, status: str, event_type: str, reason: str) -> bool:
        with self.ledger._connect() as conn:  # same internal governance package
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False
            current = str(row["status"])
            if current == "SUCCEEDED":
                self.ledger._audit(conn, "RECONCILE_NOOP_ALREADY_SUCCEEDED", item, {"requested_status": status, "reason": reason})
                conn.execute("COMMIT")
                return False
            if current not in {"CLAIMED", "RECONCILE_REQUIRED", "FAILED_RETRYABLE"}:
                self.ledger._audit(conn, "RECONCILE_STATE_BLOCKED", item, {"current_status": current, "requested_status": status})
                conn.execute("COMMIT")
                return False
            conn.execute("UPDATE dispatch_claims SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=?", (status, reason if status != "SUCCEEDED" else None, item.dedupe_key))
            self.ledger._audit(conn, event_type, item, {"from": current, "to": status, "reason": reason})
            conn.execute("COMMIT")
            return True

    def reconcile(
        self,
        item: WorkItem,
        *,
        target: str,
        evidence: Iterable[DownstreamEvidence],
        owner_gate: bool = False,
        review_gate: bool = False,
        stop_latch: bool = False,
    ) -> ReconcileDecision:
        if owner_gate or review_gate or stop_latch:
            return ReconcileDecision(ReconcileStatus.OWNER_GATE_BLOCKED, "owner_review_or_stop_gate")

        local = self.ledger.state(item.dedupe_key)
        if local is None:
            return ReconcileDecision(ReconcileStatus.FAIL_CLOSED, "local_claim_missing")
        if local.status == "SUCCEEDED":
            return ReconcileDecision(ReconcileStatus.NOOP_ALREADY_SUCCEEDED, "local_success_is_authoritative")

        rows = list(evidence)
        stale_exact = [e for e in rows if e.home_system == item.home_system and e.work_id == item.work_id and e.dedupe_key == item.dedupe_key and e.target == target and e.source_health != "FRESH"]
        exact = [e for e in rows if e.home_system == item.home_system and e.work_id == item.work_id and e.dedupe_key == item.dedupe_key and e.target == target and e.source_health == "FRESH"]
        if not exact:
            if stale_exact:
                return ReconcileDecision(ReconcileStatus.SOURCE_BLOCKED, "only_stale_or_conflicting_exact_evidence")
            return ReconcileDecision(ReconcileStatus.RECONCILE_REQUIRED, "no_fresh_exact_downstream_evidence")

        states = {e.state.upper() for e in exact}
        terminal = states & {"SUCCEEDED", "FAILED"}
        if len(terminal) > 1:
            return ReconcileDecision(ReconcileStatus.CONFLICT_BLOCKED, "conflicting_terminal_downstream_evidence")
        if "RUNNING" in states:
            if "SUCCEEDED" in states:
                return ReconcileDecision(ReconcileStatus.CONFLICT_BLOCKED, "running_and_succeeded_conflict")
            return ReconcileDecision(ReconcileStatus.WAIT_DOWNSTREAM, "fresh_exact_downstream_run_active")
        if states == {"SUCCEEDED"}:
            updated = self._set_state(item, status="SUCCEEDED", event_type="RECONCILED_SUCCEEDED", reason="fresh_exact_downstream_success")
            if not updated and self.ledger.state(item.dedupe_key).status == "SUCCEEDED":
                return ReconcileDecision(ReconcileStatus.NOOP_ALREADY_SUCCEEDED, "success_reconciliation_idempotent")
            return ReconcileDecision(ReconcileStatus.RECONCILED_SUCCEEDED, "fresh_exact_downstream_success", ledger_updated=updated)
        if states == {"FAILED"}:
            if any(e.external_effect_proven or e.external_effect_possible for e in exact):
                return ReconcileDecision(ReconcileStatus.RECONCILE_REQUIRED, "failed_downstream_but_external_effect_not_excluded")
            updated = self._set_state(item, status="FAILED_RETRYABLE", event_type="RECONCILED_FAILED_RETRYABLE", reason="fresh_exact_failure_no_external_effect")
            return ReconcileDecision(ReconcileStatus.RECONCILED_FAILED_RETRYABLE, "fresh_exact_failure_no_external_effect", ledger_updated=updated)
        return ReconcileDecision(ReconcileStatus.RECONCILE_REQUIRED, "downstream_state_unknown_or_nonterminal")
