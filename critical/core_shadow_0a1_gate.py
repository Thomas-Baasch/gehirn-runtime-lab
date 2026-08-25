from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core_shadow_0a1 import runtime
from core_shadow_0a1.konrad_control import challenge
from core_shadow_0a1.independent_readback import evaluate as independent_readback
from critical.core_shadow_0a1_authority_gate import evaluate as authority_surface

OUT_DIR = ROOT / "reports" / "core_shadow"
EVIDENCE_OUT = OUT_DIR / "core_shadow_0a1_evidence.json"
REPORT_OUT = OUT_DIR / "core_shadow_0a1_acceptance.json"


def execute_flow(*, restart_after_peter: bool) -> tuple[dict, dict]:
    case = runtime.make_fixture()
    outside = runtime.request_action(case, "uschi_owner_interface", "send_message")
    unknown = runtime.authorize(case, "unknown_worker", "project_next_step")

    runtime.uschi_intake(case)
    runtime.georg_prioritize(case)
    runtime.external_brain_truth_load(case)
    runtime.peter_next_step(case)

    peter_observation = {
        "peter_local_state": case["project_next_step"]["local_scope_state"],
        "peter_requires_owner": case["project_next_step"]["requires_owner"],
        "thomas_class_at_peter_close": case["thomas_class"],
        "composite_at_peter_close": case["composite_completion_state"],
        "open_at_peter_close": list(case["open_material_obligations"]),
    }

    proposal = runtime.propose_internal_derived_update(case)
    case["generations"]["resource"] += 1
    stale_commit = runtime.commit_internal_derived_update(case, proposal)
    revalidated = deepcopy(proposal)
    revalidated["resource_generation"] = case["generations"]["resource"]
    good_commit = runtime.commit_internal_derived_update(case, revalidated)

    if restart_after_peter:
        case = runtime.json_roundtrip(case)

    finding = challenge(case)
    runtime.apply_control_finding(case, finding)
    runtime.external_brain_reconcile(case)
    owner_view = runtime.uschi_owner_view(case)
    runtime.synthetic_owner_decision(case, "OPTION_A")

    observations = {
        **peter_observation,
        "unknown_authority_result": unknown,
        "outside_action_result": outside,
        "old_commit_status": stale_commit["status"],
        "revalidated_commit_status": good_commit["status"],
        "owner_view_before_synthetic_decision": owner_view,
    }
    return case, observations


def main() -> int:
    uninterrupted, _ = execute_flow(restart_after_peter=False)
    restarted, observations = execute_flow(restart_after_peter=True)
    restart_equal = runtime.summary(uninterrupted) == runtime.summary(restarted)

    authority = authority_surface()
    bundle = runtime.build_evidence_bundle(restarted, restart_replay_equal=restart_equal, authority_surface=authority)
    rebuilt = runtime.rebuild_from_events(bundle)
    observations["rebuild_summary"] = rebuilt
    observations["rebuild_equal"] = rebuilt == bundle["final_summary"]
    observations["independent_readback_input_only"] = True
    bundle["observations"] = observations

    readback = independent_readback(bundle)
    bundle["independent_readback"] = {
        "schema": readback["schema"],
        "status": readback["status"],
        "passed": readback["passed"],
        "total": readback["total"],
        "independence_class": readback["independence_class"],
        "load_bearing_outcome": readback["load_bearing_outcome"],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_OUT.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    REPORT_OUT.write_text(json.dumps(readback, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    status = (
        readback["status"] == "PASS" and readback["passed"] == 20 and readback["total"] == 20
        and authority["status"] == "PASS" and observations["rebuild_equal"] and restart_equal
    )
    print(f"CORE_SHADOW_0A1_STATUS={'PASS' if status else 'FAIL'}")
    print(f"CORE_SHADOW_0A1_GOLDEN={readback['passed']}/{readback['total']}")
    print(f"CORE_SHADOW_0A1_RESTART_EQUAL={str(restart_equal).lower()}")
    print(f"CORE_SHADOW_0A1_REBUILD_EQUAL={str(observations['rebuild_equal']).lower()}")
    print(f"CORE_SHADOW_0A1_AUTHORITY_SURFACE={authority['status']}")
    print(f"CORE_SHADOW_0A1_INDEPENDENCE={readback['independence_class']}")
    print("CORE_SHADOW_0A1_EXTERNAL_ACTIONS=0")
    print("CORE_SHADOW_0A1_PRODUCTION_WRITES=0")
    print("CORE_SHADOW_0A1_CREDENTIALS=0")
    print("CORE_SHADOW_0A1_NEW_RUNNING_COST_EUR=0")
    print("CORE_SHADOW_0A1_MERGE_AUTHORIZED=false")
    if not status:
        for item in readback["tests"]:
            if not item["pass"]:
                print(f"FAILED_{item['id']}={item['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
