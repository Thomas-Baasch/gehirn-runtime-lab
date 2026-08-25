from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ActivePolicy:
    policy_id: str
    status: str
    active_from: str
    review_by: str
    target_repo: str
    target_issue: int
    target_title: str
    allowed_effect: str
    execute: bool
    material_only: bool
    max_comments_per_milestone_key: int
    bootstrap_activation_is_not_trigger: bool
    kill_switch: bool
    no_inheritance: bool
    postcommit_readback_required: bool
    forbidden_effects: tuple[str, ...]


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
    is_policy_activation: bool = False


@dataclass(frozen=True)
class Decision:
    allowed_to_execute: bool
    reason: str
    rendered_body: str | None


def render_body(m: Milestone) -> str:
    return (
        "## SAFE_LIVE_SL5_MATERIAL_MILESTONE\n\n"
        f"Milestone key: `{m.key}`\n\n"
        f"Status: {m.summary}\n\n"
        "Dieser Kommentar dokumentiert ausschließlich einen materiellen Safe-Live-Hauptmeilenstein. "
        "Er erzeugt keine zusätzlichen Rollen-, Merge-, Send-, Pay-, Delete-, Contract-, Policy- oder Rights-Rechte."
    )


def evaluate(policy: ActivePolicy, issue: CurrentIssue, milestone: Milestone, today: date, requested_effect: str = "ISSUE_COMMENT") -> Decision:
    if policy.status != "ACTIVE" or not policy.execute:
        return Decision(False, "POLICY_NOT_ACTIVE", None)
    if not policy.kill_switch or not policy.no_inheritance or not policy.postcommit_readback_required:
        return Decision(False, "POLICY_SAFETY_INVARIANT_MISSING", None)
    if today > date.fromisoformat(policy.review_by):
        return Decision(False, "POLICY_REVIEW_EXPIRED", None)
    if requested_effect != policy.allowed_effect or requested_effect in policy.forbidden_effects:
        return Decision(False, "EFFECT_NOT_ALLOWED", None)
    if issue.repo != policy.target_repo or issue.number != policy.target_issue or issue.title != policy.target_title:
        return Decision(False, "TARGET_MISMATCH", None)
    if issue.state != "open":
        return Decision(False, "TARGET_NOT_OPEN", None)
    if policy.bootstrap_activation_is_not_trigger and milestone.is_policy_activation:
        return Decision(False, "BOOTSTRAP_NOT_TRIGGER", None)
    if policy.material_only and not milestone.material:
        return Decision(False, "NOT_MATERIAL", None)
    if not milestone.canon_current:
        return Decision(False, "CANON_NOT_CURRENT", None)
    if milestone.conflict:
        return Decision(False, "CONFLICT_PRESENT", None)
    marker = f"Milestone key: `{milestone.key}`"
    if sum(marker in body for body in issue.comment_bodies) >= policy.max_comments_per_milestone_key:
        return Decision(False, "DUPLICATE_MILESTONE_KEY", None)
    return Decision(True, "ACTIVE_POLICY_ALLOWS_EXACT_EFFECT", render_body(milestone))
