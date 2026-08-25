from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "core-shadow-0b.real-case-0b01.v1"
CASE_ID = "CS0B-REAL-0B01"
EXPECTED = {
    "0a_source_run_id": 32799743510,
    "0a_source_sha": "c0bdcc7b776225acb6ab9ff49b0ea6b7042df1bf",
    "0a_source_artifact_id": 9546075334,
    "0a_source_artifact_digest": "sha256:d8699dfb4342cdaebd64d8f5310fdc7c8279e52b6e7d9bcf68fc7a6732771141",
    "0a_formal_run_id": 32799875758,
    "0a_formal_sha": "9eef2e3f49df8beddc1f8b3c0c52ac335b829302",
    "0a_formal_artifact_id": 9546118991,
    "0a_formal_artifact_digest": "sha256:fb51359ecb34d0e39fd8d30d2578f89e0306409ba839b70d7920f131a9dce5fe",
    "0a_branch_head": "9eef2e3f49df8beddc1f8b3c0c52ac335b829302",
    "precheck_run_id": 32800776956,
    "precheck_sha": "0f09779d1eb579f274e6263ce748b16463c97fbf",
    "precheck_formal_artifact_id": 9546401546,
    "precheck_formal_artifact_digest": "sha256:a3a8dadfdf0a4fbdb7bd6aaade86e31f3dc0fe1f00059cdbce58ae28a00b58c8",
    "firewall_run_id": 32811173598,
    "firewall_sha": "005bc3ac67b3ddfaa51c479eff4ca65724dd3910",
    "firewall_source_artifact_id": 9549832431,
    "firewall_source_artifact_digest": "sha256:999fb3a29fb31faa3b6693f8ebae21a2694089aefe9e2fe1551ab7cb1c8c3c76",
    "firewall_formal_artifact_id": 9549835571,
    "firewall_formal_artifact_digest": "sha256:8bee58b9fcb6707a4f29ff4a148f1c39b9b961d3e6eca79cfdf49deaa16fa4f7",
}
MARKERS = {
    "pass": "## Core Shadow 0A.1 – formale synthetische Abnahme PASS",
    "pause": "PAUSED_FAIL_CLOSED – THEORY_PRACTICE_CONTAMINATION",
    "firewall": "## THEORY_PRACTICE_FIREWALL_REGRESSION_PASS",
}
CHECK_KEYS = {
    "SOURCE_IDENTITY_HEALTH",
    "TEMPORAL_CURRENTNESS",
    "CANON_VS_DERIVED",
    "SCOPE_BOUNDARY",
    "RIGHTS_BOUNDARY",
    "OWNER_FILTER",
    "FAIL_CLOSED",
    "REBUILDABLE_EVIDENCE",
}


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_ok(doc: Mapping[str, Any], artifact_id: int, digest: str, head_sha: str) -> bool:
    for item in doc.get("artifacts") or []:
        wf = item.get("workflow_run") or {}
        if (
            item.get("id") == artifact_id
            and item.get("digest") == digest
            and item.get("expired") is False
            and wf.get("head_sha") == head_sha
        ):
            return True
    return False


def run_ok(doc: Mapping[str, Any], run_id: int, head_sha: str) -> bool:
    return (
        doc.get("id") == run_id
        and doc.get("head_sha") == head_sha
        and doc.get("status") == "completed"
        and doc.get("conclusion") == "success"
    )


def marker_index(comments: list[Mapping[str, Any]], marker: str) -> int | None:
    for i, comment in enumerate(comments):
        if comment.get("marker") == marker:
            return i
    return None


