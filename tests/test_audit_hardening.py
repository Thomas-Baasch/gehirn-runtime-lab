"""Offline regressions for the 2026-11-12 code inventory counterexamples."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from critical.durable_continuation_ledger_v1_gate import item
from critical.m5_durable_single_pilot_authorization_consumption_v1_gate import bundle
from critical.m5_github_actions_run_evidence_adapter_v1_gate import intent, raw_run
from continuity.brain_continuity_supervisor import CommitObservation, ContinuityState, evaluate, load_contract
from governance.downstream_reconciliation import DownstreamEvidence, DownstreamReconciler, ReconcileStatus
from governance.durable_continuation_ledger import DurableContinuationLedger, DurableSafeContinuationExecutor
from governance.durable_single_pilot_authorization_consumption import ConsumptionStatus, DurableSinglePilotAuthorizationConsumptionLedger
from governance.github_actions_run_evidence import AdapterStatus, GitHubActionsRunEvidenceAdapter
from governance.m4_single_pilot_authority_boundary import validate_single_pilot_authority
from governance.safe_continuation_executor import NoEffectDispatchError, SafeContinuationExecutor


class AuditHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_authority_changed_target_is_blocked_before_insert(self):
        i, p, g, d, now = bundle(101)
        changed = replace(i, target="OTHER", expected_repository="synthetic/other")
        ledger = DurableSinglePilotAuthorizationConsumptionLedger(self.root / "authority.sqlite")
        result = ledger.claim(changed, g, d, as_of=now)
        self.assertEqual(result.status, ConsumptionStatus.AUTHORITY_BLOCKED)
        self.assertIsNone(ledger.state(g.grant_id))

    def test_stale_authority_cannot_outlive_preflight_or_source_freshness(self):
        i, p, g, d, now = bundle(102)
        ledger = DurableSinglePilotAuthorizationConsumptionLedger(self.root / "stale.sqlite")
        self.assertEqual(ledger.claim(i, g, d, as_of=now + timedelta(minutes=14)).status, ConsumptionStatus.AUTHORITY_BLOCKED)
        self.assertIsNone(ledger.state(g.grant_id))

    def test_changed_grant_evidence_cannot_reuse_decision(self):
        i, p, g, d, now = bundle(103)
        changed = replace(g, source_evidence_sha256="a" * 64)
        self.assertTrue(validate_single_pilot_authority(i, p, changed, as_of=now).valid)
        ledger = DurableSinglePilotAuthorizationConsumptionLedger(self.root / "changed.sqlite")
        self.assertEqual(ledger.claim(i, changed, d, as_of=now).status, ConsumptionStatus.AUTHORITY_BLOCKED)

    def test_unbound_legacy_decision_is_blocked(self):
        i, p, g, d, now = bundle(104)
        ledger = DurableSinglePilotAuthorizationConsumptionLedger(self.root / "unbound.sqlite")
        self.assertEqual(ledger.claim(i, g, replace(d, evidence_sha256=None, checked_preflight=None), as_of=now).status, ConsumptionStatus.AUTHORITY_BLOCKED)

    def test_authority_claim_cannot_precede_validation_time(self):
        i, p, g, d, now = bundle(105)
        ledger = DurableSinglePilotAuthorizationConsumptionLedger(self.root / "past.sqlite")
        self.assertEqual(ledger.claim(i, g, d, as_of=now - timedelta(seconds=1)).status, ConsumptionStatus.AUTHORITY_BLOCKED)

    def test_revocation_flag_and_workflow_id_are_strict_types(self):
        i, p, g, d, now = bundle(106)
        for changes in ({"revoked": "false"}, {"revoked": 0}, {"expected_workflow_id": float(g.expected_workflow_id)}):
            with self.subTest(changes=changes):
                self.assertFalse(validate_single_pilot_authority(i, p, replace(g, **changes), as_of=now).valid)

    def test_same_scope_fresh_authority_still_claims_once(self):
        i, p, g, d, now = bundle(107)
        ledger = DurableSinglePilotAuthorizationConsumptionLedger(self.root / "valid.sqlite")
        self.assertEqual(ledger.claim(i, g, d, as_of=now).status, ConsumptionStatus.CLAIMED_NEW)
        self.assertEqual(ledger.claim(i, g, d, as_of=now).status, ConsumptionStatus.RECONCILE_REQUIRED)

    def test_wrong_work_or_home_cannot_reuse_retryable_key(self):
        first = item("shared", work_id="A", home_system="HOME_A")
        ledger = DurableContinuationLedger(self.root / "scope.sqlite")
        claim = ledger.claim(first)
        ledger.mark_failure(first, "proved no effect", claim_token=claim.claim_token)
        callbacks = []
        result = DurableSafeContinuationExecutor(ledger, lambda w: callbacks.append(w.work_id) or True).execute(replace(first, work_id="B", home_system="HOME_B"))
        self.assertEqual(result.outcome, "FAIL_CLOSED_LEDGER_SCOPE")
        self.assertEqual(callbacks, [])
        self.assertEqual(ledger.state(first.dedupe_key).attempt_count, 1)

    def test_changed_permission_scope_cannot_reuse_key(self):
        w = item("permissions")
        ledger = DurableContinuationLedger(self.root / "permissions.sqlite")
        ledger.claim(w)
        changed = replace(w, requested_permissions=frozenset(), minimum_permissions=frozenset())
        self.assertEqual(ledger.claim(changed).status, "SCOPE_CONFLICT_BLOCKED")

    def test_wrong_scope_cannot_complete_owned_token(self):
        w = item("owner")
        ledger = DurableContinuationLedger(self.root / "owner.sqlite")
        claim = ledger.claim(w)
        with self.assertRaisesRegex(RuntimeError, "owner_or_scope_mismatch"):
            ledger.mark_success(replace(w, work_id="other"), claim_token=claim.claim_token)
        self.assertEqual(ledger.state(w.dedupe_key).status, "CLAIMED")

    def test_competing_instance_cannot_complete_without_token(self):
        w = item("competitor")
        ledger = DurableContinuationLedger(self.root / "competitor.sqlite")
        claim = ledger.claim(w)
        other = DurableContinuationLedger(self.root / "competitor.sqlite")
        self.assertIsNone(other.claim(w).claim_token)
        with self.assertRaisesRegex(RuntimeError, "owner_or_scope_mismatch"):
            other.mark_failure(w, "false failure", claim_token="not-the-owner")
        ledger.mark_success(w, claim_token=claim.claim_token)
        self.assertEqual(ledger.state(w.dedupe_key).status, "SUCCEEDED")

    def test_previous_attempt_token_cannot_complete_new_attempt(self):
        w = item("attempt")
        ledger = DurableContinuationLedger(self.root / "attempt.sqlite")
        old = ledger.claim(w)
        ledger.mark_failure(w, "proved no effect", claim_token=old.claim_token)
        current = ledger.claim(w)
        self.assertNotEqual(old.claim_token, current.claim_token)
        with self.assertRaisesRegex(RuntimeError, "owner_or_scope_mismatch"):
            ledger.mark_success(w, claim_token=old.claim_token)
        ledger.mark_success(w, claim_token=current.claim_token)

    def test_generic_timeout_after_effect_cannot_repeat_across_restart(self):
        effects = []
        def uncertain(w):
            effects.append(w.dedupe_key)
            raise TimeoutError("synthetic timeout after effect")
        w = item("timeout")
        path = self.root / "timeout.sqlite"
        first = DurableSafeContinuationExecutor(DurableContinuationLedger(path), uncertain).execute(w)
        second = DurableSafeContinuationExecutor(DurableContinuationLedger(path), uncertain).execute(w)
        self.assertEqual([first.outcome, second.outcome], ["RECONCILE_REQUIRED"] * 2)
        self.assertEqual(effects, [w.dedupe_key])

    def test_false_or_truthy_nonbool_return_does_not_prove_success_or_no_effect(self):
        for n, value in enumerate((False, None, "true", 1)):
            with self.subTest(value=value):
                calls = []
                w = item(f"return-{n}")
                ledger = DurableContinuationLedger(self.root / f"return-{n}.sqlite")
                executor = DurableSafeContinuationExecutor(ledger, lambda w: calls.append(w.dedupe_key) or value)
                self.assertEqual(executor.execute(w).outcome, "RECONCILE_REQUIRED")
                self.assertEqual(executor.execute(w).outcome, "RECONCILE_REQUIRED")
                self.assertEqual(len(calls), 1)

    def test_proven_no_effect_allows_one_new_owned_attempt(self):
        calls = []
        def callback(w):
            calls.append(w.dedupe_key)
            if len(calls) == 1:
                raise NoEffectDispatchError("synthetic rejection before effect")
            return True
        w = item("safe-retry")
        ledger = DurableContinuationLedger(self.root / "safe-retry.sqlite")
        executor = DurableSafeContinuationExecutor(ledger, callback)
        self.assertEqual(executor.execute(w).outcome, "DISPATCH_FAILED_RETRYABLE")
        self.assertEqual(executor.execute(w).outcome, "DISPATCH_CONTINUE")
        self.assertEqual(executor.execute(w).outcome, "NOOP_DUPLICATE")
        self.assertEqual(len(calls), 2)

    def test_in_memory_executor_also_blocks_unknown_effect_retry(self):
        calls = []
        def callback(w):
            calls.append(w.dedupe_key)
            raise TimeoutError("effect uncertain")
        executor = SafeContinuationExecutor(callback)
        w = item("memory")
        self.assertEqual(executor.execute(w).outcome, "RECONCILE_REQUIRED")
        self.assertEqual(executor.execute(w).outcome, "RECONCILE_REQUIRED")
        self.assertEqual(len(calls), 1)

    def test_success_cannot_be_downgraded_by_late_reconcile_request(self):
        w = item("done")
        ledger = DurableContinuationLedger(self.root / "done.sqlite")
        claim = ledger.claim(w)
        ledger.mark_success(w, claim_token=claim.claim_token)
        self.assertFalse(ledger.mark_reconcile_required(w, "late unproven report", claim_token=claim.claim_token))
        self.assertEqual(ledger.state(w.dedupe_key).status, "SUCCEEDED")

    def test_legacy_rows_are_preserved_but_not_retried_without_scope_binding(self):
        path = self.root / "legacy.sqlite"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE dispatch_claims (dedupe_key TEXT PRIMARY KEY,work_id TEXT,home_system TEXT,action_class TEXT,status TEXT,attempt_count INTEGER,retry_limit INTEGER,last_error TEXT,created_at TEXT,updated_at TEXT)")
            w = item("legacy")
            conn.execute("INSERT INTO dispatch_claims VALUES (?,?,?,?,?,1,3,NULL,'old','old')", (w.dedupe_key, w.work_id, w.home_system, w.action_class, "FAILED_RETRYABLE"))
        ledger = DurableContinuationLedger(path)
        self.assertEqual(ledger.claim(w).status, "SCOPE_CONFLICT_BLOCKED")
        self.assertEqual(ledger.state(w.dedupe_key).status, "FAILED_RETRYABLE")
        self.assertEqual(ledger.state(w.dedupe_key).attempt_count, 1)

    def test_reconciler_cannot_relabel_different_work_with_same_key(self):
        w = item("reconcile-scope")
        ledger = DurableContinuationLedger(self.root / "reconcile.sqlite")
        ledger.claim(w)
        other = replace(w, work_id="other")
        evidence = DownstreamEvidence("FRESH", other.home_system, other.work_id, other.dedupe_key, "target", "run", "SUCCEEDED", True, True, "synthetic:proof")
        result = DownstreamReconciler(ledger).reconcile(other, target="target", evidence=[evidence])
        self.assertEqual(result.status, ReconcileStatus.CONFLICT_BLOCKED)
        self.assertEqual(ledger.state(w.dedupe_key).status, "CLAIMED")

    def test_previous_attempt_failure_cannot_reopen_current_claim(self):
        w = item("attempt-evidence")
        ledger = DurableContinuationLedger(self.root / "attempt-evidence.sqlite")
        old = ledger.claim(w)
        ledger.bind_downstream_receipt(w, claim_token=old.claim_token, target="target", downstream_id="old-run", receipt_source_ref="synthetic:first-dispatch")
        ledger.mark_failure(w, "proved no effect", claim_token=old.claim_token)
        current = ledger.claim(w)
        ledger.bind_downstream_receipt(w, claim_token=current.claim_token, target="target", downstream_id="current-run", receipt_source_ref="synthetic:second-dispatch")
        evidence = DownstreamEvidence("FRESH", w.home_system, w.work_id, w.dedupe_key, "target", "old-run", "FAILED", False, False, "synthetic:first-failure")
        result = DownstreamReconciler(ledger).reconcile(w, target="target", evidence=[evidence])
        self.assertEqual(result.status, ReconcileStatus.CONFLICT_BLOCKED)
        self.assertEqual(ledger.state(w.dedupe_key).status, "CLAIMED")
        self.assertEqual(ledger.state(w.dedupe_key).attempt_count, 2)
        self.assertEqual(ledger.claim(w).status, "RECONCILE_REQUIRED")

    def test_unbound_current_attempt_cannot_borrow_old_receipt(self):
        w = item("unbound-attempt")
        ledger = DurableContinuationLedger(self.root / "unbound-attempt.sqlite")
        old = ledger.claim(w)
        ledger.bind_downstream_receipt(w, claim_token=old.claim_token, target="target", downstream_id="old-run", receipt_source_ref="synthetic:first-dispatch")
        ledger.mark_failure(w, "proved no effect", claim_token=old.claim_token)
        ledger.claim(w)
        evidence = DownstreamEvidence("FRESH", w.home_system, w.work_id, w.dedupe_key, "target", "old-run", "FAILED", False, False, "synthetic:first-failure")
        self.assertEqual(DownstreamReconciler(ledger).reconcile(w, target="target", evidence=[evidence]).status, ReconcileStatus.RECONCILE_REQUIRED)
        self.assertEqual(ledger.state(w.dedupe_key).status, "CLAIMED")

    def test_old_run_id_cannot_be_rebound_to_new_attempt(self):
        w = item("receipt-reuse")
        ledger = DurableContinuationLedger(self.root / "receipt-reuse.sqlite")
        old = ledger.claim(w)
        ledger.bind_downstream_receipt(w, claim_token=old.claim_token, target="target", downstream_id="old-run", receipt_source_ref="synthetic:dispatch")
        ledger.mark_failure(w, "proved no effect", claim_token=old.claim_token)
        current = ledger.claim(w)
        with self.assertRaisesRegex(RuntimeError, "another_attempt"):
            ledger.bind_downstream_receipt(w, claim_token=current.claim_token, target="target", downstream_id="old-run", receipt_source_ref="synthetic:dispatch")
        self.assertIsNone(ledger.state(w.dedupe_key).downstream_id)
        with self.assertRaisesRegex(RuntimeError, "owner_or_scope_mismatch"):
            ledger.bind_downstream_receipt(w, claim_token=old.claim_token, target="target", downstream_id="new-run", receipt_source_ref="synthetic:new-dispatch")

    def test_reconciler_checks_constructor_flags_before_state_change(self):
        w = item("direct-flags")
        ledger = DurableContinuationLedger(self.root / "direct-flags.sqlite")
        claim = ledger.claim(w)
        ledger.bind_downstream_receipt(w, claim_token=claim.claim_token, target="target", downstream_id="run", receipt_source_ref="synthetic:dispatch")
        ledger.mark_reconcile_required(w, "uncertain", claim_token=claim.claim_token)
        good = DownstreamEvidence("FRESH", w.home_system, w.work_id, w.dedupe_key, "target", "run", "FAILED", False, False, "synthetic:failure")
        for field in ("external_effect_possible", "external_effect_proven"):
            for value in (0, 1, "", "false", None):
                with self.subTest(field=field, value=value):
                    result = DownstreamReconciler(ledger).reconcile(w, target="target", evidence=[replace(good, **{field: value})])
                    self.assertEqual(result.status, ReconcileStatus.FAIL_CLOSED)
                    self.assertEqual(ledger.state(w.dedupe_key).status, "RECONCILE_REQUIRED")
        self.assertEqual(DownstreamReconciler(ledger).reconcile(w, target="target", evidence=[good]).status, ReconcileStatus.RECONCILED_FAILED_RETRYABLE)

    def test_claim_change_between_read_and_reconcile_write_is_blocked(self):
        w = item("reconcile-race")
        ledger = DurableContinuationLedger(self.root / "reconcile-race.sqlite")
        old = ledger.claim(w)
        ledger.bind_downstream_receipt(w, claim_token=old.claim_token, target="target", downstream_id="old-run", receipt_source_ref="synthetic:first-dispatch")
        evidence = DownstreamEvidence("FRESH", w.home_system, w.work_id, w.dedupe_key, "target", "old-run", "FAILED", False, False, "synthetic:first-failure")
        class RacingReconciler(DownstreamReconciler):
            def _set_state(self, item, **kwargs):
                self.ledger.mark_failure(item, "proved no effect", claim_token=old.claim_token)
                current = self.ledger.claim(item)
                self.ledger.bind_downstream_receipt(item, claim_token=current.claim_token, target="target", downstream_id="new-run", receipt_source_ref="synthetic:new-dispatch")
                return super()._set_state(item, **kwargs)
        result = RacingReconciler(ledger).reconcile(w, target="target", evidence=[evidence])
        self.assertEqual(result.status, ReconcileStatus.CONFLICT_BLOCKED)
        self.assertEqual(ledger.state(w.dedupe_key).status, "CLAIMED")
        self.assertEqual(ledger.state(w.dedupe_key).attempt_count, 2)
        self.assertEqual(ledger.state(w.dedupe_key).downstream_id, "new-run")

    def test_exact_current_attempt_success_still_reconciles(self):
        w = item("current-success")
        ledger = DurableContinuationLedger(self.root / "current-success.sqlite")
        claim = ledger.claim(w)
        ledger.bind_downstream_receipt(w, claim_token=claim.claim_token, target="target", downstream_id="run", receipt_source_ref="synthetic:dispatch")
        ledger.mark_reconcile_required(w, "uncertain", claim_token=claim.claim_token)
        evidence = DownstreamEvidence("FRESH", w.home_system, w.work_id, w.dedupe_key, "target", "run", "SUCCEEDED", False, False, "synthetic:success")
        result = DownstreamReconciler(ledger).reconcile(w, target="target", evidence=[evidence])
        self.assertEqual(result.status, ReconcileStatus.RECONCILED_SUCCEEDED)
        self.assertEqual(ledger.state(w.dedupe_key).status, "SUCCEEDED")

    def test_every_boolean_flag_rejects_strings_and_numbers(self):
        executor = SafeContinuationExecutor(lambda w: True)
        for flag in ("safe_internal_next", "safe_recovery", "reversible", "external_effect", "owner_gate", "stop_latch", "circuit_open"):
            for value in ("false", 0, 1, None):
                with self.subTest(flag=flag, value=value):
                    result = executor.decide(replace(item("typed"), **{flag: value}))
                    self.assertEqual(result.outcome, "FAIL_CLOSED")
                    self.assertFalse(result.dispatch)

    def test_retry_counters_reject_negative_fractional_and_bool_values(self):
        executor = SafeContinuationExecutor(lambda w: True)
        for field in ("retry_count", "retry_limit"):
            for value in (-1, 1.0, True, "3"):
                with self.subTest(field=field, value=value):
                    self.assertFalse(executor.decide(replace(item("retry-type"), **{field: value})).dispatch)

    def test_permissions_and_identity_reject_invalid_types_without_exception(self):
        executor = SafeContinuationExecutor(lambda w: True)
        for change in ({"requested_permissions": "contents:read"}, {"minimum_permissions": frozenset({1})}, {"work_id": ""}):
            self.assertEqual(executor.decide(replace(item("input"), **change)).outcome, "FAIL_CLOSED")
        self.assertEqual(executor.execute(None).outcome, "FAIL_CLOSED")

    def test_future_progress_is_unknown_and_cannot_hide_gap(self):
        contract = load_contract()
        now = contract.frozen_at + timedelta(days=1)
        future = CommitObservation(contract.progress_markers[0], now + timedelta(days=365))
        result = evaluate(contract, now=now, active_run_count=0, recent_commits=[future])
        self.assertEqual(result.state, ContinuityState.UNKNOWN)
        self.assertFalse(result.dispatch_allowed)

    def test_future_contract_is_unknown(self):
        contract = load_contract()
        result = evaluate(contract, now=contract.frozen_at - timedelta(days=1), active_run_count=0, recent_commits=[])
        self.assertEqual(result.state, ContinuityState.UNKNOWN)

    def test_small_explicit_clock_tolerance_is_preserved(self):
        contract = load_contract()
        now = contract.frozen_at + timedelta(days=1)
        commit = CommitObservation(contract.progress_markers[0], now + timedelta(seconds=30))
        self.assertEqual(evaluate(contract, now=now, active_run_count=0, recent_commits=[commit]).state, ContinuityState.PROGRESS_CONFIRMED)
        commit = replace(commit, committed_at=now + timedelta(seconds=31))
        self.assertEqual(evaluate(contract, now=now, active_run_count=0, recent_commits=[commit]).state, ContinuityState.UNKNOWN)

    def test_malformed_run_source_returns_typed_unavailable(self):
        i = intent()
        now = i.dispatch_recorded_at + timedelta(seconds=60)
        adapter = GitHubActionsRunEvidenceAdapter()
        for source in (None, [None], ["invalid"], "invalid"):
            with self.subTest(source=source):
                result = adapter.evaluate(i, source, source_fetched_at=now, as_of=now)
                self.assertEqual(result.status, AdapterStatus.SOURCE_UNAVAILABLE)

    def test_malformed_source_does_not_break_next_independent_evaluation(self):
        i = intent()
        now = i.dispatch_recorded_at + timedelta(seconds=60)
        adapter = GitHubActionsRunEvidenceAdapter()
        first = adapter.evaluate(i, [None], source_fetched_at=now, as_of=now)
        second = adapter.evaluate(i, [raw_run()], source_fetched_at=now, as_of=now)
        self.assertEqual(first.status, AdapterStatus.SOURCE_UNAVAILABLE)
        self.assertEqual(second.status, AdapterStatus.OBSERVATION_READY)

    def test_malformed_row_is_not_silently_dropped_to_assert_unique_run(self):
        i = intent()
        now = i.dispatch_recorded_at + timedelta(seconds=60)
        result = GitHubActionsRunEvidenceAdapter().evaluate(i, [raw_run(), None], source_fetched_at=now, as_of=now)
        self.assertEqual(result.status, AdapterStatus.SOURCE_UNAVAILABLE)

    def test_nested_run_status_is_typed_failure_not_hashing_exception(self):
        i = intent()
        now = i.dispatch_recorded_at + timedelta(seconds=60)
        for change in ({"status": {}}, {"conclusion": []}):
            row = raw_run()
            row.update(change)
            result = GitHubActionsRunEvidenceAdapter().evaluate(i, [row], source_fetched_at=now, as_of=now)
            self.assertEqual(result.status, AdapterStatus.FAIL_CLOSED)

    def test_interrupted_source_iterator_returns_unavailable(self):
        i = intent()
        now = i.dispatch_recorded_at + timedelta(seconds=60)
        def rows():
            yield raw_run()
            raise RuntimeError("synthetic source interruption")
        result = GitHubActionsRunEvidenceAdapter().evaluate(i, rows(), source_fetched_at=now, as_of=now)
        self.assertEqual(result.status, AdapterStatus.SOURCE_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
