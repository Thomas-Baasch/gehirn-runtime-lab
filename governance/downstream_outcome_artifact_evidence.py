from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import hashlib
from io import BytesIO
import json
from pathlib import PurePosixPath
import stat
from typing import Any, Iterable, Mapping
import zipfile

from governance.downstream_reconciliation import DownstreamEvidence
from governance.post_dispatch_verification import (
    DispatchReceipt,
    PostDispatchRunVerifier,
    RunObservation,
    VerificationStatus,
)


class OutcomeAdapterStatus(str, Enum):
    EVIDENCE_READY = "EVIDENCE_READY"
    AWAITING_OUTCOME = "AWAITING_OUTCOME"
    OUTCOME_UNCERTAIN = "OUTCOME_UNCERTAIN"
    RUN_NOT_SUCCEEDED = "RUN_NOT_SUCCEEDED"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    INTEGRITY_BLOCKED = "INTEGRITY_BLOCKED"
    IDENTITY_BLOCKED = "IDENTITY_BLOCKED"
    TEMPORAL_BLOCKED = "TEMPORAL_BLOCKED"
    EFFECT_UNSAFE_BLOCKED = "EFFECT_UNSAFE_BLOCKED"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class OutcomeArtifactIntent:
    repository: str
    expected_artifact_name: str
    expected_outcome_path: str
    outcome_deadline_at: datetime


@dataclass(frozen=True)
class GitHubArtifactBundle:
    repository_full_name: str
    run_id: str
    artifact_id: int
    name: str
    digest: str
    expired: bool
    created_at: datetime
    archive_bytes: bytes


@dataclass(frozen=True)
class OutcomeAdapterDecision:
    status: OutcomeAdapterStatus
    reason: str
    evidence: DownstreamEvidence | None = None
    dispatch_executed: bool = False
    retry_executed: bool = False
    repository_written: bool = False
    ledger_updated: bool = False


_REQUIRED_OUTCOME_STRINGS = (
    "schema",
    "home_system",
    "work_id",
    "dedupe_key",
    "target",
    "downstream_run_id",
    "head_sha",
    "workflow_fingerprint",
    "produced_at",
    "outcome_state",
    "effect_scope",
    "producer_evidence_ref",
)
_SAFE_EFFECT_SCOPES = frozenset({"NO_EXTERNAL_EFFECT", "REVERSIBLE_INTERNAL_EFFECT"})
_ALL_EFFECT_SCOPES = _SAFE_EFFECT_SCOPES | frozenset({"EXTERNAL_OR_UNKNOWN"})


def _aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.utcoffset() is not None


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


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{key}")
    return value.strip()


