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


FROZEN = datetime(2026, 8, 21, 21, 28, tzinfo=timezone.utc)


def contract(policy="AUTONOMOUS_EXPECTED_WHEN_NEXT_CONTRACT_FROZEN"):
    return mod.Contract(
        policy=policy,
        expected_title="M4 – Realprojekt Safe-Continuation Pilot – Eligibility Contract V0.1 – 2026-08-21",
        expected_drive_id="1yMRjJQo7iGKbjvAWGZzAlrpz-JIROdLIx6HwEsdYkmU",
        frozen_at=FROZEN,
        progress_markers=("m4 eligibility", "safe-continuation", "home-system eligibility"),
        branch="main",
        status_issue=21,
        stale_after_seconds=1800,
    )


class BrainContinuityTests(unittest.TestCase):
    def test_active_run_means_working(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 22, 15, tzinfo=timezone.utc),
            active_run_count=1,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.WORKING)
        self.assertFalse(decision.dispatch_allowed)

    def test_fresh_matching_commit_confirms_progress(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 22, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "Implement M4 eligibility adapter",
                    datetime(2026, 8, 21, 21, 45, tzinfo=timezone.utc),
                )
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.PROGRESS_CONFIRMED)
        self.assertEqual(decision.reason, "fresh_matching_progress_commit")

    def test_matching_commit_before_freeze_does_not_count(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 22, 15, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "M4 eligibility old work",
                    datetime(2026, 8, 21, 21, 27, 59, tzinfo=timezone.utc),
                )
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.EXECUTION_GAP)

    def test_matching_progress_expires_after_freshness_window(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 22, 31, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "M4 eligibility adapter progress",
                    datetime(2026, 8, 21, 22, 0, tzinfo=timezone.utc),
                )
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.EXECUTION_GAP)
        self.assertEqual(decision.reason, "matching_progress_commit_stale_without_active_run")

    def test_newest_matching_commit_controls_freshness(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 22, 20, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "M4 eligibility first",
                    datetime(2026, 8, 21, 21, 30, tzinfo=timezone.utc),
                ),
                mod.CommitObservation(
                    "Home-system eligibility follow-up",
                    datetime(2026, 8, 21, 22, 5, tzinfo=timezone.utc),
                ),
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.PROGRESS_CONFIRMED)

    def test_non_matching_commit_does_not_hide_gap(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 22, 15, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[
                mod.CommitObservation(
                    "Update unrelated documentation",
                    datetime(2026, 8, 21, 22, 0, tzinfo=timezone.utc),
                )
            ],
        )
        self.assertEqual(decision.state, mod.ContinuityState.EXECUTION_GAP)

    def test_first_30_minutes_are_grace(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 21, 47, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.GRACE)

    def test_exact_30_minute_boundary_is_grace(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 21, 58, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.GRACE)

    def test_after_30_minutes_without_execution_is_gap(self):
        decision = mod.evaluate(
            contract(),
            now=datetime(2026, 8, 21, 21, 58, 1, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.EXECUTION_GAP)
        self.assertFalse(decision.dispatch_allowed)

    def test_parked_policy_is_expected_wait(self):
        decision = mod.evaluate(
            contract("PARKED"),
            now=datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.WAITING_EXPECTED)

    def test_manual_policy_is_expected_wait(self):
        decision = mod.evaluate(
            contract("MANUAL_ON_DEMAND"),
            now=datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.WAITING_EXPECTED)

    def test_unknown_policy_fails_closed(self):
        decision = mod.evaluate(
            contract("SOMETHING_NEW"),
            now=datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc),
            active_run_count=0,
            recent_commits=[],
        )
        self.assertEqual(decision.state, mod.ContinuityState.UNKNOWN)
        self.assertFalse(decision.dispatch_allowed)

    def test_status_body_uses_dynamic_current_contract(self):
        body = mod._status_body(
            mod.Decision(mod.ContinuityState.EXECUTION_GAP, "gap", 0),
            contract(),
            now=datetime(2026, 8, 21, 22, 0, tzinfo=timezone.utc),
        )
        self.assertIn("M4 – Realprojekt Safe-Continuation Pilot", body)
        self.assertIn("1yMRjJQo7iGKbjvAWGZzAlrpz-JIROdLIx6HwEsdYkmU", body)
        self.assertNotIn("Phase C – Truth-Aware Answer-Set", body)

    def test_contract_load_rejects_write_rights_and_points_to_m4(self):
        data = (Path(__file__).resolve().parents[1] / "continuity" / "brain-continuity-contract.json").read_text(encoding="utf-8")
        self.assertIn('"dispatch_workflow": false', data)
        self.assertIn('"merge": false', data)
        self.assertIn('"stale_after_seconds": 1800', data)
        self.assertIn('"version": "0.2.0"', data)
        self.assertIn('M4 – Realprojekt Safe-Continuation Pilot', data)


if __name__ == "__main__":
    unittest.main()
