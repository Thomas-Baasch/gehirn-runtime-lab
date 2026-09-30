from governance.outcome_continuation_contract import (
    CONTRACT_VERSION,
    ContinuationDecision,
    OutcomeContinuationSnapshot,
    classify_continuation,
)


def snap(**overrides):
    base = dict(
        contract_version=CONTRACT_VERSION,
        work_key="WORK-1",
        owner_outcome="real result",
        outcome_evidence_present=False,
        current_effect_state="NONE",
        safe_autonomous_step_available=False,
        external_dependency_present=False,
        wake_trigger=None,
        wake_due_at=None,
        owner_action_unavoidable=False,
        owner_action_reason=None,
        effect_unknown=False,
        do_not_repeat_conflict=False,
        superseded=False,
    )
    base.update(overrides)
    return OutcomeContinuationSnapshot(**base)


def test_analysis_or_tool_end_is_not_done():
    assert classify_continuation(snap()).decision == ContinuationDecision.FAIL_CLOSED


def test_safe_next_step_forces_continuation():
    assert classify_continuation(
        snap(safe_autonomous_step_available=True)
    ).decision == ContinuationDecision.CONTINUE_AUTONOMOUSLY


def test_real_outcome_allows_done():
    assert classify_continuation(
        snap(outcome_evidence_present=True)
    ).decision == ContinuationDecision.DONE


def test_external_wait_requires_wake():
    assert classify_continuation(
        snap(external_dependency_present=True)
    ).decision == ContinuationDecision.FAIL_CLOSED
    assert classify_continuation(
        snap(external_dependency_present=True, wake_trigger="reply_received")
    ).decision == ContinuationDecision.WAIT_WITH_WAKE


def test_owner_gate_must_be_unavoidable_and_specific():
    assert classify_continuation(
        snap(owner_action_unavoidable=True)
    ).decision == ContinuationDecision.FAIL_CLOSED
    assert classify_continuation(
        snap(owner_action_unavoidable=True, owner_action_reason="signature required")
    ).decision == ContinuationDecision.OWNER_GATE


def test_unknown_effect_never_blind_retries():
    assert classify_continuation(
        snap(effect_unknown=True, safe_autonomous_step_available=True)
    ).decision == ContinuationDecision.FAIL_CLOSED
    assert classify_continuation(
        snap(effect_unknown=True, wake_due_at="2026-09-30T18:00:00+02:00")
    ).decision == ContinuationDecision.WAIT_WITH_WAKE


def test_do_not_repeat_blocks_continuation():
    assert classify_continuation(
        snap(safe_autonomous_step_available=True, do_not_repeat_conflict=True)
    ).decision == ContinuationDecision.FAIL_CLOSED


def test_supersession_closes_old_work():
    assert classify_continuation(
        snap(superseded=True)
    ).decision == ContinuationDecision.DONE
