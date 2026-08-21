from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


RP001_VERSION = "rp-001.v1"


class ProjectionError(ValueError):
    pass


class ProjectionState(str, Enum):
    EXPECTED_FROZEN = "EXPECTED_FROZEN"
    WAITING_CORRECT = "WAITING_CORRECT"
    OWNER_DECISION_K2 = "OWNER_DECISION_K2"
    MANUAL_OR_PARKED = "MANUAL_OR_PARKED"
    ACTIVE_RUN = "ACTIVE_RUN"
    CONTINUATION_CANDIDATE = "CONTINUATION_CANDIDATE"
    DEGRADED_SOURCE = "DEGRADED_SOURCE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


VALID_POLICIES = frozenset(
    {
        "AUTONOMOUS_EXPECTED",
        "WAITING_EXPECTED",
        "OWNER_REQUIRED",
        "PARKED",
        "FROZEN",
        "MANUAL_ON_DEMAND",
    }
)
VALID_SOURCE_HEALTH = frozenset({"FRESH", "STALE", "UNREACHABLE", "UNKNOWN", "CONFLICT"})


@dataclass(frozen=True)
class RP001Projection:
    contract_version: str
    project_id: str
    home_system: str
    authoritative_status_ref: str
    current_work_id: str
    work_state: str
    continuation_policy: str
    owner_gate: str
    next_contract_ref: str | None
    next_meaningful_step: str | None
    last_progress_evidence: tuple[str, ...]
    active_run_refs: tuple[str, ...]
    source_health: str
    observed_at: str
    checked_at: str
    classifier_version: str
    scope: str
    purpose: str
    sensitivity: str
    blocked_reason: str | None = None
    decision_ref: str | None = None
    supersedes_contract_ref: str | None = None

    # These are hard-coded capabilities of this projection layer, not input-controlled rights.
    writer_authority: bool = False
    canon_write_authority: bool = False
    dispatch_authority: bool = False

    def validate(self) -> None:
        if self.contract_version != RP001_VERSION:
            raise ProjectionError("unknown_contract_version")
        for name in (
            "project_id",
            "home_system",
            "authoritative_status_ref",
            "current_work_id",
            "work_state",
            "owner_gate",
            "classifier_version",
            "scope",
            "purpose",
            "sensitivity",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ProjectionError(f"{name}_required")
        if self.continuation_policy not in VALID_POLICIES:
            raise ProjectionError("unknown_continuation_policy")
        if self.source_health not in VALID_SOURCE_HEALTH:
            raise ProjectionError("unknown_source_health")
        for name in ("observed_at", "checked_at"):
            _parse_time(getattr(self, name), name)
        if _parse_time(self.checked_at, "checked_at") < _parse_time(self.observed_at, "observed_at"):
            raise ProjectionError("checked_before_observed")
        if any(not item.strip() for item in self.last_progress_evidence):
            raise ProjectionError("blank_progress_evidence")
        if any(not item.strip() for item in self.active_run_refs):
            raise ProjectionError("blank_active_run_ref")
        if self.writer_authority or self.canon_write_authority or self.dispatch_authority:
            raise ProjectionError("projection_rights_must_be_read_only")

    def state(self) -> ProjectionState:
        self.validate()
        if self.continuation_policy == "FROZEN":
            return ProjectionState.EXPECTED_FROZEN
        if self.continuation_policy == "OWNER_REQUIRED":
            return ProjectionState.OWNER_DECISION_K2
        if self.continuation_policy in {"PARKED", "MANUAL_ON_DEMAND"}:
            return ProjectionState.MANUAL_OR_PARKED
        if self.continuation_policy == "WAITING_EXPECTED":
            return ProjectionState.WAITING_CORRECT
        if self.source_health == "CONFLICT":
            return ProjectionState.SOURCE_CONFLICT
        if self.source_health in {"STALE", "UNREACHABLE", "UNKNOWN"}:
            return ProjectionState.DEGRADED_SOURCE
        if self.active_run_refs:
            return ProjectionState.ACTIVE_RUN
        if self.continuation_policy == "AUTONOMOUS_EXPECTED":
            if (self.next_contract_ref or self.next_meaningful_step) and self.last_progress_evidence:
                return ProjectionState.CONTINUATION_CANDIDATE
            return ProjectionState.DEGRADED_SOURCE
        raise ProjectionError("unhandled_projection_state")

    def as_owner_view(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "home_system": self.home_system,
            "current_work_id": self.current_work_id,
            "work_state": self.work_state,
            "continuation_policy": self.continuation_policy,
            "source_health": self.source_health,
            "projection_state": self.state().value,
            "authoritative_status_ref": self.authoritative_status_ref,
            "next_contract_ref": self.next_contract_ref,
            "next_meaningful_step": self.next_meaningful_step,
            "active_run_refs": list(self.active_run_refs),
            "checked_at": self.checked_at,
            "writer_authority": False,
            "canon_write_authority": False,
            "dispatch_authority": False,
        }


def _parse_time(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionError(f"{field}_required")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProjectionError(f"{field}_must_be_iso8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProjectionError(f"{field}_must_be_timezone_aware")
    return parsed.astimezone(timezone.utc)


def _optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def read_rp001(payload: Mapping[str, Any]) -> RP001Projection:
    try:
        projection = RP001Projection(
            contract_version=str(payload["contract_version"]),
            project_id=str(payload["project_id"]),
            home_system=str(payload["home_system"]),
            authoritative_status_ref=str(payload["authoritative_status_ref"]),
            current_work_id=str(payload["current_work_id"]),
            work_state=str(payload["work_state"]),
            continuation_policy=str(payload["continuation_policy"]),
            owner_gate=str(payload["owner_gate"]),
            next_contract_ref=_optional(payload.get("next_contract_ref")),
            next_meaningful_step=_optional(payload.get("next_meaningful_step")),
            last_progress_evidence=tuple(str(x) for x in payload.get("last_progress_evidence", [])),
            active_run_refs=tuple(str(x) for x in payload.get("active_run_refs", [])),
            source_health=str(payload["source_health"]),
            observed_at=str(payload["observed_at"]),
            checked_at=str(payload["checked_at"]),
            classifier_version=str(payload["classifier_version"]),
            scope=str(payload["scope"]),
            purpose=str(payload["purpose"]),
            sensitivity=str(payload["sensitivity"]),
            blocked_reason=_optional(payload.get("blocked_reason")),
            decision_ref=_optional(payload.get("decision_ref")),
            supersedes_contract_ref=_optional(payload.get("supersedes_contract_ref")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectionError("contract_structure_invalid") from exc
    projection.validate()
    return projection


def adapt_existing_brain_contract(
    payload: Mapping[str, Any],
    *,
    observed_at: str,
    checked_at: str,
    source_health: str = "FRESH",
    active_run_refs: Sequence[str] = (),
) -> RP001Projection:
    """Read-only adapter from the current brain continuity contract to RP-001.

    It does not modify the existing contract, supervisor, Canon, status issue, or workflows.
    """
    if payload.get("schema") != "externes-gehirn.continuity-contract":
        raise ProjectionError("legacy_brain_contract_schema_mismatch")
    expected = payload.get("expected_contract")
    watch = payload.get("watch")
    rights = payload.get("rights")
    if not isinstance(expected, Mapping) or not isinstance(watch, Mapping) or not isinstance(rights, Mapping):
        raise ProjectionError("legacy_brain_contract_structure_invalid")
    if rights.get("dispatch_workflow") is not False or rights.get("merge") is not False:
        raise ProjectionError("legacy_brain_contract_has_unsafe_rights")

    old_policy = str(payload.get("continuation_policy") or "")
    policy_map = {
        "AUTONOMOUS_EXPECTED_WHEN_NEXT_CONTRACT_FROZEN": "AUTONOMOUS_EXPECTED",
        "PARKED": "PARKED",
        "WAITING_EXTERNAL": "WAITING_EXPECTED",
        "MANUAL_ON_DEMAND": "MANUAL_ON_DEMAND",
        "FROZEN": "FROZEN",
        "OWNER_REQUIRED": "OWNER_REQUIRED",
    }
    mapped_policy = policy_map.get(old_policy)
    if mapped_policy is None:
        raise ProjectionError("legacy_policy_not_mappable_fail_closed")

    drive_id = str(expected.get("drive_id") or "").strip()
    title = str(expected.get("title") or "").strip()
    frozen_at = str(expected.get("frozen_at_utc") or "").strip()
    status_issue = int(watch.get("status_issue") or 0)
    if not drive_id or not title or not frozen_at or status_issue <= 0:
        raise ProjectionError("legacy_brain_contract_missing_authoritative_fields")

    rp_payload = {
        "contract_version": RP001_VERSION,
        "project_id": "EXTERNAL-BRAIN",
        "home_system": "EXTERNAL_BRAIN",
        "authoritative_status_ref": f"github:issue:{status_issue}",
        "current_work_id": "EXTERNAL-BRAIN-PHASE-C",
        "work_state": "NEXT_CONTRACT_FROZEN",
        "continuation_policy": mapped_policy,
        "owner_gate": "NONE",
        "next_contract_ref": f"drive:{drive_id}",
        "next_meaningful_step": title,
        "last_progress_evidence": [f"drive:{drive_id}#frozen_at={frozen_at}"],
        "active_run_refs": list(active_run_refs),
        "source_health": source_health,
        "observed_at": observed_at,
        "checked_at": checked_at,
        "classifier_version": "external-brain-rp001-reader-v1",
        "scope": "PROJECT_CONTINUITY",
        "purpose": "STATUS_PROJECTION_ONLY",
        "sensitivity": "INTERNAL",
        "blocked_reason": None,
        "decision_ref": None,
        "supersedes_contract_ref": "continuity/brain-continuity-contract.json",
    }
    return read_rp001(rp_payload)


__all__ = [
    "ProjectionError",
    "ProjectionState",
    "RP001Projection",
    "RP001_VERSION",
    "adapt_existing_brain_contract",
    "read_rp001",
]
