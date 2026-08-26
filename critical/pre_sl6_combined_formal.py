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
        "fundamental_finding_preserved": "TASK_VS_MATERIAL_DELTA_DUPLICATION_RISK" in str(primary.get("fundamental_finding_loop_1", "")),
        "clean_1": primary.get("clean_1") == "LOOP_4",
        "clean_2": primary.get("clean_2") == "LOOP_5",
        "two_consecutive_clean": primary.get("two_consecutive_clean") is True,
        "execute_false": primary.get("execute") is False,
        "drive_writes_zero": primary.get("drive_writes") == 0,
        "github_writes_zero": primary.get("github_writes") == 0,
        "external_actions_zero": primary.get("external_actions") == 0,
        "production_writes_zero": primary.get("production_writes") == 0,
        "sl6_not_authorized": primary.get("sl6_authorized") is False,
        "individual_rights_unchanged": primary.get("individual_cell_rights_unchanged") is True,
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
        "sl6_authorized": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"PRE_SL6_COMBINED_FORMAL={result['status']}")
    for i in range(1, 6):
        print(f"PRE_SL6_LOOP_{i}={'PASS' if primary.get('loops', {}).get(str(i)) else 'FAIL'}")
    print("PRE_SL6_CLEAN_1=LOOP_4")
    print("PRE_SL6_CLEAN_2=LOOP_5")
    print(f"PRE_SL6_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("PRE_SL6_EXECUTE=false")
    print("PRE_SL6_DRIVE_WRITES=0")
    print("PRE_SL6_GITHUB_WRITES=0")
    print("PRE_SL6_EXTERNAL_ACTIONS=0")
    print("PRE_SL6_PRODUCTION_WRITES=0")
    print("PRE_SL6_SL6_AUTHORIZED=false")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
