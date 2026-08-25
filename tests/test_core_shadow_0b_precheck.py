from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from core_shadow_0b.precheck import build_events, generate, rebuild, restore
from critical.core_shadow_0b_precheck_formal import PrecheckFormalError, evaluate as formal_evaluate


class CoreShadow0BPrecheckTests(unittest.TestCase):
    def test_event_rebuild_is_deterministic_and_no_effect(self):
        events = build_events()
        self.assertEqual(rebuild(events), {"case_id": "CS0B-PRECHECK-001", "status": "READY_CANDIDATE", "source": "EVENT_REBUILD"})
        self.assertTrue(all(event["external_effect"] is False for event in events))

    def test_fresh_restore_deletes_derived_then_rebuilds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            generate(root, "123", "a" * 40, "runtime/core-shadow-0b-001")
            self.assertTrue((root / "derived.json").exists())
            result = restore(root)
            self.assertFalse((root / "derived.json").exists())
            self.assertTrue(result["derived_deleted_before_rebuild"])
            self.assertTrue(result["fresh_process_restore"])
            self.assertEqual(result["external_actions"], 0)
            self.assertEqual(result["new_credentials"], 0)

    def test_tampered_event_hash_fails_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            generate(root, "123", "a" * 40, "runtime/core-shadow-0b-001")
            with (root / "events.json").open("a", encoding="utf-8") as handle:
                handle.write("tamper")
            with self.assertRaisesRegex(ValueError, "artifact_hash_mismatch:events.json"):
                restore(root)

    def test_formal_evaluator_is_artifact_only_and_fails_boundary_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            generate(root, "123", "a" * 40, "runtime/core-shadow-0b-001")
            restore_result = restore(root)
            # restore deletes derived by design; recreate a source artifact copy for independent formal evaluation
            source = Path(td) / "source"
            source.mkdir()
            generate(source, "123", "a" * 40, "runtime/core-shadow-0b-001")
            authority = {
                "schema": "core-shadow-0b.precheck-authority.v1",
                "status": "PASS",
                "write_permissions": [],
                "forbidden_interfaces": [],
                "secret_references": [],
                "i1_topology_ready": True,
            }
            result = formal_evaluate(source, restore_result, authority)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["h0b07_independence"], "PASS_I1_LOGICALLY_SEPARATE_PRECHECK")
            bad = deepcopy(authority)
            bad["write_permissions"] = ["issues: write"]
            with self.assertRaisesRegex(PrecheckFormalError, "authority_surface_not_readonly"):
                formal_evaluate(source, restore_result, bad)

    def test_manifest_has_no_secret_or_real_case_content_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = generate(root, "123", "a" * 40, "runtime/core-shadow-0b-001")
            self.assertFalse(manifest["contains_real_case_data"])
            self.assertFalse(manifest["contains_personal_data"])
            self.assertFalse(manifest["contains_secrets"])
            self.assertEqual(manifest["production_writes"], 0)
            self.assertEqual(manifest["new_running_cost_eur"], 0)
            self.assertFalse(manifest["merge_authorized"])


if __name__ == "__main__":
    unittest.main()
