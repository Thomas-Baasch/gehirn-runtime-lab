from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "continuity" / "rp001_projection.py"
SPEC = importlib.util.spec_from_file_location("rp001_projection", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def rp_payload(**changes):
    payload = {
        "contract_version": "rp-001.v1",
        "project_id": "EXTERNAL-BRAIN",
        "home_system": "EXTERNAL_BRAIN",
        "authoritative_status_ref": "github:issue:21",
        "current_work_id": "EXTERNAL-BRAIN-PHASE-C",
        "work_state": "NEXT_CONTRACT_FROZEN",
        "continuation_policy": "AUTONOMOUS_EXPECTED",
        "owner_gate": "NONE",
        "next_contract_ref": "drive:phase-c-contract",
        "next_meaningful_step": "Phase C truth-aware answer set",
        "last_progress_evidence": ["drive:phase-c-contract#frozen"],
        "active_run_refs": [],
        "source_health": "FRESH",
        "observed_at": "2026-08-21T19:18:00Z",
        "checked_at": "2026-08-21T19:19:00Z",
        "classifier_version": "external-brain-rp001-reader-v1",
        "scope": "PROJECT_CONTINUITY",
        "purpose": "STATUS_PROJECTION_ONLY",
        "sensitivity": "INTERNAL",
        "blocked_reason": None,
        "decision_ref": None,
        "supersedes_contract_ref": None,
    }
    payload.update(changes)
    return payload


class RP001ExternalBrainProjectionTests(unittest.TestCase):
    def test_independent_reader_accepts_rp001_required_fields(self):
        projection = mod.read_rp001(rp_payload())
        self.assertEqual(projection.contract_version, "rp-001.v1")
        self.assertEqual(projection.home_system, "EXTERNAL_BRAIN")
        self.assertEqual(projection.state(), mod.ProjectionState.CONTINUATION_CANDIDATE)

    def test_projection_is_hard_read_only(self):
        projection = mod.read_rp001(rp_payload())
        view = projection.as_owner_view()
        self.assertFalse(view["writer_authority"])
        self.assertFalse(view["canon_write_authority"])
        self.assertFalse(view["dispatch_authority"])
        self.assertFalse(projection.writer_authority)
        self.assertFalse(projection.canon_write_authority)
        self.assertFalse(projection.dispatch_authority)

    def test_frozen_overrides_stale_source(self):
        projection = mod.read_rp001(rp_payload(
            continuation_policy="FROZEN",
            source_health="STALE",
            next_contract_ref=None,
            next_meaningful_step=None,
            last_progress_evidence=[],
        ))
        self.assertEqual(projection.state(), mod.ProjectionState.EXPECTED_FROZEN)

    def test_unknown_stale_unreachable_are_degraded(self):
        for source_health in ("UNKNOWN", "STALE", "UNREACHABLE"):
            with self.subTest(source_health=source_health):
                projection = mod.read_rp001(rp_payload(source_health=source_health))
                self.assertEqual(projection.state(), mod.ProjectionState.DEGRADED_SOURCE)

    def test_active_run_prevents_continuation_candidate(self):
        projection = mod.read_rp001(rp_payload(active_run_refs=["github-run:123"]))
        self.assertEqual(projection.state(), mod.ProjectionState.ACTIVE_RUN)

    def test_owner_required_projects_to_k2(self):
        projection = mod.read_rp001(rp_payload(continuation_policy="OWNER_REQUIRED", owner_gate="K2"))
        self.assertEqual(projection.state(), mod.ProjectionState.OWNER_DECISION_K2)
        self.assertFalse(projection.dispatch_authority)

    def test_owner_required_without_real_gate_fails_closed_like_peter(self):
        for owner_gate in ("NONE", "NO", "FALSE"):
            with self.subTest(owner_gate=owner_gate):
                with self.assertRaisesRegex(mod.ProjectionError, "owner_required_without_owner_gate"):
                    mod.read_rp001(rp_payload(continuation_policy="OWNER_REQUIRED", owner_gate=owner_gate))

    def test_blank_optional_reference_fails_closed_like_peter(self):
        with self.assertRaisesRegex(mod.ProjectionError, "next_contract_ref_must_be_non_blank_or_null"):
            mod.read_rp001(rp_payload(next_contract_ref=" "))

    def test_parked_and_manual_do_not_become_recovery_candidates(self):
        for policy in ("PARKED", "MANUAL_ON_DEMAND"):
            with self.subTest(policy=policy):
                projection = mod.read_rp001(rp_payload(continuation_policy=policy))
                self.assertEqual(projection.state(), mod.ProjectionState.MANUAL_OR_PARKED)

    def test_waiting_expected_is_correct_wait_not_stall(self):
        projection = mod.read_rp001(rp_payload(continuation_policy="WAITING_EXPECTED", source_health="STALE"))
        self.assertEqual(projection.state(), mod.ProjectionState.WAITING_CORRECT)

    def test_source_conflict_is_visible(self):
        projection = mod.read_rp001(rp_payload(source_health="CONFLICT"))
        self.assertEqual(projection.state(), mod.ProjectionState.SOURCE_CONFLICT)

    def test_unknown_version_fails_closed(self):
        with self.assertRaises(mod.ProjectionError):
            mod.read_rp001(rp_payload(contract_version="rp-002.future"))

    def test_peter_common_golden_matrix_has_semantic_equivalence(self):
        fixture = json.loads((ROOT / "continuity" / "rp001-peter-common-golden.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["fixture_version"], "rp-001.cross-system-common.v1")
        self.assertEqual(fixture["source"]["repository"], "Thomas-Baasch/peter-system-code")
        self.assertEqual(fixture["source"]["commit"], "c895f8745b3d7285da5eb7c1af896680903fd681")
        self.assertEqual(fixture["source"]["test_blob_sha"], "3511a0146e2716f091ea4979bfe8ef49491b9b8f")
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                projection = mod.read_rp001(rp_payload(**case["changes"]))
                self.assertEqual(projection.state().value, case["expected_classification"])

    def test_peter_only_semantics_are_not_silently_claimed_by_projection(self):
        fixture = json.loads((ROOT / "continuity" / "rp001-peter-common-golden.v1.json").read_text(encoding="utf-8"))
        peter_only = fixture["role_boundary"]["peter_only"]
        self.assertEqual(len(peter_only), 3)
        self.assertTrue(any(item.startswith("C-05") for item in peter_only))
        self.assertTrue(any(item.startswith("C-08") for item in peter_only))
        self.assertTrue(any(item.startswith("C-12") for item in peter_only))

    def test_current_brain_contract_maps_to_rp001_without_modifying_source(self):
        path = ROOT / "continuity" / "brain-continuity-contract.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        before = json.dumps(payload, sort_keys=True)
        projection = mod.adapt_existing_brain_contract(
            payload,
            observed_at="2026-08-21T19:18:00Z",
            checked_at="2026-08-21T19:19:00Z",
            source_health="FRESH",
            active_run_refs=(),
        )
        after = json.dumps(payload, sort_keys=True)
        self.assertEqual(before, after)
        self.assertEqual(projection.continuation_policy, "AUTONOMOUS_EXPECTED")
        self.assertEqual(projection.authoritative_status_ref, "github:issue:21")
        self.assertEqual(projection.next_contract_ref, "drive:1sF5t2XKJJywjuaRMfaUKodUR_OAwGuZfybstXeqitM8")
        self.assertEqual(projection.state(), mod.ProjectionState.CONTINUATION_CANDIDATE)
        self.assertFalse(projection.dispatch_authority)

    def test_current_brain_contract_unsafe_rights_fail_closed(self):
        payload = json.loads((ROOT / "continuity" / "brain-continuity-contract.json").read_text(encoding="utf-8"))
        payload["rights"]["dispatch_workflow"] = True
        with self.assertRaises(mod.ProjectionError):
            mod.adapt_existing_brain_contract(
                payload,
                observed_at="2026-08-21T19:18:00Z",
                checked_at="2026-08-21T19:19:00Z",
            )

    def test_unmappable_legacy_policy_fails_closed(self):
        payload = json.loads((ROOT / "continuity" / "brain-continuity-contract.json").read_text(encoding="utf-8"))
        payload["continuation_policy"] = "SOMETHING_UNKNOWN"
        with self.assertRaises(mod.ProjectionError):
            mod.adapt_existing_brain_contract(
                payload,
                observed_at="2026-08-21T19:18:00Z",
                checked_at="2026-08-21T19:19:00Z",
            )

    def test_existing_supervisor_contract_file_remains_unchanged_by_reader(self):
        path = ROOT / "continuity" / "brain-continuity-contract.json"
        original = path.read_bytes()
        payload = json.loads(original.decode("utf-8"))
        mod.adapt_existing_brain_contract(
            payload,
            observed_at="2026-08-21T19:18:00Z",
            checked_at="2026-08-21T19:19:00Z",
        )
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
