from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

EXPECTED_TEST_IDS = [f"CS-{n:02d}" for n in range(1, 21)]
EXPECTED_CONTRACT = "1YMD3ynywpfgKYY-v7dzN4eqcx6mA0Pm9RLBjPI7hwjg"
EXPECTED_BRANCH = "runtime/core-shadow-0a1-001"
EXPECTED_JOB = "core-shadow-0a1-20of20"


class FormalAcceptanceError(ValueError):
    pass


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise FormalAcceptanceError(f"json_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise FormalAcceptanceError(f"json_object_required:{path}")
    return value


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def one_job(jobs: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    rows = jobs.get("jobs")
    if not isinstance(rows, list):
        raise FormalAcceptanceError("jobs_invalid")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("name") == name]
    if len(matches) != 1:
        raise FormalAcceptanceError(f"job_count_invalid:{name}:{len(matches)}")
    return matches[0]


def one_artifact(artifacts: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    rows = artifacts.get("artifacts")
    if not isinstance(rows, list):
        raise FormalAcceptanceError("artifacts_invalid")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("name") == name]
    if len(matches) != 1:
        raise FormalAcceptanceError(f"artifact_count_invalid:{name}:{len(matches)}")
    return matches[0]


def evaluate(
    *,
    evidence: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    authority: Mapping[str, Any],
    manifest: Mapping[str, Any],
    source_run: Mapping[str, Any],
    source_jobs: Mapping[str, Any],
    source_artifacts: Mapping[str, Any],
    evidence_path: Path,
    acceptance_path: Path,
    authority_path: Path,
    expected_run_id: int,
    expected_commit: str,
    expected_artifact_id: int,
    expected_artifact_name: str,
    expected_artifact_digest: str,
) -> dict[str, Any]:
    if manifest.get("schema") != "core-shadow-0a1.source-manifest.v1":
        raise FormalAcceptanceError("manifest_schema_invalid")
    if int(manifest.get("source_run_id") or 0) != expected_run_id:
        raise FormalAcceptanceError("manifest_run_id_mismatch")
    if manifest.get("source_commit") != expected_commit:
        raise FormalAcceptanceError("manifest_commit_mismatch")
    if manifest.get("source_branch") != EXPECTED_BRANCH:
        raise FormalAcceptanceError("manifest_branch_invalid")
    if manifest.get("contract_drive_id") != EXPECTED_CONTRACT:
        raise FormalAcceptanceError("manifest_contract_invalid")
    if manifest.get("expected_job") != EXPECTED_JOB:
        raise FormalAcceptanceError("manifest_job_invalid")
    exact_manifest = {
        "golden": "20/20",
        "restart_equal": True,
        "rebuild_equal": True,
        "authority_surface": "PASS",
        "independence_class": "I0_METHOD_SEPARATE_CODEPATH",
        "external_actions": 0,
        "production_writes": 0,
        "credentials_used": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
    }
    for key, expected in exact_manifest.items():
        if manifest.get(key) != expected:
            raise FormalAcceptanceError(f"manifest_claim_invalid:{key}")

    file_hashes = manifest.get("file_sha256")
    if not isinstance(file_hashes, Mapping):
        raise FormalAcceptanceError("manifest_hashes_missing")
    paths = {
        "core_shadow_0a1_evidence.json": evidence_path,
        "core_shadow_0a1_acceptance.json": acceptance_path,
        "core_shadow_0a1_authority_surface.json": authority_path,
    }
    observed_hashes = {name: sha256_file(path) for name, path in paths.items()}
    if dict(file_hashes) != observed_hashes:
        raise FormalAcceptanceError("artifact_file_hash_mismatch")

    if source_run.get("id") != expected_run_id:
        raise FormalAcceptanceError("source_run_id_mismatch")
    if source_run.get("head_sha") != expected_commit:
        raise FormalAcceptanceError("source_run_commit_mismatch")
    if source_run.get("head_branch") != EXPECTED_BRANCH:
        raise FormalAcceptanceError("source_run_branch_invalid")
    if source_run.get("status") != "completed" or source_run.get("conclusion") != "success":
        raise FormalAcceptanceError("source_run_not_successful")
    repository = source_run.get("repository")
    if not isinstance(repository, Mapping) or repository.get("full_name") != "Thomas-Baasch/gehirn-runtime-lab":
        raise FormalAcceptanceError("source_repository_invalid")

    job = one_job(source_jobs, EXPECTED_JOB)
    if job.get("status") != "completed" or job.get("conclusion") != "success":
        raise FormalAcceptanceError("source_job_not_successful")
    if job.get("head_sha") != expected_commit:
        raise FormalAcceptanceError("source_job_commit_mismatch")
    step_names = {
        "Syntax check",
        "Unit and negative regression tests",
        "Static no-authority-creep gate",
        "Execute frozen Core Shadow 0A.1 acceptance harness",
        "Build immutable source manifest and print evidence digests",
        "Upload immutable synthetic evidence artifact",
    }
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise FormalAcceptanceError("source_steps_missing")
    by_name = {str(step.get("name")): step for step in steps if isinstance(step, Mapping)}
    for name in step_names:
        step = by_name.get(name)
        if not isinstance(step, Mapping) or step.get("status") != "completed" or step.get("conclusion") != "success":
            raise FormalAcceptanceError(f"source_step_not_success:{name}")

    artifact = one_artifact(source_artifacts, expected_artifact_name)
    if int(artifact.get("id") or 0) != expected_artifact_id:
        raise FormalAcceptanceError("artifact_id_mismatch")
    if artifact.get("expired") is not False:
        raise FormalAcceptanceError("artifact_expired")
    if artifact.get("digest") != expected_artifact_digest:
        raise FormalAcceptanceError("artifact_digest_mismatch")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, Mapping):
        raise FormalAcceptanceError("artifact_workflow_run_missing")
    if workflow_run.get("id") != expected_run_id or workflow_run.get("head_sha") != expected_commit or workflow_run.get("head_branch") != EXPECTED_BRANCH:
        raise FormalAcceptanceError("artifact_source_binding_invalid")

    if evidence.get("schema") != "core-shadow-0a1.evidence.v1":
        raise FormalAcceptanceError("evidence_schema_invalid")
    if evidence.get("contract_drive_id") != EXPECTED_CONTRACT or evidence.get("case_id") != "CS0A1-SYN-001":
        raise FormalAcceptanceError("evidence_identity_invalid")
    boundaries = {
        "synthetic_only": True,
        "contains_personal_data": False,
        "contains_productive_data": False,
        "contains_secrets": False,
        "external_actions_executed": 0,
        "production_writes": 0,
        "credentials_used": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "restart_replay_equal": True,
    }
    for key, expected in boundaries.items():
        if evidence.get(key) != expected:
            raise FormalAcceptanceError(f"evidence_boundary_invalid:{key}")
    if evidence.get("independence_claim") != "I0_METHOD_SEPARATE_CODEPATH":
        raise FormalAcceptanceError("false_independence_claim")
    final = evidence.get("final_summary")
    if not isinstance(final, Mapping):
        raise FormalAcceptanceError("final_summary_missing")
    obligations = final.get("obligation_states")
    if not isinstance(obligations, Mapping) or len(obligations) != 8 or any(state != "CLOSED" for state in obligations.values()):
        raise FormalAcceptanceError("obligations_not_fully_closed")
    if final.get("composite_completion_state") != "CLOSED" or final.get("open_material_obligations") != []:
        raise FormalAcceptanceError("composite_not_closed_cleanly")
    if final.get("business_outcome_state") != "BENEFIT_PENDING":
        raise FormalAcceptanceError("business_outcome_semantics_invalid")
    observations = evidence.get("observations")
    if not isinstance(observations, Mapping):
        raise FormalAcceptanceError("observations_missing")
    if observations.get("composite_at_peter_close") != "OPEN" or not observations.get("open_at_peter_close"):
        raise FormalAcceptanceError("local_close_orphan_guard_unproven")
    if observations.get("old_commit_status") != "BLOCKED_STALE_PRECONDITION" or observations.get("revalidated_commit_status") != "COMMITTED_ISOLATED_DERIVED":
        raise FormalAcceptanceError("commit_time_currentness_unproven")
    if observations.get("rebuild_equal") is not True or observations.get("rebuild_summary") != final:
        raise FormalAcceptanceError("rebuild_unproven")

    if acceptance.get("schema") != "core-shadow-0a1.independent-readback.v1":
        raise FormalAcceptanceError("acceptance_schema_invalid")
    if acceptance.get("status") != "PASS" or acceptance.get("passed") != 20 or acceptance.get("total") != 20:
        raise FormalAcceptanceError("acceptance_not_20_of_20")
    if acceptance.get("independence_class") != "I0_METHOD_SEPARATE_CODEPATH":
        raise FormalAcceptanceError("acceptance_independence_invalid")
    tests = acceptance.get("tests")
    if not isinstance(tests, list):
        raise FormalAcceptanceError("acceptance_tests_missing")
    ids = [row.get("id") for row in tests if isinstance(row, Mapping)]
    if ids != EXPECTED_TEST_IDS:
        raise FormalAcceptanceError("acceptance_test_ids_invalid")
    if any(row.get("pass") is not True for row in tests if isinstance(row, Mapping)):
        raise FormalAcceptanceError("acceptance_has_failed_test")

    if authority.get("schema") != "core-shadow-0a1.authority-surface.v1" or authority.get("status") != "PASS":
        raise FormalAcceptanceError("authority_surface_not_pass")
    if authority.get("external_effect_interfaces") != [] or authority.get("workflow_write_permissions") != [] or authority.get("forbidden_workflow_tokens") != []:
        raise FormalAcceptanceError("authority_surface_not_empty")
    if authority.get("credentials_required") is not False or authority.get("production_authority_present") is not False or authority.get("merge_interface_present") is not False:
        raise FormalAcceptanceError("authority_surface_claim_invalid")
    if authority.get("new_running_cost_eur") != 0:
        raise FormalAcceptanceError("authority_cost_nonzero")

    return {
        "schema": "core-shadow-0a1.formal-acceptance.v1",
        "status": "PASS",
        "evidence_class": "SYNTHETIC_RUNTIME_FORMALLY_REACCEPTED",
        "source_run_id": expected_run_id,
        "source_commit": expected_commit,
        "source_job_id": int(job.get("id") or 0),
        "artifact_id": expected_artifact_id,
        "artifact_name": expected_artifact_name,
        "artifact_digest": expected_artifact_digest,
        "source_file_sha256": observed_hashes,
        "golden_passed": 20,
        "golden_total": 20,
        "restart_equal": True,
        "rebuild_equal": True,
        "authority_surface": "PASS",
        "independence_class": "I0_METHOD_SEPARATE_CODEPATH",
        "georg_in_flow": True,
        "composite_orphan_prevention": "PASS",
        "commit_time_currentness": "PASS",
        "external_actions_executed": 0,
        "production_writes": 0,
        "credentials_used": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
        "core_shadow_0b_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--source-run-json", required=True)
    parser.add_argument("--source-jobs-json", required=True)
    parser.add_argument("--source-artifacts-json", required=True)
    parser.add_argument("--expected-run-id", type=int, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-artifact-id", type=int, required=True)
    parser.add_argument("--expected-artifact-name", required=True)
    parser.add_argument("--expected-artifact-digest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.artifact_dir)
    try:
        result = evaluate(
            evidence=load_json(root / "core_shadow_0a1_evidence.json"),
            acceptance=load_json(root / "core_shadow_0a1_acceptance.json"),
            authority=load_json(root / "core_shadow_0a1_authority_surface.json"),
            manifest=load_json(root / "core_shadow_0a1_source_manifest.json"),
            source_run=load_json(args.source_run_json),
            source_jobs=load_json(args.source_jobs_json),
            source_artifacts=load_json(args.source_artifacts_json),
            evidence_path=root / "core_shadow_0a1_evidence.json",
            acceptance_path=root / "core_shadow_0a1_acceptance.json",
            authority_path=root / "core_shadow_0a1_authority_surface.json",
            expected_run_id=args.expected_run_id,
            expected_commit=args.expected_commit,
            expected_artifact_id=args.expected_artifact_id,
            expected_artifact_name=args.expected_artifact_name,
            expected_artifact_digest=args.expected_artifact_digest,
        )
    except (FormalAcceptanceError, ValueError) as exc:
        print(f"CORE_SHADOW_0A1_FORMAL_FAIL={exc}")
        return 1
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CORE_SHADOW_0A1_FORMAL_STATUS=PASS")
    print("CORE_SHADOW_0A1_FORMAL_EVIDENCE_CLASS=SYNTHETIC_RUNTIME_FORMALLY_REACCEPTED")
    print("CORE_SHADOW_0A1_FORMAL_GOLDEN=20/20")
    print("CORE_SHADOW_0A1_FORMAL_GEORG_IN_FLOW=true")
    print("CORE_SHADOW_0A1_FORMAL_COMPOSITE_ORPHAN_PREVENTION=PASS")
    print("CORE_SHADOW_0A1_FORMAL_COMMIT_TIME_CURRENTNESS=PASS")
    print("CORE_SHADOW_0A1_FORMAL_EXTERNAL_ACTIONS=0")
    print("CORE_SHADOW_0A1_FORMAL_PRODUCTION_WRITES=0")
    print("CORE_SHADOW_0A1_FORMAL_CREDENTIALS=0")
    print("CORE_SHADOW_0A1_FORMAL_NEW_RUNNING_COST_EUR=0")
    print("CORE_SHADOW_0A1_FORMAL_MERGE_AUTHORIZED=false")
    print("CORE_SHADOW_0A1_FORMAL_0B_AUTHORIZED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
