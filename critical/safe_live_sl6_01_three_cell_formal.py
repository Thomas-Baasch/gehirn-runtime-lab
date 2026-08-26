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
        "child_expiry_finding": primary.get("design_fundamental_finding") == "SL6_MUST_NOT_OUTLIVE_EARLIEST_CHILD_CELL_REVIEW",
        "earliest_child_review": primary.get("earliest_child_review") == "2026-09-01",
        "clean_1": primary.get("clean_1") == "LOOP_4",
        "clean_2": primary.get("clean_2") == "LOOP_5",
        "two_consecutive_clean": primary.get("two_consecutive_clean") is True,
        "policy_dry_run": primary.get("policy_status") == "DRY_RUN_ONLY",
        "max_effects_three": primary.get("max_effects_per_turn") == 3,
        "max_one_per_cell": primary.get("max_commits_per_cell") == 1,
        "execute_false": primary.get("execute") is False,
        "drive_writes_zero": primary.get("drive_writes") == 0,
        "github_writes_zero": primary.get("github_writes") == 0,
        "external_actions_zero": primary.get("external_actions") == 0,
        "production_writes_zero": primary.get("production_writes") == 0,
        "activation_false": primary.get("sl6_activation_authorized") is False,
        "no_new_action_classes": primary.get("new_action_classes") == 0,
        "no_new_targets": primary.get("new_targets") == 0,
        "workflow_actions_read": "actions: read" in workflow,
        "workflow_contents_read": "contents: read" in workflow,
        "workflow_no_write_permissions": all(x not in workflow for x in ["contents: write", "issues: write", "pull-requests: write", "actions: write"]),
        "workflow_persist_credentials_false": "persist-credentials: false" in workflow,
        "workflow_no_drive_credentials": "GOOGLE" not in workflow.upper() and "DRIVE_TOKEN" not in workflow.upper(),
    }
    passed = all(checks.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "loops": primary.get("loops"),
        "clean_1": primary.get("clean_1"),
        "clean_2": primary.get("clean_2"),
        "two_consecutive_clean": primary.get("two_consecutive_clean"),
        "execute": False,
        "drive_writes": 0,
        "github_writes": 0,
        "external_actions": 0,
        "production_writes": 0,
        "sl6_activation_authorized": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL6_01_FORMAL={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL6_01_LOOP_{i}={'PASS' if primary.get('loops', {}).get(str(i)) else 'FAIL'}")
    print("SAFE_LIVE_SL6_01_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL6_01_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL6_01_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("SAFE_LIVE_SL6_01_EXECUTE=false")
    print("SAFE_LIVE_SL6_01_DRIVE_WRITES=0")
    print("SAFE_LIVE_SL6_01_GITHUB_WRITES=0")
    print("SAFE_LIVE_SL6_01_EXTERNAL_ACTIONS=0")
    print("SAFE_LIVE_SL6_01_PRODUCTION_WRITES=0")
    print("SAFE_LIVE_SL6_01_ACTIVATION_AUTHORIZED=false")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
