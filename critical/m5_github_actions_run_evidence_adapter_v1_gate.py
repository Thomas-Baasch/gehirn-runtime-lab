from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.github_actions_run_evidence import (
    AdapterStatus,
    GitHubActionsRunEvidenceAdapter,
    GitHubDispatchIntent,
)
from governance.post_dispatch_verification import PostDispatchRunVerifier, VerificationStatus

CONTRACT_DRIVE_ID = "1n57OAjqhnPpT7ncnqKeZj6lqo2luXeY85QmhtxLgEe0"
CONTRACT_SHA256 = "b43a5163f1706497e392171fd224ee02d489584a1d3b361b5f90a05c5c513bf6"
OUT = Path("reports/continuation/m5_github_actions_run_evidence_adapter_v1.json")
STRESS = 10_000
BASE = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)


def intent() -> GitHubDispatchIntent:
    return GitHubDispatchIntent(
        repository="Thomas-Baasch/gehirn-runtime-lab",
        workflow_id=4242,
        expected_event="workflow_dispatch",
        expected_ref="main",
        expected_head_sha="a" * 40,
        home_system="SYNTHETIC_HOME",
        work_id="work-ga-001",
        dedupe_key="dedupe-ga-001",
        target="candidate-validation-v1",
        dispatch_recorded_at=BASE,
        appearance_deadline_at=BASE + timedelta(minutes=2),
        exact_run_name_token="eg:work-ga-001:dedupe-ga-001",
        receipt_source_ref="synthetic:dispatch-receipt:ga-001",
    )


def raw_run(
    *,
    run_id: int = 9001,
    status: str = "in_progress",
    conclusion=None,
    run_attempt: int = 1,
    workflow_id: int = 4242,
    repository: str = "Thomas-Baasch/gehirn-runtime-lab",
    event: str = "workflow_dispatch",
    head_branch: str = "main",
    head_sha: str = "a" * 40,
    display_title: str = "eg:work-ga-001:dedupe-ga-001",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    run_number: int = 17,
) -> dict:
    created_at = created_at or (BASE + timedelta(seconds=5))
    updated_at = updated_at or (BASE + timedelta(minutes=1))
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "run_number": run_number,
        "run_attempt": run_attempt,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "run_started_at": created_at.isoformat(),
        "name": "M5 GitHub Actions Run Evidence Adapter V1",
        "display_title": display_title,
        "repository": {"full_name": repository},
    }


