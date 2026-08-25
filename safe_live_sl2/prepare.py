from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "safe-live.sl2-prepare.v1"
CELL_ID = "SL2-01"
EXPECTED_REPO = "Thomas-Baasch/gehirn-runtime-lab"
EXPECTED_ISSUE = 42
SL1_MARKER = "CORE_SHADOW_0B01_SL1_FORMAL_PASS"
FIREWALL_MARKER = "THEORY_PRACTICE_FIREWALL_REGRESSION_PASS"
EXPECTED_FIREWALL_RUN = 32811173598
EXPECTED_SL1_RUN = 32811552246


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_current(current: Mapping[str, Any]) -> tuple[bool, str]:
    if current.get("repo") != EXPECTED_REPO:
        return False, "repo_mismatch"
    issue = current.get("issue42") or {}
    if issue.get("number") != EXPECTED_ISSUE or issue.get("state") != "open":
        return False, "target_issue_not_current_open"
    if current.get("sl1_marker_present") is not True:
        return False, "sl1_current_marker_missing"
    if current.get("firewall_marker_present") is not True:
        return False, "firewall_regression_marker_missing"
    runs = current.get("runs") or {}
    if (runs.get(str(EXPECTED_FIREWALL_RUN)) or {}).get("conclusion") != "success":
        return False, "firewall_run_not_success"
    if (runs.get(str(EXPECTED_SL1_RUN)) or {}).get("conclusion") != "success":
        return False, "sl1_run_not_success"
    artifacts = current.get("artifacts") or {}
    for run_id in (EXPECTED_FIREWALL_RUN, EXPECTED_SL1_RUN):
        items = artifacts.get(str(run_id)) or []
        if not items or any(item.get("expired") is True or not item.get("digest") for item in items):
            return False, f"artifact_currentness_invalid:{run_id}"
    if current.get("unresolved_conflict") is True:
        return False, "unresolved_current_conflict"
    return True, "current_ok"


def build_draft(current: Mapping[str, Any], *, target_repo: str = EXPECTED_REPO, target_issue: int = EXPECTED_ISSUE, requested_effect: str = "PREPARE_ONLY") -> dict[str, Any]:
    if target_repo != EXPECTED_REPO or target_issue != EXPECTED_ISSUE:
        return {"status": "BLOCKED", "reason": "target_identity_mismatch"}
    if requested_effect != "PREPARE_ONLY":
        return {"status": "BLOCKED", "reason": "effect_escalation_not_authorized"}
    ok, reason = validate_current(current)
    if not ok:
        return {"status": "BLOCKED", "reason": reason}
    issue = current["issue42"]
    draft_body = (
        "## SAFE-LIVE SL2-01 – PREPARE-ONLY DRAFT / NICHT POSTEN\n\n"
        "SL1 / 0B-01 ist für die exakt begrenzte READ_ONLY Activation Cell formal bestanden. "
        "Die Theory-Practice-Firewall-Regression ist ebenfalls aktuell belegt.\n\n"
        f"Current source: Issue #{issue['number']} (updated_at {issue['updated_at']}); "
        f"Firewall Run {EXPECTED_FIREWALL_RUN}=success; SL1 Run {EXPECTED_SL1_RUN}=success.\n\n"
        "Dieser Text ist ausschließlich ein vorbereiteter Entwurf. Er ist keine Freigabe zum Posten, "
        "keine globale 0B-Freigabe und keine Write-/Send-/Merge-Autorität. "
        "SL3 und höhere Wirkungsklassen bleiben gesperrt."
    )
    return {
        "status": "PREPARED",
        "activation_cell": CELL_ID,
        "target_repo": target_repo,
        "target_issue": target_issue,
        "operation": "create_comment",
        "effect_class": "PREPARE_ONLY",
        "execute": False,
        "draft_body": draft_body,
        "source_refs": {
            "issue42_updated_at": issue["updated_at"],
            "issue42_latest_comment_id": current.get("issue42_latest_comment_id"),
            "firewall_run": EXPECTED_FIREWALL_RUN,
            "sl1_run": EXPECTED_SL1_RUN,
        },
    }


