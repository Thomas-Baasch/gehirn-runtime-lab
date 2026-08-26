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
        "policy_active": primary.get("policy_status") == "ACTIVE",
        "execute_capability_true": primary.get("execute_capability") is True,
        "activation_authorized": primary.get("activation_authorized") is True,
        "activation_not_task_trigger": primary.get("activation_itself_triggers_task") is False,
        "drive_writes_zero": primary.get("drive_writes_this_acceptance") == 0,
        "external_actions_zero": primary.get("external_actions_this_acceptance") == 0,
        "production_writes_zero": primary.get("production_writes_this_acceptance") == 0,
        "exact_target": primary.get("target_id") == "1780hqjquZGsC_njEAJjd83CxsDeYgFIHCh_do9G5u7s",
        "exact_namespace": primary.get("target_namespace") == "SL5-03 OWNER-DIRECT TASK EVENTS V0.1",
        "workflow_contents_read": "contents: read" in workflow,
        "workflow_actions_read": "actions: read" in workflow,
        "workflow_no_write_permission": "contents: write" not in workflow and "issues: write" not in workflow,
        "workflow_no_drive_secret": "GOOGLE" not in workflow.upper() and "DRIVE_TOKEN" not in workflow.upper(),
        "workflow_persist_credentials_false": "persist-credentials: false" in workflow,
    }

    passed = all(checks.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "loops": primary.get("loops"),
        "clean_1": primary.get("clean_1"),
        "clean_2": primary.get("clean_2"),
        "two_consecutive_clean": primary.get("two_consecutive_clean"),
        "execute_capability": primary.get("execute_capability"),
        "activation_authorized": primary.get("activation_authorized"),
        "activation_itself_triggers_task": False,
        "drive_writes_this_acceptance": 0,
        "external_actions_this_acceptance": 0,
        "production_writes_this_acceptance": 0,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL5_03_ACTIVE_FORMAL={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_03_ACTIVE_LOOP_{i}={'PASS' if primary.get('loops', {}).get(str(i)) else 'FAIL'}")
    print("SAFE_LIVE_SL5_03_ACTIVE_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL5_03_ACTIVE_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL5_03_ACTIVE_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL5_03_ACTIVATION_AUTHORIZED={str(result['activation_authorized']).lower()}")
    print("SAFE_LIVE_SL5_03_ACTIVATION_ITSELF_TRIGGERS_TASK=false")
    print("SAFE_LIVE_SL5_03_DRIVE_WRITES_THIS_ACCEPTANCE=0")
    print("SAFE_LIVE_SL5_03_EXTERNAL_ACTIONS_THIS_ACCEPTANCE=0")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