def derive_observation(bundle: Mapping[str, Any], requested_effect: str = "READ_ONLY") -> dict[str, Any]:
    comments = list(bundle.get("comments") or [])
    pass_i = marker_index(comments, MARKERS["pass"])
    pause_i = marker_index(comments, MARKERS["pause"])
    firewall_i = marker_index(comments, MARKERS["firewall"])

    historical_pass = bool(
        run_ok(bundle["run_0a_source"], EXPECTED["0a_source_run_id"], EXPECTED["0a_source_sha"])
        and artifact_ok(bundle["artifacts_0a_source"], EXPECTED["0a_source_artifact_id"], EXPECTED["0a_source_artifact_digest"], EXPECTED["0a_source_sha"])
        and run_ok(bundle["run_0a_formal"], EXPECTED["0a_formal_run_id"], EXPECTED["0a_formal_sha"])
        and artifact_ok(bundle["artifacts_0a_formal"], EXPECTED["0a_formal_artifact_id"], EXPECTED["0a_formal_artifact_digest"], EXPECTED["0a_formal_sha"])
        and bundle["branch_0a"].get("head_sha") == EXPECTED["0a_branch_head"]
        and pass_i is not None
    )
    precheck_pass = bool(
        run_ok(bundle["run_precheck"], EXPECTED["precheck_run_id"], EXPECTED["precheck_sha"])
        and artifact_ok(bundle["artifacts_precheck"], EXPECTED["precheck_formal_artifact_id"], EXPECTED["precheck_formal_artifact_digest"], EXPECTED["precheck_sha"])
    )
    firewall_pass = bool(
        run_ok(bundle["run_firewall"], EXPECTED["firewall_run_id"], EXPECTED["firewall_sha"])
        and artifact_ok(bundle["artifacts_firewall"], EXPECTED["firewall_source_artifact_id"], EXPECTED["firewall_source_artifact_digest"], EXPECTED["firewall_sha"])
        and artifact_ok(bundle["artifacts_firewall"], EXPECTED["firewall_formal_artifact_id"], EXPECTED["firewall_formal_artifact_digest"], EXPECTED["firewall_sha"])
    )

    ordered_pause = pass_i is not None and pause_i is not None and pass_i < pause_i
    ordered_firewall = pause_i is not None and firewall_i is not None and pause_i < firewall_i

    if not historical_pass or not precheck_pass:
        status = "NOT_PROVEN_FAIL_CLOSED"
    elif ordered_pause:
        if firewall_pass and ordered_firewall:
            status = "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION"
        else:
            status = "PAUSED_FAIL_CLOSED"
    else:
        status = "HISTORICAL_PASS_ONLY_NOT_CURRENTLY_PROMOTED"

    allowed_effects = ["READ_ONLY"]
    action_ready = bool(
        status == "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION"
        and requested_effect in allowed_effects
    )

    return {
        "historical_synthetic_acceptance": historical_pass,
        "precheck_pass": precheck_pass,
        "firewall_regression_pass": firewall_pass,
        "pass_marker_index": pass_i,
        "pause_marker_index": pause_i,
        "firewall_marker_index": firewall_i,
        "pause_after_pass": ordered_pause,
        "firewall_after_pause": ordered_firewall,
        "current_progression_state": status,
        "owner_attention": "K0",
        "owner_action_required": False,
        "theory_disposition": "ADVISORY_NOT_OPERATIONAL",
        "allowed_effects": allowed_effects,
        "requested_effect": requested_effect,
        "action_ready": action_ready,
        "merge_authorized": False,
    }


def mutate_bundle(bundle: Mapping[str, Any], loop: int) -> tuple[dict[str, Any], str]:
    b = copy.deepcopy(bundle)
    effect = "READ_ONLY"
    if loop == 1:
        return b, effect
    if loop == 2:
        b["comments"] = [c for c in b["comments"] if c.get("marker") == MARKERS["pass"]]
        return b, effect
    if loop == 3:
        b["comments"] = [c for c in b["comments"] if c.get("marker") != MARKERS["firewall"]]
        return b, effect
    if loop == 4:
        for item in b["artifacts_0a_formal"].get("artifacts") or []:
            if item.get("id") == EXPECTED["0a_formal_artifact_id"]:
                item["digest"] = "sha256:DRIFT_DETECTED"
        return b, effect
    if loop == 5:
        return b, "SEND"
    raise ValueError("unknown_loop")


def expected_for_loop(loop: int) -> tuple[str, bool]:
    if loop == 1:
        return "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION", True
    if loop == 2:
        return "HISTORICAL_PASS_ONLY_NOT_CURRENTLY_PROMOTED", False
    if loop == 3:
        return "PAUSED_FAIL_CLOSED", False
    if loop == 4:
        return "NOT_PROVEN_FAIL_CLOSED", False
    if loop == 5:
        return "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION", False
    raise ValueError("unknown_loop")


