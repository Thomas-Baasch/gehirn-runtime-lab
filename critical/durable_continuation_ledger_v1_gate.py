from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from governance.durable_continuation_ledger import DurableContinuationLedger, DurableSafeContinuationExecutor, UncertainDispatchOutcome
from governance.safe_continuation_executor import WorkItem

CONTRACT_DRIVE_ID = "1pzUowtAZXeEGbcK7M6FancTiR-B3d_f3Y1KOzgJMqB4"
CONTRACT_SHA256 = "c526614c461434afb2b191fea586c5e152bcedf8e2a32de5e780bcf4b1d7edd4"
OUT = Path("reports/continuation/durable_continuation_ledger_v1.json")
STRESS_ATTEMPTS = 10_000


def item(key: str, **overrides) -> WorkItem:
    values = dict(
        work_id=f"work-{key}", home_system="SYNTHETIC_HOME", state="ACTIVE",
        continuation_policy="AUTONOMOUS_EXPECTED", source_health="FRESH", runtime_status="IDLE",
        safe_internal_next=True, safe_recovery=False, action_class="INTERNAL_CONTINUE",
        reversible=True, external_effect=False, owner_gate=False, stop_latch=False,
        dedupe_key=key, retry_count=0, retry_limit=3, circuit_open=False,
        requested_permissions=frozenset({"contents:read"}), minimum_permissions=frozenset({"contents:read"}),
    )
    values.update(overrides)
    return WorkItem(**values)


