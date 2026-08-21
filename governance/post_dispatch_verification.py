from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Iterable, Mapping


class VerificationStatus(str, Enum):
    EXACT_ACTIVE_FRESH = "EXACT_ACTIVE_FRESH"
    EXACT_SUCCEEDED = "EXACT_SUCCEEDED"
    EXACT_FAILED = "EXACT_FAILED"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    IDENTITY_BLOCKED = "IDENTITY_BLOCKED"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    TEMPORAL_BLOCKED = "TEMPORAL_BLOCKED"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    OWNER_GATE_BLOCKED = "OWNER_GATE_BLOCKED"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class DispatchReceipt:
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    downstream_run_id: str
    expected_head_sha: str
    expected_workflow_fingerprint: str
    dispatch_recorded_at: datetime
    receipt_source_ref: str


@dataclass(frozen=True)
class RunObservation:
    source_health: str
    observed_at: datetime
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    downstream_run_id: str
    head_sha: str
    workflow_fingerprint: str
    state: str
    run_created_at: datetime
    heartbeat_at: datetime | None
    completed_at: datetime | None
    evidence_source_ref: str


@dataclass(frozen=True)
class VerificationDecision:
    status: VerificationStatus
    reason: str
    dispatch_executed: bool = False
    retry_executed: bool = False
    ledger_updated: bool = False


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"missing_{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{key}")
    return value.strip()


