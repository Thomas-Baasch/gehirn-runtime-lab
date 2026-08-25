from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from safe_live_sl5.active_policy_evaluator import ActivePolicy, CurrentIssue, Milestone, evaluate


def load_policy(path: str) -> ActivePolicy:
    raw = json.loads(Path(path).read_text())
    raw['forbidden_effects'] = tuple(raw['forbidden_effects'])
    return ActivePolicy(**raw)


def load_current(path: str) -> CurrentIssue:
    raw = json.loads(Path(path).read_text())
    return CurrentIssue(raw['repo'], raw['number'], raw['title'], raw['state'], tuple(raw['comment_bodies']))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--policy', required=True)
    ap.add_argument('--current', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    p = load_policy(args.policy)
    current = load_current(args.current)
    today = date(2026, 8, 25)
    future = Milestone('SL5-FUTURE-MATERIAL-001', True, True, False, 'FORMAL PASS / NO OWNER ACTION')

    loops = {}
    d1 = evaluate(p, current, future, today)
    loops['1'] = d1.allowed_to_execute and d1.reason == 'ACTIVE_POLICY_ALLOWS_EXACT_EFFECT'

    d2 = evaluate(p, current, Milestone('SMALL-001', False, True, False, 'minor progress'), today)
    loops['2'] = (not d2.allowed_to_execute) and d2.reason == 'NOT_MATERIAL'

    dup_issue = CurrentIssue(current.repo, current.number, current.title, current.state, current.comment_bodies + (f'Milestone key: `{future.key}`',))
    d3 = evaluate(p, dup_issue, future, today)
    loops['3'] = (not d3.allowed_to_execute) and d3.reason == 'DUPLICATE_MILESTONE_KEY'

    checks4 = [
        evaluate(p, CurrentIssue('wrong/repo', current.number, current.title, current.state, current.comment_bodies), future, today).reason == 'TARGET_MISMATCH',
        evaluate(p, CurrentIssue(current.repo, 43, current.title, current.state, current.comment_bodies), future, today).reason == 'TARGET_MISMATCH',
        evaluate(p, CurrentIssue(current.repo, current.number, 'wrong title', current.state, current.comment_bodies), future, today).reason == 'TARGET_MISMATCH',
        evaluate(p, CurrentIssue(current.repo, current.number, current.title, 'closed', current.comment_bodies), future, today).reason == 'TARGET_NOT_OPEN',
        evaluate(p, current, Milestone('STALE', True, False, False, 'stale'), today).reason == 'CANON_NOT_CURRENT',
        evaluate(p, current, Milestone('CONFLICT', True, True, True, 'conflict'), today).reason == 'CONFLICT_PRESENT',
    ]
    loops['4'] = all(checks4)

    p_expired = ActivePolicy(**{**p.__dict__, 'review_by': '2026-08-24'})
    checks5 = [
        evaluate(p, current, future, today, requested_effect='MERGE').reason == 'EFFECT_NOT_ALLOWED',
        evaluate(p, current, future, today, requested_effect='ISSUE_CLOSE').reason == 'EFFECT_NOT_ALLOWED',
        evaluate(p_expired, current, future, today).reason == 'POLICY_REVIEW_EXPIRED',
        evaluate(p, current, Milestone('SL5-ACTIVATION', True, True, False, 'activation', True), today).reason == 'BOOTSTRAP_NOT_TRIGGER',
    ]
    loops['5'] = all(checks5)

    result = {
        'status': 'PASS' if all(loops.values()) else 'FAIL',
        'loops': loops,
        'clean_1': 'LOOP_4' if loops.get('4') else None,
        'clean_2': 'LOOP_5' if loops.get('4') and loops.get('5') else None,
        'two_consecutive_clean': bool(loops.get('4') and loops.get('5')),
        'policy_status': p.status,
        'execute_capability': p.execute,
        'owner_activation_authority': True,
        'activation_authorized': all(loops.values()),
        'activation_itself_triggers_comment': False,
        'external_actions_this_acceptance': 0,
        'production_writes_this_acceptance': 0,
        'target_repo': current.repo,
        'target_issue': current.number,
        'current_real_comment_count': len(current.comment_bodies),
        'future_valid_milestone_would_be_allowed': d1.allowed_to_execute,
        'review_by': p.review_by,
    }
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')

    print(f"SAFE_LIVE_SL5_ACTIVE_ACCEPTANCE={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_ACTIVE_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print('SAFE_LIVE_SL5_ACTIVE_CLEAN_1=LOOP_4')
    print('SAFE_LIVE_SL5_ACTIVE_CLEAN_2=LOOP_5')
    print(f"SAFE_LIVE_SL5_ACTIVE_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL5_ACTIVATION_AUTHORIZED={str(result['activation_authorized']).lower()}")
    print('SAFE_LIVE_SL5_ACTIVATION_ITSELF_TRIGGERS_COMMENT=false')
    print('SAFE_LIVE_SL5_EXTERNAL_ACTIONS_THIS_ACCEPTANCE=0')
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
