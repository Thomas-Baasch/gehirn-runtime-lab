from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

# Deliberately does NOT import core_shadow_0b.precheck.
CASE_ID = "CS0B-PRECHECK-001"
EXPECTED_BRANCH = "runtime/core-shadow-0b-001"


class PrecheckFormalError(ValueError):
    pass


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise PrecheckFormalError(f"json_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise PrecheckFormalError(f"json_object_required:{path}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independent_rebuild(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    if len(events) != 3:
        raise PrecheckFormalError("event_count_invalid")
    if [e.get("seq") for e in events] != [1, 2, 3]:
        raise PrecheckFormalError("event_sequence_invalid")
    if {e.get("case_id") for e in events} != {CASE_ID}:
        raise PrecheckFormalError("case_id_invalid")
    if any(e.get("external_effect") is not False for e in events):
        raise PrecheckFormalError("external_effect_detected")
    proposed = [e for e in events if e.get("event") == "DERIVED_STATUS_PROPOSED"]
    persist = [e for e in events if e.get("event") == "ARTIFACT_PERSIST_REQUESTED"]
    if len(proposed) != 1 or len(persist) != 1:
        raise PrecheckFormalError("required_event_invalid")
    if persist[0].get("contains_secrets") is not False or persist[0].get("contains_real_case_data") is not False:
        raise PrecheckFormalError("persist_boundary_invalid")
    return {"case_id": CASE_ID, "status": proposed[0].get("status"), "source": "EVENT_REBUILD"}


def evaluate(source_dir: Path, restore_result: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
    manifest_path = source_dir / "manifest.json"
    events_path = source_dir / "events.json"
    derived_path = source_dir / "derived.json"
    manifest = load_json(manifest_path)
    events_doc = load_json(events_path)
    derived = load_json(derived_path)

    if manifest.get("schema") != "core-shadow-0b.precheck-manifest.v1":
        raise PrecheckFormalError("manifest_schema_invalid")
    if manifest.get("case_id") != CASE_ID or manifest.get("source_branch") != EXPECTED_BRANCH:
        raise PrecheckFormalError("manifest_identity_invalid")
    boundaries = {
        "synthetic_precheck_only": True,
        "contains_real_case_data": False,
        "contains_personal_data": False,
        "contains_secrets": False,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
    }
    for key, expected in boundaries.items():
        if manifest.get(key) != expected:
            raise PrecheckFormalError(f"manifest_boundary_invalid:{key}")
    observed = {"events.json": sha(events_path), "derived.json": sha(derived_path)}
    if manifest.get("files") != observed:
        raise PrecheckFormalError("source_hash_mismatch")

    independent = independent_rebuild(events_doc.get("events") or [])
    if derived.get("case_id") != CASE_ID or derived.get("status") != independent.get("status"):
        raise PrecheckFormalError("derived_not_rebuildable")

    if restore_result.get("schema") != "core-shadow-0b.precheck-restore.v1" or restore_result.get("status") != "PASS":
        raise PrecheckFormalError("restore_result_invalid")
    restore_expect = {
        "source_run_id": manifest.get("source_run_id"),
        "source_commit": manifest.get("source_commit"),
        "source_branch": manifest.get("source_branch"),
        "event_rebuild": independent,
        "derived_deleted_before_rebuild": True,
        "artifact_hashes_verified": True,
        "fresh_process_restore": True,
        "rollback_model": "UNMERGED_BRANCH_PLUS_DISPOSABLE_DERIVED_ARTIFACT",
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
    }
    for key, expected in restore_expect.items():
        if restore_result.get(key) != expected:
            raise PrecheckFormalError(f"restore_claim_invalid:{key}")

    if authority.get("schema") != "core-shadow-0b.precheck-authority.v1" or authority.get("status") != "PASS":
        raise PrecheckFormalError("authority_not_pass")
    if authority.get("write_permissions") != [] or authority.get("forbidden_interfaces") != [] or authority.get("secret_references") != []:
        raise PrecheckFormalError("authority_surface_not_readonly")
    if authority.get("i1_topology_ready") is not True:
        raise PrecheckFormalError("i1_topology_not_ready")

    return {
        "schema": "core-shadow-0b.precheck-formal.v1",
        "status": "PASS",
        "h0b06_readonly_identity_design": "PASS",
        "h0b07_independence": "PASS_I1_LOGICALLY_SEPARATE_PRECHECK",
        "h0b08_no_productive_action_adapter": "PASS",
        "h0b09_artifact_restore_rollback": "PASS",
        "source_run_id": manifest.get("source_run_id"),
        "source_commit": manifest.get("source_commit"),
        "source_branch": manifest.get("source_branch"),
        "source_manifest_sha256": sha(manifest_path),
        "fresh_process_restore": True,
        "independent_rebuild": independent,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "m4_a5_grant_used": False,
        "real_case_read_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--restore-result", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        result = evaluate(Path(args.source_dir), load_json(args.restore_result), load_json(args.authority))
    except (PrecheckFormalError, ValueError, OSError) as exc:
        print(f"CORE_SHADOW_0B_PRECHECK_FORMAL=FAIL:{exc}")
        return 1
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CORE_SHADOW_0B_PRECHECK_FORMAL=PASS")
    print("CORE_SHADOW_0B_H0B06=PASS")
    print("CORE_SHADOW_0B_H0B07=PASS_I1_LOGICALLY_SEPARATE_PRECHECK")
    print("CORE_SHADOW_0B_H0B08=PASS")
    print("CORE_SHADOW_0B_H0B09=PASS")
    print("CORE_SHADOW_0B_REAL_CASE_READ_EXECUTED=false")
    print("CORE_SHADOW_0B_EXTERNAL_ACTIONS=0")
    print("CORE_SHADOW_0B_NEW_CREDENTIALS=0")
    print("CORE_SHADOW_0B_NEW_RUNNING_COST_EUR=0")
    print("CORE_SHADOW_0B_MERGE_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
