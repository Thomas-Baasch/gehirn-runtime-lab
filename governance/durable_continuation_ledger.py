from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from governance.safe_continuation_executor import ExecutionDecision, SafeContinuationExecutor, WorkItem


class UncertainDispatchOutcome(RuntimeError):
    """The downstream effect may have happened; local success is unproven."""


@dataclass(frozen=True)
class ClaimState:
    dedupe_key: str
    status: str
    attempt_count: int
    retry_limit: int
    last_error: str | None


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

    @staticmethod
    def _audit(conn: sqlite3.Connection, event_type: str, item: WorkItem, payload: dict) -> None:
        conn.execute(
            "INSERT INTO audit_events(event_type,work_id,dedupe_key,payload_json) VALUES(?,?,?,?)",
            (event_type, item.work_id, item.dedupe_key, json.dumps(payload, sort_keys=True, ensure_ascii=False)),
        )

    def claim(self, item: WorkItem) -> str:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO dispatch_claims(dedupe_key,work_id,home_system,action_class,status,attempt_count,retry_limit,last_error) VALUES(?,?,?,?,?,?,?,NULL)",
                        (item.dedupe_key, item.work_id, item.home_system, item.action_class, "CLAIMED", 1, item.retry_limit),
                    )
                    self._audit(conn, "CLAIMED", item, {"attempt_count": 1, "action_class": item.action_class})
                    conn.execute("COMMIT")
                    return "CLAIMED_NEW"

                status = str(row["status"])
                attempts = int(row["attempt_count"])
                retry_limit = int(row["retry_limit"])
                if status == "SUCCEEDED":
                    self._audit(conn, "DUPLICATE_BLOCKED", item, {"status": status, "attempt_count": attempts})
                    conn.execute("COMMIT")
                    return "NOOP_DUPLICATE"
                if status in {"CLAIMED", "RECONCILE_REQUIRED"}:
                    if status == "CLAIMED":
                        conn.execute("UPDATE dispatch_claims SET status='RECONCILE_REQUIRED', updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=?", (item.dedupe_key,))
                    self._audit(conn, "RECONCILE_REQUIRED", item, {"previous_status": status, "attempt_count": attempts})
                    conn.execute("COMMIT")
                    return "RECONCILE_REQUIRED"
                if status == "FAILED_RETRYABLE":
                    if attempts >= retry_limit or attempts >= item.retry_limit:
                        self._audit(conn, "CIRCUIT_OPEN", item, {"attempt_count": attempts, "retry_limit": min(retry_limit, item.retry_limit)})
                        conn.execute("COMMIT")
                        return "CIRCUIT_OPEN"
                    next_attempt = attempts + 1
                    conn.execute(
                        "UPDATE dispatch_claims SET status='CLAIMED', attempt_count=?, retry_limit=?, last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=?",
                        (next_attempt, min(retry_limit, item.retry_limit), item.dedupe_key),
                    )
                    self._audit(conn, "RETRY_CLAIMED", item, {"attempt_count": next_attempt})
                    conn.execute("COMMIT")
                    return "CLAIMED_RETRY"

                self._audit(conn, "UNKNOWN_STATUS_BLOCKED", item, {"status": status})
                conn.execute("COMMIT")
                return "FAIL_CLOSED_UNKNOWN_STATUS"
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def mark_success(self, item: WorkItem) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            if row is None or row["status"] != "CLAIMED":
                conn.execute("ROLLBACK")
                raise RuntimeError("success_without_active_claim")
            conn.execute("UPDATE dispatch_claims SET status='SUCCEEDED', last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=?", (item.dedupe_key,))
            self._audit(conn, "SUCCEEDED", item, {"action_class": item.action_class})
            conn.execute("COMMIT")

    def mark_failure(self, item: WorkItem, error: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            if row is None or row["status"] != "CLAIMED":
                conn.execute("ROLLBACK")
                raise RuntimeError("failure_without_active_claim")
            conn.execute("UPDATE dispatch_claims SET status='FAILED_RETRYABLE', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=?", (error, item.dedupe_key))
            self._audit(conn, "FAILED_RETRYABLE", item, {"error": error})
            conn.execute("COMMIT")

    def mark_reconcile_required(self, item: WorkItem, reason: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM dispatch_claims WHERE dedupe_key=?", (item.dedupe_key,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise RuntimeError("reconcile_without_claim")
            conn.execute("UPDATE dispatch_claims SET status='RECONCILE_REQUIRED', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE dedupe_key=?", (reason, item.dedupe_key))
            self._audit(conn, "RECONCILE_REQUIRED", item, {"reason": reason})
            conn.execute("COMMIT")

    def state(self, dedupe_key: str) -> ClaimState | None:
        with self._connect() as conn:
            row = conn.execute("SELECT dedupe_key,status,attempt_count,retry_limit,last_error FROM dispatch_claims WHERE dedupe_key=?", (dedupe_key,)).fetchone()
            if row is None:
                return None
            return ClaimState(str(row["dedupe_key"]), str(row["status"]), int(row["attempt_count"]), int(row["retry_limit"]), row["last_error"])

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
            claim = self.ledger.claim(item)
        except sqlite3.DatabaseError:
            return ExecutionDecision("FAIL_CLOSED_LEDGER_ERROR", False, "ledger_database_error")
        if claim == "NOOP_DUPLICATE":
            return ExecutionDecision("NOOP_DUPLICATE", False, "durable_success_dedupe")
        if claim == "RECONCILE_REQUIRED":
            return ExecutionDecision("RECONCILE_REQUIRED", False, "durable_claim_uncertain")
        if claim == "CIRCUIT_OPEN":
            return ExecutionDecision("CIRCUIT_OPEN", False, "durable_retry_limit")
        if claim == "FAIL_CLOSED_UNKNOWN_STATUS":
            return ExecutionDecision("FAIL_CLOSED_LEDGER_STATUS", False, "unknown_durable_status")
        if claim not in {"CLAIMED_NEW", "CLAIMED_RETRY"}:
            return ExecutionDecision("FAIL_CLOSED_LEDGER_STATUS", False, "unexpected_claim_result")

        if self.after_claim_hook is not None:
            # A real hard crash here leaves CLAIMED in SQLite. On reopen the next
            # executor will reconcile rather than blindly redispatch.
            self.after_claim_hook(item)

        try:
            success = bool(self.dispatch_callback(item))
        except UncertainDispatchOutcome as exc:
            self.ledger.mark_reconcile_required(item, repr(exc))
            return ExecutionDecision("RECONCILE_REQUIRED", False, "downstream_outcome_uncertain")
        except Exception as exc:
            self.ledger.mark_failure(item, repr(exc))
            return ExecutionDecision("DISPATCH_FAILED_RETRYABLE", False, "callback_exception")

        if success:
            self.ledger.mark_success(item)
            return core_decision
        self.ledger.mark_failure(item, "callback_returned_false")
        return ExecutionDecision("DISPATCH_FAILED_RETRYABLE", False, "callback_returned_false")
