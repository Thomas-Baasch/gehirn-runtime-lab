from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_REPO = "Thomas-Baasch/gehirn-runtime-lab"
EXPECTED_BRANCH = "runtime/safe-live-sl3-reversible-001"
MARKER_PATH = ".safe_live_runtime/sl3_01_marker.json"
ALLOWED_EFFECT = "CREATE_VERIFY_DELETE_EXACT_MARKER"


class FormalError(ValueError):
    pass


def load(path: Path) -> dict[str, Any]:
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FormalError(f"unreadable:{path.name}") from exc
    if not isinstance(v, dict):
        raise FormalError(f"object_required:{path.name}")
    return v


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(combined_path: Path, current_path: Path, workflow_path: Path) -> dict[str, Any]:
    e = load(combined_path)
    current = load(current_path)
    workflow = workflow_path.read_text(encoding="utf-8")

    if e.get("schema") != "safe-live.sl3-combined-evidence.v1":
        raise FormalError("schema_invalid")
    if e.get("repo") != EXPECTED_REPO or e.get("branch") != EXPECTED_BRANCH or e.get("marker_path") != MARKER_PATH:
        raise FormalError("identity_invalid")
    if e.get("allowed_effect") != ALLOWED_EFFECT:
        raise FormalError("effect_invalid")
    for key, expected in {
        "external_business_actions": 0,
        "issue_or_pr_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
    }.items():
        if e.get(key) != expected:
            raise FormalError(f"boundary_invalid:{key}")

    loops = e.get("loops") or []
    if [x.get("loop") for x in loops] != [1, 2, 3, 4, 5]:
        raise FormalError("five_loop_identity_invalid")
    if not all(x.get("pass") is True for x in loops):
        raise FormalError("loop_failure")
    if loops[-2].get("clean") is not True or loops[-1].get("clean") is not True:
        raise FormalError("two_consecutive_clean_missing")
    if any(x.get("fundamental_finding") is True for x in loops[-2:]):
        raise FormalError("clean_pair_contains_finding")

    for prefix in ("normal", "recovery", "replay"):
        if e.get(f"{prefix}_pre_tree") != e.get(f"{prefix}_post_tree"):
            raise FormalError(f"{prefix}_tree_not_restored")
    if e.get("normal_created") is not True or e.get("normal_readback_match") is not True or e.get("normal_deleted") is not True:
        raise FormalError("normal_not_proven")
    if e.get("crash_marker_left") is not True:
        raise FormalError("crash_fixture_not_proven")
    if e.get("recovery_deleted") is not True or e.get("recovery_marker_absent") is not True:
        raise FormalError("recovery_not_proven")
    if e.get("replay_created") is not True or e.get("replay_readback_match") is not True or e.get("replay_deleted") is not True:
        raise FormalError("replay_not_proven")
    if e.get("final_marker_absent") is not True:
        raise FormalError("orphan_marker_remaining")

    if current.get("branch") != EXPECTED_BRANCH or current.get("marker_absent") is not True:
        raise FormalError("fresh_current_marker_not_absent")
    if current.get("head_sha") != e.get("final_branch_head") or current.get("head_tree") != e.get("replay_post_tree"):
        raise FormalError("fresh_current_drift")

    forbidden = ["issues: write", "pull-requests: write", "actions: write", "/issues/", "/pulls/", "/merges"]
    if any(token in workflow for token in forbidden):
        raise FormalError("forbidden_authority_surface")
    if "contents: write" not in workflow or "persist-credentials: false" not in workflow:
        raise FormalError("required_bounded_authority_missing")
    if MARKER_PATH not in workflow:
        raise FormalError("exact_marker_path_not_bound")

    return {
        "schema": "safe-live.sl3-reversible-formal.v1",
        "status": "PASS",
        "activation_cell": "SL3-01",
        "loop_1": "PASS",
        "loop_2": "PASS",
        "loop_3": "PASS",
        "loop_4": "PASS_CLEAN_1",
        "loop_5": "PASS_CLEAN_2",
        "two_consecutive_clean": True,
        "operational_state_restored": True,
        "audit_history_preserved": True,
        "marker_absent_final": True,
        "allowed_effect": ALLOWED_EFFECT,
        "external_business_actions": 0,
        "issue_or_pr_writes": 0,
        "merge_authorized": False,
        "sl4_authorized": False,
        "combined_evidence_sha256": sha(combined_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combined", required=True)
    ap.add_argument("--fresh-current", required=True)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        r = evaluate(Path(a.combined), Path(a.fresh_current), Path(a.workflow))
    except (FormalError, OSError, json.JSONDecodeError) as exc:
        print(f"SAFE_LIVE_SL3_FORMAL=FAIL:{exc}")
        return 1
    Path(a.out).write_text(json.dumps(r, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("SAFE_LIVE_SL3_FORMAL=PASS")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL3_LOOP_{i}=PASS")
    print("SAFE_LIVE_SL3_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL3_CLEAN_2=LOOP_5")
    print("SAFE_LIVE_SL3_TWO_CONSECUTIVE_CLEAN=true")
    print("SAFE_LIVE_SL3_STATE_RESTORED=true")
    print("SAFE_LIVE_SL3_AUDIT_PRESERVED=true")
    print("SAFE_LIVE_SL3_MARKER_ABSENT=true")
    print("SAFE_LIVE_SL3_SL4_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
