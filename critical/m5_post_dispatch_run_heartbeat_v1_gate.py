from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.post_dispatch_verification import (
    DispatchReceipt,
    PostDispatchRunVerifier,
    RunObservation,
    VerificationStatus,
    parse_dispatch_receipt,
    parse_run_observation,
)

CONTRACT_DRIVE_ID = "1-U6PFW_dPXt8TnuvgayKXHSR__ecZqdtV5Jq_Z_SZZM"
CONTRACT_SHA256 = "4d43cb3cc5a28d8f54351a23bec8b33e1cf18bc85147c96a27c8044ed1f8729f"
OUT = Path("reports/continuation/m5_post_dispatch_run_heartbeat_v1.json")
STRESS = 10_000
BASE = datetime(2026, 8, 22, 0, 0, 0, tzinfo=timezone.utc)


def receipt() -> DispatchReceipt:
    return DispatchReceipt(
        home_system="SYNTHETIC_HOME",
        work_id="work-post-dispatch-001",
        dedupe_key="dedupe-post-dispatch-001",
        target="candidate-validation-v1",
        downstream_run_id="run-424242",
        expected_head_sha="a" * 40,
        expected_workflow_fingerprint="b" * 40,
        dispatch_recorded_at=BASE,
        receipt_source_ref="synthetic:dispatch-receipt",
    )


def observation(state: str = "IN_PROGRESS", **kw) -> RunObservation:
    values = dict(
        source_health="FRESH",
        observed_at=BASE + timedelta(minutes=2),
        home_system="SYNTHETIC_HOME",
        work_id="work-post-dispatch-001",
        dedupe_key="dedupe-post-dispatch-001",
        target="candidate-validation-v1",
        downstream_run_id="run-424242",
        head_sha="a" * 40,
        workflow_fingerprint="b" * 40,
        state=state,
        run_created_at=BASE + timedelta(seconds=5),
        heartbeat_at=BASE + timedelta(minutes=1, seconds=55),
        completed_at=None,
        evidence_source_ref=f"synthetic:run:{state}",
    )
    if state in {"SUCCEEDED", "FAILED"}:
        values["heartbeat_at"] = None
        values["completed_at"] = BASE + timedelta(minutes=1, seconds=30)
    values.update(kw)
    return RunObservation(**values)


