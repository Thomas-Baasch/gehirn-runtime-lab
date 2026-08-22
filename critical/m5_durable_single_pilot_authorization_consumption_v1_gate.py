from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading

import governance.durable_single_pilot_authorization_consumption as mod
from governance.durable_single_pilot_authorization_consumption import (
    ConsumptionStatus,
    DurableSinglePilotAuthorizationConsumptionLedger as Ledger,
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
BASE = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)


def h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def make_intent(n: int, **kw) -> PilotIntent:
    d = dict(
        home_system="SYNTHETIC_HOME", work_id=f"work-{n}", dedupe_key=f"dedupe-{n}",
        target=f"target-{n}", target_adapter="SYNTHETIC_SINGLE_PILOT_ADAPTER_V1",
        adapter_contract_drive_id="synthetic-adapter-contract-v1", adapter_contract_sha256=h("adapter"),
        action_class="INTERNAL_CONTINUE", expected_repository="Thomas-Baasch/synthetic-home",
        expected_workflow_id=4242, expected_event="workflow_dispatch", expected_ref="main",
        expected_head_sha=h(f"head-{n}")[:40], exact_run_name_token=f"eg:work-{n}:dedupe-{n}",
        outcome_contract_drive_id="15JeNfaaHDAn4a9znqAvkB7DyOLbOGXHs7gbMs4V9e54",
        outcome_contract_sha256="d150621ba21b77f5251d343b5876f81ff63749410c2628c57a3ccf8ea30575fb",
        expected_artifact_name=f"outcome-{n}", expected_outcome_path="safe-continuation-outcome.json",
        outcome_schema="safe-continuation-outcome.v1",
        preflight_contract_drive_id="1pOcZzNBuEZwIFpAPc3JCduv27RsvL1P2P3-Bwc2kDrM",
        preflight_contract_sha256="0e05fb767927a72508556363a507a6261ddf0bc5c1c4b655c4d16953f4362c11",
    )
    d.update(kw)
    return PilotIntent(**d)


def make_preflight(n: int) -> PreflightEvidence:
    return PreflightEvidence(
        status="READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT", observed_at=BASE, source_health="FRESH",
        preflight_contract_drive_id="1pOcZzNBuEZwIFpAPc3JCduv27RsvL1P2P3-Bwc2kDrM",
        preflight_contract_sha256="0e05fb767927a72508556363a507a6261ddf0bc5c1c4b655c4d16953f4362c11",
        snapshot_sha256=h(f"preflight-{n}"),
    )


def make_grant(i: PilotIntent, p: PreflightEvidence, n: int, **kw) -> OwnerAuthorizationEvidence:
    d = dict(
        source_kind="EXPLICIT_THOMAS_OWNER_AUTHORIZATION", authority_level="A5_OWNER_EXPLICIT_SINGLE_PILOT",
        verification_state="VERIFIED_OWNER_SOURCE", source_health="FRESH", source_ref=f"a0:grant:{n}",
        source_evidence_sha256=h(f"owner-evidence-{n}"), source_verified_at=BASE + timedelta(seconds=30),
        grant_id=f"grant-{n}", issued_at=BASE + timedelta(seconds=25), expires_at=BASE + timedelta(minutes=20),
        revoked=False, max_dispatches=1, used_dispatches=0, preflight_snapshot_sha256=p.snapshot_sha256,
        home_system=i.home_system, work_id=i.work_id, dedupe_key=i.dedupe_key, target=i.target,
        target_adapter=i.target_adapter, adapter_contract_drive_id=i.adapter_contract_drive_id,
        adapter_contract_sha256=i.adapter_contract_sha256, action_class=i.action_class,
        expected_repository=i.expected_repository, expected_workflow_id=i.expected_workflow_id,
        expected_event=i.expected_event, expected_ref=i.expected_ref, expected_head_sha=i.expected_head_sha,
        exact_run_name_token=i.exact_run_name_token, outcome_contract_drive_id=i.outcome_contract_drive_id,
        outcome_contract_sha256=i.outcome_contract_sha256, expected_artifact_name=i.expected_artifact_name,
        expected_outcome_path=i.expected_outcome_path, outcome_schema=i.outcome_schema,
        preflight_contract_drive_id=i.preflight_contract_drive_id,
        preflight_contract_sha256=i.preflight_contract_sha256,
    )
    d.update(kw)
    return OwnerAuthorizationEvidence(**d)


