from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable


class IncidentDecision(str, Enum):
    NO_INCIDENT = "NO_INCIDENT"
    LOCAL_ROLLBACK_ALLOWED = "LOCAL_ROLLBACK_ALLOWED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    OWNER_REQUIRED = "OWNER_REQUIRED"
    STOPPED = "STOPPED"
    FAIL_CLOSED = "FAIL_CLOSED"


class RollbackClaimStatus(str, Enum):
    CLAIMED_NEW = "CLAIMED_NEW"
    SUCCEEDED = "SUCCEEDED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    NOOP_ALREADY_SUCCEEDED = "NOOP_ALREADY_SUCCEEDED"
    SCOPE_CONFLICT_BLOCKED = "SCOPE_CONFLICT_BLOCKED"
    DECISION_BLOCKED = "DECISION_BLOCKED"


@dataclass(frozen=True)
class IncidentEvidence:
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    adapter_contract_id: str
    adapter_contract_sha256: str
    action_class: str
    durable_claim_status: str
    authorization_grant_id: str | None
    authorization_consumption_status: str | None
    grant_reuse_attempt: bool
    downstream_run_id: str | None
    downstream_outcome_status: str
    source_health: str
    source_fresh: bool
    source_conflict: bool
    stop_latch: bool
    owner_gate: bool
    incident_cause: str
    rollback_action_id: str
    rollback_action_allowlisted: bool
    rollback_reversible: bool
    rollback_external_effect: bool
    external_effect_possible: bool
    requested_permissions: tuple[str, ...]
    minimum_permissions: tuple[str, ...]
    retry_count: int
    retry_limit: int
    circuit_open: bool
    audit_integrity: bool
    ledger_integrity: bool
    identity_scope_match: bool
    adapter_binding_match: bool


@dataclass(frozen=True)
class IncidentAssessment:
    decision: IncidentDecision
    reason: str


@dataclass(frozen=True)
class RollbackClaimResult:
    status: RollbackClaimStatus
    scope_key: str
    scope_sha256: str
    detail: str = ""


def _present(value: str | None) -> bool:
    return bool(value and value.strip())


def _permissions_within_minimum(requested: Iterable[str], minimum: Iterable[str]) -> bool:
    return set(requested).issubset(set(minimum))


def classify_incident(e: IncidentEvidence) -> IncidentAssessment:
    # Contract order is fail-closed: an earlier hard boundary is never overruled later.
    if e.stop_latch:
        return IncidentAssessment(IncidentDecision.STOPPED, "stop_latch_active")
    if e.owner_gate:
        return IncidentAssessment(IncidentDecision.OWNER_REQUIRED, "owner_gate_active")

    mandatory = (
        e.home_system,
        e.work_id,
        e.dedupe_key,
        e.target,
        e.adapter_contract_id,
        e.adapter_contract_sha256,
        e.action_class,
        e.durable_claim_status,
        e.incident_cause,
        e.rollback_action_id,
    )
    if not all(_present(x) for x in mandatory):
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "mandatory_evidence_missing")
    if not e.audit_integrity or not e.ledger_integrity:
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "audit_or_ledger_integrity_failed")
    if not e.identity_scope_match or not e.adapter_binding_match:
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "identity_scope_or_adapter_mismatch")
    if e.retry_count < 0 or e.retry_limit < 0:
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "invalid_retry_state")
    if e.grant_reuse_attempt:
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "one_shot_grant_reuse_forbidden")

    if e.source_conflict:
        return IncidentAssessment(IncidentDecision.RECONCILE_REQUIRED, "source_conflict")
    if e.source_health != "FRESH" or not e.source_fresh:
        return IncidentAssessment(IncidentDecision.RECONCILE_REQUIRED, "source_stale_or_unhealthy")

    # A verified success blocks automatic rollback. If local durable state disagrees,
    # reconcile the state instead of pretending the incident is fully closed.
    if e.downstream_outcome_status == "VERIFIED_SUCCESS":
        if e.durable_claim_status in {"SUCCEEDED", "CONSUMED"}:
            return IncidentAssessment(IncidentDecision.NO_INCIDENT, "verified_success_consistent")
        return IncidentAssessment(IncidentDecision.RECONCILE_REQUIRED, "verified_success_local_state_mismatch")

    if e.external_effect_possible:
        return IncidentAssessment(IncidentDecision.RECONCILE_REQUIRED, "external_effect_possible_or_unknown")
    if e.downstream_outcome_status in {"UNKNOWN", "MISSING", "CONFLICTING"}:
        return IncidentAssessment(IncidentDecision.RECONCILE_REQUIRED, "downstream_outcome_uncertain")
    if e.durable_claim_status in {"CLAIMED", "RECONCILE_REQUIRED", "UNKNOWN"}:
        return IncidentAssessment(IncidentDecision.RECONCILE_REQUIRED, "durable_claim_uncertain")

    if e.rollback_external_effect or not e.rollback_reversible:
        return IncidentAssessment(IncidentDecision.OWNER_REQUIRED, "rollback_has_external_or_irreversible_effect")
    if e.action_class != "INTERNAL_LOCAL_ROLLBACK":
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "rollback_action_class_not_internal_local")
    if not e.rollback_action_allowlisted:
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "rollback_action_not_allowlisted")
    if not _permissions_within_minimum(e.requested_permissions, e.minimum_permissions):
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "least_privilege_violation")
    if e.circuit_open or e.retry_count >= e.retry_limit:
        return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "retry_limit_or_circuit_open")

    if e.downstream_outcome_status == "VERIFIED_NO_EXTERNAL_EFFECT" and e.durable_claim_status in {
        "FAILED_LOCAL",
        "FAILED_RETRYABLE",
    }:
        return IncidentAssessment(IncidentDecision.LOCAL_ROLLBACK_ALLOWED, "safe_local_rollback_preconditions_met")

    return IncidentAssessment(IncidentDecision.FAIL_CLOSED, "no_contractually_safe_automatic_path")


