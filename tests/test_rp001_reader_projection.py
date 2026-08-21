from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity.rp001_projection import (  # noqa: E402
    CONTRACT_VERSION,
    ProjectionContractError,
    load_projection,
    project_contract,
)


FIXTURE_PATH = ROOT / "contracts" / "rp-001-peter-fixture.v1.json"
SCHEMA_PATH = ROOT / "contracts" / "rp-001-continuity-contract.schema.v1.json"
EXPECTED_FIXTURE_DIGEST = "033a062899056145a6cd7d6e95cb389b24233dac2a04137eca10fc9b28ceb693"


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class RP001ExternalBrainReaderProjectionTests(unittest.TestCase):
    def test_contract_schema_is_same_rp001_v1_shape(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "peter://rp-001/continuity-contract/v1")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["contract_version"]["const"], CONTRACT_VERSION)
        self.assertTrue(schema["x-rp001-hard-rules"]["reader_never_gets_home_system_writer_authority"])
        self.assertTrue(schema["x-rp001-hard-rules"]["continuation_candidate_is_not_dispatch"])

    def test_frozen_peter_fixture_projects_without_semantic_change(self):
        raw = fixture()
        projected = load_projection(FIXTURE_PATH)
        self.assertEqual(projected.payload, raw)
        self.assertEqual(projected.semantic_digest(), EXPECTED_FIXTURE_DIGEST)
        self.assertEqual(projected.project_id, "PETER-SELF-001")
        self.assertEqual(projected.home_system, "PETER")
        self.assertEqual(projected.current_work_id, "RP-001")

    def test_reader_projection_never_receives_writer_dispatch_or_promotion_rights(self):
        projected = load_projection(FIXTURE_PATH)
        self.assertFalse(projected.reader_writer_authority)
        self.assertFalse(projected.dispatch_allowed)
        self.assertFalse(projected.canon_promotion_allowed)

    def test_second_real_home_system_identity_uses_same_reader_shape(self):
        raw = fixture()
        raw.update({
            "project_id": "EXTERNAL-BRAIN",
            "home_system": "EXTERNAL_BRAIN",
            "authoritative_status_ref": "github:Thomas-Baasch/gehirn-runtime-lab:continuity/brain-continuity-contract.json",
            "current_work_id": "DERIVED-RETRIEVAL-PHASE-C",
            "next_contract_ref": "drive:1sF5t2XKJJywjuaRMfaUKodUR_OAwGuZfybstXeqitM8",
            "next_meaningful_step": "Keep Phase C authority in External Brain while exposing RP-001 projection only",
        })
        projected = project_contract(raw)
        self.assertEqual(projected.home_system, "EXTERNAL_BRAIN")
        self.assertEqual(projected.project_id, "EXTERNAL-BRAIN")
        self.assertFalse(projected.reader_writer_authority)
        self.assertFalse(projected.dispatch_allowed)
        self.assertFalse(projected.canon_promotion_allowed)

    def test_unknown_contract_version_fails_closed(self):
        raw = fixture()
        raw["contract_version"] = "rp-999.future"
        with self.assertRaises(ProjectionContractError):
            project_contract(raw)

    def test_missing_required_field_fails_closed(self):
        raw = fixture()
        raw.pop("authoritative_status_ref")
        with self.assertRaises(ProjectionContractError):
            project_contract(raw)

    def test_unknown_field_fails_closed(self):
        raw = fixture()
        raw["writer_authority"] = True
        with self.assertRaises(ProjectionContractError):
            project_contract(raw)

    def test_naive_timestamp_fails_closed(self):
        raw = fixture()
        raw["checked_at"] = "2026-08-21T19:20:00"
        with self.assertRaises(ProjectionContractError):
            project_contract(raw)

    def test_owner_required_must_name_real_gate(self):
        raw = fixture()
        raw["continuation_policy"] = "OWNER_REQUIRED"
        raw["owner_gate"] = "NONE"
        with self.assertRaises(ProjectionContractError):
            project_contract(raw)
        raw["owner_gate"] = "K2"
        raw["decision_ref"] = "decision:owner-42"
        projected = project_contract(raw)
        self.assertEqual(projected.owner_gate, "K2")
        self.assertFalse(projected.dispatch_allowed)

    def test_source_health_states_never_grant_authority(self):
        for state in ("FRESH", "STALE", "UNREACHABLE", "UNKNOWN", "CONFLICT"):
            with self.subTest(state=state):
                raw = fixture()
                raw["source_health"] = state
                projected = project_contract(raw)
                self.assertEqual(projected.source_health, state)
                self.assertFalse(projected.reader_writer_authority)
                self.assertFalse(projected.dispatch_allowed)

    def test_projection_does_not_import_or_replace_existing_supervisor(self):
        source = (ROOT / "continuity" / "rp001_projection.py").read_text(encoding="utf-8")
        self.assertNotIn("brain_continuity_supervisor", source)
        self.assertTrue((ROOT / "continuity" / "brain_continuity_supervisor.py").exists())
        self.assertTrue((ROOT / "continuity" / "brain-continuity-contract.json").exists())

    def test_input_mapping_is_not_mutated(self):
        raw = fixture()
        before = deepcopy(raw)
        project_contract(raw)
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()
