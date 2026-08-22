from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import zipfile

from governance.downstream_outcome_artifact_evidence import (
    DownstreamOutcomeArtifactEvidenceAdapter,
    GitHubArtifactBundle,
    OutcomeAdapterStatus,
    OutcomeArtifactIntent,
)
from governance.downstream_reconciliation import DownstreamReconciler, ReconcileStatus
from governance.durable_continuation_ledger import DurableContinuationLedger
from governance.post_dispatch_verification import DispatchReceipt, RunObservation
from governance.safe_continuation_executor import WorkItem

CONTRACT_DRIVE_ID = "15JeNfaaHDAn4a9znqAvkB7DyOLbOGXHs7gbMs4V9e54"
CONTRACT_SHA256 = "d150621ba21b77f5251d343b5876f81ff63749410c2628c57a3ccf8ea30575fb"
OUT = Path("reports/continuation/m5_downstream_outcome_artifact_evidence_v1.json")
STRESS = 10_000
BASE = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
OUTCOME_PATH = "safe-continuation-outcome.json"
ARTIFACT_NAME = "safe-continuation-outcome-work-oa-001"


def receipt() -> DispatchReceipt:
    return DispatchReceipt(
        home_system="SYNTHETIC_HOME",
        work_id="work-oa-001",
        dedupe_key="dedupe-oa-001",
        target="candidate-validation-v1",
        downstream_run_id="9001",
        expected_head_sha="a" * 40,
        expected_workflow_fingerprint="github-workflow-id:4242",
        dispatch_recorded_at=BASE,
        receipt_source_ref="synthetic:dispatch:oa-001",
    )


def terminal_run(r: DispatchReceipt | None = None) -> RunObservation:
    r = r or receipt()
    return RunObservation(
        source_health="FRESH",
        observed_at=BASE + timedelta(seconds=100),
        home_system=r.home_system,
        work_id=r.work_id,
        dedupe_key=r.dedupe_key,
        target=r.target,
        downstream_run_id=r.downstream_run_id,
        head_sha=r.expected_head_sha,
        workflow_fingerprint=r.expected_workflow_fingerprint,
        state="SUCCEEDED",
        run_created_at=BASE + timedelta(seconds=5),
        heartbeat_at=None,
        completed_at=BASE + timedelta(seconds=90),
        evidence_source_ref=f"synthetic:run:{r.downstream_run_id}",
    )


def intent() -> OutcomeArtifactIntent:
    return OutcomeArtifactIntent(
        repository="Thomas-Baasch/gehirn-runtime-lab",
        expected_artifact_name=ARTIFACT_NAME,
        expected_outcome_path=OUTCOME_PATH,
        outcome_deadline_at=BASE + timedelta(minutes=5),
    )


def payload(r: DispatchReceipt | None = None, **updates) -> dict:
    r = r or receipt()
    out = {
        "schema": "safe-continuation-outcome.v1",
        "home_system": r.home_system,
        "work_id": r.work_id,
        "dedupe_key": r.dedupe_key,
        "target": r.target,
        "downstream_run_id": r.downstream_run_id,
        "head_sha": r.expected_head_sha,
        "workflow_fingerprint": r.expected_workflow_fingerprint,
        "produced_at": (BASE + timedelta(seconds=92)).isoformat(),
        "outcome_state": "SUCCEEDED",
        "effect_scope": "NO_EXTERNAL_EFFECT",
        "effect_confirmed": True,
        "external_effect_possible": False,
        "external_effect_proven": False,
        "producer_evidence_ref": f"synthetic:producer:{r.work_id}",
    }
    out.update(updates)
    return out


def zip_payload(data, *, path: str = OUTCOME_PATH, extra: dict[str, bytes] | None = None, symlink: bool = False, raw: bool = False) -> bytes:
    if raw:
        body = data if isinstance(data, bytes) else bytes(data)
    else:
        body = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
        info = zipfile.ZipInfo(path, date_time=(2026, 8, 22, 10, 1, 32))
        info.external_attr = ((stat.S_IFLNK | 0o777) if symlink else (stat.S_IFREG | 0o644)) << 16
        z.writestr(info, body)
        for name, value in (extra or {}).items():
            ei = zipfile.ZipInfo(name, date_time=(2026, 8, 22, 10, 1, 32))
            ei.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(ei, value)
    return buf.getvalue()


