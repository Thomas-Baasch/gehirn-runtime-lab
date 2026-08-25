from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "core-shadow-0b.precheck.v1"
CASE_ID = "CS0B-PRECHECK-001"


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_events() -> list[dict[str, Any]]:
    return [
        {"seq": 1, "event": "PRECHECK_STARTED", "case_id": CASE_ID, "external_effect": False},
        {"seq": 2, "event": "DERIVED_STATUS_PROPOSED", "case_id": CASE_ID, "status": "READY_CANDIDATE", "external_effect": False},
        {"seq": 3, "event": "ARTIFACT_PERSIST_REQUESTED", "case_id": CASE_ID, "contains_secrets": False, "contains_real_case_data": False, "external_effect": False},
    ]


def rebuild(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not events:
        raise ValueError("events_required")
    seqs = [int(e.get("seq") or 0) for e in events]
    if seqs != list(range(1, len(events) + 1)):
        raise ValueError("event_sequence_invalid")
    case_ids = {e.get("case_id") for e in events}
    if case_ids != {CASE_ID}:
        raise ValueError("case_identity_invalid")
    if any(e.get("external_effect") is not False for e in events):
        raise ValueError("external_effect_detected")
    derived = None
    artifact_requested = False
    for event in events:
        if event.get("event") == "DERIVED_STATUS_PROPOSED":
            derived = {"case_id": CASE_ID, "status": event.get("status"), "source": "EVENT_REBUILD"}
        if event.get("event") == "ARTIFACT_PERSIST_REQUESTED":
            if event.get("contains_secrets") is not False or event.get("contains_real_case_data") is not False:
                raise ValueError("artifact_boundary_invalid")
            artifact_requested = True
    if derived is None or not artifact_requested:
        raise ValueError("required_event_missing")
    return derived


def generate(out_dir: Path, run_id: str, commit: str, branch: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events = build_events()
    derived = rebuild(events)
    event_doc = {"schema": SCHEMA, "case_id": CASE_ID, "synthetic_precheck_only": True, "events": events}
    derived_doc = {"schema": "core-shadow-0b.precheck-derived.v1", **derived}
    event_path = out_dir / "events.json"
    derived_path = out_dir / "derived.json"
    event_path.write_bytes(canonical_bytes(event_doc))
    derived_path.write_bytes(canonical_bytes(derived_doc))
    manifest = {
        "schema": "core-shadow-0b.precheck-manifest.v1",
        "case_id": CASE_ID,
        "source_run_id": int(run_id),
        "source_commit": commit,
        "source_branch": branch,
        "synthetic_precheck_only": True,
        "contains_real_case_data": False,
        "contains_personal_data": False,
        "contains_secrets": False,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "files": {
            "events.json": sha256_bytes(event_path.read_bytes()),
            "derived.json": sha256_bytes(derived_path.read_bytes()),
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    return manifest


def restore(artifact_dir: Path) -> dict[str, Any]:
    manifest_path = artifact_dir / "manifest.json"
    event_path = artifact_dir / "events.json"
    derived_path = artifact_dir / "derived.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "core-shadow-0b.precheck-manifest.v1":
        raise ValueError("manifest_schema_invalid")
    if manifest.get("synthetic_precheck_only") is not True:
        raise ValueError("precheck_scope_invalid")
    for key, expected in {
        "contains_real_case_data": False,
        "contains_personal_data": False,
        "contains_secrets": False,
        "external_actions": 0,
        "production_writes": 0,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
    }.items():
        if manifest.get(key) != expected:
            raise ValueError(f"manifest_boundary_invalid:{key}")
    for name, path in (("events.json", event_path), ("derived.json", derived_path)):
        observed = sha256_bytes(path.read_bytes())
        if manifest.get("files", {}).get(name) != observed:
            raise ValueError(f"artifact_hash_mismatch:{name}")
    event_doc = json.loads(event_path.read_text(encoding="utf-8"))
    derived_doc = json.loads(derived_path.read_text(encoding="utf-8"))
    expected_derived = {"case_id": CASE_ID, "status": derived_doc.get("status"), "source": "EVENT_REBUILD"}
    derived_path.unlink()
    if derived_path.exists():
        raise ValueError("derived_delete_failed")
    rebuilt = rebuild(event_doc.get("events") or [])
    if rebuilt != expected_derived:
        raise ValueError("fresh_process_rebuild_mismatch")
    return {
        "schema": "core-shadow-0b.precheck-restore.v1",
        "status": "PASS",
        "source_run_id": manifest["source_run_id"],
        "source_commit": manifest["source_commit"],
        "source_branch": manifest["source_branch"],
        "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "event_rebuild": rebuilt,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--out-dir", required=True)
    gen.add_argument("--run-id", required=True)
    gen.add_argument("--commit", required=True)
    gen.add_argument("--branch", required=True)
    res = sub.add_parser("restore")
    res.add_argument("--artifact-dir", required=True)
    res.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.cmd == "generate":
        result = generate(Path(args.out_dir), args.run_id, args.commit, args.branch)
        print("CORE_SHADOW_0B_PRECHECK_GENERATE=PASS")
        print(f"CORE_SHADOW_0B_PRECHECK_MANIFEST_RUN={result['source_run_id']}")
        return 0
    try:
        result = restore(Path(args.artifact_dir))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"CORE_SHADOW_0B_PRECHECK_RESTORE=FAIL:{exc}")
        return 1
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CORE_SHADOW_0B_PRECHECK_RESTORE=PASS")
    print("CORE_SHADOW_0B_PRECHECK_FRESH_PROCESS=true")
    print("CORE_SHADOW_0B_PRECHECK_HASHES=true")
    print("CORE_SHADOW_0B_PRECHECK_DERIVED_DELETED=true")
    print("CORE_SHADOW_0B_PRECHECK_EXTERNAL_ACTIONS=0")
    print("CORE_SHADOW_0B_PRECHECK_PRODUCTION_WRITES=0")
    print("CORE_SHADOW_0B_PRECHECK_NEW_CREDENTIALS=0")
    print("CORE_SHADOW_0B_PRECHECK_NEW_RUNNING_COST_EUR=0")
    print("CORE_SHADOW_0B_PRECHECK_MERGE_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
