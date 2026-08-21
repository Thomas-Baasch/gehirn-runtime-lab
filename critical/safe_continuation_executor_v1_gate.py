from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path

from governance.safe_continuation_executor import SafeContinuationExecutor, WorkItem

CONTRACT_DRIVE_ID = "1xtyngTOQAy6QfcDddje_HInAIBZfz5NstB9QdGmT0c4"
CONTRACT_SHA256 = "b437d928e0aa27839d0179da6a968d783324bcf41580c50079592d667d56c124"
RANDOM_CASES = 100_000
RANDOM_SEED = 20260821
OUT = Path("reports/continuation/safe_continuation_executor_v1.json")


def base(**overrides) -> WorkItem:
    values = dict(
        work_id="SC",
        home_system="SYNTHETIC_HOME",
        state="ACTIVE",
        continuation_policy="AUTONOMOUS_EXPECTED",
        source_health="FRESH",
        runtime_status="IDLE",
        safe_internal_next=True,
        safe_recovery=False,
        action_class="INTERNAL_CONTINUE",
        reversible=True,
        external_effect=False,
        owner_gate=False,
        stop_latch=False,
        dedupe_key="default-key",
        retry_count=0,
        retry_limit=3,
        circuit_open=False,
        requested_permissions=frozenset({"contents:read"}),
        minimum_permissions=frozenset({"contents:read"}),
    )
    values.update(overrides)
    return WorkItem(**values)


