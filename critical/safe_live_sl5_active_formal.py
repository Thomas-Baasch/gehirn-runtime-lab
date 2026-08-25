from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--primary', required=True)
    ap.add_argument('--fresh-current', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    primary = json.loads(Path(args.primary).read_text())
    fresh = json.loads(Path(args.fresh_current).read_text())

    loops = primary.get('loops') or {}
    same_target = (
        primary.get('target_repo') == fresh.get('repo') == 'Thomas-Baasch/gehirn-runtime-lab'
        and primary.get('target_issue') == fresh.get('number') == 42
        and fresh.get('title') == 'CORE-SHADOW 0B – Readiness Precheck + Realfall 0B-01'
        and fresh.get('state') == 'open'
    )
    no_bootstrap_comment = all('Milestone key: `SL5-ACTIVATION`' not in (b or '') for b in fresh.get('comment_bodies', []))
    passed = all(bool(loops.get(str(i))) for i in range(1, 6)) and same_target and no_bootstrap_comment

    result = {
        'status': 'PASS' if passed else 'FAIL',
        'loops': loops,
        'clean_1': primary.get('clean_1'),
        'clean_2': primary.get('clean_2'),
        'two_consecutive_clean': primary.get('two_consecutive_clean') is True,
        'owner_activation_authority': primary.get('owner_activation_authority') is True,
        'activation_authorized': passed and primary.get('activation_authorized') is True,
        'activation_itself_triggers_comment': False,
        'fresh_target_current': same_target,
        'bootstrap_comment_absent': no_bootstrap_comment,
        'external_actions_this_acceptance': 0,
        'review_by': primary.get('review_by'),
    }
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')

    print(f"SAFE_LIVE_SL5_ACTIVE_FORMAL={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_ACTIVE_LOOP_{i}={'PASS' if loops.get(str(i)) else 'FAIL'}")
    print(f"SAFE_LIVE_SL5_ACTIVE_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL5_ACTIVATION_AUTHORIZED={str(result['activation_authorized']).lower()}")
    print('SAFE_LIVE_SL5_ACTIVATION_ITSELF_TRIGGERS_COMMENT=false')
    print('SAFE_LIVE_SL5_EXTERNAL_ACTIONS_THIS_ACCEPTANCE=0')
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
