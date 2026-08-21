from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "continuity" / "brain_continuity_supervisor.py"
SPEC = importlib.util.spec_from_file_location("brain_continuity_supervisor", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


FROZEN = datetime(2026, 8, 21, 5, 31, tzinfo=timezone.utc)


def contract(policy="AUTONOMOUS_EXPECTED_WHEN_NEXT_CONTRACT_FROZEN"):
    return mod.Contract(
        policy=policy,
        frozen_at=FROZEN,
        progress_markers=("phase c", "truth-aware", "answer-set"),
        branch="main",
        status_issue=21,
        stale_after_seconds=900,
    )


class BrainContinuityTests(unittest.TestCase):
    def test_active_run_means_working(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
            active_run_count=1,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.WORKING)
        self.assertFalse(decision.dispatch_allowed)

    def test_matching_phase_c_commit_after_freeze_confirms_progress(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "Implement Phase C truth-aware answer-set gate",
                    datetime(2026, 8, 21, 5, 45, tzinfo=timezone.utc),
                )
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.PROGRESS_CONFIRMED)

    def test_matching_old_commit_does_not_count(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "Phase C truth-aware",
                    datetime(2026, 8, 21, 5, 30, tzinfo=timezone.utc),
                )
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.EXECUTION_GAP)

    def test_non_matching_commit_does_not_hide_gap(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "Update unrelated documentation",
                    datetime(2026, 8, 21, 5, 50, tzinfo=timezone.utc),
                )
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.EXECUTION_GAP)

    def test_first_15_minutes_are_grace(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 5, 40, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.GRACE)

    def test_exact_15_minute_boundary_is_grace(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 5, 46, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.GRACE)

    def test_after_15_minutes_without_execution_is_gap(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 5, 46, 1, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.EXECUTION_GAP)
        self.assertFalse(decision.dispatch_allowed)

    def test_parked_policy_is_expected_wait(self):
        decision = mod.evaluate(
            contract("PARKED"),
            now=datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.WAITING_EXPECTED)

    def test_manual_policy_is_expected_wait(self):
        decision = mod.evaluate(
            contract("MANUAL_ON_DEMAND"),
            now=datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.WAITING_EXPECTED)

    def test_unknown_policy_fails_closed(self):
        decision = mod.evaluate(
            contract("SOMETHING_NEW"),
            now=datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.UNKNOWN)
        self.assertFalse(decision.dispatch_allowed)

    def test_contract_load_rejects_write_rights(self):
        data = (Path(__file__).resolve().parents[1] / "continuity" / "brain-continuity-contract.json").read_text(encoding="utf-8")
        self.assertIn('"dispatch_workflow": false', data)
        self.assertIn('"merge": false', data)


if __name__ == "__main__":
    unittest.main()
