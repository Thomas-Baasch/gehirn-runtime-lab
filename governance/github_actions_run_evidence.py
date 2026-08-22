from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Iterable, Mapping

from governance.post_dispatch_verification import DispatchReceipt, RunObservation


class AdapterStatus(str, Enum):
    OBSERVATION_READY = "OBSERVATION_READY"
    AWAITING_RUN = "AWAITING_RUN"
    RUN_UNCERTAIN = "RUN_UNCERTAIN"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    RECEIPT_INVALID = "RECEIPT_INVALID"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class GitHubDispatchIntent:
    repository: str
    workflow_id: int
    expected_event: str
    expected_ref: str
    expected_head_sha: str
    home_system: str
    work_id: str
    dedupe_key: str
    target: str
    dispatch_recorded_at: datetime
    appearance_deadline_at: datetime
    exact_run_name_token: str
    receipt_source_ref: str


@dataclass(frozen=True)
class AdapterDecision:
    status: AdapterStatus
    reason: str
    dispatch_receipt: DispatchReceipt | None = None
    run_observation: RunObservation | None = None
    downstream_effect_confirmed: bool = False
    dispatch_executed: bool = False
    retry_executed: bool = False
    repository_written: bool = False
    ledger_updated: bool = False


_FAILURE_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}
)


def _aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.utcoffset() is not None


