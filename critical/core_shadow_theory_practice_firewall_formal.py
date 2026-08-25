from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

CASE_ID = "CS-FIREWALL-REGRESSION-001"
EXPECTED_BRANCH = "runtime/core-shadow-firewall-regression-001"
EXPECTED_INVARIANTS = {f"F{i}" for i in range(1, 9)}


class FirewallFormalError(ValueError):
    pass


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise FirewallFormalError(f"json_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise FirewallFormalError(f"json_object_required:{path}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independently_evaluate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    live_current = inputs.get("live_source_state") == "CURRENT"
    operational_context = bool(
        inputs.get("active_operational_ref")
        and inputs.get("project_binding")
        and inputs.get("runtime_active")
    )
    current_fact = inputs.get("live_value") if live_current and operational_context else "UNKNOWN"
    conflict = bool(live_current and inputs.get("live_value") != inputs.get("theory_claim"))
    allowed = set(inputs.get("allowed_effects") or [])
    action_ready = bool(
        inputs.get("activation_lineage")
        and inputs.get("current_authority")
        and inputs.get("requested_effect") in allowed
        and operational_context
    )
    return {
        "theory_disposition": "ADVISORY_NOT_OPERATIONAL",
        "current_fact": current_fact,
        "conflict_visible": conflict,
        "operational_policy_active": operational_context,
        "runtime_capability_active": operational_context,
        "action_ready": action_ready,
        "action_effect": inputs.get("requested_effect") if action_ready else None,
    }


def invariant_checks(inputs: Mapping[str, Any], derived: Mapping[str, Any]) -> dict[str, bool]:
    live_current = inputs.get("live_source_state") == "CURRENT"
    operational_context = bool(
        inputs.get("active_operational_ref")
        and inputs.get("project_binding")
        and inputs.get("runtime_active")
    )
    conflict = bool(live_current and inputs.get("live_value") != inputs.get("theory_claim"))
    allowed = set(inputs.get("allowed_effects") or [])
    action_ready = bool(derived.get("action_ready"))
    checks = {
        "F1": derived.get("theory_disposition") == "ADVISORY_NOT_OPERATIONAL",
        "F2": not (
            inputs.get("theory_state") in {"APPROVED", "MATURE", "CLEAN", "PASS", "CLEAN_PASS_MATURE"}
            and not operational_context
            and (
                derived.get("current_fact") != "UNKNOWN"
                or derived.get("operational_policy_active")
                or derived.get("runtime_capability_active")
                or action_ready
            )
        ),
        "F3": derived.get("current_fact") == "UNKNOWN" or (live_current and operational_context),
        "F4": not (derived.get("current_fact") == inputs.get("derived_claim") and not live_current),
        "F5": live_current or derived.get("current_fact") == "UNKNOWN",
        "F6": (not conflict) or (
            derived.get("current_fact") == inputs.get("live_value")
            and derived.get("current_fact") != inputs.get("theory_claim")
        ),
        "F7": (inputs.get("requested_effect") in allowed) or (action_ready is False),
        "F8": (not action_ready) or bool(inputs.get("activation_lineage") and inputs.get("current_authority")),
    }
    if set(checks) != EXPECTED_INVARIANTS:
        raise FirewallFormalError("formal_invariant_set_invalid")
    return checks


def evaluate(artifact_dir: Path) -> dict[str, Any]:
    manifest_path = artifact_dir / "manifest.json"
    evidence_path = artifact_dir / "evidence.json"
    manifest = load_json(manifest_path)
    evidence = load_json(evidence_path)

    if manifest.get("schema") != "core-shadow.theory-practice-firewall-manifest.v1":
        raise FirewallFormalError("manifest_schema_invalid")
    if evidence.get("schema") != "core-shadow.theory-practice-firewall-regression.v1":
        raise FirewallFormalError("evidence_schema_invalid")
    if manifest.get("case_id") != CASE_ID or evidence.get("case_id") != CASE_ID:
        raise FirewallFormalError("case_id_invalid")
    if manifest.get("source_branch") != EXPECTED_BRANCH or evidence.get("source_branch") != EXPECTED_BRANCH:
        raise FirewallFormalError("branch_invalid")
    if manifest.get("files") != {"evidence.json": sha(evidence_path)}:
        raise FirewallFormalError("evidence_hash_mismatch")

    boundaries = {
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
    }
    for key, expected in boundaries.items():
        if manifest.get(key) != expected:
            raise FirewallFormalError(f"boundary_invalid:{key}")

    loops = evidence.get("loops")
    if not isinstance(loops, list) or len(loops) != 5:
        raise FirewallFormalError("five_loops_required")
    if [loop.get("loop") for loop in loops] != [1, 2, 3, 4, 5]:
        raise FirewallFormalError("loop_sequence_invalid")

    formal_loops = []
    for loop in loops:
        inputs = loop.get("inputs")
        derived = loop.get("derived")
        recorded_checks = loop.get("invariants")
        if not isinstance(inputs, dict) or not isinstance(derived, dict) or not isinstance(recorded_checks, dict):
            raise FirewallFormalError(f"loop_structure_invalid:{loop.get('loop')}")
        independent = independently_evaluate(inputs)
        if dict(derived) != independent:
            raise FirewallFormalError(f"derived_mismatch:{loop.get('loop')}")
        checks = invariant_checks(inputs, independent)
        if set(recorded_checks) != EXPECTED_INVARIANTS or dict(recorded_checks) != checks:
            raise FirewallFormalError(f"invariant_mismatch:{loop.get('loop')}")
        if not all(checks.values()) or loop.get("status") != "PASS":
            raise FirewallFormalError(f"loop_not_pass:{loop.get('loop')}")
        formal_loops.append({"loop": loop["loop"], "status": "PASS", "invariants": checks})

    if evidence.get("final_clean_pair") != [4, 5]:
        raise FirewallFormalError("final_clean_pair_invalid")

    return {
        "schema": "core-shadow.theory-practice-firewall-formal.v1",
        "status": "PASS",
        "source_run_id": evidence.get("source_run_id"),
        "source_commit": evidence.get("source_commit"),
        "source_branch": evidence.get("source_branch"),
        "evidence_sha256": sha(evidence_path),
        "manifest_sha256": sha(manifest_path),
        "loops": formal_loops,
        "clean_1": "LOOP_4",
        "clean_2": "LOOP_5",
        "theory_promotions": 0,
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
    except (FirewallFormalError, ValueError, OSError) as exc:
        print(f"CORE_SHADOW_FIREWALL_FORMAL=FAIL:{exc}")
        return 1
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CORE_SHADOW_FIREWALL_FORMAL=PASS")
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