def rollback_scope_key(e: IncidentEvidence) -> str:
    raw = "\x1f".join((e.home_system, e.work_id, e.dedupe_key, e.target, e.rollback_action_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rollback_scope_sha256(e: IncidentEvidence) -> str:
    payload = {
        "home_system": e.home_system,
        "work_id": e.work_id,
        "dedupe_key": e.dedupe_key,
        "target": e.target,
        "adapter_contract_id": e.adapter_contract_id,
        "adapter_contract_sha256": e.adapter_contract_sha256,
        "action_class": e.action_class,
        "rollback_action_id": e.rollback_action_id,
        "requested_permissions": sorted(e.requested_permissions),
        "minimum_permissions": sorted(e.minimum_permissions),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DurableRollbackLedger:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        parent = Path(self.path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rollback_claims (
                    scope_key TEXT PRIMARY KEY,
                    scope_sha256 TEXT NOT NULL,
                    home_system TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    target TEXT NOT NULL,
                    rollback_action_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _audit(conn: sqlite3.Connection, event_type: str, scope_key: str, payload: dict) -> None:
        conn.execute(
            "INSERT INTO audit_events(event_type, scope_key, payload_json, created_at) VALUES(?,?,?,?)",
            (event_type, scope_key, json.dumps(payload, sort_keys=True, separators=(",", ":")), DurableRollbackLedger._now()),
        )

    def claim(self, e: IncidentEvidence, assessment: IncidentAssessment) -> RollbackClaimResult:
        key = rollback_scope_key(e)
        sha = rollback_scope_sha256(e)
        if assessment.decision is not IncidentDecision.LOCAL_ROLLBACK_ALLOWED:
            return RollbackClaimResult(RollbackClaimStatus.DECISION_BLOCKED, key, sha, assessment.reason)

        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM rollback_claims WHERE scope_key=?", (key,)).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO rollback_claims(
                        scope_key, scope_sha256, home_system, work_id, dedupe_key, target,
                        rollback_action_id, status, last_error, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (key, sha, e.home_system, e.work_id, e.dedupe_key, e.target, e.rollback_action_id,
                     "CLAIMED", None, now, now),
                )
                self._audit(conn, "ROLLBACK_CLAIMED", key, {"scope_sha256": sha})
                conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.CLAIMED_NEW, key, sha)

            if row["scope_sha256"] != sha:
                self._audit(conn, "ROLLBACK_SCOPE_CONFLICT_BLOCKED", key, {"existing": row["scope_sha256"], "requested": sha})
                conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.SCOPE_CONFLICT_BLOCKED, key, sha, "scope_hash_mismatch")

            if row["status"] == "SUCCEEDED":
                self._audit(conn, "ROLLBACK_DUPLICATE_NOOP", key, {"scope_sha256": sha})
                conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.NOOP_ALREADY_SUCCEEDED, key, sha)

            if row["status"] == "CLAIMED":
                conn.execute(
                    "UPDATE rollback_claims SET status='RECONCILE_REQUIRED', updated_at=? WHERE scope_key=?",
                    (now, key),
                )
                self._audit(conn, "ROLLBACK_CLAIM_UNCERTAIN_RECONCILE", key, {"scope_sha256": sha})
                conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.RECONCILE_REQUIRED, key, sha, "prior_claim_has_no_verified_result")

            self._audit(conn, "ROLLBACK_RECONCILE_STICKY", key, {"scope_sha256": sha})
            conn.commit()
            return RollbackClaimResult(RollbackClaimStatus.RECONCILE_REQUIRED, key, sha, "reconcile_required_sticky")

    def mark_succeeded(self, scope_key: str, scope_sha256: str) -> RollbackClaimResult:
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM rollback_claims WHERE scope_key=?", (scope_key,)).fetchone()
            if row is None or row["scope_sha256"] != scope_sha256:
                if row is not None:
                    self._audit(conn, "ROLLBACK_RESULT_SCOPE_CONFLICT", scope_key, {"requested": scope_sha256})
                    conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.SCOPE_CONFLICT_BLOCKED, scope_key, scope_sha256)
            if row["status"] == "SUCCEEDED":
                self._audit(conn, "ROLLBACK_SUCCESS_DUPLICATE_NOOP", scope_key, {"scope_sha256": scope_sha256})
                conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.NOOP_ALREADY_SUCCEEDED, scope_key, scope_sha256)
            if row["status"] != "CLAIMED":
                self._audit(conn, "ROLLBACK_RESULT_BLOCKED_RECONCILE", scope_key, {"status": row["status"]})
                conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.RECONCILE_REQUIRED, scope_key, scope_sha256)
            conn.execute(
                "UPDATE rollback_claims SET status='SUCCEEDED', last_error=NULL, updated_at=? WHERE scope_key=?",
                (now, scope_key),
            )
            self._audit(conn, "ROLLBACK_SUCCEEDED", scope_key, {"scope_sha256": scope_sha256})
            conn.commit()
            return RollbackClaimResult(RollbackClaimStatus.SUCCEEDED, scope_key, scope_sha256)

    def mark_reconcile_required(self, scope_key: str, scope_sha256: str, reason: str) -> RollbackClaimResult:
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM rollback_claims WHERE scope_key=?", (scope_key,)).fetchone()
            if row is None or row["scope_sha256"] != scope_sha256:
                if row is not None:
                    self._audit(conn, "ROLLBACK_RECONCILE_SCOPE_CONFLICT", scope_key, {"requested": scope_sha256})
                    conn.commit()
                return RollbackClaimResult(RollbackClaimStatus.SCOPE_CONFLICT_BLOCKED, scope_key, scope_sha256)
            conn.execute(
                "UPDATE rollback_claims SET status='RECONCILE_REQUIRED', last_error=?, updated_at=? WHERE scope_key=?",
                (reason, now, scope_key),
            )
            self._audit(conn, "ROLLBACK_RECONCILE_REQUIRED", scope_key, {"reason": reason, "scope_sha256": scope_sha256})
            conn.commit()
            return RollbackClaimResult(RollbackClaimStatus.RECONCILE_REQUIRED, scope_key, scope_sha256, reason)

    def state(self, scope_key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM rollback_claims WHERE scope_key=?", (scope_key,)).fetchone()
            return dict(row) if row else None

    def audit(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM audit_events ORDER BY seq")]

    def integrity_ok(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row and row[0] == "ok")
