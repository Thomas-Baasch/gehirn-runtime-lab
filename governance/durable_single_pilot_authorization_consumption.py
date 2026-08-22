from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from governance.m4_single_pilot_authority_boundary import (
    AuthorityDecision,
    AuthorityStatus,
    OwnerAuthorizationEvidence,
    PilotIntent,
)


class ConsumptionStatus(str, Enum):
    CLAIMED_NEW = "CLAIMED_NEW"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    SCOPE_CONFLICT_BLOCKED = "SCOPE_CONFLICT_BLOCKED"
    EVIDENCE_REUSE_BLOCKED = "EVIDENCE_REUSE_BLOCKED"
    AUTHORITY_BLOCKED = "AUTHORITY_BLOCKED"
    CONSUMED = "CONSUMED"
    NOOP_ALREADY_CONSUMED = "NOOP_ALREADY_CONSUMED"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class ConsumptionDecision:
    status: ConsumptionStatus
    reason: str
    record_updated: bool = False
    dispatch_executed: bool = False
    retry_executed: bool = False
    authority_created: bool = False


@dataclass(frozen=True)
class ConsumptionRecord:
    grant_id: str
    source_evidence_sha256: str
    authorization_scope_sha256: str
    preflight_snapshot_sha256: str
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    target_adapter: str
    expected_repository: str
    expected_workflow_id: int
    expected_ref: str
    expected_head_sha: str
    exact_run_name_token: str
    outcome_contract_sha256: str
    issued_at: str
    expires_at: str
    status: str
    downstream_run_id: str | None
    receipt_source_ref: str | None
    receipt_evidence_sha256: str | None


@dataclass(frozen=True)
class VerifiedDispatchReceipt:
    verification_state: str
    source_health: str
    receipt_evidence_sha256: str
    grant_id: str
    authorization_scope_sha256: str
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    downstream_run_id: str
    expected_head_sha: str
    receipt_source_ref: str


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_VALID_AUTHORITY = AuthorityStatus.AUTHORIZATION_EVIDENCE_VALID_FOR_SEPARATE_SINGLE_DISPATCH
_VERIFIED_RECEIPT = "VERIFIED_EXACT_DISPATCH_RECEIPT"


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value))


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def authorization_scope_payload(intent: PilotIntent, grant: OwnerAuthorizationEvidence) -> dict[str, Any]:
    return {
        "grant_id": grant.grant_id,
        "preflight_snapshot_sha256": grant.preflight_snapshot_sha256,
        "home_system": intent.home_system,
        "work_id": intent.work_id,
        "dedupe_key": intent.dedupe_key,
        "target": intent.target,
        "target_adapter": intent.target_adapter,
        "adapter_contract_drive_id": intent.adapter_contract_drive_id,
        "adapter_contract_sha256": intent.adapter_contract_sha256,
        "action_class": intent.action_class,
        "expected_repository": intent.expected_repository,
        "expected_workflow_id": intent.expected_workflow_id,
        "expected_event": intent.expected_event,
        "expected_ref": intent.expected_ref,
        "expected_head_sha": intent.expected_head_sha,
        "exact_run_name_token": intent.exact_run_name_token,
        "outcome_contract_drive_id": intent.outcome_contract_drive_id,
        "outcome_contract_sha256": intent.outcome_contract_sha256,
        "expected_artifact_name": intent.expected_artifact_name,
        "expected_outcome_path": intent.expected_outcome_path,
        "outcome_schema": intent.outcome_schema,
        "preflight_contract_drive_id": intent.preflight_contract_drive_id,
        "preflight_contract_sha256": intent.preflight_contract_sha256,
    }