class DownstreamOutcomeArtifactEvidenceAdapter:
    def __init__(
        self,
        *,
        max_source_age_seconds: int = 300,
        clock_skew_seconds: int = 30,
        max_archive_bytes: int = 2 * 1024 * 1024,
        max_outcome_bytes: int = 1024 * 1024,
    ) -> None:
        if (
            max_source_age_seconds <= 0
            or clock_skew_seconds < 0
            or max_archive_bytes <= 0
            or max_outcome_bytes <= 0
        ):
            raise ValueError("invalid_adapter_limits")
        self.max_source_age = timedelta(seconds=max_source_age_seconds)
        self.clock_skew = timedelta(seconds=clock_skew_seconds)
        self.max_archive_bytes = max_archive_bytes
        self.max_outcome_bytes = max_outcome_bytes
        self.run_verifier = PostDispatchRunVerifier(
            heartbeat_max_age_seconds=max_source_age_seconds,
            clock_skew_seconds=clock_skew_seconds,
        )

    @staticmethod
    def _intent_valid(intent: OutcomeArtifactIntent) -> bool:
        return (
            isinstance(intent.repository, str)
            and bool(intent.repository.strip())
            and isinstance(intent.expected_artifact_name, str)
            and bool(intent.expected_artifact_name.strip())
            and isinstance(intent.expected_outcome_path, str)
            and bool(intent.expected_outcome_path.strip())
            and "/" not in intent.expected_outcome_path
            and "\\" not in intent.expected_outcome_path
            and _aware(intent.outcome_deadline_at)
        )

    @staticmethod
    def _bundle_matches(
        intent: OutcomeArtifactIntent,
        receipt: DispatchReceipt,
        bundle: GitHubArtifactBundle,
    ) -> bool:
        return (
            bundle.repository_full_name == intent.repository
            and bundle.run_id == receipt.downstream_run_id
            and bundle.name == intent.expected_artifact_name
        )

    def _verify_archive(
        self,
        bundle: GitHubArtifactBundle,
        *,
        expected_path: str,
    ) -> tuple[OutcomeAdapterStatus | None, str, Mapping[str, Any] | None]:
        if not isinstance(bundle.archive_bytes, bytes) or not bundle.archive_bytes:
            return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "artifact_bytes_missing", None
        if len(bundle.archive_bytes) > self.max_archive_bytes:
            return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "artifact_archive_too_large", None
        if not isinstance(bundle.digest, str) or not bundle.digest.startswith("sha256:"):
            return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "provider_digest_invalid", None
        actual_digest = "sha256:" + hashlib.sha256(bundle.archive_bytes).hexdigest()
        if actual_digest != bundle.digest:
            return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "provider_digest_mismatch", None

        try:
            with zipfile.ZipFile(BytesIO(bundle.archive_bytes), "r") as archive:
                infos = archive.infolist()
                if len(infos) != 1:
                    return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "artifact_must_contain_exactly_one_file", None
                info = infos[0]
                path = info.filename
                posix = PurePosixPath(path)
                mode = (info.external_attr >> 16) & 0o170000
                if (
                    path != expected_path
                    or posix.is_absolute()
                    or ".." in posix.parts
                    or "\\" in path
                    or info.is_dir()
                    or mode == stat.S_IFLNK
                ):
                    return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "artifact_path_or_type_invalid", None
                if info.file_size > self.max_outcome_bytes:
                    return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "outcome_file_too_large", None
                raw = archive.read(info)
        except (zipfile.BadZipFile, RuntimeError, OSError):
            return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "artifact_zip_invalid", None

        if len(raw) > self.max_outcome_bytes:
            return OutcomeAdapterStatus.INTEGRITY_BLOCKED, "outcome_bytes_too_large", None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return OutcomeAdapterStatus.FAIL_CLOSED, "outcome_json_invalid", None
        if not isinstance(payload, Mapping):
            return OutcomeAdapterStatus.FAIL_CLOSED, "outcome_json_not_object", None
        return None, "archive_ok", payload

    def evaluate(
        self,
        intent: OutcomeArtifactIntent,
        receipt: DispatchReceipt,
        run: RunObservation,
        bundles: Iterable[GitHubArtifactBundle],
        *,
        source_fetched_at: datetime,
        as_of: datetime,
        source_error: str | None = None,
    ) -> OutcomeAdapterDecision:
        if not self._intent_valid(intent):
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "invalid_outcome_intent")
        if not _aware(source_fetched_at) or not _aware(as_of):
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "timezone_required")
        if source_error:
            return OutcomeAdapterDecision(
                OutcomeAdapterStatus.SOURCE_UNAVAILABLE,
                f"source_error:{source_error}",
            )
        age = as_of - source_fetched_at
        if age > self.max_source_age or age < -self.clock_skew:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.SOURCE_STALE, "artifact_source_not_fresh")

        run_decision = self.run_verifier.verify(receipt, [run], as_of=as_of)
        if run_decision.status is not VerificationStatus.EXACT_SUCCEEDED:
            mapping = {
                VerificationStatus.EXACT_ACTIVE_FRESH: OutcomeAdapterStatus.RUN_NOT_SUCCEEDED,
                VerificationStatus.EXACT_FAILED: OutcomeAdapterStatus.RUN_NOT_SUCCEEDED,
                VerificationStatus.SOURCE_BLOCKED: OutcomeAdapterStatus.SOURCE_BLOCKED,
                VerificationStatus.IDENTITY_BLOCKED: OutcomeAdapterStatus.IDENTITY_BLOCKED,
                VerificationStatus.HEARTBEAT_STALE: OutcomeAdapterStatus.SOURCE_BLOCKED,
                VerificationStatus.TEMPORAL_BLOCKED: OutcomeAdapterStatus.TEMPORAL_BLOCKED,
                VerificationStatus.CONFLICT_BLOCKED: OutcomeAdapterStatus.CONFLICT_BLOCKED,
                VerificationStatus.OWNER_GATE_BLOCKED: OutcomeAdapterStatus.SOURCE_BLOCKED,
                VerificationStatus.FAIL_CLOSED: OutcomeAdapterStatus.FAIL_CLOSED,
            }
            return OutcomeAdapterDecision(
                mapping.get(run_decision.status, OutcomeAdapterStatus.FAIL_CLOSED),
                f"technical_run_not_exact_succeeded:{run_decision.status.value}",
            )

        exact = [b for b in bundles if self._bundle_matches(intent, receipt, b)]
        if not exact:
            status = (
                OutcomeAdapterStatus.AWAITING_OUTCOME
                if as_of <= intent.outcome_deadline_at
                else OutcomeAdapterStatus.OUTCOME_UNCERTAIN
            )
            return OutcomeAdapterDecision(status, "no_exact_outcome_artifact")
        if len(exact) != 1:
            return OutcomeAdapterDecision(
                OutcomeAdapterStatus.CONFLICT_BLOCKED,
                "multiple_exact_outcome_artifacts",
            )
        bundle = exact[0]
        if not isinstance(bundle.artifact_id, int) or bundle.artifact_id <= 0:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "invalid_artifact_id")
        if not _aware(bundle.created_at):
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "artifact_created_at_timezone_required")
        if bundle.expired:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.SOURCE_BLOCKED, "artifact_expired")
        if bundle.created_at < max(receipt.dispatch_recorded_at, run.run_created_at) - self.clock_skew:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.TEMPORAL_BLOCKED, "artifact_predates_dispatch_or_run")
        if bundle.created_at > source_fetched_at + self.clock_skew:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.TEMPORAL_BLOCKED, "artifact_created_after_source_fetch")

        blocked, reason, payload = self._verify_archive(
            bundle,
            expected_path=intent.expected_outcome_path,
        )
        if blocked is not None:
            return OutcomeAdapterDecision(blocked, reason)
        assert payload is not None

        try:
            for key in _REQUIRED_OUTCOME_STRINGS:
                _required_text(payload, key)
            for key in ("effect_confirmed", "external_effect_possible", "external_effect_proven"):
                if not isinstance(payload.get(key), bool):
                    raise ValueError(f"invalid_{key}")
            produced_at = _parse_time(payload.get("produced_at"), "produced_at")
        except ValueError as exc:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, str(exc))

        if payload["schema"] != "safe-continuation-outcome.v1":
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "outcome_schema_unknown")

        identity_pairs = (
            ("home_system", receipt.home_system),
            ("work_id", receipt.work_id),
            ("dedupe_key", receipt.dedupe_key),
            ("target", receipt.target),
            ("downstream_run_id", receipt.downstream_run_id),
            ("head_sha", receipt.expected_head_sha),
            ("workflow_fingerprint", receipt.expected_workflow_fingerprint),
        )
        for key, expected in identity_pairs:
            if payload[key] != expected:
                return OutcomeAdapterDecision(
                    OutcomeAdapterStatus.IDENTITY_BLOCKED,
                    f"outcome_identity_mismatch:{key}",
                )
        if run.head_sha != receipt.expected_head_sha or run.workflow_fingerprint != receipt.expected_workflow_fingerprint:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.IDENTITY_BLOCKED, "run_receipt_identity_mismatch")

        if produced_at < max(receipt.dispatch_recorded_at, run.run_created_at) - self.clock_skew:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.TEMPORAL_BLOCKED, "outcome_predates_dispatch_or_run")
        if produced_at > bundle.created_at + self.clock_skew:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.TEMPORAL_BLOCKED, "outcome_after_artifact_creation")
        if produced_at > source_fetched_at + self.clock_skew or produced_at > as_of + self.clock_skew:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.TEMPORAL_BLOCKED, "outcome_from_future")

        outcome_state = payload["outcome_state"].upper()
        effect_scope = payload["effect_scope"].upper()
        effect_confirmed = payload["effect_confirmed"]
        external_possible = payload["external_effect_possible"]
        external_proven = payload["external_effect_proven"]

        if outcome_state not in {"SUCCEEDED", "FAILED"}:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "outcome_state_unknown")
        if effect_scope not in _ALL_EFFECT_SCOPES:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "effect_scope_unknown")
        if external_proven and not external_possible:
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "external_effect_flags_inconsistent")
        if effect_scope in _SAFE_EFFECT_SCOPES and (external_possible or external_proven):
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "safe_scope_with_external_effect_flags")
        if effect_scope == "EXTERNAL_OR_UNKNOWN" and not (external_possible or external_proven):
            return OutcomeAdapterDecision(OutcomeAdapterStatus.FAIL_CLOSED, "external_scope_without_effect_flag")

        if outcome_state == "SUCCEEDED":
            if not effect_confirmed:
                return OutcomeAdapterDecision(OutcomeAdapterStatus.OUTCOME_UNCERTAIN, "success_effect_not_confirmed")
            if effect_scope not in _SAFE_EFFECT_SCOPES or external_possible or external_proven:
                return OutcomeAdapterDecision(
                    OutcomeAdapterStatus.EFFECT_UNSAFE_BLOCKED,
                    "success_external_or_unknown_effect_not_auto_acceptable",
                )
            evidence = DownstreamEvidence(
                source_health="FRESH",
                home_system=receipt.home_system,
                work_id=receipt.work_id,
                dedupe_key=receipt.dedupe_key,
                target=receipt.target,
                downstream_id=receipt.downstream_run_id,
                state="SUCCEEDED",
                external_effect_proven=False,
                external_effect_possible=False,
                evidence_source_ref=(
                    f"github-artifact:{intent.repository}:run:{receipt.downstream_run_id}:"
                    f"artifact:{bundle.artifact_id}:{bundle.digest}#"
                    f"{intent.expected_outcome_path}|{payload['producer_evidence_ref']}"
                ),
            )
            return OutcomeAdapterDecision(
                OutcomeAdapterStatus.EVIDENCE_READY,
                "integrity_verified_safe_success_outcome",
                evidence=evidence,
            )

        evidence = DownstreamEvidence(
            source_health="FRESH",
            home_system=receipt.home_system,
            work_id=receipt.work_id,
            dedupe_key=receipt.dedupe_key,
            target=receipt.target,
            downstream_id=receipt.downstream_run_id,
            state="FAILED",
            external_effect_proven=external_proven,
            external_effect_possible=external_possible,
            evidence_source_ref=(
                f"github-artifact:{intent.repository}:run:{receipt.downstream_run_id}:"
                f"artifact:{bundle.artifact_id}:{bundle.digest}#"
                f"{intent.expected_outcome_path}|{payload['producer_evidence_ref']}"
            ),
        )
        return OutcomeAdapterDecision(
            OutcomeAdapterStatus.EVIDENCE_READY,
            "integrity_verified_failed_outcome",
            evidence=evidence,
        )