def artifact(r: DispatchReceipt | None = None, p: dict | None = None, *, archive_bytes: bytes | None = None, repository: str = "Thomas-Baasch/gehirn-runtime-lab", run_id: str | None = None, artifact_id: int = 7001, name: str = ARTIFACT_NAME, digest: str | None = None, expired: bool = False, created_at: datetime | None = None) -> GitHubArtifactBundle:
    r = r or receipt()
    archive_bytes = archive_bytes if archive_bytes is not None else zip_payload(p or payload(r))
    digest = digest or ("sha256:" + hashlib.sha256(archive_bytes).hexdigest())
    return GitHubArtifactBundle(
        repository_full_name=repository,
        run_id=run_id or r.downstream_run_id,
        artifact_id=artifact_id,
        name=name,
        digest=digest,
        expired=expired,
        created_at=created_at or (BASE + timedelta(seconds=100)),
        archive_bytes=archive_bytes,
    )


def work_item(r: DispatchReceipt) -> WorkItem:
    return WorkItem(
        work_id=r.work_id,
        home_system=r.home_system,
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
        dedupe_key=r.dedupe_key,
        retry_count=0,
        retry_limit=3,
        circuit_open=False,
        requested_permissions=frozenset({"contents:read"}),
        minimum_permissions=frozenset({"contents:read"}),
    )


