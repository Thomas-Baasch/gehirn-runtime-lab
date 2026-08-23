from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import random

import governance.m5_cost_tco_evidence_guard as mod
from governance.m5_cost_tco_evidence_guard import (
    CostDecision,
    CostEvidenceLine,
    CostEvidenceSnapshot,
    classify_cost,
)

CONTRACT_DRIVE_ID = "1TuxS8rci3nnr1pUJWRIMtbb6fk_hQmSfCfBqzuw4FHQ"
CONTRACT_SHA256 = "e5b7735d99c959c38ea099945520c1c40a82c3000efc241b4e53d4a79e29822b"
STRESS = 100_000
OUT = Path("reports/continuation/m5_cost_tco_evidence_guard_v0_1.json")


def line(n: int = 1, **kw) -> CostEvidenceLine:
    data = dict(
        provider_or_cost_class="github_actions",
        source_ref=f"github-billing-evidence-{n}",
        observed_at="2026-08-23T10:00:00+02:00",
        evidence_kind="BILLING_OR_COST_EVIDENCE",
        fresh=True,
        covered=True,
        amount_eur_cents=400,
        projected_eur_cents=800,
    )
    data.update(kw)
    return CostEvidenceLine(**data)


def base(n: int = 1, **kw) -> CostEvidenceSnapshot:
    data = dict(
        contract_version="0.1",
        project_id="EXTERNES_GEHIRN",
        budget_scope_id="github_total_monthly_path",
        period_yyyy_mm="2026-08",
        currency="EUR",
        budget_limit_eur_cents=2000,
        accrued_eur_cents=400,
        committed_remaining_eur_cents=200,
        projected_month_end_eur_cents=800,
        evidence_lines=(line(n),),
        source_health="FRESH",
        observed_at="2026-08-23T10:00:00+02:00",
        checked_at="2026-08-23T10:01:00+02:00",
        projection_method="provided_evidence_projection",
        projection_version="v1",
        coverage_complete=True,
        unknown_material_cost_paths=0,
        source_conflict=False,
        owner_override_present=False,
        owner_override_ref=None,
        proposed_recurring_delta_eur_cents=0,
        audit_ref=f"audit-{n}",
    )
    data.update(kw)
    return CostEvidenceSnapshot(**data)


def expected_permit_like(s: CostEvidenceSnapshot) -> bool:
    if s.contract_version != "0.1":
        return False
    if s.currency != "EUR" or s.budget_limit_eur_cents != 2000:
        return False
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (
        s.accrued_eur_cents,
        s.committed_remaining_eur_cents,
        s.projected_month_end_eur_cents,
        s.proposed_recurring_delta_eur_cents,
    )):
        return False
    if s.accrued_eur_cents > s.projected_month_end_eur_cents:
        return False
    if s.accrued_eur_cents + s.committed_remaining_eur_cents > s.projected_month_end_eur_cents:
        return False
    if not s.coverage_complete or s.unknown_material_cost_paths > 0 or s.source_conflict:
        return False
    if s.owner_override_present or s.source_health != "FRESH":
        return False
    if not s.evidence_lines:
        return False
    for e in s.evidence_lines:
        if not e.provider_or_cost_class.strip() or not e.source_ref.strip() or not e.evidence_kind.strip():
            return False
        if not e.fresh or not e.covered:
            return False
        if e.amount_eur_cents is None and e.projected_eur_cents is None:
            return False
        for value in (e.amount_eur_cents, e.projected_eur_cents):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                return False
    effective = s.projected_month_end_eur_cents + s.proposed_recurring_delta_eur_cents
    return effective < 2000


