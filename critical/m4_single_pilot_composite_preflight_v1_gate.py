from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import governance.m4_single_pilot_composite_preflight as preflight_module
from governance.m4_single_pilot_composite_preflight import (
    CompositePilotSnapshot,
    CompositeStatus,
    evaluate_single_pilot_preflight,
)

CONTRACT_DRIVE_ID = "1pOcZzNBuEZwIFpAPc3JCduv27RsvL1P2P3-Bwc2kDrM"
CONTRACT_SHA256 = "0e05fb767927a72508556363a507a6261ddf0bc5c1c4b655c4d16953f4362c11"
OUTCOME_CONTRACT_DRIVE_ID = "15JeNfaaHDAn4a9znqAvkB7DyOLbOGXHs7gbMs4V9e54"
OUTCOME_CONTRACT_SHA256 = "d150621ba21b77f5251d343b5876f81ff63749410c2628c57a3ccf8ea30575fb"
OUT = Path("reports/continuation/m4_single_pilot_composite_preflight_v1.json")
STRESS = 10_000


def eligible() -> CompositePilotSnapshot:
    work_id = "work-sp-001"
    dedupe_key = "dedupe-sp-001"
    return CompositePilotSnapshot(
        home_system="SYNTHETIC_HOME",
        work_id=work_id,
        dedupe_key=dedupe_key,
        target_adapter="SYNTHETIC_SINGLE_PILOT_ADAPTER_V1",
        target="synthetic-candidate-validation",
        source_health="FRESH",
        state="ACTIVE",
        continuation_policy="AUTONOMOUS_EXPECTED",
        runtime_status="IDLE",
        safe_internal_next=True,
        safe_recovery=False,
        action_class="INTERNAL_CONTINUE",
        reversible=True,
        external_effect=False,
        protected_effects_allowed=False,
        owner_gate=False,
        review_gate=False,
        stop_latch=False,
        waiting_expected=False,
        requested_permissions=frozenset({"contents:read"}),
        minimum_permissions=frozenset({"contents:read"}),
        permission_allowlist=frozenset({"contents:read", "actions:write"}),
        retry_count=0,
        retry_limit=3,
        circuit_open=False,
        durable_claim_state="NONE",
        negative_tests_passed=True,
        audit_present=True,
        rollback_present=True,
        durable_dedupe_passed=True,
        expected_repository="Thomas-Baasch/synthetic-home",
        expected_workflow_id=4242,
        expected_event="workflow_dispatch",
        expected_ref="main",
        expected_head_sha="a" * 40,
        exact_run_name_token=f"eg:{work_id}:{dedupe_key}",
        outcome_contract_drive_id=OUTCOME_CONTRACT_DRIVE_ID,
        outcome_contract_sha256=OUTCOME_CONTRACT_SHA256,
        expected_artifact_name=f"safe-continuation-outcome-{work_id}-{dedupe_key}",
        expected_outcome_path="safe-continuation-outcome.json",
        outcome_schema="safe-continuation-outcome.v1",
        provider_digest_required=True,
        live_executor_enabled=True,
    )


def peter_real_observation() -> CompositePilotSnapshot:
    # Fresh read 2026-08-22: PETER Issue #31 / RP-004C remains WAITING_EXPECTED
    # because no valid independent local execution interface exists.
    base = eligible()
    return replace(
        base,
        home_system="PETER",
        work_id="RP-004C",
        dedupe_key="peter-rp004c-current",
        target_adapter="PETER_LOCAL_EXECUTION_INTERFACE_UNAVAILABLE",
        target="independent-local-container-wsl-test-base",
        waiting_expected=True,
        live_executor_enabled=False,
        exact_run_name_token="peter:RP-004C:peter-rp004c-current",
        expected_artifact_name="outcome-RP-004C-peter-rp004c-current",
    )


def uschi_legacy_observation() -> CompositePilotSnapshot:
    # Fresh read 2026-08-22: Issue #199 freezes Legacy as read-only migration source.
    base = eligible()
    return replace(
        base,
        home_system="USCHI 2.0 LEGACY",
        work_id="LEGACY-FROZEN",
        dedupe_key="uschi-legacy-frozen",
        target_adapter="NO_LEGACY_DISPATCH_ADAPTER",
        target="read-only-migration-source",
        state="FROZEN",
        continuation_policy="PARKED",
        live_executor_enabled=False,
        exact_run_name_token="legacy:LEGACY-FROZEN:uschi-legacy-frozen",
        expected_artifact_name="legacy-LEGACY-FROZEN-uschi-legacy-frozen",
    )


