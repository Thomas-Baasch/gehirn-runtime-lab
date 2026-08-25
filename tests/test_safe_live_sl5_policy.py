import json
from pathlib import Path

from safe_live_sl5.dryrun_policy import CurrentIssue, Milestone, Policy, evaluate, prove_no_execution


def load_policy():
    raw = json.loads(Path('safe_live_sl5/policy_v0_1.json').read_text())
    raw['forbidden_effects'] = tuple(raw['forbidden_effects'])
    return Policy(**raw)


def base_issue():
    return CurrentIssue(
        repo='Thomas-Baasch/gehirn-runtime-lab',
        number=42,
        title='CORE-SHADOW 0B – Readiness Precheck + Realfall 0B-01',
        state='open',
        comment_bodies=(),
    )


def base_milestone():
    return Milestone(
        key='SL5-DRYRUN-MATERIAL-001',
        material=True,
        canon_current=True,
        conflict=False,
        summary='FORMAL PASS / NO OWNER ACTION',
    )


def test_loop_1_material_prepare_only():
    d = evaluate(load_policy(), base_issue(), base_milestone())
    assert d.allowed_to_prepare is True
    assert d.allowed_to_execute is False
    assert d.reason == 'PREPARED_DRY_RUN_ONLY'


def test_loop_2_small_progress_blocked():
    m = Milestone('SMALL-001', False, True, False, 'minor green subtest')
    d = evaluate(load_policy(), base_issue(), m)
    assert (d.allowed_to_prepare, d.allowed_to_execute, d.reason) == (False, False, 'NOT_MATERIAL')


def test_loop_3_duplicate_and_unknown_commit_blocked():
    m = base_milestone()
    marker = f'Milestone key: `{m.key}`'
    issue = CurrentIssue(base_issue().repo, 42, base_issue().title, 'open', (marker,))
    d = evaluate(load_policy(), issue, m)
    assert d.reason == 'DUPLICATE_MILESTONE_KEY'
    assert d.allowed_to_execute is False


def test_loop_4_currentness_target_and_conflict_fail_closed():
    p = load_policy()
    cases = [
        (CurrentIssue('wrong/repo', 42, base_issue().title, 'open', ()), base_milestone(), 'TARGET_MISMATCH'),
        (CurrentIssue(base_issue().repo, 43, base_issue().title, 'open', ()), base_milestone(), 'TARGET_MISMATCH'),
        (CurrentIssue(base_issue().repo, 42, 'wrong title', 'open', ()), base_milestone(), 'TARGET_MISMATCH'),
        (CurrentIssue(base_issue().repo, 42, base_issue().title, 'closed', ()), base_milestone(), 'TARGET_NOT_OPEN'),
        (base_issue(), Milestone('STALE', True, False, False, 'stale'), 'CANON_NOT_CURRENT'),
        (base_issue(), Milestone('CONFLICT', True, True, True, 'conflict'), 'CONFLICT_PRESENT'),
    ]
    for issue, milestone, expected in cases:
        d = evaluate(p, issue, milestone)
        assert d.reason == expected
        assert d.allowed_to_execute is False


def test_loop_5_effect_escalation_and_policy_drift_blocked():
    p = load_policy()
    decisions = [
        evaluate(p, base_issue(), base_milestone(), requested_effect='MERGE'),
        evaluate(p, base_issue(), base_milestone(), requested_effect='ISSUE_CLOSE'),
    ]
    assert all(d.reason == 'EFFECT_NOT_ALLOWED' for d in decisions)
    assert prove_no_execution(decisions)
    p2 = Policy(**{**p.__dict__, 'status': 'ACTIVE'})
    d2 = evaluate(p2, base_issue(), base_milestone())
    assert d2.reason == 'POLICY_NOT_DRY_RUN_ONLY'
    assert d2.allowed_to_execute is False
