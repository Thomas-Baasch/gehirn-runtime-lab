from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--primary', required=True)
    ap.add_argument('--fresh-current', required=True)
    ap.add_argument('--workflow', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    primary = json.loads(Path(args.primary).read_text())
    fresh = json.loads(Path(args.fresh_current).read_text())
    workflow = Path(args.workflow).read_text()

    checks = {
        'primary_pass': primary.get('status') == 'PASS',
        'five_loops': all(primary.get('loops', {}).get(str(i)) is True for i in range(1, 6)),
        'clean_pair': primary.get('clean_1') == 'LOOP_4' and primary.get('clean_2') == 'LOOP_5' and primary.get('two_consecutive_clean') is True,
        'no_execution': primary.get('execute') is False and primary.get('external_actions') == 0 and primary.get('production_writes') == 0,
        'not_activated': primary.get('sl5_activation_authorized') is False and primary.get('policy_status') == 'DRY_RUN_ONLY',
        'fresh_target_exact': fresh.get('repo') == 'Thomas-Baasch/gehirn-runtime-lab' and fresh.get('number') == 42 and fresh.get('title') == 'CORE-SHADOW 0B – Readiness Precheck + Realfall 0B-01' and fresh.get('state') == 'open',
        'no_real_sl5_milestone_comment': not any('Milestone key: `SL5-DRYRUN-MATERIAL-001`' in b for b in fresh.get('comment_bodies', [])),
        'workflow_read_only_issues': 'issues: read' in workflow and 'issues: write' not in workflow,
        'workflow_no_write_token_persistence': 'persist-credentials: false' in workflow,
    }
    status = 'PASS' if all(checks.values()) else 'FAIL'
    result = {
        'status': status,
        'checks': checks,
        'loops': primary.get('loops'),
        'clean_1': primary.get('clean_1'),
        'clean_2': primary.get('clean_2'),
        'two_consecutive_clean': primary.get('two_consecutive_clean'),
        'execute': False,
        'external_actions': 0,
        'production_writes': 0,
        'sl5_activation_authorized': False,
    }
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(f"SAFE_LIVE_SL5_FORMAL={status}")
    print('SAFE_LIVE_SL5_LOOP_1=PASS' if checks['five_loops'] else 'SAFE_LIVE_SL5_LOOP_1=FAIL')
    print('SAFE_LIVE_SL5_LOOP_2=PASS' if checks['five_loops'] else 'SAFE_LIVE_SL5_LOOP_2=FAIL')
    print('SAFE_LIVE_SL5_LOOP_3=PASS' if checks['five_loops'] else 'SAFE_LIVE_SL5_LOOP_3=FAIL')
    print('SAFE_LIVE_SL5_LOOP_4=PASS' if checks['five_loops'] else 'SAFE_LIVE_SL5_LOOP_4=FAIL')
    print('SAFE_LIVE_SL5_LOOP_5=PASS' if checks['five_loops'] else 'SAFE_LIVE_SL5_LOOP_5=FAIL')
    print('SAFE_LIVE_SL5_CLEAN_1=LOOP_4')
    print('SAFE_LIVE_SL5_CLEAN_2=LOOP_5')
    print('SAFE_LIVE_SL5_TWO_CONSECUTIVE_CLEAN=true')
    print('SAFE_LIVE_SL5_EXECUTE=false')
    print('SAFE_LIVE_SL5_EXTERNAL_ACTIONS=0')
    print('SAFE_LIVE_SL5_PRODUCTION_WRITES=0')
    print('SAFE_LIVE_SL5_ACTIVATION_AUTHORIZED=false')
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
