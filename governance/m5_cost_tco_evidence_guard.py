from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Iterable

CONTRACT_VERSION = "0.1"
BUDGET_LIMIT_EUR_CENTS = 2000
WARNING_THRESHOLD_PERCENT = 80


class CostDecision(str, Enum):
    COST_PASS = "COST_PASS"
    COST_WARNING = "COST_WARNING"
    OWNER_REQUIRED = "OWNER_REQUIRED"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class CostEvidenceLine:
    provider_or_cost_class: str
    source_ref: str
    observed_at: str
    evidence_kind: str
    fresh: bool
    covered: bool
    amount_eur_cents: int | None = None
    projected_eur_cents: int | None = None


@dataclass(frozen=True)
class CostEvidenceSnapshot:
    contract_version: str
    project_id: str
    budget_scope_id: str
    period_yyyy_mm: str
    currency: str
    budget_limit_eur_cents: int
    accrued_eur_cents: int
    committed_remaining_eur_cents: int
    projected_month_end_eur_cents: int
    evidence_lines: tuple[CostEvidenceLine, ...]
    source_health: str
    observed_at: str
    checked_at: str
    projection_method: str
    projection_version: str
    coverage_complete: bool
    unknown_material_cost_paths: int
    source_conflict: bool
    owner_override_present: bool
    proposed_recurring_delta_eur_cents: int
    audit_ref: str
    owner_override_ref: str | None = None


@dataclass(frozen=True)
class CostAssessment:
    decision: CostDecision
    reason: str
    effective_projected_eur_cents: int | None
    budget_limit_eur_cents: int | None


def _blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def _as_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_must_be_timezone_aware")
    return parsed