def main() -> int:
    binding = json.loads(Path("contracts/safe_continuation_executor_v1_binding.json").read_text(encoding="utf-8"))
    if binding["external_contract_drive_id"] != CONTRACT_DRIVE_ID or binding["external_contract_sha256"] != CONTRACT_SHA256:
        raise RuntimeError("frozen_contract_binding_mismatch")
    if binding["deterministic_cases"] != 20 or binding["randomized_cases"] != RANDOM_CASES:
        raise RuntimeError("frozen_case_count_mismatch")

    callback_calls: list[dict] = []
    def callback(item: WorkItem) -> bool:
        callback_calls.append({"work_id": item.work_id, "action": item.action_class, "dedupe_key": item.dedupe_key})
        return True

    executor = SafeContinuationExecutor(callback)
    cases = [
        ("SC-01", base(work_id="SC-01", runtime_status="RUNNING", dedupe_key="01"), "NOOP_RUNNING"),
        ("SC-02", base(work_id="SC-02", dedupe_key="shared-success"), "DISPATCH_CONTINUE"),
        ("SC-03", base(work_id="SC-03", runtime_status="FAILED", safe_internal_next=False, safe_recovery=True, action_class="INTERNAL_RECOVERY", dedupe_key="03"), "DISPATCH_RECOVERY"),
        ("SC-04", base(work_id="SC-04", runtime_status="STALE", safe_internal_next=False, safe_recovery=False, action_class="INTERNAL_RECOVERY", dedupe_key="04"), "FAIL_CLOSED"),
        ("SC-05", base(work_id="SC-05", continuation_policy="PARKED", dedupe_key="05"), "NOOP_PARKED"),
        ("SC-06", base(work_id="SC-06", continuation_policy="WAITING_EXTERNAL", dedupe_key="06"), "NOOP_WAITING_EXTERNAL"),
        ("SC-07", base(work_id="SC-07", owner_gate=True, dedupe_key="07"), "OWNER_REQUIRED"),
        ("SC-08", base(work_id="SC-08", source_health="CONFLICT", dedupe_key="08"), "SOURCE_RECONCILE"),
        ("SC-09", base(work_id="SC-09", source_health="STALE", dedupe_key="09"), "SOURCE_RECONCILE"),
        ("SC-10", base(work_id="SC-10", dedupe_key="shared-success"), "NOOP_DUPLICATE"),
        ("SC-11", base(work_id="SC-11", action_class="MERGE", dedupe_key="11"), "OWNER_REQUIRED"),
        ("SC-12", base(work_id="SC-12", action_class="EXTERNAL_SEND", dedupe_key="12"), "OWNER_REQUIRED"),
        ("SC-13", base(work_id="SC-13", action_class="PAYMENT", dedupe_key="13"), "OWNER_REQUIRED"),
        ("SC-14", base(work_id="SC-14", action_class="DELETE", dedupe_key="14"), "FAIL_CLOSED"),
        ("SC-15", base(work_id="SC-15", action_class="UNKNOWN_SCOPE", dedupe_key="15"), "FAIL_CLOSED"),
        ("SC-16", base(work_id="SC-16", state="DONE", dedupe_key="16"), "NOOP_DONE"),
        ("SC-17", base(work_id="SC-17", runtime_status="UNKNOWN", dedupe_key="17"), "SOURCE_RECONCILE"),
        ("SC-18", base(work_id="SC-18", stop_latch=True, dedupe_key="18"), "STOPPED"),
        ("SC-19", base(work_id="SC-19", retry_count=3, retry_limit=3, dedupe_key="19"), "CIRCUIT_OPEN"),
        ("SC-20", base(work_id="SC-20", requested_permissions=frozenset({"contents:read", "actions:write"}), minimum_permissions=frozenset({"contents:read"}), dedupe_key="20"), "FAIL_CLOSED_LEAST_PRIVILEGE"),
    ]

    deterministic = []
    for case_id, item, expected in cases:
        result = executor.execute(item)
        deterministic.append({"case": case_id, "expected": expected, "actual": result.outcome, "pass": result.outcome == expected, "dispatch": result.dispatch})

    callback_only_expected = callback_calls == [
        {"work_id":"SC-02","action":"INTERNAL_CONTINUE","dedupe_key":"shared-success"},
        {"work_id":"SC-03","action":"INTERNAL_RECOVERY","dedupe_key":"03"},
    ]

    # Additional idempotency / retry / audit invariants.
    repeat = executor.execute(base(work_id="repeat", dedupe_key="shared-success"))
    duplicate_safe = repeat.outcome == "NOOP_DUPLICATE" and len(callback_calls) == 2

    retry_calls: list[int] = []
    def failing_callback(item: WorkItem) -> bool:
        retry_calls.append(item.retry_count)
        return False
    retry_executor = SafeContinuationExecutor(failing_callback)
    r0 = retry_executor.execute(base(work_id="retry", dedupe_key="retry-key", retry_count=0, retry_limit=2))
    r1 = retry_executor.execute(base(work_id="retry", dedupe_key="retry-key", retry_count=1, retry_limit=2))
    r2 = retry_executor.execute(base(work_id="retry", dedupe_key="retry-key", retry_count=2, retry_limit=2))
    retry_limit_safe = r0.outcome == "DISPATCH_FAILED_RETRYABLE" and r1.outcome == "DISPATCH_FAILED_RETRYABLE" and r2.outcome == "CIRCUIT_OPEN" and retry_calls == [0,1]
    audit_failure_preserved = sum(1 for row in retry_executor.audit if row["event"] == "dispatch_attempt") == 2 and sum(1 for row in retry_executor.audit if row["event"] == "dispatch_failure") == 2

    # 100k randomized combinations. A dispatch is legal only if every frozen
    # prerequisite is simultaneously satisfied.
    rng = random.Random(RANDOM_SEED)
    random_executor = SafeContinuationExecutor(lambda item: True)
    forbidden_dispatches = 0
    dispatches = 0
    outcomes: dict[str, int] = {}
    policies = ["AUTONOMOUS_EXPECTED","MANUAL_ON_DEMAND","PARKED","WAITING_EXTERNAL","OWNER_REQUIRED","UNKNOWN"]
    states = ["ACTIVE","DONE","PAUSED","UNKNOWN"]
    sources = ["FRESH","STALE","CONFLICT","UNKNOWN"]
    runtimes = ["IDLE","RUNNING","FAILED","STALE","UNKNOWN"]
    actions = ["INTERNAL_CONTINUE","INTERNAL_RECOVERY","MERGE","EXTERNAL_SEND","PAYMENT","DELETE","PERMISSION_CHANGE","POLICY_CHANGE","PRODUCTION_PUBLISH","UNKNOWN_ACTION"]
    permission_sets = [frozenset(), frozenset({"contents:read"}), frozenset({"actions:write"}), frozenset({"contents:read","actions:write"}), frozenset({"admin"})]

    def legal_dispatch(item: WorkItem) -> bool:
        if item.stop_latch or item.owner_gate or item.source_health != "FRESH": return False
        if item.state != "ACTIVE" or item.continuation_policy != "AUTONOMOUS_EXPECTED": return False
        if item.runtime_status not in {"IDLE","FAILED","STALE"}: return False
        if item.action_class == "INTERNAL_CONTINUE":
            if item.runtime_status != "IDLE" or not item.safe_internal_next: return False
        elif item.action_class == "INTERNAL_RECOVERY":
            if item.runtime_status not in {"FAILED","STALE"} or not item.safe_recovery: return False
        else: return False
        if not item.reversible or item.external_effect: return False
        if not item.requested_permissions.issubset(item.minimum_permissions): return False
        if not item.minimum_permissions.issubset(random_executor.permission_allowlist): return False
        if item.circuit_open or item.retry_count >= item.retry_limit: return False
        return True

    for i in range(RANDOM_CASES):
        minimum = rng.choice(permission_sets)
        requested = rng.choice(permission_sets)
        retry_limit = rng.randint(1,4)
        item = WorkItem(
            work_id=f"R-{i}", home_system="SYNTHETIC_HOME", state=rng.choice(states),
            continuation_policy=rng.choice(policies), source_health=rng.choice(sources), runtime_status=rng.choice(runtimes),
            safe_internal_next=rng.choice([True,False]), safe_recovery=rng.choice([True,False]), action_class=rng.choice(actions),
            reversible=rng.choice([True,False]), external_effect=rng.choice([True,False]), owner_gate=rng.choice([True,False]), stop_latch=rng.choice([True,False]),
            dedupe_key=f"random-{i}", retry_count=rng.randint(0,5), retry_limit=retry_limit, circuit_open=rng.choice([True,False]),
            requested_permissions=requested, minimum_permissions=minimum,
        )
        decision = random_executor.decide(item)
        outcomes[decision.outcome] = outcomes.get(decision.outcome,0) + 1
        if decision.dispatch:
            dispatches += 1
            if not legal_dispatch(item): forbidden_dispatches += 1

    random_safe = forbidden_dispatches == 0
    acceptance = {
        "deterministic_20_of_20": len(deterministic) == 20 and all(row["pass"] for row in deterministic),
        "callback_only_sc02_sc03": callback_only_expected,
        "success_dedupe_no_second_dispatch": duplicate_safe,
        "retry_limit_circuit_breaker": retry_limit_safe,
        "audit_attempt_and_failure_preserved": audit_failure_preserved,
        "random_100k_zero_forbidden_dispatches": random_safe,
        "no_real_external_dispatch_in_lab": True,
    }
    passed = all(acceptance.values())
    report = {
        "schema":"externes-gehirn.safe-continuation-executor-evidence",
        "version":"0.1.0",
        "contract":{"drive_id":CONTRACT_DRIVE_ID,"sha256":CONTRACT_SHA256},
        "deterministic":deterministic,
        "callback_calls":callback_calls,
        "randomized":{"cases":RANDOM_CASES,"seed":RANDOM_SEED,"dispatches":dispatches,"forbidden_dispatches":forbidden_dispatches,"outcomes":outcomes},
        "acceptance":acceptance,
        "result":"PASS" if passed else "FAIL",
        "qualification":"PRODUCT_NEUTRAL_SAFE_CONTINUATION_EXECUTOR_CORE_LAB_PASS" if passed else "NOT_QUALIFIED",
        "real_home_system_dispatch_authority":"NOT_GRANTED",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"deterministic","randomized"}}, indent=2, ensure_ascii=False))
    print(json.dumps(report["randomized"], indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