def bundle(n: int, **grant_kw):
    i = make_intent(n); p = make_preflight(n); g = make_grant(i, p, n, **grant_kw)
    as_of = BASE + timedelta(minutes=1)
    return i, p, g, validate_single_pilot_authority(i, p, g, as_of=as_of), as_of


def make_receipt(i: PilotIntent, g: OwnerAuthorizationEvidence, n: int, **kw) -> VerifiedDispatchReceipt:
    d = dict(
        verification_state="VERIFIED_EXACT_DISPATCH_RECEIPT", source_health="FRESH",
        receipt_evidence_sha256=h(f"receipt-{n}"), grant_id=g.grant_id,
        authorization_scope_sha256=authorization_scope_sha256(i, g), home_system=i.home_system,
        work_id=i.work_id, dedupe_key=i.dedupe_key, target=i.target, downstream_run_id=f"run-{n}",
        expected_head_sha=i.expected_head_sha, receipt_source_ref=f"synthetic:receipt:{n}",
    )
    d.update(kw)
    return VerifiedDispatchReceipt(**d)


def main() -> int:
    cases = []
    def rec(cid, actual, expected, detail=""):
        av = actual.value if hasattr(actual, "value") else str(actual)
        ev = expected.value if hasattr(expected, "value") else str(expected)
        cases.append({"case": cid, "actual": av, "expected": ev, "pass": av == ev, "detail": detail})

    with tempfile.TemporaryDirectory() as td:
        def path(name): return str(Path(td) / f"{name}.sqlite")

        # CL-01,02,08
        i1,p1,g1,d1,t1 = bundle(1); l1 = Ledger(path("a"))
        rec("CL-01", l1.claim(i1,g1,d1,as_of=t1).status, ConsumptionStatus.CLAIMED_NEW)
        snap1 = l1.state(g1.grant_id)
        rec("CL-02", l1.claim(i1,g1,d1,as_of=t1).status, ConsumptionStatus.RECONCILE_REQUIRED)
        reopened = Ledger(path("a")); s8 = reopened.claim(i1,g1,d1,as_of=t1).status
        rec("CL-08", "RESTART_BLOCKED_RECORD_PRESERVED" if s8 is ConsumptionStatus.RECONCILE_REQUIRED and reopened.state(g1.grant_id)==snap1 else "FAIL", "RESTART_BLOCKED_RECORD_PRESERVED")

        # CL-03
        i3 = make_intent(3, target="changed-target"); p3 = make_preflight(3)
        g3 = make_grant(i3,p3,3,grant_id=g1.grant_id,source_evidence_sha256=g1.source_evidence_sha256)
        d3 = validate_single_pilot_authority(i3,p3,g3,as_of=t1)
        rec("CL-03", l1.claim(i3,g3,d3,as_of=t1).status, ConsumptionStatus.SCOPE_CONFLICT_BLOCKED)

        # CL-04
        i4,p4,g4,d4,t4 = bundle(4); g4 = replace(g4, source_evidence_sha256=g1.source_evidence_sha256)
        d4 = validate_single_pilot_authority(i4,p4,g4,as_of=t4)
        rec("CL-04", l1.claim(i4,g4,d4,as_of=t4).status, ConsumptionStatus.EVIDENCE_REUSE_BLOCKED)

        # CL-05
        i5,p5,g5,d5,t5 = bundle(5); l5 = Ledger(path("e"))
        rec("CL-05", l5.claim(i5,g5,replace(d5,valid=False),as_of=t5).status, ConsumptionStatus.AUTHORITY_BLOCKED)

        # CL-06
        ok6=True
        for n,kw,when in [(61,{"revoked":True},BASE+timedelta(minutes=1)),(62,{"expires_at":BASE+timedelta(seconds=40)},BASE+timedelta(minutes=1)),(63,{"max_dispatches":2},BASE+timedelta(minutes=1))]:
            i=make_intent(n); p=make_preflight(n); g=make_grant(i,p,n,**kw); d=validate_single_pilot_authority(i,p,g,as_of=when); l=Ledger(path(f"f{n}"))
            ok6 &= l.claim(i,g,d,as_of=when).status is ConsumptionStatus.AUTHORITY_BLOCKED and l.state(g.grant_id) is None
        rec("CL-06", "AUTHORITY_BLOCKED_NO_RECORD" if ok6 else "FAIL", "AUTHORITY_BLOCKED_NO_RECORD")

        # CL-07
        i7,p7,g7,d7,t7=bundle(7); pth=path("race"); la,lb=Ledger(pth),Ledger(pth); barrier=threading.Barrier(2); results=[]; lock=threading.Lock()
        def race(l):
            barrier.wait(); r=l.claim(i7,g7,d7,as_of=t7).status
            with lock: results.append(r)
        a=threading.Thread(target=race,args=(la,)); b=threading.Thread(target=race,args=(lb,)); a.start(); b.start(); a.join(); b.join()
        ok7=results.count(ConsumptionStatus.CLAIMED_NEW)==1 and results.count(ConsumptionStatus.RECONCILE_REQUIRED)==1
        rec("CL-07", "ONE_CLAIM_ONE_BLOCK" if ok7 else str([x.value for x in results]), "ONE_CLAIM_ONE_BLOCK")

        # CL-09,10,11
        i9,p9,g9,d9,t9=bundle(9); l9=Ledger(path("consume")); l9.claim(i9,g9,d9,as_of=t9); r9=make_receipt(i9,g9,9)
        rec("CL-09", l9.consume(r9).status, ConsumptionStatus.CONSUMED); consumed=l9.state(g9.grant_id)
        rec("CL-10", l9.consume(r9).status, ConsumptionStatus.NOOP_ALREADY_CONSUMED)
        rec("CL-11", l9.consume(replace(r9,downstream_run_id="different",receipt_evidence_sha256=h("different"))).status, ConsumptionStatus.CONFLICT_BLOCKED)
        consumed_preserved=l9.state(g9.grant_id)==consumed

        # CL-12
        i12,p12,g12,d12,t12=bundle(12); l12=Ledger(path("mismatch")); l12.claim(i12,g12,d12,as_of=t12)
        s12=l12.consume(replace(make_receipt(i12,g12,12),target="wrong")).status; st12=l12.state(g12.grant_id)
        rec("CL-12", "SCOPE_CONFLICT_AND_RECONCILE" if s12 is ConsumptionStatus.SCOPE_CONFLICT_BLOCKED and st12 and st12.status=="RECONCILE_REQUIRED" else "FAIL", "SCOPE_CONFLICT_AND_RECONCILE")

        # CL-13
        i13,p13,g13,d13,t13=bundle(13); l13=Ledger(path("rec")); l13.claim(i13,g13,d13,as_of=t13)
        a13=l13.mark_reconcile_required(g13.grant_id,"uncertain").status; b13=l13.claim(i13,g13,d13,as_of=t13).status
        rec("CL-13", "RECONCILE_STICKY" if a13 is ConsumptionStatus.RECONCILE_REQUIRED and b13 is ConsumptionStatus.RECONCILE_REQUIRED and l13.state(g13.grant_id).status=="RECONCILE_REQUIRED" else "FAIL", "RECONCILE_STICKY")

        # CL-14
        corrupt=Path(td)/"corrupt.sqlite"; corrupt.write_bytes(b"not sqlite"); blocked=False
        try: Ledger(corrupt)
        except sqlite3.DatabaseError: blocked=True
        rec("CL-14", "FAIL_CLOSED" if blocked else "NOT_BLOCKED", "FAIL_CLOSED")

        # CL-15
        i15,p15,g15,d15,t15=bundle(15); l15=Ledger(path("audit")); l15.claim(i15,g15,d15,as_of=t15); l15.claim(i15,g15,d15,as_of=t15); l15.mark_reconcile_required(g15.grant_id,"uncertain"); l15.consume(make_receipt(i15,g15,15))
        audit=l15.audit(); seq=[x["seq"] for x in audit]; events={x["event_type"] for x in audit}
        ok15=seq==sorted(seq) and len(seq)==len(set(seq)) and {"CLAIMED","CLAIM_PRESENT_BLOCKED","RECONCILE_REQUIRED","CONSUMED"}.issubset(events)
        rec("CL-15", "APPEND_ONLY_REQUIRED_EVENTS" if ok15 else str(sorted(events)), "APPEND_ONLY_REQUIRED_EVENTS")

        # CL-16
        l16=Ledger(path("stress")); bundles=[bundle(1000+j) for j in range(100)]; first=bad=0
        for n in range(STRESS):
            i,p,g,d,t=bundles[n%100]; s=l16.claim(i,g,d,as_of=t).status
            if s is ConsumptionStatus.CLAIMED_NEW: first+=1
            elif s is not ConsumptionStatus.RECONCILE_REQUIRED: bad+=1
        ok16=first==100 and bad==0 and l16.integrity_ok(); rec("CL-16",f"FIRST={first};INVALID={bad}","FIRST=100;INVALID=0")

        # CL-17
        ia,pa,ga,da,ta=bundle(1701); ib,pb,gb,db,tb=bundle(1702); p17=path("restart"); l17=Ledger(p17); l17.claim(ia,ga,da,as_of=ta); l17.claim(ib,gb,db,as_of=tb); l17.consume(make_receipt(ib,gb,1702))
        ba,bb=l17.state(ga.grant_id),l17.state(gb.grant_id); ok17=True
        for n in range(STRESS):
            x=Ledger(p17) if n%100==0 else l17
            s=x.claim(ia,ga,da,as_of=ta).status if n%2==0 else x.claim(ib,gb,db,as_of=tb).status
            if (n%2==0 and s is not ConsumptionStatus.RECONCILE_REQUIRED) or (n%2==1 and s is not ConsumptionStatus.NOOP_ALREADY_CONSUMED): ok17=False; break
        ok17 &= l17.state(ga.grant_id)==ba and l17.state(gb.grant_id)==bb and consumed_preserved
        rec("CL-17","RECORDS_UNCHANGED" if ok17 else "FAIL","RECORDS_UNCHANGED")

        # CL-18
        forbidden={"dispatch","execute","rerun","cancel","merge","send","payment","delete","publish","create_grant","grant"}
        names={n for n,v in mod.__dict__.items() if callable(v)} | {n for n in dir(Ledger) if callable(getattr(Ledger,n,None))}; found=sorted(names&forbidden)
        rec("CL-18","NO_FORBIDDEN_EFFECT_SURFACE" if not found else str(found),"NO_FORBIDDEN_EFFECT_SURFACE")

        acceptance={
            "deterministic_18_of_18":len(cases)==18 and all(c["pass"] for c in cases),
            "sqlite_integrity":l1.integrity_ok() and l9.integrity_ok() and l16.integrity_ok() and l17.integrity_ok(),
            "concurrent_exactly_one_first_claim":ok7,
            "restart_claim_stays_blocked":s8 is ConsumptionStatus.RECONCILE_REQUIRED,
            "stress_10000_exactly_100_first_claims":ok16,
            "stress_10000_records_unchanged":ok17,
            "consumed_record_not_downgraded":consumed_preserved,
            "no_real_dispatch_surface":not found,
            "real_owner_grant_absent":True,
            "real_dispatch_authority_not_granted":True,
        }

    passed=all(acceptance.values())
    report={
        "schema":"externes-gehirn.m5-durable-single-pilot-authorization-consumption","version":"0.1.0",
        "contract":{"drive_id":CONTRACT_DRIVE_ID,"sha256":CONTRACT_SHA256},"cases":cases,
        "stress":{"claims":STRESS,"unique_grants":100,"first_claims":first,"invalid_results":bad},
        "acceptance":acceptance,"result":"PASS" if passed else "FAIL",
        "qualification":"M5_DURABLE_SINGLE_PILOT_AUTHORIZATION_CONSUMPTION_V1_PARTIAL_PASS" if passed else "NOT_QUALIFIED",
        "m4_overall":"NOT_COMPLETE","m5_overall":"PARTIAL_NOT_COMPLETE","real_owner_grant_present":False,"real_dispatch_authority":"NOT_GRANTED",
    }
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="cases"},ensure_ascii=False,indent=2))
    return 0 if passed else 1


if __name__=="__main__":
    raise SystemExit(main())
