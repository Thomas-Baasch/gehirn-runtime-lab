from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

CELL_ID = "SL3-01"
EXPECTED_REPO = "Thomas-Baasch/gehirn-runtime-lab"
EXPECTED_BRANCH = "runtime/safe-live-sl3-reversible-001"
MARKER_PATH = ".safe_live_runtime/sl3_01_marker.json"
ALLOWED_EFFECT = "CREATE_VERIFY_DELETE_EXACT_MARKER"
MARKER_DOC = {
    "activation_cell": CELL_ID,
    "purpose": "controlled_internal_reversible_state_change",
    "sensitivity": "INTERNAL_TECHNICAL_LOW",
    "contains_business_data": False,
    "contains_personal_data": False,
    "contains_secrets": False,
    "external_business_effect": False,
}


def marker_bytes() -> bytes:
    return (json.dumps(MARKER_DOC, sort_keys=True, separators=(",", ":")) + "\n").encode()


def marker_sha256() -> str:
    return hashlib.sha256(marker_bytes()).hexdigest()


def authorize(*, repo: str, branch: str, path: str, effect: str, target_exists: bool, branch_head_matches_expected: bool) -> tuple[bool, str]:
    if repo != EXPECTED_REPO:
        return False, "repo_mismatch"
    if branch != EXPECTED_BRANCH:
        return False, "branch_mismatch"
    if path != MARKER_PATH:
        return False, "path_mismatch"
    if effect != ALLOWED_EFFECT:
        return False, "effect_not_authorized"
    if target_exists:
        return False, "target_must_be_absent_before_create"
    if not branch_head_matches_expected:
        return False, "branch_head_drift"
    return True, "authorized"


def verify_lifecycle(evidence: Mapping[str, Any]) -> dict[str, Any]:
    required_false = {
        "issue_or_pr_writes": 0,
        "external_business_actions": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
    }
    for key, expected in required_false.items():
        if evidence.get(key) != expected:
            raise ValueError(f"boundary_invalid:{key}")
    if evidence.get("repo") != EXPECTED_REPO or evidence.get("branch") != EXPECTED_BRANCH or evidence.get("marker_path") != MARKER_PATH:
        raise ValueError("identity_invalid")
    if evidence.get("marker_sha256") != marker_sha256():
        raise ValueError("marker_content_hash_invalid")
    if evidence.get("normal_created") is not True or evidence.get("normal_readback_match") is not True or evidence.get("normal_deleted") is not True:
        raise ValueError("normal_lifecycle_incomplete")
    if evidence.get("normal_pre_tree") != evidence.get("normal_post_tree"):
        raise ValueError("normal_tree_not_restored")
    if evidence.get("crash_marker_left") is not True:
        raise ValueError("crash_fixture_not_real")
    return {"status": "STAGE1_PASS", "cell": CELL_ID}


def verify_combined(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if evidence.get("stage1_status") != "STAGE1_PASS":
        raise ValueError("stage1_not_pass")
    if evidence.get("recovery_deleted") is not True or evidence.get("recovery_marker_absent") is not True:
        raise ValueError("fresh_recovery_incomplete")
    if evidence.get("recovery_pre_tree") != evidence.get("recovery_post_tree"):
        raise ValueError("recovery_tree_not_restored")
    if evidence.get("replay_created") is not True or evidence.get("replay_readback_match") is not True or evidence.get("replay_deleted") is not True:
        raise ValueError("replay_incomplete")
    if evidence.get("replay_pre_tree") != evidence.get("replay_post_tree"):
        raise ValueError("replay_tree_not_restored")
    loops = evidence.get("loops") or []
    if [x.get("loop") for x in loops] != [1, 2, 3, 4, 5] or not all(x.get("pass") is True for x in loops):
        raise ValueError("five_loops_not_pass")
    if loops[-2].get("clean") is not True or loops[-1].get("clean") is not True:
        raise ValueError("two_consecutive_clean_missing")
    if any(x.get("fundamental_finding") is True for x in loops[-2:]):
        raise ValueError("clean_pair_contains_finding")
    return {
        "schema": "safe-live.sl3-reversible.v1",
        "status": "PASS",
        "activation_cell": CELL_ID,
        "minimum_loops": 5,
        "clean_1": "LOOP_4",
        "clean_2": "LOOP_5",
        "two_consecutive_clean": True,
        "allowed_effect": ALLOWED_EFFECT,
        "operational_state_restored": True,
        "audit_history_preserved": True,
        "sl4_authorized": False,
    }
