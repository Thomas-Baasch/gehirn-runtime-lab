from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sqlite3
from typing import Iterable, Mapping, Any

from governance.durable_continuation_ledger import ClaimState, DurableContinuationLedger
from governance.safe_continuation_executor import WorkItem, work_item_input_error


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
    if not isinstance(payload, Mapping) or not all(key in payload for key in required):
        raise ValueError("evidence_missing_required_field")
    string_keys = ("source_health","home_system","work_id","dedupe_key","target","downstream_id","state","evidence_source_ref")
    if any(not isinstance(payload[key], str) or not payload[key].strip() for key in string_keys):
        raise ValueError("evidence_blank_required_field")
    strings = {key: payload[key].strip() for key in string_keys}
    if not isinstance(payload["external_effect_proven"], bool) or not isinstance(payload["external_effect_possible"], bool):
        raise ValueError("evidence_effect_flags_invalid")
    return DownstreamEvidence(
        **strings,
        external_effect_proven=payload["external_effect_proven"],
        external_effect_possible=payload["external_effect_possible"],
    )


def _evidence_valid(row: DownstreamEvidence) -> bool:
    return (
        isinstance(row, DownstreamEvidence)
        and all(isinstance(getattr(row, key), str) and getattr(row, key).strip()
                for key in ("source_health", "home_system", "work_id", "dedupe_key",
                            "target", "downstream_id", "state", "evidence_source_ref"))
        and type(row.external_effect_proven) is bool
        and type(row.external_effect_possible) is bool
    )


class DownstreamReconciler:
    def __init__(self, ledger: DurableContinuationLedger) -> None:
        self.ledger = ledger

    def _set_state(self, item: WorkItem, *, expected: ClaimState, status: str, event_type: str, reason: str) -> bool:
        with self.ledger._connect() as conn:  # same internal governance package
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            if (row is None or not self.ledger._scope_matches(row, item)
                    or row["attempt_count"] != expected.attempt_count
                    or row["downstream_target"] != expected.downstream_target
                    or row["downstream_id"] != expected.downstream_id
                    or row["dispatch_receipt_source_ref"] != expected.dispatch_receipt_source_ref):
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
            conn.execute(
                "UPDATE dispatch_claims SET status=?,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=? AND attempt_count=? AND downstream_target=? AND downstream_id=? AND status=?",
                (status, reason if status != "SUCCEEDED" else None, item.dedupe_key,
                 expected.attempt_count, expected.downstream_target, expected.downstream_id, current),
            )
            self.ledger._audit(conn, event_type, item,
                               {"from": current, "to": status, "reason": reason,
                                "attempt_count": expected.attempt_count, "downstream_id": expected.downstream_id})
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
        if (work_item_input_error(item) or not isinstance(target, str) or not target.strip()
                or any(type(flag) is not bool for flag in (owner_gate, review_gate, stop_latch))):
            return ReconcileDecision(ReconcileStatus.FAIL_CLOSED, "reconcile_input_invalid")
        if owner_gate or review_gate or stop_latch:
            return ReconcileDecision(ReconcileStatus.OWNER_GATE_BLOCKED, "owner_review_or_stop_gate")

        local = self.ledger.state(item.dedupe_key)
        if local is None:
            return ReconcileDecision(ReconcileStatus.FAIL_CLOSED, "local_claim_missing")
        if not self.ledger.matches_item(item):
            return ReconcileDecision(ReconcileStatus.CONFLICT_BLOCKED, "local_claim_scope_mismatch")
        if local.status == "SUCCEEDED":
            return ReconcileDecision(ReconcileStatus.NOOP_ALREADY_SUCCEEDED, "local_success_is_authoritative")

        try:
            rows = list(evidence)
        except Exception:
            return ReconcileDecision(ReconcileStatus.SOURCE_BLOCKED, "evidence_source_unavailable")
        if any(not _evidence_valid(row) for row in rows):
            return ReconcileDecision(ReconcileStatus.FAIL_CLOSED, "evidence_runtime_types_invalid")
        if not local.downstream_id or not local.downstream_target or not local.dispatch_receipt_source_ref:
            return ReconcileDecision(ReconcileStatus.RECONCILE_REQUIRED, "exact_attempt_dispatch_receipt_missing")
        scoped = [e for e in rows if e.home_system == item.home_system and e.work_id == item.work_id
                  and e.dedupe_key == item.dedupe_key and e.target == target]
        if any(e.source_health == "FRESH" and (e.target != local.downstream_target or e.downstream_id != local.downstream_id) for e in scoped):
            return ReconcileDecision(ReconcileStatus.CONFLICT_BLOCKED, "evidence_not_bound_to_current_attempt")
        bound = [e for e in scoped if e.target == local.downstream_target and e.downstream_id == local.downstream_id]
        stale_exact = [e for e in bound if e.source_health != "FRESH"]
        exact = [e for e in bound if e.source_health == "FRESH"]
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
            updated = self._set_state(item, expected=local, status="SUCCEEDED", event_type="RECONCILED_SUCCEEDED", reason="fresh_exact_downstream_success")
            if not updated and self.ledger.state(item.dedupe_key).status == "SUCCEEDED":
                return ReconcileDecision(ReconcileStatus.NOOP_ALREADY_SUCCEEDED, "success_reconciliation_idempotent")
            if not updated:
                return ReconcileDecision(ReconcileStatus.CONFLICT_BLOCKED, "claim_changed_before_reconciliation")
            return ReconcileDecision(ReconcileStatus.RECONCILED_SUCCEEDED, "fresh_exact_downstream_success", ledger_updated=updated)
        if states == {"FAILED"}:
            if any(e.external_effect_proven or e.external_effect_possible for e in exact):
                return ReconcileDecision(ReconcileStatus.RECONCILE_REQUIRED, "failed_downstream_but_external_effect_not_excluded")
            updated = self._set_state(item, expected=local, status="FAILED_RETRYABLE", event_type="RECONCILED_FAILED_RETRYABLE", reason="fresh_exact_failure_no_external_effect")
            if not updated:
                return ReconcileDecision(ReconcileStatus.CONFLICT_BLOCKED, "claim_changed_before_reconciliation")
            return ReconcileDecision(ReconcileStatus.RECONCILED_FAILED_RETRYABLE, "fresh_exact_failure_no_external_effect", ledger_updated=updated)
        return ReconcileDecision(ReconcileStatus.RECONCILE_REQUIRED, "downstream_state_unknown_or_nonterminal")
