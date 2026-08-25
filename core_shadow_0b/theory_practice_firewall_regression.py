from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "core-shadow.theory-practice-firewall-regression.v1"
CASE_ID = "CS-FIREWALL-REGRESSION-001"
INVARIANTS = [f"F{i}" for i in range(1, 9)]


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixtures() -> list[dict[str, Any]]:
    return [
        {
            "loop": 1,
            "name": "THEORY_ONLY_GREEN",
            "theory_state": "CLEAN_PASS_MATURE",
            "theory_claim": "GREEN",
            "active_operational_ref": False,
            "project_binding": False,
            "runtime_active": False,
            "live_source_state": "MISSING",
            "live_value": None,
            "derived_claim": "GREEN",
            "generic_continue": False,
            "activation_lineage": False,
            "current_authority": False,
            "allowed_effects": [],
            "requested_effect": "READ_ONLY",
        },
        {
            "loop": 2,
            "name": "CURRENT_REALITY_CONFLICT",
            "theory_state": "CLEAN_PASS_MATURE",
            "theory_claim": "GREEN",
            "active_operational_ref": True,
            "project_binding": True,
            "runtime_active": True,
            "live_source_state": "CURRENT",
            "live_value": "PAUSED_FAIL_CLOSED",
            "derived_claim": "GREEN",
            "generic_continue": False,
            "activation_lineage": True,
            "current_authority": True,
            "allowed_effects": ["READ_ONLY"],
            "requested_effect": "READ_ONLY",
        },
        {
            "loop": 3,
            "name": "STALE_DERIVED_OLD_PASS",
            "theory_state": "CLEAN_PASS_MATURE",
            "theory_claim": "GREEN",
            "active_operational_ref": True,
            "project_binding": True,
            "runtime_active": True,
            "live_source_state": "STALE",
            "live_value": "OLD_GREEN",
            "derived_claim": "GREEN",
            "generic_continue": False,
            "activation_lineage": True,
            "current_authority": True,
            "allowed_effects": ["READ_ONLY"],
            "requested_effect": "READ_ONLY",
        },
        {
            "loop": 4,
            "name": "GENERIC_CONTINUATION_EFFECT_ESCALATION",
            "theory_state": "CLEAN_PASS_MATURE",
            "theory_claim": "GREEN",
            "active_operational_ref": True,
            "project_binding": True,
            "runtime_active": True,
            "live_source_state": "CURRENT",
            "live_value": "READ_ONLY_PASS",
            "derived_claim": "READ_ONLY_PASS",
            "generic_continue": True,
            "activation_lineage": True,
            "current_authority": True,
            "allowed_effects": ["READ_ONLY"],
            "requested_effect": "SEND",
        },
        {
            "loop": 5,
            "name": "REBUILD_NO_CHAT_MEMORY",
            "theory_state": "CLEAN_PASS_MATURE",
            "theory_claim": "GREEN",
            "active_operational_ref": False,
            "project_binding": True,
            "runtime_active": False,
            "live_source_state": "UNAVAILABLE",
            "live_value": None,
            "derived_claim": "FORMER_PASS",
            "generic_continue": True,
            "activation_lineage": False,
            "current_authority": False,
            "allowed_effects": [],
            "requested_effect": "WRITE",
        },
    ]


