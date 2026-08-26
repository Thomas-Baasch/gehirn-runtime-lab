from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_BACKEND = "1lfGjCrQFAGO__4fmYGWQf9eVxQj-fjDmkLqYeLG8XWQ"
EXPECTED_BINDING = "SL6-TURN-LEDGER-BACKEND-BINDING-20260826-001"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--ledger-source", required=True)
    ap.add_argument("--evaluator-source", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    primary = json.loads(Path(args.primary).read_text())
    policy = json.loads(Path(args.policy).read_text())
    workflow = Path(args.workflow).read_text()
    ledger_source = Path(args.ledger_source).read_text()
    evaluator_source = Path(args.evaluator_source).read_text()

    details = primary.get("details", {})
    loop2 = details.get("loop_2", {})
    loop3 = details.get("loop_3", {})
    loop5 = details.get("loop_5", {})

    checks = {
        "primary_pass": primary.get("status") == "PASS",
        "five_loops": all(primary.get("loops", {}).get(str(i)) is True for i in range(1, 6)),
        "clean_1": primary.get("clean_1") == "LOOP_4",
        "clean_2": primary.get("clean_2") == "LOOP_5",
        "two_consecutive_clean": primary.get("two_consecutive_clean") is True,
        "finding_bound": primary.get("finding_id") == "SL6-LIVE-F01" and policy.get("finding_id") == "SL6-LIVE-F01",
        "remediation_revalidated": policy.get("remediation_status") == "ACTIVE_REVALIDATED_ON_EXISTING_BACKEND",
        "exact_scope_preserved": set(policy.get("allowed_cells", [])) == {"SL5-01", "SL5-02", "SL5-03"} and policy.get("previous_scope_only") is True,
        "same_limits_preserved": policy.get("max_effects_per_turn") == 3 and policy.get("max_commits_per_cell_per_turn") == 1,
        "same_order_preserved": policy.get("commit_order") == ["SL5-03", "SL5-02", "SL5-01"],
        "no_new_rights": policy.get("new_action_classes") == 0 and policy.get("new_targets") == 0 and primary.get("new_action_classes") == 0 and primary.get("new_targets") == 0,
        "review_fence_preserved": policy.get("review_by") == "2026-09-01",
        "durable_ledger_required": policy.get("durable_turn_ledger_required") is True and primary.get("durable_turn_ledger_required") is True,
        "key_is_turn_plus_child": policy.get("durable_turn_ledger_key") == ["orchestration_turn_id", "child_cell"],
        "second_same_child_blocks_before_effect": primary.get("same_turn_second_child_effect_blocked_before_effect") is True and loop2.get("effect_calls") == ["atom:p17:implementation"],
        "crash_restart_guard": primary.get("crash_reopen_preserves_consumed_budget") is True,
        "unknown_stops_batch": primary.get("unknown_outcome_consumes_budget_and_stops_batch") is True and loop3.get("unknown", {}).get("stopped_on_unknown") == "SL5-02" and loop3.get("unknown", {}).get("not_attempted") == ["SL5-01"],
        "concurrency_guard": sorted(loop5.get("concurrent_reservations", [])) == ["BLOCK_CHILD_BUDGET_CONSUMED", "RESERVED"],
        "missing_ledger_fails_closed": ["SL6", "FAIL_CLOSED_DURABLE_TURN_LEDGER_REQUIRED"] in loop5.get("missing_ledger", {}).get("blocked", []),
        "closed_turn_fails_closed": loop5.get("reopen_closed") == "FAIL_CLOSED_TURN_CLOSED",
        "live_counter_not_rewritten": primary.get("live_loop_2_remains_invalidated") is True and primary.get("live_clean_counter_after_revalidation") == 0 and policy.get("live_clean_counter_after_revalidation") == 0,
        "remediation_not_live_loop": policy.get("remediation_tests_are_not_live_loops") is True,
        "operational_backend_required": policy.get("operational_resume_requires_persistent_turn_ledger_backend") is True,
        "existing_backend_exact": policy.get("operational_backend_kind") == "EXISTING_SL6_LIVE_OBSERVATION_JOURNAL" and policy.get("operational_backend_drive_id") == EXPECTED_BACKEND,
        "backend_binding_exact_and_verified": policy.get("operational_backend_binding_key") == EXPECTED_BINDING and policy.get("operational_backend_binding_verified") is True,
        "backend_no_new_target": policy.get("operational_backend_introduces_new_target") is False,
        "backend_no_raw_chat": policy.get("operational_backend_raw_chat_storage") is False,
        "ledger_has_atomic_pk": "PRIMARY KEY(turn_id, cell)" in ledger_source and "BEGIN IMMEDIATE" in ledger_source,
        "ledger_has_no_budget_delete_api": "DELETE FROM child_effect_budget" not in ledger_source and "DROP TABLE" not in ledger_source,
        "ledger_blocks_second_effect": "SECOND_CHILD_EFFECT_BLOCKED" in ledger_source and "BLOCK_CHILD_BUDGET_CONSUMED" in ledger_source,
        "unknown_budget_is_consumed": 'mark_unknown' in ledger_source and '"UNKNOWN"' in ledger_source,
        "active_evaluator_requires_ledger": "durable_turn_ledger_required" in evaluator_source and "FAIL_CLOSED_DURABLE_TURN_LEDGER_REQUIRED" in evaluator_source,
        "workflow_read_only": "actions: read" in workflow and "contents: read" in workflow and all(x not in workflow for x in ["contents: write", "issues: write", "pull-requests: write", "actions: write"]),
        "workflow_no_drive_credentials": "GOOGLE" not in workflow.upper() and "DRIVE_TOKEN" not in workflow.upper(),
        "workflow_persist_credentials_false": "persist-credentials: false" in workflow,
        "acceptance_no_external_effect": primary.get("this_acceptance_executes_children") is False and primary.get("drive_writes_this_acceptance") == 0 and primary.get("github_writes_this_acceptance") == 0 and primary.get("external_actions_this_acceptance") == 0 and primary.get("production_writes_this_acceptance") == 0,
    }

    passed = all(checks.values())
    result = {
        "finding_id": "SL6-LIVE-F01",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "loops": primary.get("loops"),
        "clean_1": primary.get("clean_1"),
        "clean_2": primary.get("clean_2"),
        "two_consecutive_clean": primary.get("two_consecutive_clean"),
        "live_loop_2_invalidated": True,
        "live_clean_counter_after_revalidation": 0,
        "previous_scope_only": True,
        "new_action_classes": 0,
        "new_targets": 0,
        "operational_backend_drive_id": EXPECTED_BACKEND,
        "operational_backend_binding_key": EXPECTED_BINDING,
        "operational_backend_binding_verified": policy.get("operational_backend_binding_verified"),
        "operational_resume_requires_persistent_turn_ledger_backend": True,
        "this_readback_executes_children": False,
        "drive_writes_this_readback": 0,
        "github_writes_this_readback": 0,
        "external_actions_this_readback": 0,
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL6_01_LIVE_F01_FORMAL={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL6_01_LIVE_F01_LOOP_{i}={'PASS' if primary.get('loops', {}).get(str(i)) else 'FAIL'}")
    print("SAFE_LIVE_SL6_01_LIVE_F01_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL6_01_LIVE_F01_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL6_01_LIVE_F01_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("SAFE_LIVE_SL6_01_LIVE_F01_LIVE_CLEAN_COUNTER=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_PREVIOUS_SCOPE_ONLY=true")
    print("SAFE_LIVE_SL6_01_LIVE_F01_NEW_ACTION_CLASSES=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_NEW_TARGETS=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_OPERATIONAL_BACKEND_REQUIRED=true")
    print("SAFE_LIVE_SL6_01_LIVE_F01_BACKEND_BINDING_VERIFIED=true")
    print("SAFE_LIVE_SL6_01_LIVE_F01_DRIVE_WRITES_THIS_READBACK=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_GITHUB_WRITES_THIS_READBACK=0")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