def uschi_new_observation() -> CompositePilotSnapshot:
    # Fresh read 2026-08-22: Issue #197 reports M0-M3 pass / M4 PETER orchestration next,
    # but no Externes-Gehirn allowlisted single-pilot adapter/outcome contract exists.
    base = eligible()
    return replace(
        base,
        home_system="USCHI NEU",
        work_id="RP-003-M4-PETER-ORCHESTRATION",
        dedupe_key="uschi-new-rp003-m4-unapproved",
        target_adapter="USCHI_NEW_ADAPTER_NOT_EXTERNES_GEHIRN_ALLOWLISTED",
        target="peter-portfolio-orchestration",
        exact_run_name_token="uschi:RP-003-M4-PETER-ORCHESTRATION:uschi-new-rp003-m4-unapproved",
        expected_artifact_name="uschi-RP-003-M4-PETER-ORCHESTRATION-uschi-new-rp003-m4-unapproved",
    )


def main() -> int:
    base = eligible()
    cases: list[dict] = []

    def record(case_id: str, actual, expected, detail: str = "") -> None:
        av = actual.value if hasattr(actual, "value") else str(actual)
        ev = expected.value if hasattr(expected, "value") else str(expected)
        cases.append(
            {
                "case": case_id,
                "actual": av,
                "expected": ev,
                "pass": av == ev,
                "detail": detail,
            }
        )

    record("SP-01", evaluate_single_pilot_preflight(base).status, CompositeStatus.READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT)
    record("SP-02", evaluate_single_pilot_preflight(replace(base, source_health="STALE")).status, CompositeStatus.BLOCKED_SOURCE)
    record("SP-03", evaluate_single_pilot_preflight(replace(base, state="DONE")).status, CompositeStatus.BLOCKED_STATE)
    record("SP-04", evaluate_single_pilot_preflight(replace(base, continuation_policy="MANUAL_ON_DEMAND")).status, CompositeStatus.BLOCKED_POLICY)
    record("SP-05", evaluate_single_pilot_preflight(replace(base, waiting_expected=True)).status, CompositeStatus.BLOCKED_EXPECTED_WAIT)
    record("SP-06", evaluate_single_pilot_preflight(replace(base, owner_gate=True)).status, CompositeStatus.BLOCKED_OWNER_OR_REVIEW)
    record("SP-07", evaluate_single_pilot_preflight(replace(base, review_gate=True)).status, CompositeStatus.BLOCKED_OWNER_OR_REVIEW)
    record("SP-08", evaluate_single_pilot_preflight(replace(base, stop_latch=True)).status, CompositeStatus.BLOCKED_OWNER_OR_REVIEW)

    statuses = {
        evaluate_single_pilot_preflight(replace(base, runtime_status="RUNNING")).status,
        evaluate_single_pilot_preflight(replace(base, runtime_status="UNKNOWN")).status,
    }
    record("SP-09", "BLOCKED_RUNTIME" if statuses == {CompositeStatus.BLOCKED_RUNTIME} else "NOT_BLOCKED", "BLOCKED_RUNTIME")

    recovery_bad_runtime = replace(base, action_class="INTERNAL_RECOVERY", runtime_status="IDLE", safe_internal_next=False, safe_recovery=True)
    recovery_missing_safe = replace(base, action_class="INTERNAL_RECOVERY", runtime_status="FAILED", safe_internal_next=False, safe_recovery=False)
    sp10 = all(evaluate_single_pilot_preflight(s).status is CompositeStatus.BLOCKED_SAFE_ACTION for s in (recovery_bad_runtime, recovery_missing_safe))
    record("SP-10", "BLOCKED_SAFE_ACTION" if sp10 else "NOT_BLOCKED", "BLOCKED_SAFE_ACTION")

    continue_bad = replace(base, safe_internal_next=False)
    record("SP-11", evaluate_single_pilot_preflight(continue_bad).status, CompositeStatus.BLOCKED_SAFE_ACTION)
    record("SP-12", evaluate_single_pilot_preflight(replace(base, action_class="MERGE")).status, CompositeStatus.BLOCKED_SAFE_ACTION)
    record("SP-13", evaluate_single_pilot_preflight(replace(base, reversible=False)).status, CompositeStatus.BLOCKED_OWNER_OR_EFFECT)

    sp14 = all(
        evaluate_single_pilot_preflight(s).status is CompositeStatus.BLOCKED_OWNER_OR_EFFECT
        for s in (replace(base, external_effect=True), replace(base, protected_effects_allowed=True))
    )
    record("SP-14", "BLOCKED_OWNER_OR_EFFECT" if sp14 else "NOT_BLOCKED", "BLOCKED_OWNER_OR_EFFECT")

    too_many = replace(base, requested_permissions=frozenset({"contents:read", "issues:write"}))
    outside_allowlist = replace(base, minimum_permissions=frozenset({"contents:read", "issues:write"}), requested_permissions=frozenset({"contents:read"}))
    sp15 = all(evaluate_single_pilot_preflight(s).status is CompositeStatus.BLOCKED_RIGHTS for s in (too_many, outside_allowlist))
    record("SP-15", "BLOCKED_RIGHTS" if sp15 else "NOT_BLOCKED", "BLOCKED_RIGHTS")

    sp16 = all(
        evaluate_single_pilot_preflight(s).status is CompositeStatus.BLOCKED_CIRCUIT
        for s in (replace(base, retry_count=3), replace(base, circuit_open=True))
    )
    record("SP-16", "BLOCKED_CIRCUIT" if sp16 else "NOT_BLOCKED", "BLOCKED_CIRCUIT")

    sp17 = all(
        evaluate_single_pilot_preflight(s).status is CompositeStatus.BLOCKED_DURABILITY
        for s in (
            replace(base, negative_tests_passed=False),
            replace(base, audit_present=False),
            replace(base, rollback_present=False),
            replace(base, durable_dedupe_passed=False),
        )
    )
    record("SP-17", "BLOCKED_DURABILITY" if sp17 else "NOT_BLOCKED", "BLOCKED_DURABILITY")

    sp18 = all(
        evaluate_single_pilot_preflight(s).status is CompositeStatus.FAIL_CLOSED_IDENTITY
        for s in (
            replace(base, work_id=""),
            replace(base, dedupe_key=""),
            replace(base, target=""),
            replace(base, target_adapter=""),
        )
    )
    record("SP-18", "FAIL_CLOSED_IDENTITY" if sp18 else "NOT_BLOCKED", "FAIL_CLOSED_IDENTITY")

    record("SP-19", evaluate_single_pilot_preflight(replace(base, target_adapter="REAL_ADAPTER_NOT_ALLOWLISTED")).status, CompositeStatus.BLOCKED_ADAPTER_AUTHORITY)

    run_binding_variants = (
        replace(base, expected_repository=""),
        replace(base, expected_workflow_id=0),
        replace(base, expected_event=""),
        replace(base, expected_ref=""),
        replace(base, expected_head_sha=""),
        replace(base, exact_run_name_token="missing-bindings"),
    )
    sp20 = all(evaluate_single_pilot_preflight(s).status is CompositeStatus.BLOCKED_RUN_BINDING for s in run_binding_variants)
    record("SP-20", "BLOCKED_RUN_BINDING" if sp20 else "NOT_BLOCKED", "BLOCKED_RUN_BINDING")

    claim_states = ("CLAIMED", "RECONCILE_REQUIRED", "FAILED_RETRYABLE", "UNKNOWN")
    nonclean = all(evaluate_single_pilot_preflight(replace(base, durable_claim_state=s)).status is CompositeStatus.BLOCKED_DURABLE_CLAIM for s in claim_states)
    done = evaluate_single_pilot_preflight(replace(base, durable_claim_state="SUCCEEDED")).status is CompositeStatus.BLOCKED_DUPLICATE_DONE
    record("SP-21", "BLOCKED_DURABLE_CLAIM/BLOCKED_DUPLICATE_DONE" if nonclean and done else "NOT_BLOCKED", "BLOCKED_DURABLE_CLAIM/BLOCKED_DUPLICATE_DONE")

    outcome_variants = (
        replace(base, outcome_contract_drive_id="wrong"),
        replace(base, outcome_contract_sha256="wrong"),
        replace(base, expected_artifact_name="artifact-without-bindings"),
        replace(base, expected_outcome_path="other.json"),
        replace(base, outcome_schema="weaker.v0"),
        replace(base, provider_digest_required=False),
    )
    sp22 = all(evaluate_single_pilot_preflight(s).status is CompositeStatus.BLOCKED_OUTCOME_PROOF for s in outcome_variants)
    record("SP-22", "BLOCKED_OUTCOME_PROOF" if sp22 else "NOT_BLOCKED", "BLOCKED_OUTCOME_PROOF")

    peter = evaluate_single_pilot_preflight(peter_real_observation())
    record("SP-23", peter.status, CompositeStatus.BLOCKED_EXPECTED_WAIT, "PETER Issue #31 RP-004C current wait")

    legacy = evaluate_single_pilot_preflight(uschi_legacy_observation())
    new = evaluate_single_pilot_preflight(uschi_new_observation())
    sp24_ok = legacy.status is CompositeStatus.BLOCKED_STATE and new.status is CompositeStatus.BLOCKED_ADAPTER_AUTHORITY
    record(
        "SP-24",
        f"{legacy.status.value}/{new.status.value}",
        "BLOCKED_STATE/BLOCKED_ADAPTER_AUTHORITY",
        "USCHI 2.0 LEGACY frozen; USCHI NEU lacks Externes-Gehirn adapter authority",
    )

    first = evaluate_single_pilot_preflight(base)
    before = repr(base)
    deterministic = True
    for _ in range(STRESS):
        current = evaluate_single_pilot_preflight(base)
        if current != first or current.dispatch_executed or current.retry_executed or current.claim_executed or current.write_executed:
            deterministic = False
            break
    immutable = repr(base) == before
    forbidden_names = {"dispatch", "execute", "claim", "retry", "rerun", "cancel", "write", "merge", "delete"}
    exported_forbidden_surface = any(name in preflight_module.__dict__ and callable(preflight_module.__dict__[name]) for name in forbidden_names)

    acceptance = {
        "deterministic_24_of_24": len(cases) == 24 and all(c["pass"] for c in cases),
        "stress_10000_ready_deterministic": deterministic,
        "stress_zero_dispatch_retry_claim_write": not first.dispatch_executed and not first.retry_executed and not first.claim_executed and not first.write_executed,
        "immutable_inputs": immutable,
        "no_dispatch_execute_claim_retry_write_surface": not exported_forbidden_surface,
        "synthetic_only_ready": first.ready and first.status is CompositeStatus.READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT,
        "peter_current_real_observation_blocked": peter.status is CompositeStatus.BLOCKED_EXPECTED_WAIT,
        "uschi_legacy_current_real_observation_blocked": legacy.status is CompositeStatus.BLOCKED_STATE,
        "uschi_new_current_real_observation_blocked": new.status is CompositeStatus.BLOCKED_ADAPTER_AUTHORITY,
        "real_dispatch_authority_not_granted": first.real_dispatch_authority == "NOT_GRANTED",
    }
    passed = all(acceptance.values())
    report = {
        "schema": "externes-gehirn.m4-single-pilot-composite-preflight",
        "version": "0.1.0",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256},
        "outcome_proof_contract": {"drive_id": OUTCOME_CONTRACT_DRIVE_ID, "sha256": OUTCOME_CONTRACT_SHA256},
        "cases": cases,
        "stress": {"evaluations": STRESS, "decision": first.status.value, "dispatches": 0, "retries": 0, "claims": 0, "writes": 0},
        "real_observations": {
            "PETER": {"status": peter.status.value, "source": "peter-system-code issue #31", "work": "RP-004C"},
            "USCHI_2_LEGACY": {"status": legacy.status.value, "source": "uschi-system-code issue #199"},
            "USCHI_NEU": {"status": new.status.value, "source": "uschi-system-code issue #197"},
        },
        "acceptance": acceptance,
        "result": "PASS" if passed else "FAIL",
        "qualification": "M4_SINGLE_PILOT_COMPOSITE_PREFLIGHT_V1_PASS_READ_ONLY" if passed else "NOT_QUALIFIED",
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
