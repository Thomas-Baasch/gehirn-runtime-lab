from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from critical.core_shadow_0a1_formal_acceptance import FormalAcceptanceError, evaluate

RUN_ID = 32799743510
COMMIT = "c0bdcc7b776225acb6ab9ff49b0ea6b7042df1bf"
ARTIFACT_ID = 9546075334
ARTIFACT_NAME = "core-shadow-0a1-evidence-32799743510"
ARTIFACT_DIGEST = "sha256:d8699dfb4342cdaebd64d8f5310fdc7c8279e52b6e7d9bcf68fc7a6732771141"


def source_run() -> dict:
    return {
        "id": RUN_ID,
        "head_sha": COMMIT,
        "head_branch": "runtime/core-shadow-0a1-001",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": "Thomas-Baasch/gehirn-runtime-lab"},
    }


def source_jobs() -> dict:
    names = [
        "Syntax check",
        "Unit and negative regression tests",
        "Static no-authority-creep gate",
        "Execute frozen Core Shadow 0A.1 acceptance harness",
        "Build immutable source manifest and print evidence digests",
        "Upload immutable synthetic evidence artifact",
    ]
    return {
        "jobs": [{
            "id": 44,
            "name": "core-shadow-0a1-20of20",
            "head_sha": COMMIT,
            "status": "completed",
            "conclusion": "success",
            "steps": [{"name": name, "status": "completed", "conclusion": "success"} for name in names],
        }]
    }


def source_artifacts() -> dict:
    return {
        "artifacts": [{
            "id": ARTIFACT_ID,
            "name": ARTIFACT_NAME,
            "expired": False,
            "digest": ARTIFACT_DIGEST,
            "workflow_run": {"id": RUN_ID, "head_sha": COMMIT, "head_branch": "runtime/core-shadow-0a1-001"},
        }]
    }


def evidence() -> dict:
    obligations = {f"O{n}": "CLOSED" for n in range(1, 9)}
    final = {
        "obligation_states": obligations,
        "composite_completion_state": "CLOSED",
        "open_material_obligations": [],
        "business_outcome_state": "BENEFIT_PENDING",
    }
    return {
        "schema": "core-shadow-0a1.evidence.v1",
        "contract_drive_id": "1YMD3ynywpfgKYY-v7dzN4eqcx6mA0Pm9RLBjPI7hwjg",
        "case_id": "CS0A1-SYN-001",
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
        "independence_claim": "I0_METHOD_SEPARATE_CODEPATH",
        "final_summary": final,
        "observations": {
            "composite_at_peter_close": "OPEN",
            "open_at_peter_close": ["O5", "O6", "O7", "O8"],
            "old_commit_status": "BLOCKED_STALE_PRECONDITION",
            "revalidated_commit_status": "COMMITTED_ISOLATED_DERIVED",
            "rebuild_equal": True,
            "rebuild_summary": final,
        },
    }


def acceptance() -> dict:
    return {
        "schema": "core-shadow-0a1.independent-readback.v1",
        "status": "PASS",
        "passed": 20,
        "total": 20,
        "independence_class": "I0_METHOD_SEPARATE_CODEPATH",
        "tests": [{"id": f"CS-{n:02d}", "pass": True} for n in range(1, 21)],
    }


def authority() -> dict:
    return {
        "schema": "core-shadow-0a1.authority-surface.v1",
        "status": "PASS",
        "external_effect_interfaces": [],
        "workflow_write_permissions": [],
        "forbidden_workflow_tokens": [],
        "credentials_required": False,
        "production_authority_present": False,
        "merge_interface_present": False,
        "new_running_cost_eur": 0,
    }


class FormalAcceptanceTests(unittest.TestCase):
    def build(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        objs = {
            "core_shadow_0a1_evidence.json": evidence(),
            "core_shadow_0a1_acceptance.json": acceptance(),
            "core_shadow_0a1_authority_surface.json": authority(),
        }
        hashes = {}
        for name, obj in objs.items():
            path = root / name
            path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "schema": "core-shadow-0a1.source-manifest.v1",
            "source_run_id": RUN_ID,
            "source_commit": COMMIT,
            "source_branch": "runtime/core-shadow-0a1-001",
            "contract_drive_id": "1YMD3ynywpfgKYY-v7dzN4eqcx6mA0Pm9RLBjPI7hwjg",
            "expected_job": "core-shadow-0a1-20of20",
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
            "file_sha256": hashes,
        }
        return temp, root, objs, manifest

    def call(self, root, objs, manifest):
        return evaluate(
            evidence=objs["core_shadow_0a1_evidence.json"],
            acceptance=objs["core_shadow_0a1_acceptance.json"],
            authority=objs["core_shadow_0a1_authority_surface.json"],
            manifest=manifest,
            source_run=source_run(),
            source_jobs=source_jobs(),
            source_artifacts=source_artifacts(),
            evidence_path=root / "core_shadow_0a1_evidence.json",
            acceptance_path=root / "core_shadow_0a1_acceptance.json",
            authority_path=root / "core_shadow_0a1_authority_surface.json",
            expected_run_id=RUN_ID,
            expected_commit=COMMIT,
            expected_artifact_id=ARTIFACT_ID,
            expected_artifact_name=ARTIFACT_NAME,
            expected_artifact_digest=ARTIFACT_DIGEST,
        )

    def test_valid_frozen_artifact_is_formally_reaccepted(self):
        temp, root, objs, manifest = self.build()
        self.addCleanup(temp.cleanup)
        result = self.call(root, objs, manifest)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["evidence_class"], "SYNTHETIC_RUNTIME_FORMALLY_REACCEPTED")
        self.assertEqual(result["golden_passed"], 20)
        self.assertTrue(result["georg_in_flow"])
        self.assertFalse(result["core_shadow_0b_authorized"])

    def test_hash_or_artifact_binding_tamper_fails_closed(self):
        temp, root, objs, manifest = self.build()
        self.addCleanup(temp.cleanup)
        manifest = deepcopy(manifest)
        manifest["file_sha256"]["core_shadow_0a1_evidence.json"] = "0" * 64
        with self.assertRaisesRegex(FormalAcceptanceError, "artifact_file_hash_mismatch"):
            self.call(root, objs, manifest)

    def test_failed_golden_or_authority_creep_fails_closed(self):
        temp, root, objs, manifest = self.build()
        self.addCleanup(temp.cleanup)
        bad = deepcopy(objs)
        bad["core_shadow_0a1_acceptance.json"]["tests"][7]["pass"] = False
        with self.assertRaisesRegex(FormalAcceptanceError, "acceptance_has_failed_test"):
            self.call(root, bad, manifest)
        bad = deepcopy(objs)
        bad["core_shadow_0a1_authority_surface.json"]["external_effect_interfaces"] = ["send_message"]
        with self.assertRaisesRegex(FormalAcceptanceError, "authority_surface_not_empty"):
            self.call(root, bad, manifest)

    def test_local_close_cannot_be_rewritten_as_composite_close(self):
        temp, root, objs, manifest = self.build()
        self.addCleanup(temp.cleanup)
        bad = deepcopy(objs)
        bad["core_shadow_0a1_evidence.json"]["observations"]["composite_at_peter_close"] = "CLOSED"
        with self.assertRaisesRegex(FormalAcceptanceError, "local_close_orphan_guard_unproven"):
            self.call(root, bad, manifest)


if __name__ == "__main__":
    unittest.main()
