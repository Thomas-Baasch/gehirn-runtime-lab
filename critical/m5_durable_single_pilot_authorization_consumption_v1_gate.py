from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading

import governance.durable_single_pilot_authorization_consumption as consumption_module
from governance.durable_single_pilot_authorization_consumption import (
    ConsumptionStatus,
    DurableSinglePilotAuthorizationConsumptionLedger,
    VerifiedDispatchReceipt,
    authorization_scope_sha256,
)
from governance.m4_single_pilot_authority_boundary import (
    OwnerAuthorizationEvidence,
    PilotIntent,
    PreflightEvidence,
    validate_single_pilot_authority,
)

CONTRACT_DRIVE_ID = "10rzjvz-S90DGirZwkTd8VuezRC1fXGTQMvLudLzG8jI"
CONTRACT_SHA256 = "84a730a29b8e51dc5772c27083b8622750cc8c5be2e2c9ab76b1af4d8a6a1ca8"
OUT = Path("reports/continuation/m5_durable_single_pilot_authorization_consumption_v1.json")
STRESS = 10_000
BASE = datetime(2026, 8, 22, 12, 30, 0, tzinfo=timezone.utc)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def intent(index: int = 1, **changes) -> PilotIntent:
    values = dict(
        home_system="SYNTHETIC_HOME",
        work_id=f"work-consume-{index:03d}",
        dedupe_key=f"dedupe-consume-{index:03d}",
        target=f"synthetic-target-{index:03d}",
        target_adapter="SYNTHETIC_SINGLE_PILOT_ADAPTER_V1",
        adapter_contract_drive_id="synthetic-adapter-contract-v1",
        adapter_contract_sha256=sha("adapter-contract-v1"),
        action_class="INTERNAL_CONTINUE",
        expected_repository="Thomas-Baasch/synthetic-home",
        expected_workflow_id=4242,
        expected_event="workflow_dispatch",
        expected_ref="main",
        expected_head_sha=sha(f"head-{index}")[:40],
        exact_run_name_token=f"eg:work-consume-{index:03d}:dedupe-consume-{index:03d}",
        outcome_contract_drive_id="15JeNfaaHDAn4a9znqAvkB7DyOLbOGXHs7gbMs4V9e54",
        outcome_contract_sha256="d150621ba21b77f5251d343b5876f81ff63749410c2628c57a3ccf8ea30575fb",
        expected_artifact_name=f"safe-continuation-outcome-{index:03d}",
        expected_outcome_path="safe-continuation-outcome.json",
        outcome_schema="safe-continuation-outcome.v1",
        preflight_contract_drive_id="1pOcZzNBuEZwIFpAPc3JCduv27RsvL1P2P3-Bwc2kDrM",
        preflight_contract_sha256="0e05fb767927a72508556363a507a6261ddf0bc5c1c4b655c4d16953f4362c11",
    )
    values.update(changes)
    return PilotIntent(**values)


def preflight(index: int = 1) -> PreflightEvidence:
    return PreflightEvidence(
        status="READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT",
        observed_at=BASE,
        source_health="FRESH",
        preflight_contract_drive_id="1pOcZzNBuEZwIFpAPc3JCduv27RsvL1P2P3-Bwc2kDrM",
        preflight_contract_sha256="0e05fb767927a72508556363a507a6261ddf0bc5c1c4b655c4d16953f4362c11",
        snapshot_sha256=sha(f"preflight-{index}"),
    )