def main() -> int:
    verifier = PostDispatchRunVerifier(heartbeat_max_age_seconds=300, clock_skew_seconds=30)
    r = receipt()
    as_of = BASE + timedelta(minutes=2, seconds=10)
    cases: list[dict] = []

    def record(case_id: str, actual: VerificationStatus, expected: VerificationStatus, detail: str = "") -> None:
        cases.append({"case": case_id, "actual": actual.value, "expected": expected.value, "pass": actual is expected, "detail": detail})

    record("PH-01", verifier.verify(r, [observation("IN_PROGRESS")], as_of=as_of).status, VerificationStatus.EXACT_ACTIVE_FRESH)
    record("PH-02", verifier.verify(r, [observation("QUEUED")], as_of=as_of).status, VerificationStatus.EXACT_ACTIVE_FRESH)
    record("PH-03", verifier.verify(r, [observation("SUCCEEDED")], as_of=as_of).status, VerificationStatus.EXACT_SUCCEEDED)
    record("PH-04", verifier.verify(r, [observation("FAILED")], as_of=as_of).status, VerificationStatus.EXACT_FAILED)
    record("PH-05", verifier.verify(r, [observation(source_health="STALE")], as_of=as_of).status, VerificationStatus.SOURCE_BLOCKED)
    record("PH-06", verifier.verify(r, [observation(downstream_run_id="run-wrong")], as_of=as_of).status, VerificationStatus.IDENTITY_BLOCKED)
    record("PH-07", verifier.verify(r, [observation(head_sha="c" * 40)], as_of=as_of).status, VerificationStatus.IDENTITY_BLOCKED)
    record("PH-08", verifier.verify(r, [observation(workflow_fingerprint="d" * 40)], as_of=as_of).status, VerificationStatus.IDENTITY_BLOCKED)
    record("PH-09", verifier.verify(r, [observation(home_system="OTHER_HOME")], as_of=as_of).status, VerificationStatus.IDENTITY_BLOCKED)
    record("PH-10", verifier.verify(r, [observation(work_id="other-work")], as_of=as_of).status, VerificationStatus.IDENTITY_BLOCKED)
    record("PH-11", verifier.verify(r, [observation(target="other-target")], as_of=as_of).status, VerificationStatus.IDENTITY_BLOCKED)
    record("PH-12", verifier.verify(r, [observation(heartbeat_at=BASE + timedelta(minutes=1, seconds=55), observed_at=BASE + timedelta(minutes=10))], as_of=BASE + timedelta(minutes=10, seconds=10)).status, VerificationStatus.HEARTBEAT_STALE)
    record("PH-13", verifier.verify(r, [observation(heartbeat_at=None)], as_of=as_of).status, VerificationStatus.HEARTBEAT_STALE)
    record("PH-14", verifier.verify(r, [observation(run_created_at=BASE - timedelta(minutes=2), heartbeat_at=BASE + timedelta(minutes=1))], as_of=as_of).status, VerificationStatus.TEMPORAL_BLOCKED)
    record("PH-15", verifier.verify(r, [observation("SUCCEEDED", completed_at=BASE + timedelta(minutes=5))], as_of=as_of).status, VerificationStatus.TEMPORAL_BLOCKED)
    same_time = BASE + timedelta(minutes=2)
    conflict = [observation("IN_PROGRESS", observed_at=same_time), observation("FAILED", observed_at=same_time, completed_at=BASE + timedelta(minutes=1, seconds=30), heartbeat_at=None)]
    record("PH-16", verifier.verify(r, conflict, as_of=as_of).status, VerificationStatus.CONFLICT_BLOCKED)
    record("PH-17", verifier.verify(r, [observation()], as_of=as_of, review_gate=True).status, VerificationStatus.OWNER_GATE_BLOCKED)
    malformed_blocked = False
    unknown_blocked = verifier.verify(r, [observation(state="MYSTERY")], as_of=as_of).status is VerificationStatus.FAIL_CLOSED
    try:
        parse_run_observation({"source_health": "FRESH"})
    except ValueError:
        malformed_blocked = True
    cases.append({"case": "PH-18", "actual": "FAIL_CLOSED" if malformed_blocked and unknown_blocked else "NOT_BLOCKED", "expected": "FAIL_CLOSED", "pass": malformed_blocked and unknown_blocked})

    # Explicit parser checks: timezone-awareness is mandatory.
    receipt_payload = {
        "home_system": r.home_system, "work_id": r.work_id, "dedupe_key": r.dedupe_key, "target": r.target,
        "downstream_run_id": r.downstream_run_id, "expected_head_sha": r.expected_head_sha,
        "expected_workflow_fingerprint": r.expected_workflow_fingerprint,
        "dispatch_recorded_at": r.dispatch_recorded_at.isoformat(), "receipt_source_ref": r.receipt_source_ref,
    }
    parser_roundtrip = parse_dispatch_receipt(receipt_payload) == r
    naive_time_blocked = False
    bad_payload = dict(receipt_payload); bad_payload["dispatch_recorded_at"] = "2026-08-22T00:00:00"
    try:
        parse_dispatch_receipt(bad_payload)
    except ValueError:
        naive_time_blocked = True

    # 10k identical read-only verifications. Immutable dataclasses must remain unchanged.
    stress_obs = observation("IN_PROGRESS")
    r_before = repr(r); o_before = repr(stress_obs)
    first = verifier.verify(r, [stress_obs], as_of=as_of)
    deterministic = True
    for _ in range(STRESS):
        current = verifier.verify(r, [stress_obs], as_of=as_of)
        if current != first or current.dispatch_executed or current.retry_executed or current.ledger_updated:
            deterministic = False
            break
    immutable = repr(r) == r_before and repr(stress_obs) == o_before
    no_dispatch_surface = not hasattr(verifier, "dispatch") and not hasattr(verifier, "execute")

    acceptance = {
        "deterministic_18_of_18": len(cases) == 18 and all(c["pass"] for c in cases),
        "stress_10000_read_only_deterministic": deterministic,
        "stress_zero_dispatch_retry_ledger_write": not first.dispatch_executed and not first.retry_executed and not first.ledger_updated,
        "immutable_inputs": immutable,
        "no_dispatch_or_execute_surface": no_dispatch_surface,
        "parser_roundtrip": parser_roundtrip,
        "timezone_naive_fail_closed": naive_time_blocked,
        "real_dispatch_authority_not_granted": True,
    }
    passed = all(acceptance.values())
    report = {
        "schema": "externes-gehirn.m5-post-dispatch-run-heartbeat-evidence",
        "version": "0.1.0",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256},
        "cases": cases,
        "stress": {"evaluations": STRESS, "decision": first.status.value, "dispatches": 0, "retries": 0, "ledger_writes": 0},
        "acceptance": acceptance,
        "result": "PASS" if passed else "FAIL",
        "qualification": "M5_POST_DISPATCH_RUN_HEARTBEAT_V1_PARTIAL_PASS" if passed else "NOT_QUALIFIED",
        "m4_overall": "NOT_COMPLETE",
        "m5_overall": "PARTIAL_NOT_COMPLETE",
        "real_dispatch_authority": "NOT_GRANTED",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
