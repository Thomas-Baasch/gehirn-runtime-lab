from __future__ import annotations

import unittest

from core_shadow_0b.theory_practice_firewall_regression import evaluate_one, fixtures


class TheoryPracticeFirewallRegressionTests(unittest.TestCase):
    def test_five_complete_loops_pass_all_invariants(self) -> None:
        results = [evaluate_one(f) for f in fixtures()]
        self.assertEqual([r["loop"] for r in results], [1, 2, 3, 4, 5])
        for result in results:
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(set(result["invariants"]), {f"F{i}" for i in range(1, 9)})
            self.assertTrue(all(result["invariants"].values()))

    def test_theory_only_cannot_become_current_truth(self) -> None:
        result = evaluate_one(fixtures()[0])
        self.assertEqual(result["derived"]["theory_disposition"], "ADVISORY_NOT_OPERATIONAL")
        self.assertEqual(result["derived"]["current_fact"], "UNKNOWN")
        self.assertFalse(result["derived"]["operational_policy_active"])
        self.assertFalse(result["derived"]["runtime_capability_active"])
        self.assertFalse(result["derived"]["action_ready"])

    def test_current_reality_wins_and_conflict_stays_visible(self) -> None:
        result = evaluate_one(fixtures()[1])
        self.assertEqual(result["derived"]["current_fact"], "PAUSED_FAIL_CLOSED")
        self.assertTrue(result["derived"]["conflict_visible"])
        self.assertNotEqual(result["derived"]["current_fact"], fixtures()[1]["theory_claim"])

    def test_stale_source_and_derived_green_do_not_false_green(self) -> None:
        result = evaluate_one(fixtures()[2])
        self.assertEqual(result["derived"]["current_fact"], "UNKNOWN")
        self.assertFalse(result["derived"]["action_ready"] is True and fixtures()[2]["requested_effect"] not in fixtures()[2]["allowed_effects"])

    def test_generic_continue_cannot_escalate_read_only_to_send(self) -> None:
        result = evaluate_one(fixtures()[3])
        self.assertTrue(fixtures()[3]["generic_continue"])
        self.assertEqual(fixtures()[3]["allowed_effects"], ["READ_ONLY"])
        self.assertEqual(fixtures()[3]["requested_effect"], "SEND")
        self.assertFalse(result["derived"]["action_ready"])

    def test_unknown_survives_rebuild_without_live_source(self) -> None:
        result = evaluate_one(fixtures()[4])
        self.assertEqual(result["derived"]["current_fact"], "UNKNOWN")
        self.assertEqual(result["derived"]["theory_disposition"], "ADVISORY_NOT_OPERATIONAL")
        self.assertFalse(result["derived"]["action_ready"])

    def test_exact_activation_lineage_can_allow_only_exact_read_effect(self) -> None:
        f = dict(fixtures()[1])
        f["theory_claim"] = f["live_value"]
        f["requested_effect"] = "READ_ONLY"
        result = evaluate_one(f)
        self.assertTrue(result["derived"]["action_ready"])
        self.assertEqual(result["derived"]["action_effect"], "READ_ONLY")

    def test_removing_authority_blocks_even_exact_read_effect(self) -> None:
        f = dict(fixtures()[1])
        f["theory_claim"] = f["live_value"]
        f["current_authority"] = False
        f["requested_effect"] = "READ_ONLY"
        result = evaluate_one(f)
        self.assertFalse(result["derived"]["action_ready"])


if __name__ == "__main__":
    unittest.main()
