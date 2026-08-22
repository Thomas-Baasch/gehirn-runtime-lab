from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import governance.m4_single_pilot_authority_boundary as authority_module
from governance.m4_single_pilot_authority_boundary import (
    AuthorityStatus,
    OwnerAuthorizationEvidence,
    PilotIntent,
    PreflightEvidence,
    validate_single_pilot_authority,
)

CONTRACT_DRIVE_ID = "1fIiqfcBQaPZ4Yq6vHfiVBaa6Okc5JAXsL0zDmtq8pCk"
CONTRACT_SHA256 = "58c235b87ba393134aad58daebb833d4c01a5d9ba0d2a93dd0c86bdaed78e66c"
PREFLIGHT_CONTRACT_ID = "1pOcZzNBuEZwIFpAPc3JCduv27RsvL1P2P3-Bwc2kDrM"
PREFLIGHT_CONTRACT_SHA = "0e05fb767927a72508556363a507a6261ddf0bc5c1c4b655c4d16953f4362c11"
OUTCOME_CONTRACT_ID = "15JeNfaaHDAn4a9znqAvkB7DyOLbOGXHs7gbMs4V9e54"
OUTCOME_CONTRACT_SHA = "d150621ba21b77f5251d343b5876f81ff63749410c2628c57a3ccf8ea30575fb"
OUT = Path("reports/continuation/m4_single_pilot_authority_boundary_v1.json")
STRESS = 10_000
BASE = datetime(2026, 8, 22, 11, 0, 0, tzinfo=timezone.utc)


def pilot_intent() -> PilotIntent:
    return PilotIntent(
        home_system="SYNTHETIC_HOME",
        work_id="work-ab-001",
        dedupe_key="dedupe-ab-001",
        target="synthetic-single-pilot",
        target_adapter="SYNTHETIC_SINGLE_PILOT_ADAPTER_V1",
        adapter_contract_drive_id="synthetic-adapter-contract-v1",
        adapter_contract_sha256="b" * 64,
        action_class="INTERNAL_CONTINUE",
        expected_repository="Thomas-Baasch/synthetic-home",
        expected_workflow_id=4242,
        expected_event="workflow_dispatch",
        expected_ref="main",
        expected_head_sha="a" * 40,
        exact_run_name_token="eg:work-ab-001:dedupe-ab-001",
        outcome_contract_drive_id=OUTCOME_CONTRACT_ID,
        outcome_contract_sha256=OUTCOME_CONTRACT_SHA,
        expected_artifact_name="safe-continuation-outcome-work-ab-001-dedupe-ab-001",
        expected_outcome_path="safe-continuation-outcome.json",
        outcome_schema="safe-continuation-outcome.v1",
        preflight_contract_drive_id=PREFLIGHT_CONTRACT_ID,
        preflight_contract_sha256=PREFLIGHT_CONTRACT_SHA,
    )


def preflight(status: str = "READY_FOR_SEPARATELY_AUTHORIZED_SINGLE_PILOT") -> PreflightEvidence:
    return PreflightEvidence(
        status=status,
        observed_at=BASE,
        source_health="FRESH",
        preflight_contract_drive_id=PREFLIGHT_CONTRACT_ID,
        preflight_contract_sha256=PREFLIGHT_CONTRACT_SHA,
        snapshot_sha256="d" * 64,
    )