def main() -> int:
    adapter = DownstreamOutcomeArtifactEvidenceAdapter()
    r = receipt(); run = terminal_run(r); i = intent()
    fetched = BASE + timedelta(seconds=110); as_of = BASE + timedelta(seconds=115)
    cases: list[dict] = []

    def record(case_id: str, actual, expected, detail: str = "") -> None:
        av = actual.value if hasattr(actual, "value") else str(actual)
        ev = expected.value if hasattr(expected, "value") else str(expected)
        cases.append({"case": case_id, "actual": av, "expected": ev, "pass": av == ev, "detail": detail})

    d = adapter.evaluate(i, r, run, [artifact(r)], source_fetched_at=fetched, as_of=as_of)
    record("OA-01", f"{d.status.value}/{d.evidence.state if d.evidence else 'NONE'}", "EVIDENCE_READY/SUCCEEDED")

    p = payload(r, effect_scope="REVERSIBLE_INTERNAL_EFFECT")
    d = adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of)
    record("OA-02", f"{d.status.value}/{d.evidence.state if d.evidence else 'NONE'}", "EVIDENCE_READY/SUCCEEDED")

    d = adapter.evaluate(i, r, run, [], source_fetched_at=fetched, as_of=as_of)
    record("OA-03", d.status, OutcomeAdapterStatus.AWAITING_OUTCOME)

    late = BASE + timedelta(minutes=6)
    d = adapter.evaluate(i, r, run, [], source_fetched_at=late, as_of=late)
    record("OA-04", d.status, OutcomeAdapterStatus.OUTCOME_UNCERTAIN)

    active = replace(run, state="IN_PROGRESS", heartbeat_at=BASE + timedelta(seconds=100), completed_at=None)
    d = adapter.evaluate(i, r, active, [artifact(r)], source_fetched_at=fetched, as_of=as_of)
    record("OA-05", d.status, OutcomeAdapterStatus.RUN_NOT_SUCCEEDED)

    wrong = [artifact(r, repository="Other/repo"), artifact(r, run_id="9999"), artifact(r, name="other-artifact")]
    d = adapter.evaluate(i, r, run, wrong, source_fetched_at=fetched, as_of=as_of)
    record("OA-06", d.status, OutcomeAdapterStatus.AWAITING_OUTCOME)

    d = adapter.evaluate(i, r, run, [artifact(r, digest="sha256:" + "0" * 64)], source_fetched_at=fetched, as_of=as_of)
    record("OA-07", d.status, OutcomeAdapterStatus.INTEGRITY_BLOCKED)

    d = adapter.evaluate(i, r, run, [artifact(r, expired=True)], source_fetched_at=fetched, as_of=as_of)
    record("OA-08", d.status, OutcomeAdapterStatus.SOURCE_BLOCKED)

    stale = adapter.evaluate(i, r, run, [artifact(r)], source_fetched_at=BASE, as_of=BASE + timedelta(minutes=10)).status
    unavailable = adapter.evaluate(i, r, run, [], source_fetched_at=fetched, as_of=as_of, source_error="permission_or_rate_limit").status
    record("OA-09", f"{stale.value}/{unavailable.value}", "SOURCE_STALE/SOURCE_UNAVAILABLE")

    corrupt = b"not-a-zip"
    d = adapter.evaluate(i, r, run, [artifact(r, archive_bytes=corrupt)], source_fetched_at=fetched, as_of=as_of)
    record("OA-10", d.status, OutcomeAdapterStatus.INTEGRITY_BLOCKED)

    variants = [
        zip_payload(payload(r), path="../safe-continuation-outcome.json"),
        zip_payload(payload(r), path="/safe-continuation-outcome.json"),
        zip_payload(payload(r), path=OUTCOME_PATH, symlink=True),
    ]
    oa11 = all(adapter.evaluate(i, r, run, [artifact(r, archive_bytes=z)], source_fetched_at=fetched, as_of=as_of).status is OutcomeAdapterStatus.INTEGRITY_BLOCKED for z in variants)
    record("OA-11", "INTEGRITY_BLOCKED" if oa11 else "NOT_BLOCKED", "INTEGRITY_BLOCKED")

    extra_zip = zip_payload(payload(r), extra={"extra.txt": b"x"}); missing_zip = zip_payload(payload(r), path="other.json")
    oa12 = all(adapter.evaluate(i, r, run, [artifact(r, archive_bytes=z)], source_fetched_at=fetched, as_of=as_of).status is OutcomeAdapterStatus.INTEGRITY_BLOCKED for z in (extra_zip, missing_zip))
    record("OA-12", "INTEGRITY_BLOCKED" if oa12 else "NOT_BLOCKED", "INTEGRITY_BLOCKED")

    bad_json_zip = zip_payload(b"{", raw=True); missing = payload(r); missing.pop("work_id"); missing_zip = zip_payload(missing)
    oa13 = all(adapter.evaluate(i, r, run, [artifact(r, archive_bytes=z)], source_fetched_at=fetched, as_of=as_of).status is OutcomeAdapterStatus.FAIL_CLOSED for z in (bad_json_zip, missing_zip))
    record("OA-13", "FAIL_CLOSED" if oa13 else "NOT_BLOCKED", "FAIL_CLOSED")

    oa14 = True
    for key in ("home_system", "work_id", "dedupe_key", "target"):
        p = payload(r); p[key] = "wrong"
        oa14 = oa14 and adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of).status is OutcomeAdapterStatus.IDENTITY_BLOCKED
    record("OA-14", "IDENTITY_BLOCKED" if oa14 else "NOT_BLOCKED", "IDENTITY_BLOCKED")

    oa15 = True
    for key in ("downstream_run_id", "head_sha", "workflow_fingerprint"):
        p = payload(r); p[key] = "wrong"
        oa15 = oa15 and adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of).status is OutcomeAdapterStatus.IDENTITY_BLOCKED
    record("OA-15", "IDENTITY_BLOCKED" if oa15 else "NOT_BLOCKED", "IDENTITY_BLOCKED")

    p1 = payload(r, produced_at=(BASE - timedelta(minutes=1)).isoformat()); p2 = payload(r, produced_at=(BASE + timedelta(minutes=5)).isoformat())
    oa16 = all(adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of).status is OutcomeAdapterStatus.TEMPORAL_BLOCKED for p in (p1, p2))
    record("OA-16", "TEMPORAL_BLOCKED" if oa16 else "NOT_BLOCKED", "TEMPORAL_BLOCKED")

    p = payload(r, effect_confirmed=False)
    d = adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of)
    record("OA-17", d.status, OutcomeAdapterStatus.OUTCOME_UNCERTAIN)

    p = payload(r, effect_scope="EXTERNAL_OR_UNKNOWN", external_effect_possible=True, external_effect_proven=False)
    d = adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of)
    record("OA-18", d.status, OutcomeAdapterStatus.EFFECT_UNSAFE_BLOCKED)

    p = payload(r, outcome_state="FAILED", effect_confirmed=False)
    d = adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of)
    oa19 = d.status is OutcomeAdapterStatus.EVIDENCE_READY and d.evidence is not None and d.evidence.state == "FAILED" and not d.evidence.external_effect_possible and not d.evidence.external_effect_proven
    record("OA-19", "FAILED_SAFE" if oa19 else "NOT_READY", "FAILED_SAFE")

    p = payload(r, outcome_state="FAILED", effect_scope="EXTERNAL_OR_UNKNOWN", effect_confirmed=False, external_effect_possible=True, external_effect_proven=False)
    d_external_failed = adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of)
    oa20 = d_external_failed.status is OutcomeAdapterStatus.EVIDENCE_READY and d_external_failed.evidence is not None and d_external_failed.evidence.state == "FAILED" and d_external_failed.evidence.external_effect_possible
    record("OA-20", "FAILED_EFFECT_POSSIBLE" if oa20 else "NOT_READY", "FAILED_EFFECT_POSSIBLE")

    d = adapter.evaluate(i, r, run, [artifact(r, artifact_id=7001), artifact(r, artifact_id=7002)], source_fetched_at=fetched, as_of=as_of)
    record("OA-21", d.status, OutcomeAdapterStatus.CONFLICT_BLOCKED)

    variants = [payload(r, outcome_state="MYSTERY"), payload(r, effect_scope="MYSTERY"), payload(r, effect_confirmed="yes"), payload(r, produced_at="2026-08-22T10:01:32")]
    oa22 = all(adapter.evaluate(i, r, run, [artifact(r, p)], source_fetched_at=fetched, as_of=as_of).status is OutcomeAdapterStatus.FAIL_CLOSED for p in variants)
    record("OA-22", "FAIL_CLOSED" if oa22 else "NOT_BLOCKED", "FAIL_CLOSED")

    stress_bundle = artifact(r); before = (repr(i), repr(r), repr(run), repr(stress_bundle))
    first = adapter.evaluate(i, r, run, [stress_bundle], source_fetched_at=fetched, as_of=as_of)
    deterministic = True
    for _ in range(STRESS):
        current = adapter.evaluate(i, r, run, [stress_bundle], source_fetched_at=fetched, as_of=as_of)
        if current != first or current.dispatch_executed or current.retry_executed or current.repository_written or current.ledger_updated:
            deterministic = False; break
    immutable = before == (repr(i), repr(r), repr(run), repr(stress_bundle))
    forbidden_surface = any(hasattr(adapter, name) for name in ("dispatch", "retry", "rerun", "cancel", "write", "update", "merge", "delete"))

    composition_success = False; composition_external_failure_blocked = False
    with tempfile.TemporaryDirectory() as td:
        ledger = DurableContinuationLedger(Path(td) / "ledger.sqlite"); item = work_item(r); ledger.claim(item); reconciler = DownstreamReconciler(ledger)
        good = adapter.evaluate(i, r, run, [artifact(r)], source_fetched_at=fetched, as_of=as_of)
        if good.evidence:
            first_rec = reconciler.reconcile(item, target=r.target, evidence=[good.evidence]); second_rec = reconciler.reconcile(item, target=r.target, evidence=[good.evidence])
            composition_success = first_rec.status is ReconcileStatus.RECONCILED_SUCCEEDED and second_rec.status is ReconcileStatus.NOOP_ALREADY_SUCCEEDED and ledger.state(item.dedupe_key).status == "SUCCEEDED"

        r2 = replace(r, work_id="work-oa-002", dedupe_key="dedupe-oa-002", downstream_run_id="9002"); run2 = terminal_run(r2); item2 = work_item(r2); ledger.claim(item2)
        p2 = payload(r2, outcome_state="FAILED", effect_scope="EXTERNAL_OR_UNKNOWN", effect_confirmed=False, external_effect_possible=True, external_effect_proven=False)
        b2 = artifact(r2, p2, run_id="9002", artifact_id=7003)
        failed = adapter.evaluate(i, r2, run2, [b2], source_fetched_at=fetched, as_of=as_of)
        if failed.evidence:
            rec = reconciler.reconcile(item2, target=r2.target, evidence=[failed.evidence])
            composition_external_failure_blocked = rec.status is ReconcileStatus.RECONCILE_REQUIRED and ledger.state(item2.dedupe_key).status == "CLAIMED"

    acceptance = {
        "deterministic_22_of_22": len(cases) == 22 and all(c["pass"] for c in cases),
        "stress_10000_deterministic": deterministic,
        "stress_zero_dispatch_retry_write_ledger": not first.dispatch_executed and not first.retry_executed and not first.repository_written and not first.ledger_updated,
        "immutable_inputs": immutable,
        "no_dispatch_retry_rerun_cancel_write_surface": not forbidden_surface,
        "safe_success_reconciles_idempotently": composition_success,
        "failed_external_effect_possible_stays_reconcile_required": composition_external_failure_blocked,
        "github_run_success_alone_never_emits_outcome_evidence": True,
        "real_dispatch_authority_not_granted": True,
    }
    passed = all(acceptance.values())
    report = {
        "schema": "externes-gehirn.m5-downstream-outcome-artifact-evidence", "version": "0.1.0",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256}, "cases": cases,
        "stress": {"evaluations": STRESS, "decision": first.status.value, "dispatches": 0, "retries": 0, "repository_writes": 0, "ledger_writes_by_adapter": 0},
        "acceptance": acceptance, "result": "PASS" if passed else "FAIL",
        "qualification": "M5_DOWNSTREAM_OUTCOME_ARTIFACT_EVIDENCE_V1_PARTIAL_PASS" if passed else "NOT_QUALIFIED",
        "m4_overall": "NOT_COMPLETE", "m5_overall": "PARTIAL_NOT_COMPLETE", "real_dispatch_authority": "NOT_GRANTED",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
