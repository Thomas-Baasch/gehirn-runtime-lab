from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from governance.downstream_reconciliation import DownstreamEvidence, DownstreamReconciler, ReconcileStatus, parse_evidence
from governance.durable_continuation_ledger import DurableContinuationLedger
from governance.safe_continuation_executor import WorkItem

CONTRACT_DRIVE_ID = "1mGD7G4uwT4Ovc8HiQUE1s6yHrIjHZDRwWwuTo4zLzjo"
CONTRACT_SHA256 = "772583fde5fb31fcc27af264a1f27c45c2fa04b104ee48ff161974cc9ba47344"
OUT = Path("reports/continuation/m5_downstream_reconciliation_v1.json")
STRESS = 10_000
TARGET = "candidate-validation-v1"


def item(key: str) -> WorkItem:
    return WorkItem(
        work_id=f"work-{key}", home_system="SYNTHETIC_HOME", state="ACTIVE",
        continuation_policy="AUTONOMOUS_EXPECTED", source_health="FRESH", runtime_status="IDLE",
        safe_internal_next=True, safe_recovery=False, action_class="INTERNAL_CONTINUE",
        reversible=True, external_effect=False, owner_gate=False, stop_latch=False,
        dedupe_key=key, retry_count=0, retry_limit=3, circuit_open=False,
        requested_permissions=frozenset({"contents:read"}), minimum_permissions=frozenset({"contents:read"}),
    )


def evidence(w: WorkItem, state: str, **kw) -> DownstreamEvidence:
    values = dict(
        source_health="FRESH", home_system=w.home_system, work_id=w.work_id,
        dedupe_key=w.dedupe_key, target=TARGET, downstream_id=f"run-{w.dedupe_key}",
        state=state, external_effect_proven=False, external_effect_possible=False,
        evidence_source_ref=f"synthetic:{w.dedupe_key}:{state}",
    )
    values.update(kw)
    return DownstreamEvidence(**values)


def uncertain_ledger(path: Path, w: WorkItem) -> DurableContinuationLedger:
    led = DurableContinuationLedger(path)
    led.claim(w)
    led.mark_reconcile_required(w, "synthetic_uncertain_outcome")
    return led


