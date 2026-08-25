from __future__ import annotations

import unittest

from core_shadow_0b.real_case_0b01 import EXPECTED, MARKERS, derive_observation, evaluate_loop


def run_doc(run_id: int, sha: str) -> dict:
    return {"id": run_id, "head_sha": sha, "status": "completed", "conclusion": "success"}


def artifact_doc(items: list[tuple[int, str, str]]) -> dict:
    return {
        "artifacts": [
            {"id": artifact_id, "digest": digest, "expired": False, "workflow_run": {"head_sha": sha}}
            for artifact_id, digest, sha in items
        ]
    }


def bundle() -> dict:
    return {
        "issue_41": {"issue_number": 41, "title": "CORE-SHADOW 0A.1 – synthetischer Full-Role Integrationsharness", "state": "open"},
        "comments": [
            {"id": 1, "marker": MARKERS["pass"], "created_at": "2026-08-25T02:03:00Z"},
            {"id": 2, "marker": MARKERS["pause"], "created_at": "2026-08-25T02:15:35Z"},
            {"id": 3, "marker": MARKERS["firewall"], "created_at": "2026-08-25T05:02:00Z"},
        ],
        "run_0a_source": run_doc(EXPECTED["0a_source_run_id"], EXPECTED["0a_source_sha"]),
        "artifacts_0a_source": artifact_doc([(EXPECTED["0a_source_artifact_id"], EXPECTED["0a_source_artifact_digest"], EXPECTED["0a_source_sha"])]),
        "run_0a_formal": run_doc(EXPECTED["0a_formal_run_id"], EXPECTED["0a_formal_sha"]),
        "artifacts_0a_formal": artifact_doc([(EXPECTED["0a_formal_artifact_id"], EXPECTED["0a_formal_artifact_digest"], EXPECTED["0a_formal_sha"])]),
        "branch_0a": {"name": "runtime/core-shadow-0a1-001", "head_sha": EXPECTED["0a_branch_head"]},
        "run_precheck": run_doc(EXPECTED["precheck_run_id"], EXPECTED["precheck_sha"]),
        "artifacts_precheck": artifact_doc([(EXPECTED["precheck_formal_artifact_id"], EXPECTED["precheck_formal_artifact_digest"], EXPECTED["precheck_sha"])]),
        "run_firewall": run_doc(EXPECTED["firewall_run_id"], EXPECTED["firewall_sha"]),
        "artifacts_firewall": artifact_doc([
            (EXPECTED["firewall_source_artifact_id"], EXPECTED["firewall_source_artifact_digest"], EXPECTED["firewall_sha"]),
            (EXPECTED["firewall_formal_artifact_id"], EXPECTED["firewall_formal_artifact_digest"], EXPECTED["firewall_sha"]),
        ]),
    }


class CoreShadow0B01Tests(unittest.TestCase):
    def test_real_current_set_is_accepted_read_only_and_owner_k0(self) -> None:
        result = derive_observation(bundle(), "READ_ONLY")
        self.assertEqual(result["current_progression_state"], "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION")
        self.assertEqual(result["owner_attention"], "K0")
        self.assertFalse(result["owner_action_required"])
        self.assertTrue(result["action_ready"])
        self.assertEqual(result["allowed_effects"], ["READ_ONLY"])

    def test_old_pass_alone_is_not_current_promotion(self) -> None:
        b = bundle()
        b["comments"] = [b["comments"][0]]
        result = derive_observation(b, "READ_ONLY")
        self.assertEqual(result["current_progression_state"], "HISTORICAL_PASS_ONLY_NOT_CURRENTLY_PROMOTED")
        self.assertFalse(result["action_ready"])

    def test_pause_without_regression_fails_closed(self) -> None:
        b = bundle()
        b["comments"] = b["comments"][:2]
        result = derive_observation(b, "READ_ONLY")
        self.assertEqual(result["current_progression_state"], "PAUSED_FAIL_CLOSED")
        self.assertFalse(result["action_ready"])

    def test_artifact_digest_drift_fails_closed(self) -> None:
        b = bundle()
        b["artifacts_0a_formal"]["artifacts"][0]["digest"] = "sha256:DRIFT"
        result = derive_observation(b, "READ_ONLY")
        self.assertEqual(result["current_progression_state"], "NOT_PROVEN_FAIL_CLOSED")
        self.assertFalse(result["action_ready"])

    def test_read_only_pass_does_not_allow_send(self) -> None:
        result = derive_observation(bundle(), "SEND")
        self.assertEqual(result["current_progression_state"], "CURRENTLY_ACCEPTED_FOR_SYNTHETIC_SCOPE_WITH_FIREWALL_REGRESSION")
        self.assertFalse(result["action_ready"])

    def test_all_five_acceptance_loops_pass(self) -> None:
        results = [evaluate_loop(bundle(), i) for i in range(1, 6)]
        self.assertEqual([r["loop"] for r in results], [1, 2, 3, 4, 5])
        self.assertTrue(all(r["status"] == "PASS" for r in results))
        for result in results:
            self.assertTrue(all(result["checks"].values()))


if __name__ == "__main__":
    unittest.main()