def grant(i: PilotIntent, p: PreflightEvidence, index: int = 1, **changes) -> OwnerAuthorizationEvidence:
    values = dict(
        source_kind="EXPLICIT_THOMAS_OWNER_AUTHORIZATION",
        authority_level="A5_OWNER_EXPLICIT_SINGLE_PILOT",
        verification_state="VERIFIED_OWNER_SOURCE",
        source_health="FRESH",
        source_ref=f"a0-owner-evidence:consume-{index:03d}",
        source_evidence_sha256=sha(f"owner-evidence-{index}"),
        source_verified_at=BASE + timedelta(seconds=30),
        grant_id=f"single-pilot-consume-{index:03d}",
        issued_at=BASE + timedelta(seconds=25),
        expires_at=BASE + timedelta(minutes=20),
        revoked=False,
        max_dispatches=1,
        used_dispatches=0,
        preflight_snapshot_sha256=p.snapshot_sha256,
        home_system=i.home_system,
        work_id=i.work_id,
        dedupe_key=i.dedupe_key,
        target=i.target,
        target_adapter=i.target_adapter,
        adapter_contract_drive_id=i.adapter_contract_drive_id,
        adapter_contract_sha256=i.adapter_contract_sha256,
        action_class=i.action_class,
        expected_repository=i.expected_repository,
        expected_workflow_id=i.expected_workflow_id,
        expected_event=i.expected_event,
        expected_ref=i.expected_ref,
        expected_head_sha=i.expected_head_sha,
        exact_run_name_token=i.exact_run_name_token,
        outcome_contract_drive_id=i.outcome_contract_drive_id,
        outcome_contract_sha256=i.outcome_contract_sha256,
        expected_artifact_name=i.expected_artifact_name,
        expected_outcome_path=i.expected_outcome_path,
        outcome_schema=i.outcome_schema,
        preflight_contract_drive_id=i.preflight_contract_drive_id,
        preflight_contract_sha256=i.preflight_contract_sha256,
    )
    values.update(changes)
    return OwnerAuthorizationEvidence(**values)


def valid_bundle(index: int = 1, **grant_changes):
    i = intent(index)
    p = preflight(index)
    g = grant(i, p, index, **grant_changes)
    as_of = BASE + timedelta(minutes=1)
    d = validate_single_pilot_authority(i, p, g, as_of=as_of)
    return i, p, g, d, as_of


def receipt(i: PilotIntent, g: OwnerAuthorizationEvidence, index: int = 1, **changes) -> VerifiedDispatchReceipt:
    values = dict(
        verification_state="VERIFIED_EXACT_DISPATCH_RECEIPT",
        source_health="FRESH",
        receipt_evidence_sha256=sha(f"dispatch-receipt-{index}"),
        grant_id=g.grant_id,
        authorization_scope_sha256=authorization_scope_sha256(i, g),
        home_system=i.home_system,
        work_id=i.work_id,
        dedupe_key=i.dedupe_key,
        target=i.target,
        downstream_run_id=f"run-consume-{index:03d}",
        expected_head_sha=i.expected_head_sha,
        receipt_source_ref=f"synthetic:verified-dispatch-receipt:{index:03d}",
    )
    values.update(changes)
    return VerifiedDispatchReceipt(**values)


def dbpath(root: str, name: str) -> str:
    return str(Path(root) / f"{name}.sqlite")


