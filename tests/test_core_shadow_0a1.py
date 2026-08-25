from __future__ import annotations

from copy import deepcopy
import unittest

from core_shadow_0a1 import runtime
from core_shadow_0a1.konrad_control import challenge
from core_shadow_0a1.independent_readback import evaluate as independent_readback
from critical.core_shadow_0a1_authority_gate import evaluate as authority_surface


def complete_case() -> tuple[dict, dict]:
    case = runtime.make_fixture()
    outside = runtime.request_action(case, "uschi_owner_interface", "send_message")
    unknown = runtime.authorize(case, "unknown_worker", "project_next_step")
    runtime.uschi_intake(case)
    runtime.georg_prioritize(case)
    runtime.external_brain_truth_load(case)
    runtime.peter_next_step(case)
    peter = {
        "peter_local_state": case["project_next_step"]["local_scope_state"],
        "peter_requires_owner": case["project_next_step"]["requires_owner"],
        "thomas_class_at_peter_close": case["thomas_class"],
        "composite_at_peter_close": case["composite_completion_state"],
        "open_at_peter_close": list(case["open_material_obligations"]),
    }
    proposal = runtime.propose_internal_derived_update(case)
    case["generations"]["resource"] += 1
    old = runtime.commit_internal_derived_update(case, proposal)
    revalidated = deepcopy(proposal)
    revalidated["resource_generation"] = case["generations"]["resource"]
    new = runtime.commit_internal_derived_update(case, revalidated)
    case = runtime.json_roundtrip(case)
    runtime.apply_control_finding(case, challenge(case))
    runtime.external_brain_reconcile(case)
    runtime.uschi_owner_view(case)
    runtime.synthetic_owner_decision(case)
    observations = {
        **peter,
        "unknown_authority_result": unknown,
        "outside_action_result": outside,
        "old_commit_status": old["status"],
        "revalidated_commit_status": new["status"],
        "independent_readback_input_only": True,
    }
    return case, observations


class CoreShadow0A1Tests(unittest.TestCase):
    def test_georg_is_in_flow_but_has_no_owner_or_control_authority(self):
        case = runtime.make_fixture()
        runtime.uschi_intake(case)
        runtime.georg_prioritize(case)
        self.assertEqual(case["priority"]["class"], "P1_SYNTHETIC_INTEGRATION")
        self.assertIn("project_next_step", case["peter_mandate"]["allowed"])
        self.assertIn("owner_decision", case["peter_mandate"]["forbidden"])
        self.assertIn("control_override", case["peter_mandate"]["forbidden"])
        self.assertFalse(runtime.authorize(case, "georg_group_ceo", "decide")["allowed"])

    def test_local_peter_close_cannot_close_composite(self):
        case = runtime.make_fixture()
        runtime.uschi_intake(case)
        runtime.georg_prioritize(case)
        runtime.external_brain_truth_load(case)
        runtime.peter_next_step(case)
        self.assertEqual(case["project_next_step"]["local_scope_state"], "CLOSED")
        self.assertEqual(case["composite_completion_state"], "OPEN")
        self.assertIn("O5", case["open_material_obligations"])
        self.assertEqual(case["thomas_class"], "K0")

    def test_stale_commit_is_blocked_then_revalidated_internal_commit_passes(self):
        case = runtime.make_fixture()
        runtime.uschi_intake(case)
        runtime.georg_prioritize(case)
        runtime.external_brain_truth_load(case)
        runtime.peter_next_step(case)
        proposal = runtime.propose_internal_derived_update(case)
        case["generations"]["resource"] += 1
        self.assertEqual(runtime.commit_internal_derived_update(case, proposal)["status"], "BLOCKED_STALE_PRECONDITION")
        proposal["resource_generation"] = case["generations"]["resource"]
        self.assertEqual(runtime.commit_internal_derived_update(case, proposal)["status"], "COMMITTED_ISOLATED_DERIVED")

    def test_unknown_authority_and_outside_action_fail_closed(self):
        case = runtime.make_fixture()
        self.assertEqual(runtime.authorize(case, "unknown_worker", "project_next_step")["reason"], "UNKNOWN_SUBJECT")
        result = runtime.request_action(case, "uschi_owner_interface", "send_message")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "OUTSIDE_ACTION_BOUNDARY")

    def test_konrad_challenge_is_readonly_method_separate_and_visible(self):
        case = runtime.make_fixture()
        runtime.uschi_intake(case)
        runtime.georg_prioritize(case)
        runtime.external_brain_truth_load(case)
        runtime.peter_next_step(case)
        finding = challenge(case)
        self.assertEqual(finding["severity"], "MATERIAL")
        self.assertTrue(finding["read_only"])
        self.assertEqual(finding["independence_class"], "I0_METHOD_SEPARATE_CODEPATH")
        self.assertFalse(finding["requires_owner"])
        runtime.apply_control_finding(case, finding)
        runtime.external_brain_reconcile(case)
        view = runtime.uschi_owner_view(case)
        self.assertTrue(view["dissent_visible"])
        self.assertEqual(view["thomas_class"], "K2")

    def test_event_rebuild_matches_final_load_bearing_state(self):
        case, _ = complete_case()
        authority = authority_surface()
        bundle = runtime.build_evidence_bundle(case, restart_replay_equal=True, authority_surface=authority)
        rebuilt = runtime.rebuild_from_events(bundle)
        self.assertEqual(rebuilt, bundle["final_summary"])

    def test_independent_readback_rejects_manipulated_external_effect(self):
        case, observations = complete_case()
        authority = authority_surface()
        bundle = runtime.build_evidence_bundle(case, restart_replay_equal=True, authority_surface=authority)
        rebuilt = runtime.rebuild_from_events(bundle)
        observations["rebuild_summary"] = rebuilt
        observations["rebuild_equal"] = rebuilt == bundle["final_summary"]
        bundle["observations"] = observations
        baseline = independent_readback(bundle)
        self.assertEqual(baseline["status"], "PASS")
        bad = deepcopy(bundle)
        bad["external_actions_executed"] = 1
        result = independent_readback(bad)
        cs11 = next(row for row in result["tests"] if row["id"] == "CS-11")
        self.assertFalse(cs11["pass"])
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