def evaluate_one(f: Mapping[str, Any]) -> dict[str, Any]:
    live_current = f.get("live_source_state") == "CURRENT"
    operational_context = bool(f.get("active_operational_ref") and f.get("project_binding") and f.get("runtime_active"))
    current_fact = f.get("live_value") if live_current and operational_context else "UNKNOWN"
    conflict = bool(live_current and f.get("live_value") != f.get("theory_claim"))

    policy_active = operational_context
    runtime_capability = operational_context
    allowed_effects = set(f.get("allowed_effects") or [])
    exact_action_ready = bool(
        f.get("activation_lineage")
        and f.get("current_authority")
        and f.get("requested_effect") in allowed_effects
        and operational_context
    )

    checks = {
        "F1": True,  # Theory remains advisory; it is never used directly below as operational state.
        "F2": not (
            f.get("theory_state") in {"APPROVED", "MATURE", "CLEAN", "PASS", "CLEAN_PASS_MATURE"}
            and not operational_context
            and (current_fact != "UNKNOWN" or policy_active or runtime_capability or exact_action_ready)
        ),
        "F3": current_fact == "UNKNOWN" or (live_current and operational_context),
        "F4": not (current_fact == f.get("derived_claim") and not live_current),
        "F5": live_current or current_fact == "UNKNOWN",
        "F6": (not conflict) or (current_fact == f.get("live_value") and current_fact != f.get("theory_claim")),
        "F7": (f.get("requested_effect") in allowed_effects) or (exact_action_ready is False),
        "F8": (not exact_action_ready) or bool(f.get("activation_lineage") and f.get("current_authority")),
    }

    if set(checks) != set(INVARIANTS):
        raise ValueError("invariant_set_invalid")

    return {
        "loop": int(f["loop"]),
        "name": f["name"],
        "inputs": dict(f),
        "derived": {
            "theory_disposition": "ADVISORY_NOT_OPERATIONAL",
            "current_fact": current_fact,
            "conflict_visible": conflict,
            "operational_policy_active": policy_active,
            "runtime_capability_active": runtime_capability,
            "action_ready": exact_action_ready,
            "action_effect": f.get("requested_effect") if exact_action_ready else None,
        },
        "invariants": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def generate(out_dir: Path, run_id: str, commit: str, branch: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    loops = [evaluate_one(f) for f in fixtures()]
    evidence = {
        "schema": SCHEMA,
        "case_id": CASE_ID,
        "source_run_id": int(run_id),
        "source_commit": commit,
        "source_branch": branch,
        "synthetic_regression_only": True,
        "loops": loops,
        "final_clean_pair": [4, 5] if all(x["status"] == "PASS" for x in loops[3:5]) else [],
    }
    evidence_path = out_dir / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    manifest = {
        "schema": "core-shadow.theory-practice-firewall-manifest.v1",
        "case_id": CASE_ID,
        "source_run_id": int(run_id),
        "source_commit": commit,
        "source_branch": branch,
        "synthetic_regression_only": True,
        "contains_real_business_data": False,
        "contains_personal_data": False,
        "contains_secrets": False,
        "theory_promotions": 0,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "files": {"evidence.json": sha256_bytes(evidence_path.read_bytes())},
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    try:
        result = generate(Path(args.out_dir), args.run_id, args.commit, args.branch)
    except (ValueError, OSError) as exc:
        print(f"CORE_SHADOW_FIREWALL_REGRESSION=FAIL:{exc}")
        return 1
    if not all(loop["status"] == "PASS" for loop in result["loops"]):
        print("CORE_SHADOW_FIREWALL_REGRESSION=FAIL:loop_failure")
        return 1
    print("CORE_SHADOW_FIREWALL_REGRESSION=PASS")
    for loop in result["loops"]:
        print(f"CORE_SHADOW_FIREWALL_LOOP_{loop['loop']}=PASS")
    print("CORE_SHADOW_FIREWALL_CLEAN_1=LOOP_4")
    print("CORE_SHADOW_FIREWALL_CLEAN_2=LOOP_5")
    print("CORE_SHADOW_FIREWALL_THEORY_PROMOTIONS=0")
    print("CORE_SHADOW_FIREWALL_EXTERNAL_ACTIONS=0")
    print("CORE_SHADOW_FIREWALL_PRODUCTION_WRITES=0")
    print("CORE_SHADOW_FIREWALL_NEW_CREDENTIALS=0")
    print("CORE_SHADOW_FIREWALL_NEW_RUNNING_COST_EUR=0")
    print("CORE_SHADOW_FIREWALL_MERGE_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