def main() -> int:
    cases: list[dict] = []

    def record(case_id: str, actual, expected, detail: str = "") -> None:
        av = actual.value if hasattr(actual, "value") else str(actual)
        ev = expected.value if hasattr(expected, "value") else str(expected)
        cases.append({"case": case_id, "actual": av, "expected": ev, "pass": av == ev, "detail": detail})

    with tempfile.TemporaryDirectory() as root:
        # CL-01 / CL-02 / CL-08: first claim, duplicate block, restart persistence.
        i1, p1, g1, d1, as1 = valid_bundle(1)
        path1 = dbpath(root, "cl01")
        ledger1 = DurableSinglePilotAuthorizationConsumptionLedger(path1)
        record("CL-01", ledger1.claim(i1, g1, d1, as_of=as1).status, ConsumptionStatus.CLAIMED_NEW)
        before_dup = ledger1.state(g1.grant_id)
        record("CL-02", ledger1.claim(i1, g1, d1, as_of=as1).status, ConsumptionStatus.RECONCILE_REQUIRED)
        after_dup = ledger1.state(g1.grant_id)
        restart = DurableSinglePilotAuthorizationConsumptionLedger(path1)
        restart_status = restart.claim(i1, g1, d1, as_of=as1).status
        cl08 = restart_status is ConsumptionStatus.RECONCILE_REQUIRED and restart.state(g1.grant_id) == after_dup == before_dup
        record("CL-08", "RESTART_BLOCKED_RECORD_PRESERVED" if cl08 else "FAIL", "RESTART_BLOCKED_RECORD_PRESERVED")

        # CL-03: same grant id, different exact authorized scope.
        i3 = intent(3, target="synthetic-target-003-changed")
        p3 = preflight(3)
        g3 = grant(i3, p3, 3, grant_id=g1.grant_id, source_evidence_sha256=g1.source_evidence_sha256)
        d3 = validate_single_pilot_authority(i3, p3, g3, as_of=as1)
        record("CL-03", ledger1.claim(i3, g3, d3, as_of=as1).status, ConsumptionStatus.SCOPE_CONFLICT_BLOCKED)

        # CL-04: a new grant id cannot relabel already-used owner evidence.
        i4 = intent(4)
        p4 = preflight(4)
        g4 = grant(i4, p4, 4, source_evidence_sha256=g1.source_evidence_sha256)
        d4 = validate_single_pilot_authority(i4, p4, g4, as_of=as1)
        record("CL-04", ledger1.claim(i4, g4, d4, as_of=as1).status, ConsumptionStatus.EVIDENCE_REUSE_BLOCKED)

        # CL-05: upstream authority decision must be exact VALID.
        i5, p5, g5, d5, as5 = valid_bundle(5)
        blocked_decision = replace(d5, valid=False)
        l5 = DurableSinglePilotAuthorizationConsumptionLedger(dbpath(root, "cl05"))
        record("CL-05", l5.claim(i5, g5, blocked_decision, as_of=as5).status, ConsumptionStatus.AUTHORITY_BLOCKED)

        # CL-06: revoked, expired and non-single-use all block before a record exists.
        cl06_ok = True
        for suffix, changes, check_time in (
            ("revoked", {"revoked": True}, BASE + timedelta(minutes=1)),
            ("expired", {"expires_at": BASE + timedelta(seconds=40)}, BASE + timedelta(minutes=1)),
            ("multi", {"max_dispatches": 2}, BASE + timedelta(minutes=1)),
        ):
            ix = 60 + len(suffix)
            ii = intent(ix); pp = preflight(ix); gg = grant(ii, pp, ix, **changes)
            dd = validate_single_pilot_authority(ii, pp, gg, as_of=check_time)
            ll = DurableSinglePilotAuthorizationConsumptionLedger(dbpath(root, f"cl06-{suffix}"))
            if ll.claim(ii, gg, dd, as_of=check_time).status is not ConsumptionStatus.AUTHORITY_BLOCKED or ll.state(gg.grant_id) is not None:
                cl06_ok = False
        record("CL-06", "AUTHORITY_BLOCKED_NO_RECORD" if cl06_ok else "FAIL", "AUTHORITY_BLOCKED_NO_RECORD")

        # CL-07: two independent ledger instances race for the same grant.
        i7, p7, g7, d7, as7 = valid_bundle(7)
        path7 = dbpath(root, "cl07")
        a = DurableSinglePilotAuthorizationConsumptionLedger(path7)
        b = DurableSinglePilotAuthorizationConsumptionLedger(path7)
        barrier = threading.Barrier(2)
        results: list[ConsumptionStatus] = []
        lock = threading.Lock()

        def contender(ledger):
            barrier.wait()
            result = ledger.claim(i7, g7, d7, as_of=as7).status
            with lock:
                results.append(result)

        t1 = threading.Thread(target=contender, args=(a,)); t2 = threading.Thread(target=contender, args=(b,))
        t1.start(); t2.start(); t1.join(); t2.join()
        cl07 = results.count(ConsumptionStatus.CLAIMED_NEW) == 1 and results.count(ConsumptionStatus.RECONCILE_REQUIRED) == 1
        record("CL-07", "ONE_CLAIM_ONE_BLOCK" if cl07 else str([r.value for r in results]), "ONE_CLAIM_ONE_BLOCK")

        # CL-09/10/11: consume exact, replay idempotent, conflicting replay blocked.
        i9, p9, g9, d9, as9 = valid_bundle(9)
        l9 = DurableSinglePilotAuthorizationConsumptionLedger(dbpath(root, "cl09"))
        l9.claim(i9, g9, d9, as_of=as9)
        r9 = receipt(i9, g9, 9)
        record("CL-09", l9.consume(r9).status, ConsumptionStatus.CONSUMED)
        consumed_record = l9.state(g9.grant_id)
        record("CL-10", l9.consume(r9).status, ConsumptionStatus.NOOP_ALREADY_CONSUMED)
        conflict = replace(r9, downstream_run_id="different-run", receipt_evidence_sha256=sha("different-receipt"))
        record("CL-11", l9.consume(conflict).status, ConsumptionStatus.CONFLICT_BLOCKED)
        consumed_preserved = l9.state(g9.grant_id) == consumed_record

        # CL-12: mismatched receipt never consumes and makes uncertainty sticky.
        i12, p12, g12, d12, as12 = valid_bundle(12)
        l12 = DurableSinglePilotAuthorizationConsumptionLedger(dbpath(root, "cl12"))
        l12.claim(i12, g12, d12, as_of=as12)
        bad12 = replace(receipt(i12, g12, 12), target="wrong-target")
        s12 = l12.consume(bad12).status
        state12 = l12.state(g12.grant_id)
        cl12 = s12 is ConsumptionStatus.SCOPE_CONFLICT_BLOCKED and state12 is not None and state12.status == "RECONCILE_REQUIRED"
        record("CL-12", "SCOPE_CONFLICT_AND_RECONCILE" if cl12 else "FAIL", "SCOPE_CONFLICT_AND_RECONCILE")

        # CL-13: explicit uncertainty remains sticky and blocks a new claim.
        i13, p13, g13, d13, as13 = valid_bundle(13)
        l13 = DurableSinglePilotAuthorizationConsumptionLedger(dbpath(root, "cl13"))
        l13.claim(i13, g13, d13, as_of=as13)
        mark13 = l13.mark_reconcile_required(g13.grant_id, "synthetic_uncertain_after_claim")
        retry13 = l13.claim(i13, g13, d13, as_of=as13)
        cl13 = mark13.status is ConsumptionStatus.RECONCILE_REQUIRED and retry13.status is ConsumptionStatus.RECONCILE_REQUIRED and l13.state(g13.grant_id).status == "RECONCILE_REQUIRED"
        record("CL-13", "RECONCILE_STICKY" if cl13 else "FAIL", "RECONCILE_STICKY")

        # CL-14: corrupt SQLite fails closed before any claim/consume can succeed.
        corrupt = Path(root) / "cl14.sqlite"
        corrupt.write_bytes(b"not-a-sqlite-database")
        corrupt_blocked = False
        try:
            DurableSinglePilotAuthorizationConsumptionLedger(corrupt)
        except sqlite3.DatabaseError:
            corrupt_blocked = True
        record("CL-14", "FAIL_CLOSED" if corrupt_blocked else "NOT_BLOCKED", "FAIL_CLOSED")

        # CL-15: audit append-only includes claim/block/consume/reconcile events.
        i15, p15, g15, d15, as15 = valid_bundle(15)
        l15 = DurableSinglePilotAuthorizationConsumptionLedger(dbpath(root, "cl15"))
        l15.claim(i15, g15, d15, as_of=as15)
        l15.claim(i15, g15, d15, as_of=as15)
        l15.mark_reconcile_required(g15.grant_id, "synthetic-audit-reconcile")
        l15.consume(receipt(i15, g15, 15))
        audit15 = l15.audit()
        events15 = [e["event_type"] for e in audit15]
        seq15 = [e["seq"] for e in audit15]
        cl15 = seq15 == sorted(seq15) and len(set(seq15)) == len(seq15) and {"CLAIMED", "CLAIM_PRESENT_BLOCKED", "RECONCILE_REQUIRED", "CONSUMED"}.issubset(events15)
        record("CL-15", "APPEND_ONLY_REQUIRED_EVENTS" if cl15 else str(events15), "APPEND_ONLY_REQUIRED_EVENTS")

        # CL-16: 10k claims over 100 unique grants => exactly 100 first claims.
        l16 = DurableSinglePilotAuthorizationConsumptionLedger(dbpath(root, "cl16"))
        bundles = [valid_bundle(1000 + j) for j in range(100)]
        first_claims = 0
        invalid_stress = 0
        for n in range(STRESS):
            ii, pp, gg, dd, aa = bundles[n % 100]
            status = l16.claim(ii, gg, dd, as_of=aa).status
            if status is ConsumptionStatus.CLAIMED_NEW:
                first_claims += 1
            elif status is not ConsumptionStatus.RECONCILE_REQUIRED:
                invalid_stress += 1
        cl16 = first_claims == 100 and invalid_stress == 0 and l16.integrity_ok()
        record("CL-16", f"FIRST={first_claims};INVALID={invalid_stress}", "FIRST=100;INVALID=0")

        # CL-17: 10k restart/recheck attempts do not mutate CLAIMED/CONSUMED records.
        i17a, p17a, g17a, d17a, as17a = valid_bundle(1701)
        i17b, p17b, g17b, d17b, as17b = valid_bundle(1702)
        path17 = dbpath(root, "cl17")
        l17 = DurableSinglePilotAuthorizationConsumptionLedger(path17)
        l17.claim(i17a, g17a, d17a, as_of=as17a)
        l17.claim(i17b, g17b, d17b, as_of=as17b)
        l17.consume(receipt(i17b, g17b, 1702))
        before17a = l17.state(g17a.grant_id); before17b = l17.state(g17b.grant_id)
        cl17 = True
        for n in range(STRESS):
            reopened = DurableSinglePilotAuthorizationConsumptionLedger(path17)
            if n % 2 == 0:
                status = reopened.claim(i17a, g17a, d17a, as_of=as17a).status
                if status is not ConsumptionStatus.RECONCILE_REQUIRED:
                    cl17 = False; break
            else:
                status = reopened.claim(i17b, g17b, d17b, as_of=as17b).status
                if status is not ConsumptionStatus.NOOP_ALREADY_CONSUMED:
                    cl17 = False; break
        after17a = l17.state(g17a.grant_id); after17b = l17.state(g17b.grant_id)
        cl17 = cl17 and before17a == after17a and before17b == after17b and consumed_preserved
        record("CL-17", "RECORDS_UNCHANGED" if cl17 else "FAIL", "RECORDS_UNCHANGED")

        # CL-18: no real-effect surface exists.
        forbidden = {"dispatch", "execute", "rerun", "cancel", "merge", "send", "payment", "delete", "publish", "create_grant", "grant"}
        module_callables = {name for name, value in consumption_module.__dict__.items() if callable(value)}
        class_callables = {name for name in dir(DurableSinglePilotAuthorizationConsumptionLedger) if callable(getattr(DurableSinglePilotAuthorizationConsumptionLedger, name, None))}
        forbidden_found = sorted((module_callables | class_callables) & forbidden)
        record("CL-18", "NO_FORBIDDEN_EFFECT_SURFACE" if not forbidden_found else str(forbidden_found), "NO_FORBIDDEN_EFFECT_SURFACE")

        acceptance = {
            "deterministic_18_of_18": len(cases) == 18 and all(c["pass"] for c in cases),
            "sqlite_integrity": ledger1.integrity_ok() and l9.integrity_ok() and l16.integrity_ok() and l17.integrity_ok(),
            "concurrent_exactly_one_first_claim": cl07,
            "restart_claim_stays_blocked": cl08,
            "stress_10000_exactly_100_first_claims": cl16,
            "stress_10000_records_unchanged": cl17,
            "consumed_record_not_downgraded": consumed_preserved,
            "no_real_dispatch_surface": not forbidden_found,
            "real_owner_grant_present": False,
            "real_dispatch_authority_not_granted": True,
        }

    passed = all(acceptance.values())
    report = {
        "schema": "externes-gehirn.m5-durable-single-pilot-authorization-consumption",
        "version": "0.1.0",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256},
        "cases": cases,
        "stress": {"claims": STRESS, "unique_grants": 100, "first_claims": first_claims, "invalid_results": invalid_stress},
        "acceptance": acceptance,
        "result": "PASS" if passed else "FAIL",
        "qualification": "M5_DURABLE_SINGLE_PILOT_AUTHORIZATION_CONSUMPTION_V1_PARTIAL_PASS" if passed else "NOT_QUALIFIED",
        "m4_overall": "NOT_COMPLETE",
        "m5_overall": "PARTIAL_NOT_COMPLETE",
        "real_owner_grant_present": False,
        "real_dispatch_authority": "NOT_GRANTED",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
