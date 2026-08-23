from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import tempfile

import governance.m5_incident_rollback_safety as mod
from governance.m5_incident_rollback_safety import (
    DurableRollbackLedger,
    IncidentDecision,
    IncidentEvidence,
    RollbackClaimStatus,
    classify_incident,
)

CONTRACT_DRIVE_ID = "1hPFoj1RHekpBIdvh0ZJpnlmMrxxFKi6BC9_cWIAAlas"
CONTRACT_SHA256 = "20b31ddfcfc489e4c2de128312c95055d9b1a71e19f81d46465765af3453eab2"
OUT = Path("reports/continuation/m5_incident_rollback_safety_v0_1.json")
STRESS = 100_000


def h(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def base(n: int = 1, **kw) -> IncidentEvidence:
    d = dict(
        home_system="SYNTHETIC_HOME",
        work_id=f"work-{n}",
        dedupe_key=f"dedupe-{n}",
        target=f"target-{n}",
        adapter_contract_id="synthetic-adapter-contract-v1",
        adapter_contract_sha256=h("adapter"),
        action_class="INTERNAL_LOCAL_ROLLBACK",
        durable_claim_status="FAILED_LOCAL",
        authorization_grant_id=f"grant-{n}",
        authorization_consumption_status="CONSUMED",
        grant_reuse_attempt=False,
        downstream_run_id=None,
        downstream_outcome_status="VERIFIED_NO_EXTERNAL_EFFECT",
        source_health="FRESH",
        source_fresh=True,
        source_conflict=False,
        stop_latch=False,
        owner_gate=False,
        incident_cause="synthetic_local_failure",
        rollback_action_id="restore_local_snapshot",
        rollback_action_allowlisted=True,
        rollback_reversible=True,
        rollback_external_effect=False,
        external_effect_possible=False,
        requested_permissions=("local:rollback",),
        minimum_permissions=("local:rollback",),
        retry_count=0,
        retry_limit=1,
        circuit_open=False,
        audit_integrity=True,
        ledger_integrity=True,
        identity_scope_match=True,
        adapter_binding_match=True,
    )
    d.update(kw)
    return IncidentEvidence(**d)


def expected_safe(e: IncidentEvidence) -> bool:
    return all((
        not e.stop_latch,
        not e.owner_gate,
        bool(e.home_system and e.work_id and e.dedupe_key and e.target and e.adapter_contract_id and e.adapter_contract_sha256),
        e.action_class == "INTERNAL_LOCAL_ROLLBACK",
        e.durable_claim_status in {"FAILED_LOCAL", "FAILED_RETRYABLE"},
        not e.grant_reuse_attempt,
        e.downstream_outcome_status == "VERIFIED_NO_EXTERNAL_EFFECT",
        e.source_health == "FRESH",
        e.source_fresh,
        not e.source_conflict,
        e.rollback_action_allowlisted,
        e.rollback_reversible,
        not e.rollback_external_effect,
        not e.external_effect_possible,
        set(e.requested_permissions).issubset(set(e.minimum_permissions)),
        e.retry_count >= 0,
        e.retry_limit > e.retry_count,
        not e.circuit_open,
        e.audit_integrity,
        e.ledger_integrity,
        e.identity_scope_match,
        e.adapter_binding_match,
    ))


def main() -> int:
    cases: list[dict] = []

    def rec(case_id: str, actual, expected, detail: str = "") -> None:
        av = actual.value if hasattr(actual, "value") else str(actual)
        ev = expected.value if hasattr(expected, "value") else str(expected)
        cases.append({"case": case_id, "actual": av, "expected": ev, "pass": av == ev, "detail": detail})

    rec("IR-01", classify_incident(base(1, durable_claim_status="SUCCEEDED", downstream_outcome_status="VERIFIED_SUCCESS")).decision, IncidentDecision.NO_INCIDENT)
    safe = base(2)
    rec("IR-02", classify_incident(safe).decision, IncidentDecision.LOCAL_ROLLBACK_ALLOWED)

    callback_count = 0
    with tempfile.TemporaryDirectory() as td:
        ledger = DurableRollbackLedger(Path(td) / "rollback.sqlite")
        a = classify_incident(safe)
        claim = ledger.claim(safe, a)
        rec("IR-03A", claim.status, RollbackClaimStatus.CLAIMED_NEW)
        if claim.status is RollbackClaimStatus.CLAIMED_NEW:
            callback_count += 1
            done = ledger.mark_succeeded(claim.scope_key, claim.scope_sha256)
        else:
            done = claim
        rec("IR-03B", done.status, RollbackClaimStatus.SUCCEEDED)

        rec("IR-04", classify_incident(base(4, external_effect_possible=True)).decision, IncidentDecision.RECONCILE_REQUIRED)
        rec("IR-05", classify_incident(base(5, downstream_outcome_status="UNKNOWN")).decision, IncidentDecision.RECONCILE_REQUIRED)
        rec("IR-06", classify_incident(base(6, durable_claim_status="CLAIMED", downstream_outcome_status="UNKNOWN")).decision, IncidentDecision.RECONCILE_REQUIRED)
        rec("IR-07", classify_incident(base(7, durable_claim_status="SUCCEEDED", downstream_outcome_status="VERIFIED_SUCCESS")).decision, IncidentDecision.NO_INCIDENT)
        rec("IR-08", classify_incident(base(8, source_fresh=False)).decision, IncidentDecision.RECONCILE_REQUIRED)
        rec("IR-09", classify_incident(base(9, source_conflict=True)).decision, IncidentDecision.RECONCILE_REQUIRED)
        rec("IR-10", classify_incident(base(10, identity_scope_match=False)).decision, IncidentDecision.FAIL_CLOSED)
        rec("IR-11", classify_incident(base(11, stop_latch=True)).decision, IncidentDecision.STOPPED)
        rec("IR-12", classify_incident(base(12, owner_gate=True)).decision, IncidentDecision.OWNER_REQUIRED)
        rec("IR-13", classify_incident(base(13, rollback_action_allowlisted=False)).decision, IncidentDecision.FAIL_CLOSED)
        rec("IR-14", classify_incident(base(14, requested_permissions=("local:rollback", "repo:write"))).decision, IncidentDecision.FAIL_CLOSED)
        rec("IR-15", classify_incident(base(15, rollback_external_effect=True)).decision, IncidentDecision.OWNER_REQUIRED)
        rec("IR-16", classify_incident(base(16, circuit_open=True)).decision, IncidentDecision.FAIL_CLOSED)

        before = callback_count
        duplicate = ledger.claim(safe, a)
        if duplicate.status is RollbackClaimStatus.CLAIMED_NEW:
            callback_count += 1
        rec("IR-17A", duplicate.status, RollbackClaimStatus.NOOP_ALREADY_SUCCEEDED)
        rec("IR-17B", callback_count, before)

        crash_e = base(18)
        crash_path = Path(td) / "crash.sqlite"
        crash_a = classify_incident(crash_e)
        first = DurableRollbackLedger(crash_path).claim(crash_e, crash_a)
        crash_callbacks = 1 if first.status is RollbackClaimStatus.CLAIMED_NEW else 0
        second = DurableRollbackLedger(crash_path).claim(crash_e, crash_a)
        if second.status is RollbackClaimStatus.CLAIMED_NEW:
            crash_callbacks += 1
        rec("IR-18A", second.status, RollbackClaimStatus.RECONCILE_REQUIRED)
        rec("IR-18B", crash_callbacks, 1)

        corrupt = Path(td) / "corrupt.sqlite"
        corrupt.write_bytes(b"not sqlite")
        blocked = False
        try:
            DurableRollbackLedger(corrupt)
        except sqlite3.DatabaseError:
            blocked = True
        rec("IR-19", "FAIL_CLOSED" if blocked else "NOT_BLOCKED", "FAIL_CLOSED")

        forbidden = {"dispatch", "merge", "revert", "send", "payment", "delete", "publish", "deploy", "create_grant", "grant"}
        names = {name for name, value in mod.__dict__.items() if callable(value)} | {
            name for name in dir(DurableRollbackLedger) if callable(getattr(DurableRollbackLedger, name, None))
        }
        found = sorted(names & forbidden)
        rec("IR-20", "NO_FORBIDDEN_EFFECT_SURFACE" if not found else str(found), "NO_FORBIDDEN_EFFECT_SURFACE")
        rec("IR-21", classify_incident(base(21, grant_reuse_attempt=True)).decision, IncidentDecision.FAIL_CLOSED)

        rng = random.Random(20260823)
        stress_bad = 0
        stress_allowed = 0
        for n in range(STRESS):
            e = base(
                1000 + (n % 1000),
                durable_claim_status=rng.choice(["FAILED_LOCAL", "FAILED_RETRYABLE", "CLAIMED", "SUCCEEDED", "UNKNOWN"]),
                downstream_outcome_status=rng.choice(["VERIFIED_NO_EXTERNAL_EFFECT", "UNKNOWN", "VERIFIED_SUCCESS", "CONFLICTING"]),
                source_health=rng.choice(["FRESH", "STALE", "UNKNOWN"]),
                source_fresh=rng.choice([True, False]),
                source_conflict=rng.choice([False, False, False, True]),
                stop_latch=rng.choice([False, False, False, True]),
                owner_gate=rng.choice([False, False, False, True]),
                rollback_action_allowlisted=rng.choice([True, True, False]),
                rollback_reversible=rng.choice([True, True, False]),
                rollback_external_effect=rng.choice([False, False, True]),
                external_effect_possible=rng.choice([False, False, True]),
                requested_permissions=rng.choice([("local:rollback",), ("local:rollback", "repo:write")]),
                retry_count=rng.choice([0, 1, 2]),
                retry_limit=rng.choice([1, 2]),
                circuit_open=rng.choice([False, False, True]),
                audit_integrity=rng.choice([True, True, True, False]),
                ledger_integrity=rng.choice([True, True, True, False]),
                identity_scope_match=rng.choice([True, True, True, False]),
                adapter_binding_match=rng.choice([True, True, True, False]),
                grant_reuse_attempt=rng.choice([False, False, False, True]),
            )
            actual_allowed = classify_incident(e).decision is IncidentDecision.LOCAL_ROLLBACK_ALLOWED
            expected_allowed = expected_safe(e)
            stress_allowed += int(actual_allowed)
            stress_bad += int(actual_allowed != expected_allowed)

        stress_e = base(99999)
        stress_a = classify_incident(stress_e)
        stress_ledger = DurableRollbackLedger(Path(td) / "stress.sqlite")
        first = stress_ledger.claim(stress_e, stress_a)
        duplicate_callbacks = 0
        if first.status is RollbackClaimStatus.CLAIMED_NEW:
            duplicate_callbacks += 1
            stress_ledger.mark_succeeded(first.scope_key, first.scope_sha256)
        duplicate_bad = 0
        for _ in range(10_000):
            r = stress_ledger.claim(stress_e, stress_a)
            if r.status is RollbackClaimStatus.CLAIMED_NEW:
                duplicate_callbacks += 1
            if r.status is not RollbackClaimStatus.NOOP_ALREADY_SUCCEEDED:
                duplicate_bad += 1

        audit = ledger.audit()
        seq = [row["seq"] for row in audit]
        audit_monotonic = seq == sorted(seq) and len(seq) == len(set(seq))
        required_events = {"ROLLBACK_CLAIMED", "ROLLBACK_SUCCEEDED", "ROLLBACK_DUPLICATE_NOOP"}
        audit_events = {row["event_type"] for row in audit}

        acceptance = {
            "contract_drive_id": CONTRACT_DRIVE_ID,
            "contract_sha256": CONTRACT_SHA256,
            "deterministic_cases_at_least_20": len(cases) >= 20,
            "deterministic_cases_all_pass": all(c["pass"] for c in cases),
            "stress_100000_classifier_mismatches": stress_bad,
            "stress_100000_allowed_count": stress_allowed,
            "duplicate_10000_invalid_results": duplicate_bad,
            "duplicate_callback_count_exactly_one": duplicate_callbacks == 1,
            "append_only_audit_monotonic": audit_monotonic,
            "required_audit_events_present": required_events.issubset(audit_events),
            "ledger_integrity": ledger.integrity_ok() and stress_ledger.integrity_ok(),
            "real_external_effects": 0,
            "authority_created": 0,
        }
        passed = (
            acceptance["deterministic_cases_at_least_20"]
            and acceptance["deterministic_cases_all_pass"]
            and stress_bad == 0
            and duplicate_bad == 0
            and acceptance["duplicate_callback_count_exactly_one"]
            and audit_monotonic
            and acceptance["required_audit_events_present"]
            and acceptance["ledger_integrity"]
        )

        report = {"status": "PASS" if passed else "FAIL", "cases": cases, "acceptance": acceptance}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"status": report["status"], "cases": len(cases), "acceptance": acceptance}, indent=2, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
