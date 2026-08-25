from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", required=True)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    primary = json.loads(Path(args.primary).read_text())
    workflow = Path(args.workflow).read_text()

    checks = {
        "primary_pass": primary.get("status") == "PASS",
        "five_loops": all(primary.get("loops", {}).get(str(i)) is True for i in range(1, 6)),
        "clean_1": primary.get("clean_1") == "LOOP_4",
        "clean_2": primary.get("clean_2") == "LOOP_5",
        "two_consecutive_clean": primary.get("two_consecutive_clean") is True,
        "dry_run_only": primary.get("policy_status") == "DRY_RUN_ONLY",
        "execute_false": primary.get("execute") is False,
        "drive_writes_zero": primary.get("drive_writes") == 0,
        "external_actions_zero": primary.get("external_actions") == 0,
        "production_writes_zero": primary.get("production_writes") == 0,
        "activation_not_authorized": primary.get("activation_authorized") is False,
        "workflow_contents_read": "contents: read" in workflow,
        "workflow_actions_read": "actions: read" in workflow,
        "workflow_no_write_permission": "issues: write" not in workflow and "contents: write" not in workflow,
        "workflow_no_drive_secret": "GOOGLE" not in workflow.upper() and "DRIVE_TOKEN" not in workflow.upper(),
        "workflow_persist_credentials_false": "persist-credentials: false" in workflow,
    }

    passed = all(checks.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "source_status": primary.get("status"),
        "loops": primary.get("loops"),
        "clean_1": primary.get("clean_1"),
        "clean_2": primary.get("clean_2"),
        "two_consecutive_clean": primary.get("two_consecutive_clean"),
        "execute": False,
        "drive_writes": 0,
        "external_actions": 0,
        "production_writes": 0,
        "activation_authorized": False,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL5_02_FORMAL={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_02_LOOP_{i}={'PASS' if primary.get('loops', {}).get(str(i)) else 'FAIL'}")
    print("SAFE_LIVE_SL5_02_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL5_02_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL5_02_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("SAFE_LIVE_SL5_02_EXECUTE=false")
    print("SAFE_LIVE_SL5_02_DRIVE_WRITES=0")
    print("SAFE_LIVE_SL5_02_EXTERNAL_ACTIONS=0")
    print("SAFE_LIVE_SL5_02_PRODUCTION_WRITES=0")
    print("SAFE_LIVE_SL5_02_ACTIVATION_AUTHORIZED=false")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