def grant(intent: PilotIntent | None = None, pf: PreflightEvidence | None = None) -> OwnerAuthorizationEvidence:
    i = intent or pilot_intent()
    p = pf or preflight()
    return OwnerAuthorizationEvidence(
        source_kind="EXPLICIT_THOMAS_OWNER_AUTHORIZATION",
        authority_level="A5_OWNER_EXPLICIT_SINGLE_PILOT",
        verification_state="VERIFIED_OWNER_SOURCE",
        source_health="FRESH",
        source_ref="a0-owner-evidence:EGE-SYNTHETIC-AB-001",
        source_evidence_sha256="c" * 64,
        source_verified_at=BASE + timedelta(seconds=65),
        grant_id="single-pilot-grant-ab-001",
        issued_at=BASE + timedelta(seconds=60),
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


def main() -> int:
    i = pilot_intent()
    p = preflight()
    g = grant(i, p)
    as_of = BASE + timedelta(seconds=90)
    cases: list[dict] = []

    def record(case_id: str, actual, expected, detail: str = "") -> None:
        av = actual.value if hasattr(actual, "value") else str(actual)
        ev = expected.value if hasattr(expected, "value") else str(expected)
        cases.append({"case": case_id, "actual": av, "expected": ev, "pass": av == ev, "detail": detail})

    record("AB-01", validate_single_pilot_authority(i, p, g, as_of=as_of).status, AuthorityStatus.AUTHORIZATION_EVIDENCE_VALID_FOR_SEPARATE_SINGLE_DISPATCH)
    record("AB-02", validate_single_pilot_authority(i, replace(p, status="BLOCKED_EXPECTED_WAIT"), g, as_of=as_of).status, AuthorityStatus.BLOCKED_PREFLIGHT)

    stale_pf = replace(p, observed_at=BASE - timedelta(minutes=11))
    unhealthy_pf = replace(p, source_health="STALE")
    ab03 = all(validate_single_pilot_authority(i, x, g, as_of=as_of).status is AuthorityStatus.BLOCKED_PREFLIGHT for x in (stale_pf, unhealthy_pf))
    record("AB-03", "BLOCKED_PREFLIGHT" if ab03 else "NOT_BLOCKED", "BLOCKED_PREFLIGHT")

    generic_a3 = replace(g, source_kind="GENERAL_A3_AUTONOMY", authority_level="A3_PROJECT_AUTONOMY")
    wrong_verification = replace(g, verification_state="SELF_DECLARED")
    ab04 = all(validate_single_pilot_authority(i, p, x, as_of=as_of).status is AuthorityStatus.BLOCKED_AUTHENTICITY for x in (generic_a3, wrong_verification))
    record("AB-04", "BLOCKED_AUTHENTICITY" if ab04 else "NOT_BLOCKED", "BLOCKED_AUTHENTICITY")

    stale_source = replace(g, source_verified_at=BASE - timedelta(minutes=6))
    unhealthy_source = replace(g, source_health="STALE")
    ab05 = all(validate_single_pilot_authority(i, p, x, as_of=as_of).status is AuthorityStatus.BLOCKED_AUTHENTICITY for x in (stale_source, unhealthy_source))
    record("AB-05", "BLOCKED_AUTHENTICITY" if ab05 else "NOT_BLOCKED", "BLOCKED_AUTHENTICITY")

    record("AB-06", validate_single_pilot_authority(i, p, replace(g, revoked=True), as_of=as_of).status, AuthorityStatus.BLOCKED_REVOKED)

    # Isolate expiry from all other freshness gates: preflight is only 90s old,
    # source verification is fresh, but this grant expired at +80s.
    expired_grant = replace(
        g,
        source_verified_at=BASE + timedelta(seconds=75),
        expires_at=BASE + timedelta(seconds=80),
    )
    record("AB-07", validate_single_pilot_authority(i, p, expired_grant, as_of=as_of).status, AuthorityStatus.BLOCKED_TEMPORAL)

    predates = replace(g, issued_at=BASE - timedelta(minutes=1), expires_at=BASE + timedelta(minutes=10))
    future = replace(g, issued_at=BASE + timedelta(minutes=3), expires_at=BASE + timedelta(minutes=20))
    ab08 = all(validate_single_pilot_authority(i, p, x, as_of=as_of).status is AuthorityStatus.BLOCKED_TEMPORAL for x in (predates, future))
    record("AB-08", "BLOCKED_TEMPORAL" if ab08 else "NOT_BLOCKED", "BLOCKED_TEMPORAL")

    long_ttl = replace(g, expires_at=g.issued_at + timedelta(minutes=31))
    record("AB-09", validate_single_pilot_authority(i, p, long_ttl, as_of=as_of).status, AuthorityStatus.BLOCKED_TEMPORAL)
    record("AB-10", validate_single_pilot_authority(i, p, replace(g, max_dispatches=2), as_of=as_of).status, AuthorityStatus.BLOCKED_NOT_SINGLE_USE)
    record("AB-11", validate_single_pilot_authority(i, p, replace(g, used_dispatches=1), as_of=as_of).status, AuthorityStatus.BLOCKED_ALREADY_CONSUMED)

    ab12 = all(
        validate_single_pilot_authority(i, p, x, as_of=as_of).status is AuthorityStatus.BLOCKED_AUTHENTICITY
        for x in (replace(g, grant_id=""), replace(g, source_ref=""), replace(g, source_evidence_sha256="not-a-sha"))
    )
    record("AB-12", "BLOCKED_AUTHENTICITY" if ab12 else "NOT_BLOCKED", "BLOCKED_AUTHENTICITY")

    ab13 = all(
        validate_single_pilot_authority(i, p, replace(g, **{key: "wrong"}), as_of=as_of).status is AuthorityStatus.BLOCKED_SCOPE_MISMATCH
        for key in ("home_system", "work_id", "dedupe_key", "target")
    )
    record("AB-13", "BLOCKED_SCOPE_MISMATCH" if ab13 else "NOT_BLOCKED", "BLOCKED_SCOPE_MISMATCH")

    ab14 = all(
        validate_single_pilot_authority(i, p, replace(g, **{key: ("e" * 64 if key.endswith("sha256") else "wrong")}), as_of=as_of).status is AuthorityStatus.BLOCKED_SCOPE_MISMATCH
        for key in ("target_adapter", "adapter_contract_drive_id", "adapter_contract_sha256")
    )
    record("AB-14", "BLOCKED_SCOPE_MISMATCH" if ab14 else "NOT_BLOCKED", "BLOCKED_SCOPE_MISMATCH")

    run_variants = (
        replace(g, expected_repository="Other/repo"),
        replace(g, expected_workflow_id=9999),
        replace(g, expected_event="pull_request"),
        replace(g, expected_ref="other"),
        replace(g, expected_head_sha="f" * 40),
        replace(g, exact_run_name_token="other-run"),
    )
    ab15 = all(validate_single_pilot_authority(i, p, x, as_of=as_of).status is AuthorityStatus.BLOCKED_SCOPE_MISMATCH for x in run_variants)
    record("AB-15", "BLOCKED_SCOPE_MISMATCH" if ab15 else "NOT_BLOCKED", "BLOCKED_SCOPE_MISMATCH")

    wrong_action = replace(g, action_class="MERGE")
    intent_action = replace(i, action_class="MERGE")
    a = validate_single_pilot_authority(i, p, wrong_action, as_of=as_of).status
    b = validate_single_pilot_authority(intent_action, p, grant(intent_action, p), as_of=as_of).status
    ab16 = a is AuthorityStatus.BLOCKED_SCOPE_MISMATCH and b is AuthorityStatus.BLOCKED_SCOPE_MISMATCH
    record("AB-16", "BLOCKED_SCOPE_MISMATCH" if ab16 else "NOT_BLOCKED", "BLOCKED_SCOPE_MISMATCH")

    wrong_pf_contract = replace(g, preflight_contract_drive_id="wrong")
    evidence_wrong_pf_contract = replace(p, preflight_contract_sha256="e" * 64)
    ab17 = (
        validate_single_pilot_authority(i, p, wrong_pf_contract, as_of=as_of).status is AuthorityStatus.BLOCKED_SCOPE_MISMATCH
        and validate_single_pilot_authority(i, evidence_wrong_pf_contract, g, as_of=as_of).status is AuthorityStatus.BLOCKED_SCOPE_MISMATCH
    )
    record("AB-17", "BLOCKED_SCOPE_MISMATCH" if ab17 else "NOT_BLOCKED", "BLOCKED_SCOPE_MISMATCH")

    record("AB-18", validate_single_pilot_authority(i, p, replace(g, preflight_snapshot_sha256="e" * 64), as_of=as_of).status, AuthorityStatus.BLOCKED_SCOPE_MISMATCH)

    outcome_variants = (
        replace(g, outcome_contract_drive_id="wrong"),
        replace(g, outcome_contract_sha256="e" * 64),
        replace(g, expected_artifact_name="other"),
        replace(g, expected_outcome_path="other.json"),
        replace(g, outcome_schema="other.v0"),
    )
    ab19 = all(validate_single_pilot_authority(i, p, x, as_of=as_of).status is AuthorityStatus.BLOCKED_SCOPE_MISMATCH for x in outcome_variants)
    record("AB-19", "BLOCKED_SCOPE_MISMATCH" if ab19 else "NOT_BLOCKED", "BLOCKED_SCOPE_MISMATCH")

    wildcard_intent = replace(i, target="ANY")
    wildcard_grant = replace(g, expected_ref="*")
    ab20 = (
        validate_single_pilot_authority(wildcard_intent, p, grant(wildcard_intent, p), as_of=as_of).status is AuthorityStatus.BLOCKED_WILDCARD_SCOPE
        and validate_single_pilot_authority(i, p, wildcard_grant, as_of=as_of).status is AuthorityStatus.BLOCKED_WILDCARD_SCOPE
    )
    record("AB-20", "BLOCKED_WILDCARD_SCOPE" if ab20 else "NOT_BLOCKED", "BLOCKED_WILDCARD_SCOPE")

    current_real_preflight_statuses = (
        "BLOCKED_EXPECTED_WAIT",
        "BLOCKED_STATE",
        "BLOCKED_ADAPTER_AUTHORITY",
    )
    ab21 = all(
        validate_single_pilot_authority(i, replace(p, status=status), g, as_of=as_of).status is AuthorityStatus.BLOCKED_PREFLIGHT
        for status in current_real_preflight_statuses
    )
    record("AB-21", "BLOCKED_PREFLIGHT" if ab21 else "NOT_BLOCKED", "BLOCKED_PREFLIGHT", "no grant can override current PETER/USCHI composite blocks")

    first = validate_single_pilot_authority(i, p, g, as_of=as_of)
    before = (repr(i), repr(p), repr(g))
    deterministic = True
    for _ in range(STRESS):
        cur = validate_single_pilot_authority(i, p, g, as_of=as_of)
        if cur != first or cur.dispatch_executed or cur.claim_executed or cur.retry_executed or cur.write_executed or cur.authority_created:
            deterministic = False
            break
    immutable = before == (repr(i), repr(p), repr(g))
    forbidden_names = {"dispatch", "execute", "claim", "retry", "rerun", "cancel", "write", "grant", "create", "merge", "delete"}
    forbidden_surface = any(name in authority_module.__dict__ and callable(authority_module.__dict__[name]) for name in forbidden_names)
    ab22_ok = (
        deterministic
        and immutable
        and not forbidden_surface
        and not first.dispatch_executed
        and not first.claim_executed
        and not first.retry_executed
        and not first.write_executed
        and not first.authority_created
    )
    record("AB-22", "NO_AUTHORITY_OR_EFFECT_SURFACE" if ab22_ok else "SURFACE_OR_EFFECT_FOUND", "NO_AUTHORITY_OR_EFFECT_SURFACE")

    acceptance = {
        "deterministic_22_of_22": len(cases) == 22 and all(c["pass"] for c in cases),
        "stress_10000_exact_valid_deterministic": deterministic,
        "immutable_inputs": immutable,
        "zero_dispatch_claim_retry_write_authority_creation": ab22_ok,
        "general_a3_autonomy_not_owner_grant": ab04,
        "current_peter_uschi_blocks_cannot_be_overridden_by_grant": ab21,
        "single_use_required": validate_single_pilot_authority(i, p, replace(g, max_dispatches=2), as_of=as_of).status is AuthorityStatus.BLOCKED_NOT_SINGLE_USE,
        "consumed_grant_blocked": validate_single_pilot_authority(i, p, replace(g, used_dispatches=1), as_of=as_of).status is AuthorityStatus.BLOCKED_ALREADY_CONSUMED,
        "real_dispatch_authority_not_granted": first.real_dispatch_authority == "NOT_GRANTED",
    }
    passed = all(acceptance.values())
    report = {
        "schema": "externes-gehirn.m4-single-pilot-authority-boundary",
        "version": "0.1.0",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256},
        "preflight_contract": {"drive_id": PREFLIGHT_CONTRACT_ID, "sha256": PREFLIGHT_CONTRACT_SHA},
        "cases": cases,
        "stress": {"evaluations": STRESS, "decision": first.status.value, "dispatches": 0, "claims": 0, "retries": 0, "writes": 0, "authority_created": 0},
        "current_real_preflight_observations": {
            "PETER": "BLOCKED_EXPECTED_WAIT",
            "USCHI_2_LEGACY": "BLOCKED_STATE",
            "USCHI_NEU": "BLOCKED_ADAPTER_AUTHORITY",
        },
        "acceptance": acceptance,
        "result": "PASS" if passed else "FAIL",
        "qualification": "M4_SINGLE_PILOT_AUTHORITY_BOUNDARY_V1_PASS_READ_ONLY" if passed else "NOT_QUALIFIED",
        "m4_overall": "NOT_COMPLETE",
        "real_owner_grant_present": False,
        "real_dispatch_authority": "NOT_GRANTED",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
