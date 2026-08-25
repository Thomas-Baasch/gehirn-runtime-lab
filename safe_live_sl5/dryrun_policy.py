from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CurrentIssue:
    repo: str
    number: int
    title: str
    state: str
    comment_bodies: tuple[str, ...]


@dataclass(frozen=True)
class Milestone:
    key: str
    material: bool
    canon_current: bool
    conflict: bool
    summary: str


@dataclass(frozen=True)
class Policy:
    policy_id: str
    status: str
    target_repo: str
    target_issue: int
    target_title: str
    allowed_effect: str
    execute: bool
    material_only: bool
    max_comments_per_milestone_key: int
    expiry_required: bool
    kill_switch: bool
    no_inheritance: bool
    forbidden_effects: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    allowed_to_prepare: bool
    allowed_to_execute: bool
    reason: str
    milestone_key: str
    rendered_body: str | None


def render_body(m: Milestone) -> str:
    return (
        "## SAFE_LIVE_SL5_MATERIAL_MILESTONE\n\n"
        f"Milestone key: `{m.key}`\n\n"
        f"Status: {m.summary}\n\n"
        "Dieser Kommentar dokumentiert ausschließlich einen materiellen Safe-Live-Hauptmeilenstein. "
        "Er erzeugt keine zusätzlichen Rollen-, Merge-, Send-, Pay-, Delete-, Contract-, Policy- oder Rights-Rechte."
    )


def evaluate(policy: Policy, issue: CurrentIssue, milestone: Milestone, requested_effect: str = "ISSUE_COMMENT") -> Decision:
    if policy.status != "DRY_RUN_ONLY":
        return Decision(False, False, "POLICY_NOT_DRY_RUN_ONLY", milestone.key, None)
    if policy.execute:
        return Decision(False, False, "EXECUTE_MUST_BE_FALSE_IN_ACCEPTANCE", milestone.key, None)
    if not policy.kill_switch or not policy.no_inheritance:
        return Decision(False, False, "POLICY_SAFETY_INVARIANT_MISSING", milestone.key, None)
    if requested_effect != policy.allowed_effect or requested_effect in policy.forbidden_effects:
        return Decision(False, False, "EFFECT_NOT_ALLOWED", milestone.key, None)
    if issue.repo != policy.target_repo or issue.number != policy.target_issue or issue.title != policy.target_title:
        return Decision(False, False, "TARGET_MISMATCH", milestone.key, None)
    if issue.state != "open":
        return Decision(False, False, "TARGET_NOT_OPEN", milestone.key, None)
    if policy.material_only and not milestone.material:
        return Decision(False, False, "NOT_MATERIAL", milestone.key, None)
    if not milestone.canon_current:
        return Decision(False, False, "CANON_NOT_CURRENT", milestone.key, None)
    if milestone.conflict:
        return Decision(False, False, "CONFLICT_PRESENT", milestone.key, None)
    marker = f"Milestone key: `{milestone.key}`"
    if sum(marker in body for body in issue.comment_bodies) >= policy.max_comments_per_milestone_key:
        return Decision(False, False, "DUPLICATE_MILESTONE_KEY", milestone.key, None)
    body = render_body(milestone)
    return Decision(True, False, "PREPARED_DRY_RUN_ONLY", milestone.key, body)


def prove_no_execution(decisions: Iterable[Decision]) -> bool:
    return all(d.allowed_to_execute is False for d in decisions)
