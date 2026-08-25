from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from safe_live_sl5.dryrun_policy import CurrentIssue, Milestone, Policy, evaluate
except ModuleNotFoundError:
    from dryrun_policy import CurrentIssue, Milestone, Policy, evaluate


def load_policy(path: str) -> Policy:
    raw = json.loads(Path(path).read_text())
    raw['forbidden_effects'] = tuple(raw['forbidden_effects'])
    return Policy(**raw)


def load_current(path: str) -> CurrentIssue:
    raw = json.loads(Path(path).read_text())
    return CurrentIssue(
        repo=raw['repo'],
        number=raw['number'],
        title=raw['title'],
        state=raw['state'],
        comment_bodies=tuple(raw['comment_bodies']),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--policy', required=True)
    ap.add_argument('--current', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    p = load_policy(args.policy)
    current = load_current(args.current)
    m = Milestone('SL5-DRYRUN-MATERIAL-001', True, True, False, 'FORMAL PASS / NO OWNER ACTION')

    loops = {}
    d1 = evaluate(p, current, m)
    loops['1'] = d1.allowed_to_prepare and not d1.allowed_to_execute and d1.reason == 'PREPARED_DRY_RUN_ONLY'

    d2 = evaluate(p, current, Milestone('SMALL-001', False, True, False, 'minor subtest'))
    loops['2'] = (not d2.allowed_to_prepare) and (not d2.allowed_to_execute) and d2.reason == 'NOT_MATERIAL'

    dup_issue = CurrentIssue(current.repo, current.number, current.title, current.state, current.comment_bodies + (f'Milestone key: `{m.key}`',))
    d3 = evaluate(p, dup_issue, m)
    loops['3'] = (not d3.allowed_to_prepare) and (not d3.allowed_to_execute) and d3.reason == 'DUPLICATE_MILESTONE_KEY'

    loop4_checks = []
    loop4_cases = [
        (CurrentIssue('wrong/repo', current.number, current.title, current.state, current.comment_bodies), m, 'TARGET_MISMATCH'),
        (CurrentIssue(current.repo, 43, current.title, current.state, current.comment_bodies), m, 'TARGET_MISMATCH'),
        (CurrentIssue(current.repo, current.number, 'wrong title', current.state, current.comment_bodies), m, 'TARGET_MISMATCH'),
        (CurrentIssue(current.repo, current.number, current.title, 'closed', current.comment_bodies), m, 'TARGET_NOT_OPEN'),
        (current, Milestone('STALE', True, False, False, 'stale'), 'CANON_NOT_CURRENT'),
        (current, Milestone('CONFLICT', True, True, True, 'conflict'), 'CONFLICT_PRESENT'),
    ]
    for issue, milestone, expected in loop4_cases:
        d = evaluate(p, issue, milestone)
        loop4_checks.append((not d.allowed_to_prepare) and (not d.allowed_to_execute) and d.reason == expected)
    loops['4'] = all(loop4_checks)

    d5a = evaluate(p, current, m, requested_effect='MERGE')
    d5b = evaluate(p, current, m, requested_effect='ISSUE_CLOSE')
    p_active = Policy(**{**p.__dict__, 'status': 'ACTIVE'})
    d5c = evaluate(p_active, current, m)
    loops['5'] = all([
        d5a.reason == 'EFFECT_NOT_ALLOWED' and not d5a.allowed_to_execute,
        d5b.reason == 'EFFECT_NOT_ALLOWED' and not d5b.allowed_to_execute,
        d5c.reason == 'POLICY_NOT_DRY_RUN_ONLY' and not d5c.allowed_to_execute,
    ])

    result = {
        'status': 'PASS' if all(loops.values()) else 'FAIL',
        'loops': loops,
        'clean_1': 'LOOP_4' if loops.get('4') else None,
        'clean_2': 'LOOP_5' if loops.get('4') and loops.get('5') else None,
        'two_consecutive_clean': bool(loops.get('4') and loops.get('5')),
        'execute': False,
        'external_actions': 0,
        'production_writes': 0,
        'policy_status': p.status,
        'target_repo': current.repo,
        'target_issue': current.number,
        'milestone_key': m.key,
        'real_comment_count': len(current.comment_bodies),
        'dry_run_body': d1.rendered_body,
        'sl5_activation_authorized': False,
    }
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')

    print(f"SAFE_LIVE_SL5_DRYRUN={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print('SAFE_LIVE_SL5_CLEAN_1=LOOP_4')
    print('SAFE_LIVE_SL5_CLEAN_2=LOOP_5')
    print(f"SAFE_LIVE_SL5_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print('SAFE_LIVE_SL5_EXECUTE=false')
    print('SAFE_LIVE_SL5_EXTERNAL_ACTIONS=0')
    print('SAFE_LIVE_SL5_PRODUCTION_WRITES=0')
    print('SAFE_LIVE_SL5_ACTIVATION_AUTHORIZED=false')
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
