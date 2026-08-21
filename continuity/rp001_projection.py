from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


CONTRACT_VERSION = "rp-001.v1"
ALLOWED_POLICIES = frozenset({
    "AUTONOMOUS_EXPECTED",
    "WAITING_EXPECTED",
    "OWNER_REQUIRED",
    "PARKED",
    "FROZEN",
    "MANUAL_ON_DEMAND",
})
ALLOWED_SOURCE_HEALTH = frozenset({"FRESH", "STALE", "UNREACHABLE", "UNKNOWN", "CONFLICT"})
REQUIRED_FIELDS = frozenset({
    "contract_version",
    "project_id",
    "home_system",
    "authoritative_status_ref",
    "current_work_id",
    "work_state",
    "continuation_policy",
    "owner_gate",
    "last_progress_evidence",
    "active_run_refs",
    "source_health",
    "observed_at",
    "checked_at",
    "classifier_version",
    "scope",
    "purpose",
    "sensitivity",
})
OPTIONAL_FIELDS = frozenset({
    "next_contract_ref",
    "next_meaningful_step",
    "blocked_reason",
    "decision_ref",
    "supersedes_contract_ref",
})
ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
STRING_FIELDS = frozenset({
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
})
NULLABLE_STRING_FIELDS = frozenset({
    "next_contract_ref",
    "next_meaningful_step",
    "blocked_reason",
    "decision_ref",
    "supersedes_contract_ref",
})


class ProjectionContractError(ValueError):
    pass


def _nonblank(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionContractError(f"{field} must be a non-blank string")
    return value


def _timestamp(value: Any, field: str) -> str:
    text = _nonblank(value, field)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProjectionContractError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProjectionContractError(f"{field} must be timezone-aware")
    return text


def _string_array(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProjectionContractError(f"{field} must be an array")
    result = []
    for item in value:
        result.append(_nonblank(item, field))
    return tuple(result)


@dataclass(frozen=True)
class ContinuityProjection:
    payload: dict[str, Any]
    project_id: str
    home_system: str
    authoritative_status_ref: str
    current_work_id: str
    work_state: str
    continuation_policy: str
    owner_gate: str
    source_health: str
    last_progress_evidence: tuple[str, ...]
    active_run_refs: tuple[str, ...]
    observed_at: str
    checked_at: str
    scope: str
    purpose: str
    sensitivity: str
    reader_writer_authority: bool = False
    dispatch_allowed: bool = False
    canon_promotion_allowed: bool = False

    def semantic_digest(self) -> str:
        encoded = json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def project_contract(payload: Mapping[str, Any]) -> ContinuityProjection:
    if not isinstance(payload, Mapping):
        raise ProjectionContractError("contract must be an object")
    keys = set(payload)
    missing = REQUIRED_FIELDS - keys
    unknown = keys - ALL_FIELDS
    if missing:
        raise ProjectionContractError(f"missing required fields: {sorted(missing)}")
    if unknown:
        raise ProjectionContractError(f"unknown fields: {sorted(unknown)}")
    if payload.get("contract_version") != CONTRACT_VERSION:
        raise ProjectionContractError("unknown contract version")

    values = dict(payload)
    for field in STRING_FIELDS:
        _nonblank(values.get(field), field)
    for field in NULLABLE_STRING_FIELDS:
        value = values.get(field)
        if value is not None:
            _nonblank(value, field)

    policy = _nonblank(values.get("continuation_policy"), "continuation_policy")
    if policy not in ALLOWED_POLICIES:
        raise ProjectionContractError("unknown continuation policy")
    source_health = _nonblank(values.get("source_health"), "source_health")
    if source_health not in ALLOWED_SOURCE_HEALTH:
        raise ProjectionContractError("unknown source health")

    progress = _string_array(values.get("last_progress_evidence"), "last_progress_evidence")
    active_runs = _string_array(values.get("active_run_refs"), "active_run_refs")
    observed_at = _timestamp(values.get("observed_at"), "observed_at")
    checked_at = _timestamp(values.get("checked_at"), "checked_at")

    if policy == "OWNER_REQUIRED" and values.get("owner_gate") == "NONE":
        raise ProjectionContractError("owner-required contract must name an owner gate")

    return ContinuityProjection(
        payload=values,
        project_id=str(values["project_id"]),
        home_system=str(values["home_system"]),
        authoritative_status_ref=str(values["authoritative_status_ref"]),
        current_work_id=str(values["current_work_id"]),
        work_state=str(values["work_state"]),
        continuation_policy=policy,
        owner_gate=str(values["owner_gate"]),
        source_health=source_health,
        last_progress_evidence=progress,
        active_run_refs=active_runs,
        observed_at=observed_at,
        checked_at=checked_at,
        scope=str(values["scope"]),
        purpose=str(values["purpose"]),
        sensitivity=str(values["sensitivity"]),
    )


def load_projection(path: str | Path) -> ContinuityProjection:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectionContractError("contract unreadable") from exc
    return project_contract(payload)


__all__ = [
    "CONTRACT_VERSION",
    "ContinuityProjection",
    "ProjectionContractError",
    "load_projection",
    "project_contract",
]