def _valid_money(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_lines(lines: Iterable[CostEvidenceLine]) -> tuple[str | None, bool]:
    incomplete = False
    for line in lines:
        if _blank(line.provider_or_cost_class) or _blank(line.source_ref) or _blank(line.evidence_kind):
            return "invalid_evidence_line_identity", incomplete
        if _blank(line.observed_at):
            return "invalid_evidence_line_time", incomplete
        try:
            _as_dt(line.observed_at)
        except (TypeError, ValueError):
            return "invalid_evidence_line_time", incomplete
        if line.amount_eur_cents is None and line.projected_eur_cents is None:
            return "evidence_line_missing_amount", incomplete
        if line.amount_eur_cents is not None and not _valid_money(line.amount_eur_cents):
            return "invalid_evidence_line_amount", incomplete
        if line.projected_eur_cents is not None and not _valid_money(line.projected_eur_cents):
            return "invalid_evidence_line_projection", incomplete
        if not line.fresh or not line.covered:
            incomplete = True
    return None, incomplete


def classify_cost(snapshot: CostEvidenceSnapshot) -> CostAssessment:
    if snapshot.contract_version != CONTRACT_VERSION:
        return CostAssessment(CostDecision.FAIL_CLOSED, "unknown_contract_version", None, None)

    required_strings = (
        snapshot.project_id,
        snapshot.budget_scope_id,
        snapshot.currency,
        snapshot.observed_at,
        snapshot.checked_at,
        snapshot.projection_method,
        snapshot.projection_version,
        snapshot.audit_ref,
    )
    if any(_blank(value) for value in required_strings):
        return CostAssessment(CostDecision.FAIL_CLOSED, "missing_required_field", None, None)

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", snapshot.period_yyyy_mm):
        return CostAssessment(CostDecision.FAIL_CLOSED, "invalid_period", None, None)

    if snapshot.currency != "EUR":
        return CostAssessment(CostDecision.FAIL_CLOSED, "currency_must_be_eur", None, None)

    if snapshot.budget_limit_eur_cents != BUDGET_LIMIT_EUR_CENTS:
        return CostAssessment(CostDecision.FAIL_CLOSED, "unexpected_budget_limit", None, None)

    money_values = (
        snapshot.accrued_eur_cents,
        snapshot.committed_remaining_eur_cents,
        snapshot.projected_month_end_eur_cents,
        snapshot.proposed_recurring_delta_eur_cents,
    )
    if not all(_valid_money(value) for value in money_values):
        return CostAssessment(CostDecision.FAIL_CLOSED, "invalid_money_value", None, BUDGET_LIMIT_EUR_CENTS)

    if not isinstance(snapshot.unknown_material_cost_paths, int) or isinstance(snapshot.unknown_material_cost_paths, bool) or snapshot.unknown_material_cost_paths < 0:
        return CostAssessment(CostDecision.FAIL_CLOSED, "invalid_unknown_cost_path_count", None, BUDGET_LIMIT_EUR_CENTS)

    if snapshot.accrued_eur_cents > snapshot.projected_month_end_eur_cents:
        return CostAssessment(CostDecision.FAIL_CLOSED, "accrued_exceeds_projection", None, BUDGET_LIMIT_EUR_CENTS)

    if snapshot.accrued_eur_cents + snapshot.committed_remaining_eur_cents > snapshot.projected_month_end_eur_cents:
        return CostAssessment(CostDecision.FAIL_CLOSED, "committed_sum_exceeds_projection", None, BUDGET_LIMIT_EUR_CENTS)

    try:
        observed = _as_dt(snapshot.observed_at)
        checked = _as_dt(snapshot.checked_at)
    except (TypeError, ValueError):
        return CostAssessment(CostDecision.FAIL_CLOSED, "invalid_snapshot_time", None, BUDGET_LIMIT_EUR_CENTS)
    if observed > checked:
        return CostAssessment(CostDecision.FAIL_CLOSED, "observed_after_checked", None, BUDGET_LIMIT_EUR_CENTS)

    lines = tuple(snapshot.evidence_lines)
    if snapshot.coverage_complete and not lines:
        return CostAssessment(CostDecision.FAIL_CLOSED, "complete_coverage_without_evidence", None, BUDGET_LIMIT_EUR_CENTS)

    line_error, line_incomplete = _validate_lines(lines)
    if line_error:
        return CostAssessment(CostDecision.FAIL_CLOSED, line_error, None, BUDGET_LIMIT_EUR_CENTS)

    if snapshot.source_conflict:
        return CostAssessment(CostDecision.FAIL_CLOSED, "source_conflict", None, BUDGET_LIMIT_EUR_CENTS)

    effective = snapshot.projected_month_end_eur_cents + snapshot.proposed_recurring_delta_eur_cents

    if snapshot.owner_override_present:
        return CostAssessment(CostDecision.OWNER_REQUIRED, "owner_override_requires_separate_validation", effective, BUDGET_LIMIT_EUR_CENTS)

    if snapshot.source_health != "FRESH":
        return CostAssessment(CostDecision.EVIDENCE_INCOMPLETE, "source_not_fresh", effective, BUDGET_LIMIT_EUR_CENTS)

    if not snapshot.coverage_complete or snapshot.unknown_material_cost_paths > 0 or line_incomplete:
        return CostAssessment(CostDecision.EVIDENCE_INCOMPLETE, "cost_evidence_incomplete", effective, BUDGET_LIMIT_EUR_CENTS)

    if effective >= BUDGET_LIMIT_EUR_CENTS:
        return CostAssessment(CostDecision.OWNER_REQUIRED, "budget_limit_reached_or_exceeded", effective, BUDGET_LIMIT_EUR_CENTS)

    if effective * 100 >= BUDGET_LIMIT_EUR_CENTS * WARNING_THRESHOLD_PERCENT:
        return CostAssessment(CostDecision.COST_WARNING, "budget_warning_threshold_reached", effective, BUDGET_LIMIT_EUR_CENTS)

    return CostAssessment(CostDecision.COST_PASS, "complete_fresh_evidence_under_budget", effective, BUDGET_LIMIT_EUR_CENTS)