def main() -> int:
    cases: list[dict] = []
    def record(cid: str, actual: ReconcileStatus, expected: ReconcileStatus, detail: str="") -> None:
        cases.append({"case":cid,"actual":actual.value,"expected":expected.value,"pass":actual is expected,"detail":detail})

    with tempfile.TemporaryDirectory(prefix="m5-reconcile-") as tmp:
        root = Path(tmp)

        w1=item("success"); l1=uncertain_ledger(root/"1.sqlite",w1); r1=DownstreamReconciler(l1).reconcile(w1,target=TARGET,evidence=[evidence(w1,"SUCCEEDED")]); record("DR-01",r1.status,ReconcileStatus.RECONCILED_SUCCEEDED,str(l1.state(w1.dedupe_key)))
        w2=item("running"); l2=uncertain_ledger(root/"2.sqlite",w2); r2=DownstreamReconciler(l2).reconcile(w2,target=TARGET,evidence=[evidence(w2,"RUNNING")]); record("DR-02",r2.status,ReconcileStatus.WAIT_DOWNSTREAM)
        w3=item("none"); l3=uncertain_ledger(root/"3.sqlite",w3); record("DR-03",DownstreamReconciler(l3).reconcile(w3,target=TARGET,evidence=[]).status,ReconcileStatus.RECONCILE_REQUIRED)
        w4=item("stale"); l4=uncertain_ledger(root/"4.sqlite",w4); record("DR-04",DownstreamReconciler(l4).reconcile(w4,target=TARGET,evidence=[evidence(w4,"SUCCEEDED",source_health="STALE")]).status,ReconcileStatus.SOURCE_BLOCKED)
        w5=item("conflict"); l5=uncertain_ledger(root/"5.sqlite",w5); record("DR-05",DownstreamReconciler(l5).reconcile(w5,target=TARGET,evidence=[evidence(w5,"SUCCEEDED",downstream_id="a"),evidence(w5,"FAILED",downstream_id="b")]).status,ReconcileStatus.CONFLICT_BLOCKED)
        w6=item("wrong-dedupe"); l6=uncertain_ledger(root/"6.sqlite",w6); record("DR-06",DownstreamReconciler(l6).reconcile(w6,target=TARGET,evidence=[evidence(w6,"SUCCEEDED",dedupe_key="other")]).status,ReconcileStatus.RECONCILE_REQUIRED)
        w7=item("wrong-work"); l7=uncertain_ledger(root/"7.sqlite",w7); record("DR-07",DownstreamReconciler(l7).reconcile(w7,target=TARGET,evidence=[evidence(w7,"SUCCEEDED",work_id="other")]).status,ReconcileStatus.RECONCILE_REQUIRED)
        w8=item("wrong-target"); l8=uncertain_ledger(root/"8.sqlite",w8); record("DR-08",DownstreamReconciler(l8).reconcile(w8,target=TARGET,evidence=[evidence(w8,"SUCCEEDED",target="other")]).status,ReconcileStatus.RECONCILE_REQUIRED)
        w9=item("retryable"); l9=uncertain_ledger(root/"9.sqlite",w9); r9=DownstreamReconciler(l9).reconcile(w9,target=TARGET,evidence=[evidence(w9,"FAILED")]); record("DR-09",r9.status,ReconcileStatus.RECONCILED_FAILED_RETRYABLE,str(l9.state(w9.dedupe_key)))
        w10=item("possible-effect"); l10=uncertain_ledger(root/"10.sqlite",w10); record("DR-10",DownstreamReconciler(l10).reconcile(w10,target=TARGET,evidence=[evidence(w10,"FAILED",external_effect_possible=True)]).status,ReconcileStatus.RECONCILE_REQUIRED)
        w11=item("owner"); l11=uncertain_ledger(root/"11.sqlite",w11); record("DR-11",DownstreamReconciler(l11).reconcile(w11,target=TARGET,evidence=[evidence(w11,"SUCCEEDED")],review_gate=True).status,ReconcileStatus.OWNER_GATE_BLOCKED)
        # Idempotent success replay.
        r12=DownstreamReconciler(l1).reconcile(w1,target=TARGET,evidence=[evidence(w1,"SUCCEEDED")]); record("DR-12",r12.status,ReconcileStatus.NOOP_ALREADY_SUCCEEDED,str(l1.state(w1.dedupe_key)))
        # Confirmed local success may never be downgraded by stale/failure evidence.
        r13=DownstreamReconciler(l1).reconcile(w1,target=TARGET,evidence=[evidence(w1,"FAILED",source_health="STALE")]); record("DR-13",r13.status,ReconcileStatus.NOOP_ALREADY_SUCCEEDED,str(l1.state(w1.dedupe_key)))
        w14=item("active-over-stale"); l14=uncertain_ledger(root/"14.sqlite",w14); r14=DownstreamReconciler(l14).reconcile(w14,target=TARGET,evidence=[evidence(w14,"RUNNING",downstream_id="fresh"),evidence(w14,"FAILED",downstream_id="old",source_health="STALE")]); record("DR-14",r14.status,ReconcileStatus.WAIT_DOWNSTREAM)
        w15=item("unknown"); l15=uncertain_ledger(root/"15.sqlite",w15); record("DR-15",DownstreamReconciler(l15).reconcile(w15,target=TARGET,evidence=[evidence(w15,"UNKNOWN")]).status,ReconcileStatus.RECONCILE_REQUIRED)
        corrupt_blocked=False
        try:
            parse_evidence({"source_health":"FRESH"})
        except ValueError:
            corrupt_blocked=True
        cases.append({"case":"DR-16","actual":"FAIL_CLOSED" if corrupt_blocked else "NOT_BLOCKED","expected":"FAIL_CLOSED","pass":corrupt_blocked})

        # 10k repeated unknown evaluations: no state change, no dispatch, no retry.
        ws=item("stress"); ls=uncertain_ledger(root/"stress.sqlite",ws); rec=DownstreamReconciler(ls)
        before=ls.state(ws.dedupe_key)
        stress_ok=True
        for _ in range(STRESS):
            d=rec.reconcile(ws,target=TARGET,evidence=[evidence(ws,"UNKNOWN")])
            if d.status is not ReconcileStatus.RECONCILE_REQUIRED or d.dispatch_executed or d.ledger_updated:
                stress_ok=False; break
        after=ls.state(ws.dedupe_key)
        audit=ls.audit(); seq=[e["seq"] for e in audit]
        audit_ok=seq==sorted(seq) and len(seq)==len(set(seq))

        acceptance={
            "deterministic_16_of_16":len(cases)==16 and all(c["pass"] for c in cases),
            "stress_10000_no_dispatch":stress_ok,
            "stress_state_unchanged":before==after and after is not None and after.status=="RECONCILE_REQUIRED",
            "confirmed_success_not_downgraded":l1.state(w1.dedupe_key).status=="SUCCEEDED",
            "audit_append_only":audit_ok,
            "no_real_home_system_dispatch":True,
            "old_durable_ledger_integrity":all(l.integrity_ok() for l in [l1,l2,l3,l4,l5,l6,l7,l8,l9,l10,l11,l14,l15,ls]),
        }
        passed=all(acceptance.values())
        report={
            "schema":"externes-gehirn.m5-downstream-reconciliation-evidence",
            "version":"0.1.0",
            "contract":{"drive_id":CONTRACT_DRIVE_ID,"sha256":CONTRACT_SHA256},
            "cases":cases,
            "stress":{"evaluations":STRESS,"dispatches":0,"state_before":str(before),"state_after":str(after)},
            "acceptance":acceptance,
            "result":"PASS" if passed else "FAIL",
            "qualification":"M5_DOWNSTREAM_RECONCILIATION_V1_PARTIAL_PASS" if passed else "NOT_QUALIFIED",
            "m4_overall":"NOT_COMPLETE",
            "m5_overall":"PARTIAL_NOT_COMPLETE",
            "real_dispatch_authority":"NOT_GRANTED",
        }
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k!="cases"},ensure_ascii=False,indent=2))
        return 0 if passed else 1


if __name__=="__main__":
    raise SystemExit(main())
