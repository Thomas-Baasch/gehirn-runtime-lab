from __future__ import annotations

from dataclasses import dataclass
from datetime import date

PETER_REGISTRY = "1W-EV0ihSgcNOFEhbZLikXo2biTrFEBUsIeW9gUfiXjQ"
MENTORENRAT_REGISTRY = "1j3reLxLZcHs8jb3-_6KgsGTuqifI2uEwAXcJP7eVquQ"
UNROUTED_INBOX = "1g_pIv7jATAN7c3PJZ58JmKJiXtWyXGGZX7FGdiTqDHo"
ALLOWED_EFFECT = "DRIVE_DERIVED_DELTA_APPEND_OR_NOOP_ONLY"


@dataclass(frozen=True)
class ActivePolicy:
    policy_id: str
    status: str
    active_from: str
    review_by: str
    allowed_targets: tuple[str, ...]
    allowed_delta_types: tuple[str, ...]
    allowed_effect: str
    execute: bool
    max_statement_chars: int
    background_allowed: bool
    raw_chat_allowed: bool
    home_system_write_allowed: bool
    activation_is_not_trigger: bool
    kill_switch: bool
    no_inheritance: bool
    postcommit_readback_required: bool


@dataclass(frozen=True)
class TargetSnapshot:
    target_id: str
    existing_delta_keys: tuple[str, ...] = ()
    revision_current: bool = True


@dataclass(frozen=True)
class DeltaCandidate:
    delta_key: str
    delta_type: str
    target_id: str
    statement: str
    source_locator: str
    sensitivity: str = "LOW"
    current: bool = True
    ambiguous: bool = False
    conflict: bool = False
    sealed: bool = False
    background: bool = False
    raw_chat: bool = False
    requested_effect: str = ALLOWED_EFFECT
    requested_home_system_write: bool = False
    is_policy_activation: bool = False


@dataclass(frozen=True)
class Decision:
    allowed_to_execute: bool
    action: str
    reason: str
    rendered_event: dict | None = None


def _block(reason: str) -> Decision:
    return Decision(False, "NOOP", reason, None)


def evaluate(policy: ActivePolicy, target: TargetSnapshot, delta: DeltaCandidate, today: date) -> Decision:
    if policy.status != "ACTIVE" or not policy.execute:
        return _block("POLICY_NOT_ACTIVE")
    if not policy.kill_switch or not policy.no_inheritance or not policy.postcommit_readback_required:
        return _block("POLICY_SAFETY_INVARIANT_MISSING")
    if today > date.fromisoformat(policy.review_by):
        return _block("POLICY_REVIEW_EXPIRED")
    if delta.is_policy_activation and policy.activation_is_not_trigger:
        return _block("BOOTSTRAP_NOT_TRIGGER")
    if delta.requested_effect != policy.allowed_effect:
        return _block("EFFECT_NOT_ALLOWED")
    if target.target_id != delta.target_id or delta.target_id not in policy.allowed_targets:
        return _block("TARGET_NOT_ALLOWLISTED")
    if delta.background or policy.background_allowed:
        return _block("BACKGROUND_NOT_ALLOWED")
    if delta.raw_chat or policy.raw_chat_allowed:
        return _block("RAW_CHAT_NOT_ALLOWED")
    if delta.requested_home_system_write or policy.home_system_write_allowed:
        return _block("HOME_SYSTEM_WRITE_NOT_ALLOWED")
    if delta.sealed:
        return _block("SEALED_CONTENT_BLOCKED")
    if delta.sensitivity != "LOW":
        return _block("SENSITIVITY_NOT_ALLOWED")
    if delta.delta_type not in policy.allowed_delta_types:
        return _block("DELTA_TYPE_NOT_ALLOWED")
    if not delta.source_locator.strip():
        return _block("SOURCE_LOCATOR_REQUIRED")
    if not delta.statement.strip():
        return _block("EMPTY_STATEMENT")
    if len(delta.statement) > policy.max_statement_chars:
        return _block("STATEMENT_TOO_LONG")
    if not delta.current:
        return _block("CURRENTNESS_NOT_CLEAN")
    if not target.revision_current:
        return _block("TARGET_REVISION_DRIFT")
    if delta.ambiguous and delta.target_id != UNROUTED_INBOX:
        return _block("AMBIGUOUS_TARGET_REQUIRES_UNROUTED")
    if delta.conflict and delta.delta_type != "SUPERSESSION_CONFLICT_POINTER":
        return _block("CONFLICT_REQUIRES_POINTER_TYPE")
    if delta.delta_key in target.existing_delta_keys:
        return _block("DUPLICATE_DELTA_KEY")

    rendered = {
        "delta_key": delta.delta_key,
        "delta_type": delta.delta_type,
        "target_id": delta.target_id,
        "statement": delta.statement.strip(),
        "source_locator": delta.source_locator.strip(),
        "sensitivity": delta.sensitivity,
        "derived_only": True,
        "home_system_authoritative": True,
    }
    if delta.conflict:
        rendered["status"] = "CONFLICT_HELD"

    return Decision(True, "APPEND_DERIVED_DELTA", "ACTIVE_POLICY_ALLOWS_EXACT_EFFECT", rendered)