def _require_text(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{key}")
    return value.strip()


def _parse_time(value: Any, key: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{key}")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid_{key}") from exc
    if not _aware(dt):
        raise ValueError(f"timezone_required_{key}")
    return dt


def _repo_name(raw: Mapping[str, Any]) -> str:
    repo = raw.get("repository")
    if isinstance(repo, Mapping):
        return _require_text(repo.get("full_name"), "repository.full_name")
    return _require_text(raw.get("repository_full_name"), "repository_full_name")


class GitHubActionsRunEvidenceAdapter:
    def __init__(
        self,
        *,
        max_source_age_seconds: int = 300,
        clock_skew_seconds: int = 30,
    ) -> None:
        if max_source_age_seconds <= 0 or clock_skew_seconds < 0:
            raise ValueError("invalid_adapter_limits")
        self.max_source_age = timedelta(seconds=max_source_age_seconds)
        self.clock_skew = timedelta(seconds=clock_skew_seconds)

    @staticmethod
    def _intent_valid(intent: GitHubDispatchIntent) -> bool:
        return (
            isinstance(intent.workflow_id, int)
            and intent.workflow_id > 0
            and all(
                isinstance(v, str) and bool(v.strip())
                for v in (
                    intent.repository,
                    intent.expected_event,
                    intent.expected_ref,
                    intent.expected_head_sha,
                    intent.home_system,
                    intent.work_id,
                    intent.dedupe_key,
                    intent.target,
                    intent.exact_run_name_token,
                    intent.receipt_source_ref,
                )
            )
            and _aware(intent.dispatch_recorded_at)
            and _aware(intent.appearance_deadline_at)
            and intent.appearance_deadline_at >= intent.dispatch_recorded_at
        )

    def _matches(self, intent: GitHubDispatchIntent, raw: Mapping[str, Any]) -> bool:
        try:
            if _repo_name(raw) != intent.repository:
                return False
            if int(raw.get("workflow_id")) != intent.workflow_id:
                return False
            if _require_text(raw.get("event"), "event") != intent.expected_event:
                return False
            if _require_text(raw.get("head_branch"), "head_branch") != intent.expected_ref:
                return False
            if _require_text(raw.get("head_sha"), "head_sha") != intent.expected_head_sha:
                return False
            display = raw.get("display_title")
            if not isinstance(display, str) or display != intent.exact_run_name_token:
                return False
            created = _parse_time(raw.get("created_at"), "created_at")
            if created < intent.dispatch_recorded_at - self.clock_skew:
                return False
            return True
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _identity(raw: Mapping[str, Any]) -> tuple[int, int]:
        rid = raw.get("id")
        attempt = raw.get("run_attempt", 1)
        if not isinstance(rid, int) or rid <= 0 or not isinstance(attempt, int) or attempt <= 0:
            raise ValueError("invalid_run_identity")
        return rid, attempt

    @staticmethod
    def _state(raw: Mapping[str, Any]) -> tuple[str, datetime, datetime]:
        status = _require_text(raw.get("status"), "status").lower()
        conclusion = raw.get("conclusion")
        created = _parse_time(raw.get("created_at"), "created_at")
        updated = _parse_time(raw.get("updated_at"), "updated_at")
        if updated < created:
            raise ValueError("updated_before_created")
        if status == "queued":
            if conclusion not in (None, ""):
                raise ValueError("queued_with_conclusion")
            return "QUEUED", created, updated
        if status == "in_progress":
            if conclusion not in (None, ""):
                raise ValueError("in_progress_with_conclusion")
            return "IN_PROGRESS", created, updated
        if status == "completed":
            if conclusion == "success":
                return "SUCCEEDED", created, updated
            if conclusion in _FAILURE_CONCLUSIONS:
                return "FAILED", created, updated
            raise ValueError("unknown_completed_conclusion")
        raise ValueError("unknown_status")

    def evaluate(
        self,
        intent: GitHubDispatchIntent,
        raw_runs: Iterable[Mapping[str, Any]],
        *,
        source_fetched_at: datetime,
        as_of: datetime,
        source_error: str | None = None,
    ) -> AdapterDecision:
        if not self._intent_valid(intent):
            return AdapterDecision(AdapterStatus.RECEIPT_INVALID, "invalid_dispatch_intent")
        if not _aware(source_fetched_at) or not _aware(as_of):
            return AdapterDecision(AdapterStatus.FAIL_CLOSED, "timezone_required")
        if source_error:
            return AdapterDecision(AdapterStatus.SOURCE_UNAVAILABLE, f"source_error:{source_error}")
        age = as_of - source_fetched_at
        if age > self.max_source_age or age < -self.clock_skew:
            return AdapterDecision(AdapterStatus.SOURCE_STALE, "github_source_not_fresh")

        rows = list(raw_runs)
        exact = [raw for raw in rows if self._matches(intent, raw)]
        if not exact:
            status = (
                AdapterStatus.AWAITING_RUN
                if as_of <= intent.appearance_deadline_at
                else AdapterStatus.RUN_UNCERTAIN
            )
            return AdapterDecision(status, "no_exact_github_run")

        try:
            identities = [self._identity(raw) for raw in exact]
        except ValueError as exc:
            return AdapterDecision(AdapterStatus.FAIL_CLOSED, str(exc))

        run_ids = {rid for rid, _ in identities}
        if len(run_ids) != 1:
            return AdapterDecision(AdapterStatus.CONFLICT_BLOCKED, "multiple_exact_run_ids")
        attempts = {attempt for _, attempt in identities}
        if attempts != {1}:
            return AdapterDecision(AdapterStatus.CONFLICT_BLOCKED, "rerun_attempt_not_authorized")

        try:
            stamped = [(_parse_time(raw.get("updated_at"), "updated_at"), raw) for raw in exact]
        except ValueError as exc:
            return AdapterDecision(AdapterStatus.FAIL_CLOSED, str(exc))
        latest_at = max(ts for ts, _ in stamped)
        latest = [raw for ts, raw in stamped if ts == latest_at]
        signatures = {(raw.get("status"), raw.get("conclusion")) for raw in latest}
        if len(signatures) != 1:
            return AdapterDecision(AdapterStatus.CONFLICT_BLOCKED, "conflicting_latest_same_run")
        raw = latest[0]

        try:
            run_id, attempt = self._identity(raw)
            state, created, updated = self._state(raw)
            run_number = raw.get("run_number")
            if not isinstance(run_number, int) or run_number <= 0:
                raise ValueError("invalid_run_number")
            if updated > source_fetched_at + self.clock_skew:
                raise ValueError("run_updated_after_source_fetch")
        except (TypeError, ValueError) as exc:
            return AdapterDecision(AdapterStatus.FAIL_CLOSED, str(exc))

        workflow_fingerprint = f"github-workflow-id:{intent.workflow_id}"
        receipt = DispatchReceipt(
            home_system=intent.home_system,
            work_id=intent.work_id,
            dedupe_key=intent.dedupe_key,
            target=intent.target,
            downstream_run_id=str(run_id),
            expected_head_sha=intent.expected_head_sha,
            expected_workflow_fingerprint=workflow_fingerprint,
            dispatch_recorded_at=intent.dispatch_recorded_at,
            receipt_source_ref=intent.receipt_source_ref,
        )
        observation = RunObservation(
            source_health="FRESH",
            observed_at=source_fetched_at,
            home_system=intent.home_system,
            work_id=intent.work_id,
            dedupe_key=intent.dedupe_key,
            target=intent.target,
            downstream_run_id=str(run_id),
            head_sha=intent.expected_head_sha,
            workflow_fingerprint=workflow_fingerprint,
            state=state,
            run_created_at=created,
            heartbeat_at=updated if state in {"QUEUED", "IN_PROGRESS"} else None,
            completed_at=updated if state in {"SUCCEEDED", "FAILED"} else None,
            evidence_source_ref=(
                f"github-actions:{intent.repository}:workflow:{intent.workflow_id}:"
                f"run:{run_id}:attempt:{attempt}:number:{run_number}"
            ),
        )
        return AdapterDecision(
            AdapterStatus.OBSERVATION_READY,
            f"unique_exact_github_run:{state.lower()}",
            dispatch_receipt=receipt,
            run_observation=observation,
            downstream_effect_confirmed=False,
        )