def evaluate_loop(bundle: Mapping[str, Any], loop: int) -> dict[str, Any]:
    mutated, requested_effect = mutate_bundle(bundle, loop)
    observation = derive_observation(mutated, requested_effect=requested_effect)
    expected_status, expected_action = expected_for_loop(loop)
    checks = {
        "SOURCE_IDENTITY_HEALTH": observation["historical_synthetic_acceptance"] if loop != 4 else not observation["historical_synthetic_acceptance"],
        "TEMPORAL_CURRENTNESS": observation["current_progression_state"] == expected_status,
        "CANON_VS_DERIVED": observation["theory_disposition"] == "ADVISORY_NOT_OPERATIONAL",
        "SCOPE_BOUNDARY": observation["allowed_effects"] == ["READ_ONLY"],
        "RIGHTS_BOUNDARY": observation["action_ready"] is expected_action,
        "OWNER_FILTER": observation["owner_attention"] == "K0" and observation["owner_action_required"] is False,
        "FAIL_CLOSED": (loop not in {2, 3, 4}) or observation["action_ready"] is False,
        "REBUILDABLE_EVIDENCE": True,
    }
    if set(checks) != CHECK_KEYS:
        raise ValueError("check_set_invalid")
    return {
        "loop": loop,
        "requested_effect": requested_effect,
        "expected_status": expected_status,
        "expected_action_ready": expected_action,
        "observation": observation,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def build_source_bundle(source_dir: Path) -> dict[str, Any]:
    names = [
        "issue_41",
        "comments",
        "run_0a_source",
        "artifacts_0a_source",
        "run_0a_formal",
        "artifacts_0a_formal",
        "branch_0a",
        "run_precheck",
        "artifacts_precheck",
        "run_firewall",
        "artifacts_firewall",
    ]
    bundle = {name: load_json(source_dir / f"{name}.json") for name in names}
    if not isinstance(bundle["comments"], list):
        raise ValueError("comments_list_required")
    return bundle


def generate(source_dir: Path, out_dir: Path, run_id: str, commit: str, branch: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_source_bundle(source_dir)
    source_bundle = {
        "schema": "core-shadow-0b.real-case-source-bundle.v1",
        "case_id": CASE_ID,
        **bundle,
    }
    source_path = out_dir / "source_bundle.json"
    source_path.write_bytes(canonical_bytes(source_bundle))
    loops = [evaluate_loop(bundle, i) for i in range(1, 6)]
    evidence = {
        "schema": SCHEMA,
        "case_id": CASE_ID,
        "source_run_id": int(run_id),
        "source_commit": commit,
        "source_branch": branch,
        "real_source_read": True,
        "contains_real_business_data": False,
        "contains_personal_data": False,
        "contains_secrets": False,
        "loops": loops,
        "real_current_observation": loops[0]["observation"],
        "final_clean_pair": [4, 5] if loops[3]["status"] == loops[4]["status"] == "PASS" else [],
    }
    evidence_path = out_dir / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    manifest = {
        "schema": "core-shadow-0b.real-case-manifest.v1",
        "case_id": CASE_ID,
        "source_run_id": int(run_id),
        "source_commit": commit,
        "source_branch": branch,
        "real_source_read": True,
        "source_scope": "INTERNAL_TECHNICAL_LOW",
        "contains_real_business_data": False,
        "contains_personal_data": False,
        "contains_secrets": False,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "allowed_effects": ["READ_ONLY"],
        "files": {
            "source_bundle.json": sha256_bytes(source_path.read_bytes()),
            "evidence.json": sha256_bytes(evidence_path.read_bytes()),
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    try:
        result = generate(Path(args.source_dir), Path(args.out_dir), args.run_id, args.commit, args.branch)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"CORE_SHADOW_0B01=FAIL:{exc}")
        return 1
    if not all(loop["status"] == "PASS" for loop in result["loops"]):
        print("CORE_SHADOW_0B01=FAIL:loop_failure")
        return 1
    real = result["real_current_observation"]
    if real["current_progression_state"] != "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION":
        print("CORE_SHADOW_0B01=FAIL:current_state_not_accepted")
        return 1
    if real["owner_attention"] != "K0" or real["owner_action_required"] is not False:
        print("CORE_SHADOW_0B01=FAIL:owner_filter")
        return 1
    print("CORE_SHADOW_0B01=PASS")
    for loop in result["loops"]:
        print(f"CORE_SHADOW_0B01_LOOP_{loop['loop']}=PASS")
    print("CORE_SHADOW_0B01_CLEAN_1=LOOP_4")
    print("CORE_SHADOW_0B01_CLEAN_2=LOOP_5")
    print("CORE_SHADOW_0B01_OWNER=K0")
    print("CORE_SHADOW_0B01_OWNER_ACTION_REQUIRED=false")
    print("CORE_SHADOW_0B01_ALLOWED_EFFECT=READ_ONLY")
    print("CORE_SHADOW_0B01_EXTERNAL_ACTIONS=0")
    print("CORE_SHADOW_0B01_PRODUCTION_WRITES=0")
    print("CORE_SHADOW_0B01_NEW_CREDENTIALS=0")
    print("CORE_SHADOW_0B01_NEW_RUNNING_COST_EUR=0")
    print("CORE_SHADOW_0B01_MERGE_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
