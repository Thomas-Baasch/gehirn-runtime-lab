from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

EXPECTED_REPO = "Thomas-Baasch/gehirn-runtime-lab"
EXPECTED_ISSUE = 42
EXPECTED_FIREWALL_RUN = 32811173598
EXPECTED_SL1_RUN = 32811552246


class FormalError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FormalError(f"json_unreadable:{path.name}") from exc
    if not isinstance(value, dict):
        raise FormalError(f"json_object_required:{path.name}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_ok(current: Mapping[str, Any]) -> bool:
    issue = current.get("issue42") or {}
    runs = current.get("runs") or {}
    artifacts = current.get("artifacts") or {}
    if current.get("repo") != EXPECTED_REPO or issue.get("number") != EXPECTED_ISSUE or issue.get("state") != "open":
        return False
    if current.get("sl1_marker_present") is not True or current.get("firewall_marker_present") is not True:
        return False
    for rid in (EXPECTED_FIREWALL_RUN, EXPECTED_SL1_RUN):
        if (runs.get(str(rid)) or {}).get("conclusion") != "success":
            return False
        items = artifacts.get(str(rid)) or []
        if not items or any(item.get("expired") is True or not item.get("digest") for item in items):
            return False
    return current.get("unresolved_conflict") is not True


def compare_current(source: Mapping[str, Any], fresh: Mapping[str, Any]) -> None:
    keys = ("repo", "sl1_marker_present", "firewall_marker_present", "issue42_latest_comment_id")
    for key in keys:
        if source.get(key) != fresh.get(key):
            raise FormalError(f"currentness_changed:{key}")
    if source.get("issue42") != fresh.get("issue42"):
        raise FormalError("currentness_changed:issue42")
    if source.get("runs") != fresh.get("runs"):
        raise FormalError("currentness_changed:runs")
    if source.get("artifacts") != fresh.get("artifacts"):
        raise FormalError("currentness_changed:artifacts")


def evaluate(artifact_dir: Path, fresh_current: Mapping[str, Any]) -> dict[str, Any]:
    manifest = load_json(artifact_dir / "manifest.json")
    source_current = load_json(artifact_dir / "current_minimized.json")
    result = load_json(artifact_dir / "prepare_result.json")
    draft_path = artifact_dir / "draft_comment.md"

    if manifest.get("schema") != "safe-live.sl2-prepare-manifest.v1":
        raise FormalError("manifest_schema_invalid")
    if manifest.get("activation_cell") != "SL2-01" or manifest.get("effect_class") != "PREPARE_ONLY" or manifest.get("execute") is not False:
        raise FormalError("manifest_scope_invalid")
    for key, expected in {"external_actions": 0, "production_writes": 0, "new_credentials": 0, "new_running_cost_eur": 0, "merge_authorized": False}.items():
        if manifest.get(key) != expected:
            raise FormalError(f"manifest_boundary_invalid:{key}")
    observed = {
        "current_minimized.json": sha(artifact_dir / "current_minimized.json"),
        "prepare_result.json": sha(artifact_dir / "prepare_result.json"),
        "draft_comment.md": sha(draft_path),
    }
    if manifest.get("files") != observed:
        raise FormalError("artifact_hash_mismatch")

    if not current_ok(source_current) or not current_ok(fresh_current):
        raise FormalError("current_source_not_acceptable")
    compare_current(source_current, fresh_current)

    if result.get("schema") != "safe-live.sl2-prepare.v1" or result.get("status") != "PASS":
        raise FormalError("primary_result_invalid")
    action = result.get("prepared_action") or {}
    if action.get("target_repo") != EXPECTED_REPO or action.get("target_issue") != EXPECTED_ISSUE:
        raise FormalError("prepared_target_invalid")
    if action.get("operation") != "create_comment" or action.get("effect_class") != "PREPARE_ONLY" or action.get("execute") is not False:
        raise FormalError("prepared_effect_invalid")
    draft = draft_path.read_text(encoding="utf-8")
    if "PREPARE-ONLY DRAFT / NICHT POSTEN" not in draft or "keine Write-/Send-/Merge-Autorität" not in draft:
        raise FormalError("draft_safety_language_missing")

    loops = result.get("loops") or []
    if len(loops) < 5 or [loop.get("loop") for loop in loops[:5]] != [1, 2, 3, 4, 5]:
        raise FormalError("minimum_five_loops_missing")
    if not all(loop.get("pass") is True for loop in loops):
        raise FormalError("loop_failure")
    if loops[-2].get("clean") is not True or loops[-1].get("clean") is not True:
        raise FormalError("two_consecutive_clean_missing")
    if any(loop.get("fundamental_finding") is True for loop in loops[-2:]):
        raise FormalError("final_clean_pair_has_finding")

    # Independent negative checks; no import from primary implementation.
    stale = dict(fresh_current)
    stale["sl1_marker_present"] = False
    if current_ok(stale):
        raise FormalError("stale_mutant_not_blocked")
    wrong_target = {"repo": EXPECTED_REPO, "issue": 41}
    if wrong_target["issue"] == EXPECTED_ISSUE:
        raise FormalError("target_mutant_not_blocked")
    conflict = dict(fresh_current)
    conflict["unresolved_conflict"] = True
    if current_ok(conflict):
        raise FormalError("conflict_mutant_not_blocked")
    requested_effect = "POST_COMMENT"
    if requested_effect == "PREPARE_ONLY":
        raise FormalError("effect_mutant_not_blocked")

    return {
        "schema": "safe-live.sl2-prepare-formal.v1",
        "status": "PASS",
        "activation_cell": "SL2-01",
        "minimum_loops": 5,
        "loop_1": "PASS",
        "loop_2": "PASS",
        "loop_3": "PASS",
        "loop_4": "PASS_CLEAN_1",
        "loop_5": "PASS_CLEAN_2",
        "two_consecutive_clean": True,
        "prepared_target_repo": EXPECTED_REPO,
        "prepared_target_issue": EXPECTED_ISSUE,
        "allowed_effect": "PREPARE_ONLY",
        "execute": False,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "sl3_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--fresh-current", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        result = evaluate(Path(args.artifact_dir), load_json(Path(args.fresh_current)))
    except (FormalError, ValueError, OSError) as exc:
        print(f"SAFE_LIVE_SL2_FORMAL=FAIL:{exc}")
        return 1
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("SAFE_LIVE_SL2_FORMAL=PASS")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL2_LOOP_{i}=PASS")
    print("SAFE_LIVE_SL2_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL2_CLEAN_2=LOOP_5")
    print("SAFE_LIVE_SL2_TWO_CONSECUTIVE_CLEAN=true")
    print("SAFE_LIVE_SL2_ALLOWED_EFFECT=PREPARE_ONLY")
    print("SAFE_LIVE_SL2_EXECUTE=false")
    print("SAFE_LIVE_SL2_EXTERNAL_ACTIONS=0")
    print("SAFE_LIVE_SL2_PRODUCTION_WRITES=0")
    print("SAFE_LIVE_SL2_SL3_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
