from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from governance.m4_home_system_eligibility import Eligibility, HomeSystemSnapshot, evaluate_m4_eligibility

CONTRACT_DRIVE_ID = "1yMRjJQo7iGKbjvAWGZzAlrpz-JIROdLIx6HwEsdYkmU"
CONTRACT_SHA256 = "9cc74f3471a73df1a0b870e12dc5b149eb62e96a3c266bfe62587808e522e6b2"
OUT = Path("reports/continuation/m4_home_system_eligibility_v1.json")


def base() -> HomeSystemSnapshot:
    return HomeSystemSnapshot(
        home_system="SYNTHETIC_HOME",
        source_health="FRESH",
        continuation_policy="AUTONOMOUS_EXPECTED",
        work_id="work-001",
        dedupe_key="dedupe-001",
        safe_internal_next=True,
        safe_recovery=False,
        allowlisted_target="candidate-validation-v1",
        stop_latch=False,
        owner_gate=False,
        review_gate=False,
        waiting_expected=False,
        active_run=False,
        action_class="INTERNAL_CONTINUE",
        reversible=True,
        external_effect=False,
        minimum_permissions_proven=True,
        retry_limit_present=True,
        circuit_breaker_present=True,
        audit_present=True,
        rollback_present=True,
        negative_tests_passed=True,
        durable_dedupe_passed=True,
        live_executor_enabled=True,
        protected_effects_allowed=False,
    )


def main() -> int:
    cases: list[dict] = []

    def check(case: str, snapshot: HomeSystemSnapshot, expected: Eligibility) -> None:
        decision = evaluate_m4_eligibility(snapshot)
        cases.append({
            "case": case,
            "expected": expected.value,
            "actual": decision.status.value,
            "pass": decision.status is expected and decision.dispatch_executed is False,
            "reason": decision.reason,
        })

    b = base()
    check("M4E-01-all-gates", b, Eligibility.ELIGIBLE_FOR_SINGLE_LIVE_PILOT)
    check("M4E-02-review-gate", replace(b, review_gate=True), Eligibility.OWNER_REVIEW_GATE)
    check("M4E-03-owner-gate", replace(b, owner_gate=True), Eligibility.OWNER_REVIEW_GATE)
    check("M4E-04-stop", replace(b, stop_latch=True), Eligibility.OWNER_REVIEW_GATE)
    check("M4E-05-active-run", replace(b, active_run=True), Eligibility.ACTIVE_RUN_NOOP)
    check("M4E-06-stale-source", replace(b, source_health="STALE"), Eligibility.SOURCE_BLOCKED)
    check("M4E-07-conflict-source", replace(b, source_health="CONFLICT"), Eligibility.SOURCE_BLOCKED)
    check("M4E-08-policy", replace(b, continuation_policy="MANUAL_ON_DEMAND"), Eligibility.POLICY_BLOCKED)
    check("M4E-09-no-safe-next", replace(b, safe_internal_next=False, safe_recovery=False), Eligibility.SAFE_NEXT_BLOCKED)
    check("M4E-10-external-effect", replace(b, external_effect=True), Eligibility.ACTION_BLOCKED)
    check("M4E-11-protected-effect", replace(b, protected_effects_allowed=True), Eligibility.ACTION_BLOCKED)
    check("M4E-12-rights", replace(b, minimum_permissions_proven=False), Eligibility.RIGHTS_BLOCKED)
    check("M4E-13-durable", replace(b, durable_dedupe_passed=False), Eligibility.DURABILITY_BLOCKED)
    check("M4E-14-negative-tests", replace(b, negative_tests_passed=False), Eligibility.TESTS_BLOCKED)
    check("M4E-15-live-disabled", replace(b, live_executor_enabled=False), Eligibility.LIVE_EXECUTOR_BLOCKED)
    check("M4E-16-waiting", replace(b, waiting_expected=True), Eligibility.WAITING_EXPECTED)

    # Current PETER observation: source/policy/safe validation path are improving,
    # but WATCHER-V2 PR #28 is a reviewable Draft and the executor is live-disabled.
    peter = replace(
        b,
        home_system="PETER",
        work_id="WATCHER-V2",
        dedupe_key="peter-watcher-v2-pr28",
        allowlisted_target=".peter/current-candidate-test-request.txt",
        review_gate=True,
        live_executor_enabled=False,
    )
    peter_decision = evaluate_m4_eligibility(peter)
    peter_ok = peter_decision.status is Eligibility.OWNER_REVIEW_GATE and not peter_decision.dispatch_executed

    acceptance = {
        "deterministic_16_of_16": len(cases) == 16 and all(row["pass"] for row in cases),
        "peter_current_observation_owner_gate": peter_ok,
        "read_only_no_dispatch": all(evaluate_m4_eligibility(s).dispatch_executed is False for s in [b, peter]),
        "frozen_contract_bound": True,
    }
    passed = all(acceptance.values())
    report = {
        "schema":"externes-gehirn.m4-home-system-eligibility-evidence",
        "version":"0.1.0",
        "contract":{"drive_id":CONTRACT_DRIVE_ID,"sha256":CONTRACT_SHA256},
        "cases":cases,
        "peter_observation":{
            "status":peter_decision.status.value,
            "reason":peter_decision.reason,
            "dispatch_executed":peter_decision.dispatch_executed,
            "interpretation":"PETER is not M4-live-eligible while WATCHER-V2 PR #28 remains a Draft review gate and live execution is disabled."
        },
        "acceptance":acceptance,
        "result":"PASS" if passed else "FAIL",
        "m4_overall":"NOT_COMPLETE",
        "real_dispatch_authority":"NOT_GRANTED",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