def main() -> int:
    adapter = GitHubActionsRunEvidenceAdapter(max_source_age_seconds=300, clock_skew_seconds=30)
    verifier = PostDispatchRunVerifier(heartbeat_max_age_seconds=300, clock_skew_seconds=30)
    i = intent()
    fetched = BASE + timedelta(minutes=1, seconds=10)
    as_of = BASE + timedelta(minutes=1, seconds=15)
    cases: list[dict] = []

    def record(case_id: str, actual, expected, detail: str = "") -> None:
        actual_value = actual.value if hasattr(actual, "value") else str(actual)
        expected_value = expected.value if hasattr(expected, "value") else str(expected)
        cases.append(
            {
                "case": case_id,
                "actual": actual_value,
                "expected": expected_value,
                "pass": actual_value == expected_value,
                "detail": detail,
            }
        )

    # GA-01 queued -> normalized active observation and downstream verifier accepts identity/freshness.
    d = adapter.evaluate(i, [raw_run(status="queued", conclusion=None)], source_fetched_at=fetched, as_of=as_of)
    v = verifier.verify(d.dispatch_receipt, [d.run_observation], as_of=as_of) if d.run_observation else None
    record("GA-01", f"{d.status.value}/{v.status.value if v else 'NONE'}", "OBSERVATION_READY/EXACT_ACTIVE_FRESH")

    # GA-02 in progress.
    d = adapter.evaluate(i, [raw_run(status="in_progress", conclusion=None)], source_fetched_at=fetched, as_of=as_of)
    v = verifier.verify(d.dispatch_receipt, [d.run_observation], as_of=as_of) if d.run_observation else None
    record("GA-02", f"{d.status.value}/{v.status.value if v else 'NONE'}", "OBSERVATION_READY/EXACT_ACTIVE_FRESH")

    # GA-03 completed success is only technical run success.
    d = adapter.evaluate(i, [raw_run(status="completed", conclusion="success")], source_fetched_at=fetched, as_of=as_of)
    v = verifier.verify(d.dispatch_receipt, [d.run_observation], as_of=as_of) if d.run_observation else None
    record("GA-03", f"{d.status.value}/{v.status.value if v else 'NONE'}", "OBSERVATION_READY/EXACT_SUCCEEDED")

    # GA-04 failure.
    d = adapter.evaluate(i, [raw_run(status="completed", conclusion="failure")], source_fetched_at=fetched, as_of=as_of)
    v = verifier.verify(d.dispatch_receipt, [d.run_observation], as_of=as_of) if d.run_observation else None
    record("GA-04", f"{d.status.value}/{v.status.value if v else 'NONE'}", "OBSERVATION_READY/EXACT_FAILED")

    # GA-05 cancelled.
    d = adapter.evaluate(i, [raw_run(status="completed", conclusion="cancelled")], source_fetched_at=fetched, as_of=as_of)
    record("GA-05", d.run_observation.state if d.run_observation else d.status, "FAILED")

    # GA-06 timed out.
    d = adapter.evaluate(i, [raw_run(status="completed", conclusion="timed_out")], source_fetched_at=fetched, as_of=as_of)
    record("GA-06", d.run_observation.state if d.run_observation else d.status, "FAILED")

    # GA-07 missing before appearance deadline.
    d = adapter.evaluate(i, [], source_fetched_at=fetched, as_of=BASE + timedelta(minutes=1, seconds=30))
    record("GA-07", d.status, AdapterStatus.AWAITING_RUN)

    # GA-08 missing after appearance deadline.
    late = BASE + timedelta(minutes=3)
    d = adapter.evaluate(i, [], source_fetched_at=late, as_of=late)
    record("GA-08", d.status, AdapterStatus.RUN_UNCERTAIN)

    # GA-09 stale source.
    d = adapter.evaluate(i, [raw_run()], source_fetched_at=BASE, as_of=BASE + timedelta(minutes=10))
    record("GA-09", d.status, AdapterStatus.SOURCE_STALE)

    # GA-10 source unavailable / rate limit.
    d = adapter.evaluate(i, [], source_fetched_at=fetched, as_of=as_of, source_error="rate_limit")
    record("GA-10", d.status, AdapterStatus.SOURCE_UNAVAILABLE)

    # GA-11 wrong repository/workflow ignored.
    wrong = [raw_run(repository="Other/repo"), raw_run(workflow_id=9999)]
    d = adapter.evaluate(i, wrong, source_fetched_at=fetched, as_of=as_of)
    record("GA-11", d.status, AdapterStatus.AWAITING_RUN)

    # GA-12 wrong head SHA ignored.
    d = adapter.evaluate(i, [raw_run(head_sha="c" * 40)], source_fetched_at=fetched, as_of=as_of)
    record("GA-12", d.status, AdapterStatus.AWAITING_RUN)

    # GA-13 wrong ref/event ignored.
    d = adapter.evaluate(
        i,
        [raw_run(head_branch="feature/other"), raw_run(event="pull_request")],
        source_fetched_at=fetched,
        as_of=as_of,
    )
    record("GA-13", d.status, AdapterStatus.AWAITING_RUN)

    # GA-14 pre-dispatch run ignored.
    d = adapter.evaluate(
        i,
        [raw_run(created_at=BASE - timedelta(minutes=2), updated_at=BASE - timedelta(minutes=1))],
        source_fetched_at=fetched,
        as_of=as_of,
    )
    record("GA-14", d.status, AdapterStatus.AWAITING_RUN)

    # GA-15 two different exact run IDs conflict.
    d = adapter.evaluate(i, [raw_run(run_id=9001), raw_run(run_id=9002)], source_fetched_at=fetched, as_of=as_of)
    record("GA-15", d.status, AdapterStatus.CONFLICT_BLOCKED)

    # GA-16 conflicting terminal results at same freshness for the same run.
    same = BASE + timedelta(minutes=1)
    d = adapter.evaluate(
        i,
        [
            raw_run(status="completed", conclusion="success", updated_at=same),
            raw_run(status="completed", conclusion="failure", updated_at=same),
        ],
        source_fetched_at=fetched,
        as_of=as_of,
    )
    record("GA-16", d.status, AdapterStatus.CONFLICT_BLOCKED)

    # GA-17 repeated consistent snapshots reduce to freshest same run/attempt view.
    d = adapter.evaluate(
        i,
        [
            raw_run(status="queued", conclusion=None, updated_at=BASE + timedelta(seconds=20)),
            raw_run(status="in_progress", conclusion=None, updated_at=BASE + timedelta(minutes=1)),
        ],
        source_fetched_at=fetched,
        as_of=as_of,
    )
    record("GA-17", d.run_observation.state if d.run_observation else d.status, "IN_PROGRESS")

    # GA-18 unauthorized rerun attempt is a conflict.
    d = adapter.evaluate(i, [raw_run(run_attempt=2)], source_fetched_at=fetched, as_of=as_of)
    record("GA-18", d.status, AdapterStatus.CONFLICT_BLOCKED)

    # GA-19 technical GitHub success never proves downstream effect success.
    d = adapter.evaluate(i, [raw_run(status="completed", conclusion="success")], source_fetched_at=fetched, as_of=as_of)
    ga19_ok = (
        d.status is AdapterStatus.OBSERVATION_READY
        and d.run_observation is not None
        and d.run_observation.state == "SUCCEEDED"
        and d.downstream_effect_confirmed is False
    )
    record("GA-19", "TECHNICAL_ONLY" if ga19_ok else "EFFECT_INFERRED", "TECHNICAL_ONLY")

    # GA-20 invalid receipt, unknown status and timezone-naive times all fail closed.
    bad_intent = replace(i, exact_run_name_token="")
    invalid_receipt = adapter.evaluate(bad_intent, [], source_fetched_at=fetched, as_of=as_of).status is AdapterStatus.RECEIPT_INVALID
    unknown_status = adapter.evaluate(i, [raw_run(status="mystery")], source_fetched_at=fetched, as_of=as_of).status is AdapterStatus.FAIL_CLOSED
    naive = raw_run(); naive["created_at"] = "2026-08-22T10:00:05"
    naive_time = adapter.evaluate(i, [naive], source_fetched_at=fetched, as_of=as_of).status in {AdapterStatus.AWAITING_RUN, AdapterStatus.FAIL_CLOSED}
    ga20_ok = invalid_receipt and unknown_status and naive_time
    record("GA-20", "FAIL_CLOSED" if ga20_ok else "NOT_BLOCKED", "FAIL_CLOSED")

    stress_raw = raw_run(status="in_progress", conclusion=None)
    intent_before = repr(i)
    raw_before = deepcopy(stress_raw)
    first = adapter.evaluate(i, [stress_raw], source_fetched_at=fetched, as_of=as_of)
    deterministic = True
    for _ in range(STRESS):
        cur = adapter.evaluate(i, [stress_raw], source_fetched_at=fetched, as_of=as_of)
        if cur != first or cur.dispatch_executed or cur.retry_executed or cur.repository_written or cur.ledger_updated:
            deterministic = False
            break
    immutable = repr(i) == intent_before and stress_raw == raw_before
    forbidden_surface = any(
        hasattr(adapter, name)
        for name in ("dispatch", "rerun", "cancel", "write", "update", "merge", "delete")
    )
    verifier_composition = False
    if first.dispatch_receipt and first.run_observation:
        downstream = verifier.verify(first.dispatch_receipt, [first.run_observation], as_of=as_of)
        verifier_composition = downstream.status is VerificationStatus.EXACT_ACTIVE_FRESH

    acceptance = {
        "deterministic_20_of_20": len(cases) == 20 and all(c["pass"] for c in cases),
        "stress_10000_deterministic": deterministic,
        "stress_zero_dispatch_retry_write_ledger": (
            not first.dispatch_executed
            and not first.retry_executed
            and not first.repository_written
            and not first.ledger_updated
        ),
        "immutable_inputs": immutable,
        "no_dispatch_rerun_cancel_write_surface": not forbidden_surface,
        "post_dispatch_verifier_composition": verifier_composition,
        "downstream_effect_not_inferred_from_github_success": ga19_ok,
        "real_dispatch_authority_not_granted": True,
    }
    passed = all(acceptance.values())
    report = {
        "schema": "externes-gehirn.m5-github-actions-run-evidence-adapter",
        "version": "0.1.0",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256},
        "cases": cases,
        "stress": {
            "evaluations": STRESS,
            "decision": first.status.value,
            "dispatches": 0,
            "retries": 0,
            "repository_writes": 0,
            "ledger_writes": 0,
        },
        "acceptance": acceptance,
        "result": "PASS" if passed else "FAIL",
        "qualification": "M5_GITHUB_ACTIONS_RUN_EVIDENCE_ADAPTER_V1_PARTIAL_PASS" if passed else "NOT_QUALIFIED",
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