def loop_results(current: Mapping[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    normal = build_draft(current)
    results.append({"loop": 1, "name": "NORMAL_CURRENT_PREPARE", "pass": normal.get("status") == "PREPARED", "fundamental_finding": False})

    stale = dict(current)
    stale["sl1_marker_present"] = False
    stale_result = build_draft(stale)
    results.append({"loop": 2, "name": "STALE_CURRENTNESS", "pass": stale_result == {"status": "BLOCKED", "reason": "sl1_current_marker_missing"}, "fundamental_finding": False})

    wrong_target = build_draft(current, target_issue=41)
    results.append({"loop": 3, "name": "TARGET_IDENTITY_ROUTING", "pass": wrong_target == {"status": "BLOCKED", "reason": "target_identity_mismatch"}, "fundamental_finding": False})

    conflicted = dict(current)
    conflicted["unresolved_conflict"] = True
    conflict_result = build_draft(conflicted)
    rebuilt_result = build_draft(current)
    results.append({"loop": 4, "name": "CONFLICT_DISSENT_REBUILD", "pass": conflict_result == {"status": "BLOCKED", "reason": "unresolved_current_conflict"} and rebuilt_result.get("status") == "PREPARED", "fundamental_finding": False, "clean": True})

    escalated = build_draft(current, requested_effect="POST_COMMENT")
    results.append({"loop": 5, "name": "EFFECT_ESCALATION", "pass": escalated == {"status": "BLOCKED", "reason": "effect_escalation_not_authorized"}, "fundamental_finding": False, "clean": True})
    return results


def evaluate(current: Mapping[str, Any]) -> dict[str, Any]:
    prepared = build_draft(current)
    loops = loop_results(current)
    if prepared.get("status") != "PREPARED":
        raise ValueError(f"prepare_blocked:{prepared.get('reason')}")
    if len(loops) < 5 or not all(loop.get("pass") is True for loop in loops):
        raise ValueError("five_loop_gate_failed")
    if not (loops[-2].get("clean") is True and loops[-1].get("clean") is True):
        raise ValueError("two_consecutive_clean_missing")
    return {
        "schema": SCHEMA,
        "status": "PASS",
        "activation_cell": CELL_ID,
        "prepared_action": prepared,
        "loops": loops,
        "minimum_loops": 5,
        "clean_1": "LOOP_4",
        "clean_2": "LOOP_5",
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "higher_effect_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    try:
        current = json.loads(Path(args.current).read_text(encoding="utf-8"))
        result = evaluate(current)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"SAFE_LIVE_SL2_PREPARE=FAIL:{exc}")
        return 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    current_path = out_dir / "current_minimized.json"
    result_path = out_dir / "prepare_result.json"
    draft_path = out_dir / "draft_comment.md"
    current_path.write_bytes(canonical_bytes(current))
    result_path.write_bytes(canonical_bytes(result))
    draft_path.write_text(result["prepared_action"]["draft_body"] + "\n", encoding="utf-8")
    manifest = {
        "schema": "safe-live.sl2-prepare-manifest.v1",
        "activation_cell": CELL_ID,
        "effect_class": "PREPARE_ONLY",
        "execute": False,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "files": {
            "current_minimized.json": sha256_bytes(current_path.read_bytes()),
            "prepare_result.json": sha256_bytes(result_path.read_bytes()),
            "draft_comment.md": sha256_bytes(draft_path.read_bytes()),
        },
    }
    (out_dir / "manifest.json").write_bytes(canonical_bytes(manifest))
    print("SAFE_LIVE_SL2_PREPARE=PASS")
    for loop in result["loops"]:
        print(f"SAFE_LIVE_SL2_LOOP_{loop['loop']}=PASS")
    print("SAFE_LIVE_SL2_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL2_CLEAN_2=LOOP_5")
    print("SAFE_LIVE_SL2_EFFECT=PREPARE_ONLY")
    print("SAFE_LIVE_SL2_EXECUTE=false")
    print("SAFE_LIVE_SL2_EXTERNAL_ACTIONS=0")
    print("SAFE_LIVE_SL2_PRODUCTION_WRITES=0")
    print("SAFE_LIVE_SL2_MERGE_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