def authorization_scope_sha256(intent: PilotIntent, grant: OwnerAuthorizationEvidence) -> str:
    raw = json.dumps(authorization_scope_payload(intent, grant), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DurableSinglePilotAuthorizationConsumptionLedger:
    """Durably claim and consume already-validated single-pilot owner grants.

    This ledger never creates owner authority and has no dispatch surface.
    A CLAIMED state is intentionally sticky across restart: if downstream
    execution is uncertain, the caller must reconcile rather than claim again.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS authorization_consumption (
                    grant_id TEXT PRIMARY KEY,
                    source_evidence_sha256 TEXT NOT NULL UNIQUE,
                    authorization_scope_sha256 TEXT NOT NULL,
                    preflight_snapshot_sha256 TEXT NOT NULL,
                    home_system TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    target TEXT NOT NULL,
                    target_adapter TEXT NOT NULL,
                    expected_repository TEXT NOT NULL,
                    expected_workflow_id INTEGER NOT NULL,
                    expected_ref TEXT NOT NULL,
                    expected_head_sha TEXT NOT NULL,
                    exact_run_name_token TEXT NOT NULL,
                    outcome_contract_sha256 TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    downstream_run_id TEXT,
                    receipt_source_ref TEXT,
                    receipt_evidence_sha256 TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS authorization_consumption_audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    grant_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def _audit(conn: sqlite3.Connection, event_type: str, grant_id: str, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO authorization_consumption_audit(event_type,grant_id,payload_json) VALUES(?,?,?)",
            (event_type, grant_id, json.dumps(payload, sort_keys=True, ensure_ascii=False)),
        )

    @staticmethod
    def _authority_ok(decision: AuthorityDecision, grant: OwnerAuthorizationEvidence, *, as_of: datetime) -> bool:
        if (
            decision.status is not _VALID_AUTHORITY
            or not decision.valid
            or decision.dispatch_executed
            or decision.claim_executed
            or decision.retry_executed
            or decision.write_executed
            or decision.authority_created
        ):
            return False
        if not _aware(as_of) or not _aware(grant.issued_at) or not _aware(grant.expires_at):
            return False
        if grant.revoked or grant.max_dispatches != 1 or grant.used_dispatches != 0:
            return False
        if as_of < grant.issued_at or as_of > grant.expires_at:
            return False
        if not _nonblank(grant.grant_id) or not _sha(grant.source_evidence_sha256) or not _sha(grant.preflight_snapshot_sha256):
            return False
        return True

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ConsumptionRecord:
        return ConsumptionRecord(
            grant_id=str(row["grant_id"]),
            source_evidence_sha256=str(row["source_evidence_sha256"]),
            authorization_scope_sha256=str(row["authorization_scope_sha256"]),
            preflight_snapshot_sha256=str(row["preflight_snapshot_sha256"]),
            home_system=str(row["home_system"]),
            work_id=str(row["work_id"]),
            dedupe_key=str(row["dedupe_key"]),
            target=str(row["target"]),
            target_adapter=str(row["target_adapter"]),
            expected_repository=str(row["expected_repository"]),
            expected_workflow_id=int(row["expected_workflow_id"]),
            expected_ref=str(row["expected_ref"]),
            expected_head_sha=str(row["expected_head_sha"]),
            exact_run_name_token=str(row["exact_run_name_token"]),
            outcome_contract_sha256=str(row["outcome_contract_sha256"]),
            issued_at=str(row["issued_at"]),
            expires_at=str(row["expires_at"]),
            status=str(row["status"]),
            downstream_run_id=row["downstream_run_id"],
            receipt_source_ref=row["receipt_source_ref"],
            receipt_evidence_sha256=row["receipt_evidence_sha256"],
        )

    def claim(
        self,
        intent: PilotIntent,
        grant: OwnerAuthorizationEvidence,
        authority_decision: AuthorityDecision,
        *,
        as_of: datetime,
    ) -> ConsumptionDecision:
        if not self._authority_ok(authority_decision, grant, as_of=as_of):
            return ConsumptionDecision(ConsumptionStatus.AUTHORITY_BLOCKED, "upstream_authority_not_exactly_valid")

        scope_sha = authorization_scope_sha256(intent, grant)
        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT * FROM authorization_consumption WHERE grant_id=?", (grant.grant_id,)).fetchone()
                if existing is not None:
                    rec = self._record_from_row(existing)
                    if rec.authorization_scope_sha256 != scope_sha or rec.source_evidence_sha256 != grant.source_evidence_sha256:
                        self._audit(conn, "SCOPE_CONFLICT_BLOCKED", grant.grant_id, {"existing_scope": rec.authorization_scope_sha256, "requested_scope": scope_sha})
                        conn.execute("COMMIT")
                        return ConsumptionDecision(ConsumptionStatus.SCOPE_CONFLICT_BLOCKED, "grant_id_reused_with_different_scope")
                    if rec.status == "CONSUMED":
                        self._audit(conn, "CLAIM_NOOP_ALREADY_CONSUMED", grant.grant_id, {})
                        conn.execute("COMMIT")
                        return ConsumptionDecision(ConsumptionStatus.NOOP_ALREADY_CONSUMED, "grant_already_consumed")
                    if rec.status in {"CLAIMED", "RECONCILE_REQUIRED"}:
                        self._audit(conn, "CLAIM_PRESENT_BLOCKED", grant.grant_id, {"status": rec.status})
                        conn.execute("COMMIT")
                        return ConsumptionDecision(ConsumptionStatus.RECONCILE_REQUIRED, "durable_grant_claim_already_present")
                    self._audit(conn, "UNKNOWN_STATE_BLOCKED", grant.grant_id, {"status": rec.status})
                    conn.execute("COMMIT")
                    return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "unknown_consumption_state")

                reused = conn.execute(
                    "SELECT grant_id FROM authorization_consumption WHERE source_evidence_sha256=?",
                    (grant.source_evidence_sha256,),
                ).fetchone()
                if reused is not None:
                    other = str(reused["grant_id"])
                    self._audit(conn, "EVIDENCE_REUSE_BLOCKED", grant.grant_id, {"existing_grant_id": other})
                    conn.execute("COMMIT")
                    return ConsumptionDecision(ConsumptionStatus.EVIDENCE_REUSE_BLOCKED, "same_owner_evidence_already_bound_to_another_grant")

                conn.execute(
                    """
                    INSERT INTO authorization_consumption(
                        grant_id,source_evidence_sha256,authorization_scope_sha256,preflight_snapshot_sha256,
                        home_system,work_id,dedupe_key,target,target_adapter,expected_repository,
                        expected_workflow_id,expected_ref,expected_head_sha,exact_run_name_token,
                        outcome_contract_sha256,issued_at,expires_at,status
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'CLAIMED')
                    """,
                    (
                        grant.grant_id,
                        grant.source_evidence_sha256,
                        scope_sha,
                        grant.preflight_snapshot_sha256,
                        intent.home_system,
                        intent.work_id,
                        intent.dedupe_key,
                        intent.target,
                        intent.target_adapter,
                        intent.expected_repository,
                        intent.expected_workflow_id,
                        intent.expected_ref,
                        intent.expected_head_sha,
                        intent.exact_run_name_token,
                        intent.outcome_contract_sha256,
                        grant.issued_at.isoformat(),
                        grant.expires_at.isoformat(),
                    ),
                )
                self._audit(conn, "CLAIMED", grant.grant_id, {"scope_sha256": scope_sha, "source_evidence_sha256": grant.source_evidence_sha256})
                conn.execute("COMMIT")
                return ConsumptionDecision(ConsumptionStatus.CLAIMED_NEW, "single_use_authorization_durably_claimed", record_updated=True)
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "authorization_consumption_database_error")

    def mark_reconcile_required(self, grant_id: str, reason: str) -> ConsumptionDecision:
        if not _nonblank(grant_id) or not _nonblank(reason):
            return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "reconcile_identity_or_reason_missing")
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT status FROM authorization_consumption WHERE grant_id=?", (grant_id,)).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "reconcile_without_claim")
                status = str(row["status"])
                if status == "CONSUMED":
                    self._audit(conn, "RECONCILE_NOOP_ALREADY_CONSUMED", grant_id, {"reason": reason})
                    conn.execute("COMMIT")
                    return ConsumptionDecision(ConsumptionStatus.NOOP_ALREADY_CONSUMED, "consumed_is_not_downgraded")
                if status not in {"CLAIMED", "RECONCILE_REQUIRED"}:
                    self._audit(conn, "RECONCILE_STATE_BLOCKED", grant_id, {"status": status})
                    conn.execute("COMMIT")
                    return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "reconcile_state_not_allowlisted")
                conn.execute(
                    "UPDATE authorization_consumption SET status='RECONCILE_REQUIRED', updated_at=CURRENT_TIMESTAMP WHERE grant_id=?",
                    (grant_id,),
                )
                self._audit(conn, "RECONCILE_REQUIRED", grant_id, {"from": status, "reason": reason})
                conn.execute("COMMIT")
                return ConsumptionDecision(ConsumptionStatus.RECONCILE_REQUIRED, "grant_requires_downstream_reconciliation", record_updated=status != "RECONCILE_REQUIRED")
        except sqlite3.DatabaseError:
            return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "authorization_consumption_database_error")

    @staticmethod
    def _receipt_valid(receipt: VerifiedDispatchReceipt) -> bool:
        return (
            receipt.verification_state == _VERIFIED_RECEIPT
            and receipt.source_health == "FRESH"
            and _sha(receipt.receipt_evidence_sha256)
            and _nonblank(receipt.grant_id)
            and _sha(receipt.authorization_scope_sha256)
            and all(
                _nonblank(v)
                for v in (
                    receipt.home_system,
                    receipt.work_id,
                    receipt.dedupe_key,
                    receipt.target,
                    receipt.downstream_run_id,
                    receipt.expected_head_sha,
                    receipt.receipt_source_ref,
                )
            )
        )

    def consume(self, receipt: VerifiedDispatchReceipt) -> ConsumptionDecision:
        if not self._receipt_valid(receipt):
            return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "verified_dispatch_receipt_invalid")
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM authorization_consumption WHERE grant_id=?", (receipt.grant_id,)).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "consume_without_claim")
                rec = self._record_from_row(row)

                exact_scope = (
                    rec.authorization_scope_sha256 == receipt.authorization_scope_sha256
                    and rec.home_system == receipt.home_system
                    and rec.work_id == receipt.work_id
                    and rec.dedupe_key == receipt.dedupe_key
                    and rec.target == receipt.target
                    and rec.expected_head_sha == receipt.expected_head_sha
                )
                if not exact_scope:
                    if rec.status in {"CLAIMED", "RECONCILE_REQUIRED"}:
                        conn.execute(
                            "UPDATE authorization_consumption SET status='RECONCILE_REQUIRED', updated_at=CURRENT_TIMESTAMP WHERE grant_id=?",
                            (receipt.grant_id,),
                        )
                    self._audit(conn, "RECEIPT_SCOPE_CONFLICT_BLOCKED", receipt.grant_id, {"receipt_scope": receipt.authorization_scope_sha256, "record_scope": rec.authorization_scope_sha256})
                    conn.execute("COMMIT")
                    return ConsumptionDecision(ConsumptionStatus.SCOPE_CONFLICT_BLOCKED, "dispatch_receipt_scope_mismatch", record_updated=rec.status == "CLAIMED")

                if rec.status == "CONSUMED":
                    same_receipt = (
                        rec.downstream_run_id == receipt.downstream_run_id
                        and rec.receipt_source_ref == receipt.receipt_source_ref
                        and rec.receipt_evidence_sha256 == receipt.receipt_evidence_sha256
                    )
                    self._audit(conn, "CONSUME_REPLAY", receipt.grant_id, {"same_receipt": same_receipt})
                    conn.execute("COMMIT")
                    if same_receipt:
                        return ConsumptionDecision(ConsumptionStatus.NOOP_ALREADY_CONSUMED, "exact_consumption_receipt_replayed_idempotently")
                    return ConsumptionDecision(ConsumptionStatus.CONFLICT_BLOCKED, "consumed_grant_presented_with_different_receipt")

                if rec.status not in {"CLAIMED", "RECONCILE_REQUIRED"}:
                    self._audit(conn, "CONSUME_STATE_BLOCKED", receipt.grant_id, {"status": rec.status})
                    conn.execute("COMMIT")
                    return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "consume_state_not_allowlisted")

                conn.execute(
                    """
                    UPDATE authorization_consumption
                    SET status='CONSUMED', downstream_run_id=?, receipt_source_ref=?, receipt_evidence_sha256=?, updated_at=CURRENT_TIMESTAMP
                    WHERE grant_id=?
                    """,
                    (receipt.downstream_run_id, receipt.receipt_source_ref, receipt.receipt_evidence_sha256, receipt.grant_id),
                )
                self._audit(conn, "CONSUMED", receipt.grant_id, {"downstream_run_id": receipt.downstream_run_id, "receipt_evidence_sha256": receipt.receipt_evidence_sha256})
                conn.execute("COMMIT")
                return ConsumptionDecision(ConsumptionStatus.CONSUMED, "exact_verified_dispatch_receipt_consumed_single_use_grant", record_updated=True)
        except sqlite3.DatabaseError:
            return ConsumptionDecision(ConsumptionStatus.FAIL_CLOSED, "authorization_consumption_database_error")

    def state(self, grant_id: str) -> ConsumptionRecord | None:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM authorization_consumption WHERE grant_id=?", (grant_id,)).fetchone()
                return None if row is None else self._record_from_row(row)
        except sqlite3.DatabaseError:
            return None

    def audit(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq,event_type,grant_id,payload_json,created_at FROM authorization_consumption_audit ORDER BY seq"
            ).fetchall()
            return [
                {
                    "seq": int(row["seq"]),
                    "event_type": str(row["event_type"]),
                    "grant_id": str(row["grant_id"]),
                    "payload": json.loads(row["payload_json"]),
                    "created_at": str(row["created_at"]),
                }
                for row in rows
            ]

    def integrity_ok(self) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                return row is not None and str(row[0]).lower() == "ok"
        except sqlite3.DatabaseError:
            return False