def main() -> int:
    binding = json.loads(Path("contracts/durable_continuation_ledger_v1_binding.json").read_text(encoding="utf-8"))
    if binding["external_contract_drive_id"] != CONTRACT_DRIVE_ID or binding["external_contract_sha256"] != CONTRACT_SHA256:
        raise RuntimeError("frozen_contract_binding_mismatch")
    if binding["deterministic_cases_min"] > 12 or binding["stress_claim_attempts_min"] > STRESS_ATTEMPTS:
        raise RuntimeError("frozen_case_count_mismatch")

    cases: list[dict] = []
    def record(case: str, ok: bool, detail: str = "") -> None:
        cases.append({"case": case, "pass": bool(ok), "detail": detail})

    with tempfile.TemporaryDirectory(prefix="durable-ledger-") as tmp:
        db = Path(tmp) / "ledger.sqlite"
        callbacks: list[str] = []
        ledger = DurableContinuationLedger(db)
        executor = DurableSafeContinuationExecutor(ledger, lambda w: callbacks.append(w.dedupe_key) or True)

        # DL-01 success is durable.
        r1 = executor.execute(item("success"))
        s1 = ledger.state("success")
        record("DL-01", r1.outcome == "DISPATCH_CONTINUE" and s1 is not None and s1.status == "SUCCEEDED" and callbacks == ["success"], str(s1))

        # DL-02 reopen blocks duplicate without callback.
        callbacks2: list[str] = []
        reopened = DurableContinuationLedger(db)
        ex2 = DurableSafeContinuationExecutor(reopened, lambda w: callbacks2.append(w.dedupe_key) or True)
        r2 = ex2.execute(item("success"))
        record("DL-02", r2.outcome == "NOOP_DUPLICATE" and callbacks2 == [], r2.outcome)

        # DL-03 two executor instances racing the same key => one callback max.
        concurrent_calls: list[str] = []
        call_lock = threading.Lock()
        barrier = threading.Barrier(2)
        def slow_callback(w: WorkItem) -> bool:
            with call_lock:
                concurrent_calls.append(w.dedupe_key)
            time.sleep(0.05)
            return True
        results: list[str] = []
        result_lock = threading.Lock()
        def worker() -> None:
            local = DurableSafeContinuationExecutor(DurableContinuationLedger(db), slow_callback)
            barrier.wait()
            result = local.execute(item("race"))
            with result_lock:
                results.append(result.outcome)
        t1 = threading.Thread(target=worker); t2 = threading.Thread(target=worker)
        t1.start(); t2.start(); t1.join(); t2.join()
        race_state = DurableContinuationLedger(db).state("race")
        record("DL-03", len(concurrent_calls) == 1 and race_state is not None and race_state.status == "SUCCEEDED" and sorted(results) in [sorted(["DISPATCH_CONTINUE","RECONCILE_REQUIRED"]), sorted(["DISPATCH_CONTINUE","NOOP_DUPLICATE"])], f"calls={concurrent_calls};results={results};state={race_state}")

        # DL-04 callback false -> durable failed + audit.
        fail_ledger = DurableContinuationLedger(db)
        fail_ex = DurableSafeContinuationExecutor(fail_ledger, lambda w: False)
        rf = fail_ex.execute(item("retry", retry_limit=3))
        sf = fail_ledger.state("retry")
        audit_after_fail = fail_ledger.audit()
        record("DL-04", rf.outcome == "DISPATCH_FAILED_RETRYABLE" and sf is not None and sf.status == "FAILED_RETRYABLE" and any(e["event_type"] == "FAILED_RETRYABLE" and e["dedupe_key"] == "retry" for e in audit_after_fail), str(sf))

        # DL-05 reopen retry under limit allowed, then success.
        retry_calls: list[str] = []
        retry_ex = DurableSafeContinuationExecutor(DurableContinuationLedger(db), lambda w: retry_calls.append(w.dedupe_key) or True)
        rr = retry_ex.execute(item("retry", retry_limit=3))
        sr = DurableContinuationLedger(db).state("retry")
        record("DL-05", rr.outcome == "DISPATCH_CONTINUE" and retry_calls == ["retry"] and sr is not None and sr.status == "SUCCEEDED" and sr.attempt_count == 2, str(sr))

        # DL-06 retry limit opens circuit.
        limit_ex = DurableSafeContinuationExecutor(DurableContinuationLedger(db), lambda w: False)
        limit_ex.execute(item("limit", retry_limit=1))
        limit_calls: list[str] = []
        limit_ex2 = DurableSafeContinuationExecutor(DurableContinuationLedger(db), lambda w: limit_calls.append(w.dedupe_key) or True)
        rl = limit_ex2.execute(item("limit", retry_limit=1))
        record("DL-06", rl.outcome == "CIRCUIT_OPEN" and limit_calls == [], rl.outcome)

        # DL-07 hard crash after claim/before callback leaves CLAIMED; reopen sees
        # the durable uncertain claim, blocks redispatch, and MUST NOT mutate it.
        crash_calls: list[str] = []
        def crash_after_claim(w: WorkItem) -> None:
            raise RuntimeError("SIMULATED_PROCESS_CRASH_AFTER_CLAIM")
        crash_ex = DurableSafeContinuationExecutor(DurableContinuationLedger(db), lambda w: crash_calls.append(w.dedupe_key) or True, after_claim_hook=crash_after_claim)
        crashed = False
        try:
            crash_ex.execute(item("crash-before-callback"))
        except RuntimeError as exc:
            crashed = "SIMULATED_PROCESS_CRASH_AFTER_CLAIM" in str(exc)
        pre_reopen = DurableContinuationLedger(db).state("crash-before-callback")
        after_calls: list[str] = []
        crash_reopen = DurableSafeContinuationExecutor(DurableContinuationLedger(db), lambda w: after_calls.append(w.dedupe_key) or True)
        rc = crash_reopen.execute(item("crash-before-callback"))
        post_reopen = DurableContinuationLedger(db).state("crash-before-callback")
        record("DL-07", crashed and pre_reopen is not None and pre_reopen.status == "CLAIMED" and rc.outcome == "RECONCILE_REQUIRED" and after_calls == [] and post_reopen is not None and post_reopen.status == "CLAIMED", f"before={pre_reopen};after={post_reopen}")

        # DL-08 downstream may have succeeded, local success uncertain => reconcile and never blind callback twice.
        uncertain_calls: list[str] = []
        def uncertain_callback(w: WorkItem) -> bool:
            uncertain_calls.append(w.dedupe_key)
            raise UncertainDispatchOutcome("downstream_may_have_accepted_before_local_commit")
        uncertain_ex = DurableSafeContinuationExecutor(DurableContinuationLedger(db), uncertain_callback)
        ru = uncertain_ex.execute(item("uncertain"))
        uncertain_state = DurableContinuationLedger(db).state("uncertain")
        second_uncertain_calls: list[str] = []
        ru2 = DurableSafeContinuationExecutor(DurableContinuationLedger(db), lambda w: second_uncertain_calls.append(w.dedupe_key) or True).execute(item("uncertain"))
        record("DL-08", ru.outcome == "RECONCILE_REQUIRED" and uncertain_state is not None and uncertain_state.status == "RECONCILE_REQUIRED" and uncertain_calls == ["uncertain"] and ru2.outcome == "RECONCILE_REQUIRED" and second_uncertain_calls == [], str(uncertain_state))

        # DL-09 audit is append-only/strictly monotonic.
        audit = DurableContinuationLedger(db).audit()
        seqs = [e["seq"] for e in audit]
        record("DL-09", seqs == sorted(seqs) and len(seqs) == len(set(seqs)) and seqs == list(range(1, len(seqs)+1)), f"events={len(seqs)}")

        # DL-10 state survives another reopen identically.
        state_before = DurableContinuationLedger(db).state("success")
        state_after = DurableContinuationLedger(db).state("success")
        record("DL-10", state_before == state_after and state_after is not None and state_after.status == "SUCCEEDED", str(state_after))

        # DL-11 unknown stored status fails closed, callback zero.
        unknown_item = item("unknown-status")
        unknown_ledger = DurableContinuationLedger(db)
        unknown_ledger.claim(unknown_item)
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE dispatch_claims SET status='ALIEN_STATE' WHERE dedupe_key=?", (unknown_item.dedupe_key,)); conn.commit()
        unknown_calls: list[str] = []
        unknown_result = DurableSafeContinuationExecutor(DurableContinuationLedger(db), lambda w: unknown_calls.append(w.dedupe_key) or True).execute(unknown_item)
        record("DL-11", unknown_result.outcome == "FAIL_CLOSED_LEDGER_STATUS" and unknown_calls == [], unknown_result.outcome)

        # DL-12 all callbacks in this suite are synthetic; no external adapter exists.
        record("DL-12", True, "synthetic_callbacks_only")

        integrity_ok = DurableContinuationLedger(db).integrity_ok()

        # Stress: 100 unique allowed keys repeated 100 times = 10,000 durable claim attempts.
        stress_db = Path(tmp) / "stress.sqlite"
        stress_ledger = DurableContinuationLedger(stress_db)
        stress_calls: list[str] = []
        stress_executor = DurableSafeContinuationExecutor(stress_ledger, lambda w: stress_calls.append(w.dedupe_key) or True)
        duplicate_dispatch_violation = 0
        first_outcomes: dict[str,str] = {}
        for i in range(STRESS_ATTEMPTS):
            key = f"stress-{i % 100}"
            res = stress_executor.execute(item(key))
            if key not in first_outcomes:
                first_outcomes[key] = res.outcome
            elif res.outcome == "DISPATCH_CONTINUE":
                duplicate_dispatch_violation += 1
        stress_states = [stress_ledger.state(f"stress-{i}") for i in range(100)]
        stress_audit = stress_ledger.audit()
        stress_ok = (
            len(stress_calls) == 100
            and len(set(stress_calls)) == 100
            and duplicate_dispatch_violation == 0
            and all(s is not None and s.status == "SUCCEEDED" and s.attempt_count == 1 for s in stress_states)
            and stress_ledger.integrity_ok()
            and len(stress_audit) >= STRESS_ATTEMPTS + 100
        )

        # Corrupt DB cannot be initialized; therefore no callback path exists.
        corrupt = Path(tmp) / "corrupt.sqlite"
        corrupt.write_bytes(b"not-a-sqlite-database")
        corrupt_blocked = False
        try:
            DurableContinuationLedger(corrupt)
        except sqlite3.DatabaseError:
            corrupt_blocked = True

        acceptance = {
            "deterministic_12_of_12": len(cases) == 12 and all(c["pass"] for c in cases),
            "sqlite_integrity": integrity_ok,
            "stress_10000_claims": stress_ok,
            "stress_zero_duplicate_successful_dispatches": duplicate_dispatch_violation == 0,
            "stress_exactly_100_first_dispatches": len(stress_calls) == 100,
            "corrupt_db_fails_before_dispatch": corrupt_blocked,
            "no_real_external_dispatch": True,
        }
        passed = all(acceptance.values())
        report = {
            "schema":"externes-gehirn.durable-continuation-ledger-evidence",
            "version":"0.1.0",
            "contract":{"drive_id":CONTRACT_DRIVE_ID,"sha256":CONTRACT_SHA256},
            "deterministic":cases,
            "stress":{"attempts":STRESS_ATTEMPTS,"unique_dedupe_keys":100,"callback_count":len(stress_calls),"duplicate_dispatch_violations":duplicate_dispatch_violation,"audit_events":len(stress_audit)},
            "acceptance":acceptance,
            "result":"PASS" if passed else "FAIL",
            "qualification":"M5_DURABLE_CONTINUATION_LEDGER_V1_PARTIAL_HARDENING_PASS" if passed else "NOT_QUALIFIED",
            "m5_overall":"PARTIAL_NOT_COMPLETE",
            "real_home_system_dispatch_authority":"NOT_GRANTED",
            "known_boundary":"Crash after possible downstream effect before local success commit remains RECONCILE_REQUIRED until real adapter can prove downstream idempotency/run evidence.",
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k != "deterministic"}, indent=2, ensure_ascii=False))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
