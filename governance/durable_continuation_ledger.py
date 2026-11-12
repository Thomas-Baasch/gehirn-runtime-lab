from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from governance.safe_continuation_executor import (
    ExecutionDecision, NoEffectDispatchError, SafeContinuationExecutor,
    UncertainDispatchOutcome, WorkItem, work_item_input_error,
)


@dataclass(frozen=True)
class ClaimState:
    dedupe_key: str
    status: str
    attempt_count: int
    retry_limit: int
    last_error: str | None
    downstream_target: str | None = None
    downstream_id: str | None = None
    dispatch_receipt_source_ref: str | None = None


@dataclass(frozen=True)
class ClaimResult:
    status: str
    claim_token: str | None = None


def work_scope_sha256(item: WorkItem) -> str:
    payload = {"work_id": item.work_id, "home_system": item.home_system,
               "action_class": item.action_class, "dedupe_key": item.dedupe_key,
               "requested_permissions": sorted(item.requested_permissions),
               "minimum_permissions": sorted(item.minimum_permissions)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DurableContinuationLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_db(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dispatch_claims (
                    dedupe_key TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    home_system TEXT NOT NULL,
                    action_class TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    retry_limit INTEGER NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(dispatch_claims)")}
            for name in ("claim_token", "scope_sha256", "downstream_target", "downstream_id", "dispatch_receipt_source_ref"):
                if name not in columns:
                    conn.execute(f"ALTER TABLE dispatch_claims ADD COLUMN {name} TEXT")
            # Older claims are retained; an absent scope/token cannot authorize
            # a retry or completion and requires evidence-based reconciliation.
            conn.execute("COMMIT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dispatch_receipt_bindings (
                    home_system TEXT NOT NULL,
                    target TEXT NOT NULL,
                    downstream_id TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    receipt_source_ref TEXT NOT NULL,
                    PRIMARY KEY (home_system, target, downstream_id)
                )
            """)

    @staticmethod
    def _audit(conn: sqlite3.Connection, event_type: str, item: WorkItem, payload: dict) -> None:
        conn.execute(
            "INSERT INTO audit_events(event_type,work_id,dedupe_key,payload_json) VALUES(?,?,?,?)",
            (event_type, item.work_id, item.dedupe_key, json.dumps(payload, sort_keys=True, ensure_ascii=False)),
        )

    @staticmethod
    def _scope_matches(row: sqlite3.Row, item: WorkItem) -> bool:
        return (
            row["work_id"] == item.work_id
            and row["home_system"] == item.home_system
            and row["action_class"] == item.action_class
            and row["scope_sha256"] == work_scope_sha256(item)
        )

    def matches_item(self, item: WorkItem) -> bool:
        if work_item_input_error(item):
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            return row is not None and self._scope_matches(row, item)

    def claim(self, item: WorkItem) -> ClaimResult:
        if work_item_input_error(item):
            return ClaimResult("FAIL_CLOSED_INVALID_ITEM")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
                if row is None:
                    token = uuid4().hex
                    conn.execute(
                        "INSERT INTO dispatch_claims(dedupe_key,work_id,home_system,action_class,status,attempt_count,retry_limit,last_error,claim_token,scope_sha256) VALUES(?,?,?,?,?,?,?,NULL,?,?)",
                        (item.dedupe_key, item.work_id, item.home_system, item.action_class, "CLAIMED", 1, item.retry_limit, token, work_scope_sha256(item)),
                    )
                    self._audit(conn, "CLAIMED", item, {"attempt_count": 1, "action_class": item.action_class})
                    conn.execute("COMMIT")
                    return ClaimResult("CLAIMED_NEW", token)

                if not self._scope_matches(row, item):
                    self._audit(conn, "SCOPE_CONFLICT_BLOCKED", item, {"reason": "dedupe_key_scope_mismatch_or_legacy_unbound_scope"})
                    conn.execute("COMMIT")
                    return ClaimResult("SCOPE_CONFLICT_BLOCKED")

                status = str(row["status"])
                attempts = int(row["attempt_count"])
                retry_limit = int(row["retry_limit"])
                if status == "SUCCEEDED":
                    self._audit(conn, "DUPLICATE_BLOCKED", item, {"status": status, "attempt_count": attempts})
                    conn.execute("COMMIT")
                    return ClaimResult("NOOP_DUPLICATE")
                if status == "CLAIMED":
                    # Critical ownership rule: a competing/restarted executor must
                    # never mutate another executor's live/possibly-live claim.
                    # It only observes the uncertainty and blocks redispatch. The
                    # legitimate claim holder can still mark success/failure.
                    self._audit(conn, "CLAIM_PRESENT_BLOCKED", item, {"status": status, "attempt_count": attempts})
                    conn.execute("COMMIT")
                    return ClaimResult("RECONCILE_REQUIRED")
                if status == "RECONCILE_REQUIRED":
                    self._audit(conn, "RECONCILE_REQUIRED", item, {"previous_status": status, "attempt_count": attempts})
                    conn.execute("COMMIT")
                    return ClaimResult("RECONCILE_REQUIRED")
                if status == "FAILED_RETRYABLE":
                    if attempts >= retry_limit or attempts >= item.retry_limit:
                        self._audit(conn, "CIRCUIT_OPEN", item, {"attempt_count": attempts, "retry_limit": min(retry_limit, item.retry_limit)})
                        conn.execute("COMMIT")
                        return ClaimResult("CIRCUIT_OPEN")
                    next_attempt = attempts + 1
                    token = uuid4().hex
                    conn.execute(
                        "UPDATE dispatch_claims SET status='CLAIMED', attempt_count=?, retry_limit=?, claim_token=?, last_error=NULL, downstream_target=NULL, downstream_id=NULL, dispatch_receipt_source_ref=NULL, updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=?",
                        (next_attempt, min(retry_limit, item.retry_limit), token, item.dedupe_key),
                    )
                    self._audit(conn, "RETRY_CLAIMED", item, {"attempt_count": next_attempt})
                    conn.execute("COMMIT")
                    return ClaimResult("CLAIMED_RETRY", token)

                self._audit(conn, "UNKNOWN_STATUS_BLOCKED", item, {"status": status})
                conn.execute("COMMIT")
                return ClaimResult("FAIL_CLOSED_UNKNOWN_STATUS")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def _complete_claim(self, item: WorkItem, *, claim_token: str, status: str, error: str | None) -> bool:
        if work_item_input_error(item) or not isinstance(claim_token, str) or not claim_token:
            raise RuntimeError("completion_identity_invalid")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            if row is None or not self._scope_matches(row, item) or row["claim_token"] != claim_token:
                conn.execute("ROLLBACK")
                raise RuntimeError("completion_claim_owner_or_scope_mismatch")
            if row["status"] == "SUCCEEDED" and status == "RECONCILE_REQUIRED":
                conn.execute("COMMIT")
                return False
            if row["status"] != "CLAIMED":
                conn.execute("ROLLBACK")
                raise RuntimeError("completion_without_active_claim")
            changed = conn.execute(
                "UPDATE dispatch_claims SET status=?,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=? AND claim_token=? AND status='CLAIMED'",
                (status, error, item.dedupe_key, claim_token),
            ).rowcount
            if changed != 1:
                conn.execute("ROLLBACK")
                raise RuntimeError("claim_changed_before_completion")
            self._audit(conn, status, item, {"error": error, "attempt_count": int(row["attempt_count"])})
            conn.execute("COMMIT")
            return True

    def mark_success(self, item: WorkItem, *, claim_token: str) -> None:
        self._complete_claim(item, claim_token=claim_token, status="SUCCEEDED", error=None)

    def mark_failure(self, item: WorkItem, error: str, *, claim_token: str) -> None:
        """Complete a claim only after the adapter proved absence of effect."""
        self._complete_claim(item, claim_token=claim_token, status="FAILED_RETRYABLE", error=error)

    def mark_reconcile_required(self, item: WorkItem, reason: str, *, claim_token: str) -> bool:
        return self._complete_claim(item, claim_token=claim_token, status="RECONCILE_REQUIRED", error=reason)

    def bind_downstream_receipt(
        self, item: WorkItem, *, claim_token: str, target: str,
        downstream_id: str, receipt_source_ref: str,
    ) -> None:
        """Bind an authenticated dispatch receipt to its own claimed attempt.

        Call with the token returned for that dispatch, not a token obtained
        later for another attempt. This method neither dispatches nor invents
        receipt evidence. A prior run ID cannot be rebound to a new attempt.
        """
        if work_item_input_error(item) or any(not isinstance(v, str) or not v.strip()
                                             for v in (claim_token, target, downstream_id, receipt_source_ref)):
            raise RuntimeError("dispatch_receipt_binding_invalid")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            if (row is None or not self._scope_matches(row, item) or row["claim_token"] != claim_token
                    or row["status"] not in {"CLAIMED", "RECONCILE_REQUIRED"}):
                conn.execute("ROLLBACK")
                raise RuntimeError("dispatch_receipt_claim_owner_or_scope_mismatch")
            existing = conn.execute(
                "SELECT * FROM dispatch_receipt_bindings WHERE home_system=? AND target=? AND downstream_id=?",
                (item.home_system, target, downstream_id),
            ).fetchone()
            if existing is not None and (
                existing["work_id"] != item.work_id or existing["dedupe_key"] != item.dedupe_key
                or existing["attempt_count"] != row["attempt_count"]
                or existing["receipt_source_ref"] != receipt_source_ref
            ):
                conn.execute("ROLLBACK")
                raise RuntimeError("dispatch_receipt_already_bound_to_another_attempt")
            if row["downstream_id"] is not None and (
                row["downstream_id"] != downstream_id or row["downstream_target"] != target
                or row["dispatch_receipt_source_ref"] != receipt_source_ref
            ):
                conn.execute("ROLLBACK")
                raise RuntimeError("claim_already_has_another_dispatch_receipt")
            conn.execute(
                "INSERT OR IGNORE INTO dispatch_receipt_bindings VALUES(?,?,?,?,?,?,?)",
                (item.home_system, target, downstream_id, item.work_id, item.dedupe_key,
                 row["attempt_count"], receipt_source_ref),
            )
            conn.execute(
                "UPDATE dispatch_claims SET downstream_target=?,downstream_id=?,dispatch_receipt_source_ref=?,updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=? AND claim_token=?",
                (target, downstream_id, receipt_source_ref, item.dedupe_key, claim_token),
            )
            self._audit(conn, "DOWNSTREAM_RECEIPT_BOUND", item,
                        {"target": target, "downstream_id": downstream_id,
                         "attempt_count": row["attempt_count"], "receipt_source_ref": receipt_source_ref})
            conn.execute("COMMIT")

    def state(self, dedupe_key: str) -> ClaimState | None:
        with self._connect() as conn:
            row = conn.execute("SELECT dedupe_key,status,attempt_count,retry_limit,last_error,downstream_target,downstream_id,dispatch_receipt_source_ref FROM dispatch_claims WHERE dedupe_key=?", (dedupe_key,)).fetchone()
            if row is None:
                return None
            return ClaimState(str(row["dedupe_key"]), str(row["status"]), int(row["attempt_count"]), int(row["retry_limit"]), row["last_error"], row["downstream_target"], row["downstream_id"], row["dispatch_receipt_source_ref"])

    def audit(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT seq,event_type,work_id,dedupe_key,payload_json,created_at FROM audit_events ORDER BY seq").fetchall()
            return [{"seq": int(r["seq"]), "event_type": str(r["event_type"]), "work_id": str(r["work_id"]), "dedupe_key": str(r["dedupe_key"]), "payload": json.loads(r["payload_json"]), "created_at": str(r["created_at"])} for r in rows]

    def integrity_ok(self) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                return row is not None and str(row[0]).lower() == "ok"
        except sqlite3.DatabaseError:
            return False


class DurableSafeContinuationExecutor:
    def __init__(self, ledger: DurableContinuationLedger, dispatch_callback: Callable[[WorkItem], bool], *, after_claim_hook: Callable[[WorkItem], None] | None = None) -> None:
        self.ledger = ledger
        self.dispatch_callback = dispatch_callback
        self.after_claim_hook = after_claim_hook
        self.core = SafeContinuationExecutor(lambda item: True)

    def execute(self, item: WorkItem) -> ExecutionDecision:
        core_decision = self.core.decide(item)
        if not core_decision.dispatch:
            return core_decision

        try:
            claim_result = self.ledger.claim(item)
        except sqlite3.DatabaseError:
            return ExecutionDecision("FAIL_CLOSED_LEDGER_ERROR", False, "ledger_database_error")
        claim = claim_result.status
        if claim == "NOOP_DUPLICATE":
            return ExecutionDecision("NOOP_DUPLICATE", False, "durable_success_dedupe")
        if claim == "RECONCILE_REQUIRED":
            return ExecutionDecision("RECONCILE_REQUIRED", False, "durable_claim_uncertain")
        if claim == "CIRCUIT_OPEN":
            return ExecutionDecision("CIRCUIT_OPEN", False, "durable_retry_limit")
        if claim == "SCOPE_CONFLICT_BLOCKED":
            return ExecutionDecision("FAIL_CLOSED_LEDGER_SCOPE", False, "dedupe_key_scope_mismatch")
        if claim == "FAIL_CLOSED_UNKNOWN_STATUS":
            return ExecutionDecision("FAIL_CLOSED_LEDGER_STATUS", False, "unknown_durable_status")
        if claim not in {"CLAIMED_NEW", "CLAIMED_RETRY"}:
            return ExecutionDecision("FAIL_CLOSED_LEDGER_STATUS", False, "unexpected_claim_result")
        token = claim_result.claim_token
        if not token:
            return ExecutionDecision("FAIL_CLOSED_LEDGER_STATUS", False, "claim_token_missing")

        if self.after_claim_hook is not None:
            # A real hard crash here leaves CLAIMED in SQLite. On reopen the next
            # executor sees the durable claim and returns RECONCILE_REQUIRED
            # without mutating the claim or blindly redispatching.
            self.after_claim_hook(item)

        try:
            success = self.dispatch_callback(item)
        except NoEffectDispatchError as exc:
            self.ledger.mark_failure(item, repr(exc), claim_token=token)
            return ExecutionDecision("DISPATCH_FAILED_RETRYABLE", False, "adapter_proved_no_effect")
        except Exception as exc:
            self.ledger.mark_reconcile_required(item, repr(exc), claim_token=token)
            return ExecutionDecision("RECONCILE_REQUIRED", False, "downstream_outcome_uncertain")

        if success is True:
            self.ledger.mark_success(item, claim_token=token)
            return core_decision
        self.ledger.mark_reconcile_required(item, "callback_did_not_confirm_success", claim_token=token)
        return ExecutionDecision("RECONCILE_REQUIRED", False, "callback_did_not_confirm_success")
