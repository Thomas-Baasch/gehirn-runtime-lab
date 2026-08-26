from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", required=True)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    primary = json.loads(Path(args.primary).read_text())
    workflow = Path(args.workflow).read_text()
    policy = json.loads(Path(args.policy).read_text())

    checks = {
        "primary_pass": primary.get("status") == "PASS",
        "five_loops": all(primary.get("loops", {}).get(str(i)) is True for i in range(1,6)),
        "clean_1": primary.get("clean_1") == "LOOP_4",
        "clean_2": primary.get("clean_2") == "LOOP_5",
        "two_clean": primary.get("two_consecutive_clean") is True,
        "policy_active": primary.get("policy_status") == "ACTIVE" and policy.get("status") == "ACTIVE",
        "activation_authorized": primary.get("activation_authorized") is True,
        "owner_authority_exact": policy.get("owner_authority") == "Ja, aktiviere SL6-01.",
        "review_by_earliest_child": policy.get("review_by") == "2026-09-01" and primary.get("review_by") == "2026-09-01",
        "three_children_only": set(policy.get("allowed_cells", {}).keys()) == {"SL5-01","SL5-02","SL5-03"},
        "max_three": policy.get("max_effects_per_turn") == 3 and policy.get("max_commits_per_cell_per_turn") == 1,
        "commit_order": policy.get("commit_order") == ["SL5-03","SL5-02","SL5-01"],
        "no_new_rights": policy.get("new_action_classes") == 0 and policy.get("new_targets") == 0 and primary.get("new_action_classes") == 0 and primary.get("new_targets") == 0,
        "no_background": policy.get("background_allowed") is False,
        "activation_no_trigger": policy.get("activation_is_not_trigger") is True and primary.get("activation_itself_triggers_effect") is False,
        "guards": all(policy.get(k) is True for k in ["child_currentness_required","child_active_required","child_expiry_dominates","semantic_atom_uniqueness_required","task_dominance_to_sl5_03","unknown_commit_stops_remaining_batch","postcommit_readback_required_per_child","kill_switch","no_inheritance"]),
        "acceptance_no_effect": primary.get("this_acceptance_executes_children") is False and primary.get("drive_writes_this_acceptance") == 0 and primary.get("github_writes_this_acceptance") == 0 and primary.get("external_actions_this_acceptance") == 0 and primary.get("production_writes_this_acceptance") == 0,
        "workflow_actions_read": "actions: read" in workflow,
        "workflow_contents_read": "contents: read" in workflow,
        "workflow_no_write_permission": all(x not in workflow for x in ["contents: write","issues: write","pull-requests: write","actions: write"]),
        "workflow_no_drive_secret": "GOOGLE" not in workflow.upper() and "DRIVE_TOKEN" not in workflow.upper(),
        "persist_credentials_false": "persist-credentials: false" in workflow,
    }
    passed = all(checks.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "loops": primary.get("loops"),
        "clean_1": primary.get("clean_1"),
        "clean_2": primary.get("clean_2"),
        "two_consecutive_clean": primary.get("two_consecutive_clean"),
        "activation_authorized": primary.get("activation_authorized"),
        "activation_itself_triggers_effect": False,
        "this_acceptance_executes_children": False,
        "drive_writes_this_acceptance": 0,
        "github_writes_this_acceptance": 0,
        "external_actions_this_acceptance": 0,
        "production_writes_this_acceptance": 0,
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    print(f"SAFE_LIVE_SL6_01_ACTIVE_FORMAL={result['status']}")
    for i in range(1,6): print(f"SAFE_LIVE_SL6_01_ACTIVE_LOOP_{i}={'PASS' if primary.get('loops',{}).get(str(i)) else 'FAIL'}")
    print("SAFE_LIVE_SL6_01_ACTIVE_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL6_01_ACTIVE_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL6_01_ACTIVE_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL6_01_ACTIVATION_AUTHORIZED={str(result['activation_authorized']).lower()}")
    print("SAFE_LIVE_SL6_01_ACTIVATION_ITSELF_TRIGGERS_EFFECT=false")
    print("SAFE_LIVE_SL6_01_THIS_ACCEPTANCE_EXECUTES_CHILDREN=false")
    print("SAFE_LIVE_SL6_01_DRIVE_WRITES_THIS_ACCEPTANCE=0")
    print("SAFE_LIVE_SL6_01_GITHUB_WRITES_THIS_ACCEPTANCE=0")
    return 0 if passed else 1

if __name__ == "__main__": raise SystemExit(main())