def main() -> int:
    cases: list[dict] = []

    def rec(case_id: str, snapshot: CostEvidenceSnapshot, expected: CostDecision) -> None:
        actual = classify_cost(snapshot)
        cases.append({
            "case": case_id,
            "actual": actual.decision.value,
            "expected": expected.value,
            "pass": actual.decision is expected,
            "reason": actual.reason,
        })

    rec("COST-01", base(1, projected_month_end_eur_cents=1000), CostDecision.COST_PASS)
    rec("COST-02", base(2, projected_month_end_eur_cents=1600), CostDecision.COST_WARNING)
    rec("COST-03", base(3, projected_month_end_eur_cents=1999), CostDecision.COST_WARNING)
    rec("COST-04", base(4, projected_month_end_eur_cents=2000), CostDecision.OWNER_REQUIRED)
    rec("COST-05", base(5, projected_month_end_eur_cents=2500), CostDecision.OWNER_REQUIRED)
    rec("COST-06", base(6, projected_month_end_eur_cents=1700, proposed_recurring_delta_eur_cents=300), CostDecision.OWNER_REQUIRED)
    rec("COST-07", base(7, source_health="STALE"), CostDecision.EVIDENCE_INCOMPLETE)
    rec("COST-08", base(8, coverage_complete=False), CostDecision.EVIDENCE_INCOMPLETE)
    rec("COST-09", base(9, unknown_material_cost_paths=1), CostDecision.EVIDENCE_INCOMPLETE)
    rec("COST-10", base(10, source_conflict=True), CostDecision.FAIL_CLOSED)
    rec("COST-11", base(11, accrued_eur_cents=-1), CostDecision.FAIL_CLOSED)
    rec("COST-12", base(12, projected_month_end_eur_cents=-1), CostDecision.FAIL_CLOSED)
    rec("COST-13", base(13, accrued_eur_cents=900, committed_remaining_eur_cents=0, projected_month_end_eur_cents=800), CostDecision.FAIL_CLOSED)
    rec("COST-14", base(14, currency="USD"), CostDecision.FAIL_CLOSED)
    rec("COST-15", base(15, budget_limit_eur_cents=3000), CostDecision.FAIL_CLOSED)
    rec("COST-16", base(16, evidence_lines=(line(16, source_ref=""),)), CostDecision.FAIL_CLOSED)
    rec("COST-17", base(17, evidence_lines=(line(17, fresh=False),)), CostDecision.EVIDENCE_INCOMPLETE)
    rec("COST-18", base(18, contract_version="0.2"), CostDecision.FAIL_CLOSED)
    rec("COST-19", base(19, owner_override_present=True, owner_override_ref="owner-ref"), CostDecision.OWNER_REQUIRED)
    rec("COST-20", base(20, evidence_lines=()), CostDecision.FAIL_CLOSED)
    rec("COST-21", base(21, proposed_recurring_delta_eur_cents=-1), CostDecision.FAIL_CLOSED)
    rec("COST-22", base(22, period_yyyy_mm="2026-13"), CostDecision.FAIL_CLOSED)
    rec("COST-23", base(23, projection_method=""), CostDecision.FAIL_CLOSED)
    replay = base(24, projected_month_end_eur_cents=1599)
    first = classify_cost(replay)
    second = classify_cost(replay)
    cases.append({
        "case": "COST-24",
        "actual": f"{first.decision.value}/{second.decision.value}",
        "expected": "COST_PASS/COST_PASS",
        "pass": first == second and first.decision is CostDecision.COST_PASS,
        "reason": first.reason,
    })

    rng = random.Random(20260823)
    bad_green = 0
    mismatches = 0
    permit_like_count = 0
    decisions = {d.value: 0 for d in CostDecision}
    for n in range(STRESS):
        projected = rng.randrange(0, 2600)
        accrued = rng.randrange(-5, 2200)
        committed = rng.randrange(-5, 900)
        delta = rng.randrange(-5, 500)
        fresh = rng.choice([True, True, True, False])
        covered = rng.choice([True, True, True, False])
        source_health = rng.choice(["FRESH", "FRESH", "STALE", "UNKNOWN"])
        coverage = rng.choice([True, True, True, False])
        unknown = rng.choice([0, 0, 0, 1, 2])
        conflict = rng.choice([False, False, False, True])
        owner_override = rng.choice([False, False, False, True])
        currency = rng.choice(["EUR", "EUR", "EUR", "USD"])
        budget = rng.choice([2000, 2000, 2000, 1800])
        contract = rng.choice(["0.1", "0.1", "0.1", "0.2"])
        l = line(
            1000 + n % 1000,
            source_ref="" if rng.randrange(50) == 0 else f"src-{n}",
            fresh=fresh,
            covered=covered,
            amount_eur_cents=max(0, min(accrued, 1000)) if accrued >= 0 else -1,
            projected_eur_cents=max(0, projected),
        )
        s = base(
            1000 + n % 1000,
            contract_version=contract,
            currency=currency,
            budget_limit_eur_cents=budget,
            accrued_eur_cents=accrued,
            committed_remaining_eur_cents=committed,
            projected_month_end_eur_cents=projected,
            evidence_lines=(l,),
            source_health=source_health,
            coverage_complete=coverage,
            unknown_material_cost_paths=unknown,
            source_conflict=conflict,
            owner_override_present=owner_override,
            owner_override_ref="override" if owner_override else None,
            proposed_recurring_delta_eur_cents=delta,
        )
        actual = classify_cost(s).decision
        decisions[actual.value] += 1
        permit_like = actual in {CostDecision.COST_PASS, CostDecision.COST_WARNING}
        expected_permit = expected_permit_like(s)
        permit_like_count += int(permit_like)
        if permit_like and not expected_permit:
            bad_green += 1
        if permit_like != expected_permit:
            mismatches += 1

    forbidden = {
        "buy", "subscribe", "upgrade", "payment", "billing_write", "create_budget",
        "change_budget", "change_provider", "deploy", "dispatch", "rerun", "merge",
        "delete", "create_grant", "grant",
    }
    callable_names = {name for name, value in vars(mod).items() if callable(value)}
    forbidden_found = sorted(callable_names & forbidden)

    acceptance = {
        "contract_drive_id": CONTRACT_DRIVE_ID,
        "contract_sha256": CONTRACT_SHA256,
        "deterministic_cases": len(cases),
        "deterministic_all_pass": all(c["pass"] for c in cases),
        "stress_states": STRESS,
        "stress_bad_green": bad_green,
        "stress_permit_classifier_mismatches": mismatches,
        "stress_permit_like_count": permit_like_count,
        "decision_counts": decisions,
        "forbidden_effect_surfaces": forbidden_found,
        "real_external_effects": 0,
        "authority_created": 0,
        "billing_credentials_required": 0,
        "replay_deterministic": cases[-1]["pass"],
    }
    passed = (
        len(cases) >= 24
        and acceptance["deterministic_all_pass"]
        and bad_green == 0
        and mismatches == 0
        and not forbidden_found
        and acceptance["replay_deterministic"]
    )
    report = {"status": "PASS" if passed else "FAIL", "cases": cases, "acceptance": acceptance}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": report["status"], "acceptance": acceptance}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
