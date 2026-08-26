from __future__ import annotations

from dataclasses import dataclass

TARGET_CONTROL_VIEW = "1780hqjquZGsC_njEAJjd83CxsDeYgFIHCh_do9G5u7s"
TARGET_NAMESPACE = "SL5-03 OWNER-DIRECT TASK EVENTS V0.1"
ALLOWED_EFFECT = "DRIVE_USCHI_TASK_EVENT_APPEND_OR_NOOP_ONLY"
ALLOWED_EVENT_TYPES = (
    "TASK_CREATE_CONFIRMED",
    "TASK_CORRECT_OWNER",
    "TASK_CANCEL_OWNER",
    "TASK_COMPLETE_OWNER",
)


@dataclass(frozen=True)
class Policy:
    status: str = "DRY_RUN_ONLY"
    target_id: str = TARGET_CONTROL_VIEW
    target_namespace: str = TARGET_NAMESPACE
    allowed_effect: str = ALLOWED_EFFECT
    allowed_event_types: tuple[str, ...] = ALLOWED_EVENT_TYPES
    max_title_chars: int = 180
    execute_allowed: bool = False
    background_allowed: bool = False
    raw_chat_allowed: bool = False
    home_system_write_allowed: bool = False


@dataclass(frozen=True)
class TargetSnapshot:
    target_id: str
    existing_event_keys: tuple[str, ...] = ()
    existing_task_ids: tuple[str, ...] = ()
    revision_current: bool = True


@dataclass(frozen=True)
class TaskEventCandidate:
    event_key: str
    task_id: str
    event_type: str
    target_id: str
    title: str
    source_locator: str
    sensitivity: str = "LOW"
    owner_explicit: bool = True
    confirmed_task_semantics: bool = True
    incomplete: bool = False
    ambiguous: bool = False
    inferred_due: bool = False
    inferred_priority: bool = False
    due_value: str | None = None
    due_source_explicit: bool = False
    home_system_pointer: str | None = None
    requested_effect: str = ALLOWED_EFFECT
    requested_home_system_write: bool = False
    background: bool = False
    raw_chat: bool = False
    supersedes_event_key: str | None = None


@dataclass(frozen=True)
class Decision:
    allowed_to_prepare: bool
    allowed_to_execute: bool
    action: str
    reason: str
    rendered_event: dict | None = None


def _block(reason: str) -> Decision:
    return Decision(False, False, "NOOP", reason, None)


def evaluate(policy: Policy, target: TargetSnapshot, event: TaskEventCandidate) -> Decision:
    if policy.status != "DRY_RUN_ONLY":
        return _block("POLICY_NOT_DRY_RUN_ONLY")
    if event.requested_effect != policy.allowed_effect:
        return _block("EFFECT_NOT_ALLOWED")
    if target.target_id != policy.target_id or event.target_id != policy.target_id:
        return _block("TARGET_MISMATCH")
    if not target.revision_current:
        return _block("TARGET_REVISION_DRIFT")
    if event.background or policy.background_allowed:
        return _block("BACKGROUND_NOT_ALLOWED")
    if event.raw_chat or policy.raw_chat_allowed:
        return _block("RAW_CHAT_NOT_ALLOWED")
    if event.requested_home_system_write or policy.home_system_write_allowed:
        return _block("HOME_SYSTEM_WRITE_NOT_ALLOWED")
    if event.sensitivity != "LOW":
        return _block("SENSITIVITY_NOT_ALLOWED")
    if not event.owner_explicit:
        return _block("OWNER_EXPLICIT_REQUIRED")
    if event.incomplete:
        return _block("INCOMPLETE_INPUT_NO_TASK_WRITE")
    if event.ambiguous:
        return _block("AMBIGUOUS_INPUT_NO_TASK_WRITE")
    if event.event_type not in policy.allowed_event_types:
        return _block("EVENT_TYPE_NOT_ALLOWED")
    if not event.event_key.strip() or not event.task_id.strip():
        return _block("STABLE_IDS_REQUIRED")
    if event.event_key in target.existing_event_keys:
        return Decision(False, False, "NOOP", "DUPLICATE_EVENT_KEY", None)
    if not event.source_locator.strip():
        return _block("SOURCE_LOCATOR_REQUIRED")
    if not event.title.strip():
        return _block("EMPTY_TITLE")
    if len(event.title) > policy.max_title_chars:
        return _block("TITLE_TOO_LONG")
    if event.inferred_due or (event.due_value and not event.due_source_explicit):
        return _block("INFERRED_DUE_NOT_ALLOWED")
    if event.inferred_priority:
        return _block("INFERRED_PRIORITY_NOT_ALLOWED")

    if event.event_type == "TASK_CREATE_CONFIRMED":
        if not event.confirmed_task_semantics:
            return _block("CONFIRMED_TASK_SEMANTICS_REQUIRED")
        if event.task_id in target.existing_task_ids:
            return _block("TASK_ALREADY_EXISTS_USE_CORRECTION")
        if event.supersedes_event_key:
            return _block("CREATE_MUST_NOT_SUPERSEDE")
    else:
        if event.task_id not in target.existing_task_ids:
            return _block("TASK_NOT_FOUND")
        if not event.supersedes_event_key:
            return _block("SUPERSESSION_POINTER_REQUIRED")

    rendered = {
        "namespace": policy.target_namespace,
        "event_key": event.event_key,
        "task_id": event.task_id,
        "event_type": event.event_type,
        "task_title": event.title.strip(),
        "source_locator": event.source_locator.strip(),
        "owner_explicit": True,
        "sensitivity": "LOW",
        "derived_only": True,
        "home_system_authoritative": True,
        "priority": "UNRANKED",
    }
    if event.home_system_pointer:
        rendered["home_system_pointer"] = event.home_system_pointer
    if event.due_value:
        rendered["due"] = event.due_value
        rendered["due_source_explicit"] = True
    if event.supersedes_event_key:
        rendered["supersedes_event_key"] = event.supersedes_event_key

    return Decision(
        allowed_to_prepare=True,
        allowed_to_execute=False,
        action="PREPARE_TASK_EVENT_APPEND_DRY_RUN_ONLY",
        reason="PREPARED_DRY_RUN_ONLY",
        rendered_event=rendered,
    )
