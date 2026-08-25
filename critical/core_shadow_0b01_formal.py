from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

CASE_ID = "CS0B-REAL-0B01"
EXPECTED_BRANCH = "runtime/core-shadow-0b-realcase-001"
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
BANNED_KEYS = {"email", "avatar_url", "user", "actor", "author", "triggering_actor", "committer"}


class FormalError(ValueError):
    pass


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise FormalError(f"json_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise FormalError(f"json_object_required:{path}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_banned_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in BANNED_KEYS:
                raise FormalError(f"personal_metadata_key_present:{key}")
            reject_banned_keys(child)
    elif isinstance(value, list):
        for child in value:
            reject_banned_keys(child)


def artifact_ok(doc: Mapping[str, Any], artifact_id: int, digest: str, head_sha: str) -> bool:
    for item in doc.get("artifacts") or []:
        wf = item.get("workflow_run") or {}
        if item.get("id") == artifact_id and item.get("digest") == digest and item.get("expired") is False and wf.get("head_sha") == head_sha:
            return True
    return False


def run_ok(doc: Mapping[str, Any], run_id: int, head_sha: str) -> bool:
    return doc.get("id") == run_id and doc.get("head_sha") == head_sha and doc.get("status") == "completed" and doc.get("conclusion") == "success"


def marker_index(comments: list[Mapping[str, Any]], marker: str) -> int | None:
    for i, comment in enumerate(comments):
        if comment.get("marker") == marker:
            return i
    return None


def derive(bundle: Mapping[str, Any], requested_effect: str) -> dict[str, Any]:
    comments = list(bundle.get("comments") or [])
    pass_i = marker_index(comments, MARKERS["pass"])
    pause_i = marker_index(comments, MARKERS["pause"])
    firewall_i = marker_index(comments, MARKERS["firewall"])
    historical = bool(
        run_ok(bundle["run_0a_source"], EXPECTED["0a_source_run_id"], EXPECTED["0a_source_sha"])
        and artifact_ok(bundle["artifacts_0a_source"], EXPECTED["0a_source_artifact_id"], EXPECTED["0a_source_artifact_digest"], EXPECTED["0a_source_sha"])
        and run_ok(bundle["run_0a_formal"], EXPECTED["0a_formal_run_id"], EXPECTED["0a_formal_sha"])
        and artifact_ok(bundle["artifacts_0a_formal"], EXPECTED["0a_formal_artifact_id"], EXPECTED["0a_formal_artifact_digest"], EXPECTED["0a_formal_sha"])
        and bundle["branch_0a"].get("head_sha") == EXPECTED["0a_branch_head"]
        and pass_i is not None
    )
    precheck = bool(
        run_ok(bundle["run_precheck"], EXPECTED["precheck_run_id"], EXPECTED["precheck_sha"])
        and artifact_ok(bundle["artifacts_precheck"], EXPECTED["precheck_formal_artifact_id"], EXPECTED["precheck_formal_artifact_digest"], EXPECTED["precheck_sha"])
    )
    firewall = bool(
        run_ok(bundle["run_firewall"], EXPECTED["firewall_run_id"], EXPECTED["firewall_sha"])
        and artifact_ok(bundle["artifacts_firewall"], EXPECTED["firewall_source_artifact_id"], EXPECTED["firewall_source_artifact_digest"], EXPECTED["firewall_sha"])
        and artifact_ok(bundle["artifacts_firewall"], EXPECTED["firewall_formal_artifact_id"], EXPECTED["firewall_formal_artifact_digest"], EXPECTED["firewall_sha"])
    )
    pause_after = pass_i is not None and pause_i is not None and pass_i < pause_i
    firewall_after = pause_i is not None and firewall_i is not None and pause_i < firewall_i
    if not historical or not precheck:
        state = "NOT_PROVEN_FAIL_CLOSED"
    elif pause_after:
        state = "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION" if firewall and firewall_after else "PAUSED_FAIL_CLOSED"
    else:
        state = "HISTORICAL_PASS_ONLY_NOT_CURRENTLY_PROMOTED"
    allowed = ["READ_ONLY"]
    action_ready = state == "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION" and requested_effect == "READ_ONLY"
    return {
        "historical_synthetic_acceptance": historical,
        "precheck_pass": precheck,
        "firewall_regression_pass": firewall,
        "pass_marker_index": pass_i,
        "pause_marker_index": pause_i,
        "firewall_marker_index": firewall_i,
        "pause_after_pass": pause_after,
        "firewall_after_pause": firewall_after,
        "current_progression_state": state,
        "owner_attention": "K0",
        "owner_action_required": False,
        "theory_disposition": "ADVISORY_NOT_OPERATIONAL",
        "allowed_effects": allowed,
        "requested_effect": requested_effect,
        "action_ready": action_ready,
        "merge_authorized": False,
    }


def mutation(bundle: Mapping[str, Any], loop: int) -> tuple[dict[str, Any], str]:
    b = copy.deepcopy(bundle)
    if loop == 1:
        return b, "READ_ONLY"
    if loop == 2:
        b["comments"] = [c for c in b["comments"] if c.get("marker") == MARKERS["pass"]]
        return b, "READ_ONLY"
    if loop == 3:
        b["comments"] = [c for c in b["comments"] if c.get("marker") != MARKERS["firewall"]]
        return b, "READ_ONLY"
    if loop == 4:
        for item in b["artifacts_0a_formal"].get("artifacts") or []:
            if item.get("id") == EXPECTED["0a_formal_artifact_id"]:
                item["digest"] = "sha256:DRIFT_DETECTED"
        return b, "READ_ONLY"
    if loop == 5:
        return b, "SEND"
    raise FormalError("unknown_loop")


def expected(loop: int) -> tuple[str, bool]:
    table = {
        1: ("CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION", True),
        2: ("HISTORICAL_PASS_ONLY_NOT_CURRENTLY_PROMOTED", False),
        3: ("PAUSED_FAIL_CLOSED", False),
        4: ("NOT_PROVEN_FAIL_CLOSED", False),
        5: ("CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION", False),
    }
    return table[loop]


def formal_loop(bundle: Mapping[str, Any], loop: int) -> dict[str, Any]:
    b, effect = mutation(bundle, loop)
    obs = derive(b, effect)
    state, action = expected(loop)
    checks = {
        "SOURCE_IDENTITY_HEALTH": obs["historical_synthetic_acceptance"] if loop != 4 else not obs["historical_synthetic_acceptance"],
        "TEMPORAL_CURRENTNESS": obs["current_progression_state"] == state,
        "CANON_VS_DERIVED": obs["theory_disposition"] == "ADVISORY_NOT_OPERATIONAL",
        "SCOPE_BOUNDARY": obs["allowed_effects"] == ["READ_ONLY"],
        "RIGHTS_BOUNDARY": obs["action_ready"] is action,
        "OWNER_FILTER": obs["owner_attention"] == "K0" and obs["owner_action_required"] is False,
        "FAIL_CLOSED": (loop not in {2, 3, 4}) or obs["action_ready"] is False,
        "REBUILDABLE_EVIDENCE": True,
    }
    if set(checks) != CHECK_KEYS or not all(checks.values()):
        raise FormalError(f"formal_loop_fail:{loop}:{checks}")
    return {"loop": loop, "observation": obs, "checks": checks, "status": "PASS"}


def evaluate(artifact_dir: Path) -> dict[str, Any]:
    manifest_path = artifact_dir / "manifest.json"
    source_path = artifact_dir / "source_bundle.json"
    evidence_path = artifact_dir / "evidence.json"
    manifest = load_json(manifest_path)
    source = load_json(source_path)
    evidence = load_json(evidence_path)
    if manifest.get("schema") != "core-shadow-0b.real-case-manifest.v1":
        raise FormalError("manifest_schema_invalid")
    if source.get("schema") != "core-shadow-0b.real-case-source-bundle.v1" or evidence.get("schema") != "core-shadow-0b.real-case-0b01.v1":
        raise FormalError("artifact_schema_invalid")
    if {manifest.get("case_id"), source.get("case_id"), evidence.get("case_id")} != {CASE_ID}:
        raise FormalError("case_identity_invalid")
    if manifest.get("source_branch") != EXPECTED_BRANCH or evidence.get("source_branch") != EXPECTED_BRANCH:
        raise FormalError("branch_invalid")
    reject_banned_keys(source)
    if manifest.get("files") != {"source_bundle.json": sha(source_path), "evidence.json": sha(evidence_path)}:
        raise FormalError("artifact_hash_mismatch")
    boundaries = {
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
    }
    for key, expected_value in boundaries.items():
        if manifest.get(key) != expected_value:
            raise FormalError(f"boundary_invalid:{key}")

    bundle = {k: v for k, v in source.items() if k not in {"schema", "case_id"}}
    loops = [formal_loop(bundle, i) for i in range(1, 6)]
    recorded = evidence.get("loops")
    if not isinstance(recorded, list) or len(recorded) != 5:
        raise FormalError("recorded_five_loops_required")
    for formal, rec in zip(loops, recorded):
        if rec.get("loop") != formal["loop"] or rec.get("status") != "PASS" or rec.get("observation") != formal["observation"] or rec.get("checks") != formal["checks"]:
            raise FormalError(f"recorded_loop_mismatch:{formal['loop']}")
    if evidence.get("real_current_observation") != loops[0]["observation"]:
        raise FormalError("real_observation_mismatch")
    if evidence.get("final_clean_pair") != [4, 5]:
        raise FormalError("clean_pair_invalid")
    if loops[0]["observation"]["owner_attention"] != "K0" or loops[0]["observation"]["owner_action_required"] is not False:
        raise FormalError("owner_filter_invalid")
    return {
        "schema": "core-shadow-0b.real-case-formal.v1",
        "status": "PASS",
        "source_run_id": evidence.get("source_run_id"),
        "source_commit": evidence.get("source_commit"),
        "source_branch": evidence.get("source_branch"),
        "source_bundle_sha256": sha(source_path),
        "evidence_sha256": sha(evidence_path),
        "manifest_sha256": sha(manifest_path),
        "loops": loops,
        "clean_1": "LOOP_4",
        "clean_2": "LOOP_5",
        "real_current_state": loops[0]["observation"]["current_progression_state"],
        "owner_attention": "K0",
        "owner_action_required": False,
        "allowed_effects": ["READ_ONLY"],
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "independence_claim": "I1_LOGICALLY_SEPARATE_FORMAL_EVALUATOR",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        result = evaluate(Path(args.artifact_dir))
    except (FormalError, ValueError, OSError) as exc:
        print(f"CORE_SHADOW_0B01_FORMAL=FAIL:{exc}")
        return 1
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CORE_SHADOW_0B01_FORMAL=PASS")
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