def _parse_time(value: Any, key: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{key}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid_{key}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timezone_required_{key}")
    return parsed


def parse_dispatch_receipt(payload: Mapping[str, Any]) -> DispatchReceipt:
    return DispatchReceipt(
        home_system=_required_string(payload, "home_system"),
        work_id=_required_string(payload, "work_id"),
        dedupe_key=_required_string(payload, "dedupe_key"),
        target=_required_string(payload, "target"),
        downstream_run_id=_required_string(payload, "downstream_run_id"),
        expected_head_sha=_required_string(payload, "expected_head_sha"),
        expected_workflow_fingerprint=_required_string(payload, "expected_workflow_fingerprint"),
        dispatch_recorded_at=_parse_time(payload.get("dispatch_recorded_at"), "dispatch_recorded_at"),
        receipt_source_ref=_required_string(payload, "receipt_source_ref"),
    )


def parse_run_observation(payload: Mapping[str, Any]) -> RunObservation:
    return RunObservation(
        source_health=_required_string(payload, "source_health").upper(),
        observed_at=_parse_time(payload.get("observed_at"), "observed_at"),
        home_system=_required_string(payload, "home_system"),
        work_id=_required_string(payload, "work_id"),
        dedupe_key=_required_string(payload, "dedupe_key"),
        target=_required_string(payload, "target"),
        downstream_run_id=_required_string(payload, "downstream_run_id"),
        head_sha=_required_string(payload, "head_sha"),
        workflow_fingerprint=_required_string(payload, "workflow_fingerprint"),
        state=_required_string(payload, "state").upper(),
        run_created_at=_parse_time(payload.get("run_created_at"), "run_created_at"),
        heartbeat_at=_parse_time(payload.get("heartbeat_at"), "heartbeat_at", optional=True),
        completed_at=_parse_time(payload.get("completed_at"), "completed_at", optional=True),
        evidence_source_ref=_required_string(payload, "evidence_source_ref"),
    )


class PostDispatchRunVerifier:
    ACTIVE_STATES = frozenset({"QUEUED", "IN_PROGRESS"})
    TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED"})

    def __init__(self, *, heartbeat_max_age_seconds: int = 300, clock_skew_seconds: int = 30) -> None:
        if heartbeat_max_age_seconds <= 0 or clock_skew_seconds < 0:
            raise ValueError("invalid_verifier_limits")
        self.heartbeat_max_age = timedelta(seconds=heartbeat_max_age_seconds)
        self.clock_skew = timedelta(seconds=clock_skew_seconds)

    @staticmethod
    def _identity_matches(receipt: DispatchReceipt, obs: RunObservation) -> bool:
        return (
            obs.home_system == receipt.home_system
            and obs.work_id == receipt.work_id
            and obs.dedupe_key == receipt.dedupe_key
            and obs.target == receipt.target
            and obs.downstream_run_id == receipt.downstream_run_id
            and obs.head_sha == receipt.expected_head_sha
            and obs.workflow_fingerprint == receipt.expected_workflow_fingerprint
        )

    @staticmethod
    def _near_identity(receipt: DispatchReceipt, obs: RunObservation) -> bool:
        return (
            obs.downstream_run_id == receipt.downstream_run_id
            or (
                obs.home_system == receipt.home_system
                and obs.work_id == receipt.work_id
                and obs.dedupe_key == receipt.dedupe_key
                and obs.target == receipt.target
            )
        )

    def verify(
        self,
        receipt: DispatchReceipt,
        observations: Iterable[RunObservation],
        *,
        as_of: datetime,
        owner_gate: bool = False,
        review_gate: bool = False,
        stop_latch: bool = False,
    ) -> VerificationDecision:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            return VerificationDecision(VerificationStatus.FAIL_CLOSED, "as_of_timezone_required")
        if owner_gate or review_gate or stop_latch:
            return VerificationDecision(VerificationStatus.OWNER_GATE_BLOCKED, "owner_review_or_stop_gate")

        rows = list(observations)
        if not rows:
            return VerificationDecision(VerificationStatus.SOURCE_BLOCKED, "no_run_observation")

        exact = [obs for obs in rows if self._identity_matches(receipt, obs)]
        fresh_exact = [obs for obs in exact if obs.source_health == "FRESH"]
        if not fresh_exact:
            if exact:
                return VerificationDecision(VerificationStatus.SOURCE_BLOCKED, "only_stale_exact_observation")
            if any(self._near_identity(receipt, obs) for obs in rows):
                return VerificationDecision(VerificationStatus.IDENTITY_BLOCKED, "run_identity_mismatch")
            return VerificationDecision(VerificationStatus.IDENTITY_BLOCKED, "no_exact_run_identity")

        latest_at = max(obs.observed_at for obs in fresh_exact)
        latest = [obs for obs in fresh_exact if obs.observed_at == latest_at]
        if len({obs.state for obs in latest}) > 1:
            return VerificationDecision(VerificationStatus.CONFLICT_BLOCKED, "conflicting_latest_exact_observations")
        obs = latest[0]

        if obs.observed_at > as_of + self.clock_skew:
            return VerificationDecision(VerificationStatus.TEMPORAL_BLOCKED, "observation_from_future")
        if obs.run_created_at < receipt.dispatch_recorded_at - self.clock_skew:
            return VerificationDecision(VerificationStatus.TEMPORAL_BLOCKED, "run_predates_dispatch")
        if obs.run_created_at > obs.observed_at + self.clock_skew:
            return VerificationDecision(VerificationStatus.TEMPORAL_BLOCKED, "run_created_after_observation")

        if obs.state in self.ACTIVE_STATES:
            if obs.heartbeat_at is None:
                return VerificationDecision(VerificationStatus.HEARTBEAT_STALE, "active_run_missing_heartbeat")
            if obs.heartbeat_at < obs.run_created_at - self.clock_skew or obs.heartbeat_at > obs.observed_at + self.clock_skew:
                return VerificationDecision(VerificationStatus.TEMPORAL_BLOCKED, "heartbeat_temporally_invalid")
            age = as_of - obs.heartbeat_at
            if age > self.heartbeat_max_age:
                return VerificationDecision(VerificationStatus.HEARTBEAT_STALE, "active_run_heartbeat_stale")
            if age < -self.clock_skew:
                return VerificationDecision(VerificationStatus.TEMPORAL_BLOCKED, "heartbeat_from_future")
            return VerificationDecision(VerificationStatus.EXACT_ACTIVE_FRESH, "exact_active_run_with_fresh_heartbeat")

        if obs.state in self.TERMINAL_STATES:
            if obs.completed_at is None:
                return VerificationDecision(VerificationStatus.FAIL_CLOSED, "terminal_run_missing_completion")
            if obs.completed_at < obs.run_created_at - self.clock_skew or obs.completed_at > obs.observed_at + self.clock_skew:
                return VerificationDecision(VerificationStatus.TEMPORAL_BLOCKED, "completion_temporally_invalid")
            if obs.completed_at > as_of + self.clock_skew:
                return VerificationDecision(VerificationStatus.TEMPORAL_BLOCKED, "completion_from_future")
            status = VerificationStatus.EXACT_SUCCEEDED if obs.state == "SUCCEEDED" else VerificationStatus.EXACT_FAILED
            return VerificationDecision(status, f"exact_terminal_{obs.state.lower()}")

        return VerificationDecision(VerificationStatus.FAIL_CLOSED, "unknown_run_state")
