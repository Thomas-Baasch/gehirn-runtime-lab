from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


CONTRACT_VERSION = "0.1"


class ContinuationDecision(str, Enum):
    DONE = "DONE"
    CONTINUE_AUTONOMOUSLY = "CONTINUE_AUTONOMOUSLY"
    WAIT_WITH_WAKE = "WAIT_WITH_WAKE"
    OWNER_GATE = "OWNER_GATE"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class OutcomeContinuationSnapshot:
    contract_version: str
    work_key: str
    owner_outcome: str
    outcome_evidence_present: bool
    current_effect_state: str
    safe_autonomous_step_available: bool
    external_dependency_present: bool
    wake_trigger: str | None
    wake_due_at: str | None
    owner_action_unavoidable: bool
    owner_action_reason: str | None
    effect_unknown: bool
    do_not_repeat_conflict: bool
    superseded: bool


@dataclass(frozen=True)
class ContinuationAssessment:
    decision: ContinuationDecision
    reason: str


def _blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def classify_continuation(snapshot: OutcomeContinuationSnapshot) -> ContinuationAssessment:
    """Classify whether work may honestly stop.

    This contract deliberately does not execute effects. It prevents analysis,
    tool, document, handoff, or run completion from being mistaken for the
    owner's real outcome.
    """
    if snapshot.contract_version != CONTRACT_VERSION:
        return ContinuationAssessment(
            ContinuationDecision.FAIL_CLOSED, "unknown_contract_version"
        )

    if _blank(snapshot.work_key) or _blank(snapshot.owner_outcome):
        return ContinuationAssessment(
            ContinuationDecision.FAIL_CLOSED, "missing_work_identity_or_owner_outcome"
        )

    if snapshot.superseded:
        return ContinuationAssessment(
            ContinuationDecision.DONE, "work_superseded_by_current_owner_state"
        )

    if snapshot.outcome_evidence_present:
        if snapshot.effect_unknown:
            return ContinuationAssessment(
                ContinuationDecision.FAIL_CLOSED,
                "outcome_claim_conflicts_with_unknown_effect",
            )
        return ContinuationAssessment(
            ContinuationDecision.DONE, "real_owner_outcome_evidenced"
        )

    if snapshot.effect_unknown:
        return ContinuationAssessment(
            ContinuationDecision.WAIT_WITH_WAKE,
            "effect_unknown_requires_readback_before_retry",
        ) if not _blank(snapshot.wake_trigger) or not _blank(snapshot.wake_due_at) else ContinuationAssessment(
            ContinuationDecision.FAIL_CLOSED,
            "effect_unknown_without_readback_wake",
        )

    if snapshot.do_not_repeat_conflict:
        return ContinuationAssessment(
            ContinuationDecision.FAIL_CLOSED,
            "continuation_conflicts_with_do_not_repeat",
        )

    if snapshot.safe_autonomous_step_available:
        return ContinuationAssessment(
            ContinuationDecision.CONTINUE_AUTONOMOUSLY,
            "owner_outcome_open_and_safe_next_step_exists",
        )

    if snapshot.external_dependency_present:
        if _blank(snapshot.wake_trigger) and _blank(snapshot.wake_due_at):
            return ContinuationAssessment(
                ContinuationDecision.FAIL_CLOSED,
                "external_wait_without_explicit_wake",
            )
        return ContinuationAssessment(
            ContinuationDecision.WAIT_WITH_WAKE,
            "external_dependency_bound_to_explicit_wake",
        )

    if snapshot.owner_action_unavoidable:
        if _blank(snapshot.owner_action_reason):
            return ContinuationAssessment(
                ContinuationDecision.FAIL_CLOSED,
                "owner_gate_without_specific_unavoidable_reason",
            )
        return ContinuationAssessment(
            ContinuationDecision.OWNER_GATE,
            "owner_action_is_the_first_unavoidable_next_step",
        )

    return ContinuationAssessment(
        ContinuationDecision.FAIL_CLOSED,
        "open_owner_outcome_without_next_step_wake_or_real_gate",
    )
