from __future__ import annotations

import json
from pathlib import Path

from governance.canon_router import (
    Authority,
    EpistemicStatus,
    FailClosedCanonRouter,
    GovernanceError,
    KnowledgeType,
    RouteStatus,
    Sensitivity,
)


def authority(
    actor: str,
    projects: set[str],
    purposes: set[str],
    sensitivity: Sensitivity = Sensitivity.CONFIDENTIAL,
    *,
    verify: bool = False,
    correct: bool = False,
    promote: bool = False,
) -> Authority:
    return Authority(
        actor_id=actor,
        allowed_projects=frozenset(projects),
        allowed_purposes=frozenset(purposes),
        sensitivity_clearance=sensitivity,
        can_verify=verify,
        can_correct=correct,
        can_promote_decision=promote,
    )


def make_record(
    gate: FailClosedCanonRouter,
    *,
    auth: Authority,
    source: str,
    subject: str,
    target: str,
    kind: KnowledgeType,
    status: EpistemicStatus,
    content: str,
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
    purpose: str = "cross_project_memory",
    predecessor_id: str | None = None,
):
    return gate.new_record(
        source_ref=source,
        subject=subject,
        target_domain=target,
        knowledge_type=kind,
        epistemic_status=status,
        confidence=1.0,
        sensitivity=sensitivity,
        purpose=purpose,
        content=content,
        authority=auth,
        predecessor_id=predecessor_id,
    )


def main() -> int:
    results: dict[str, dict] = {}

    # GT-04 — ambiguous target must never be guessed.
    gt04_gate = FailClosedCanonRouter()
    router_auth = authority(
        "router", {"WZW", "Externes Gehirn"}, {"cross_project_memory"}
    )
    gt04 = gt04_gate.route(
        explicit_target=None,
        target_candidates=["WZW", "Externes Gehirn"],
        authority=router_auth,
    )
    gt04_pass = gt04.status == RouteStatus.AMBIGUOUS and gt04.target_domain is None
    results["GT-04"] = {
        "pass": gt04_pass,
        "status": gt04.status.value,
        "target_domain": gt04.target_domain,
        "reason": gt04.reason,
    }

    # GT-05 — IDEA and DECISION are separate dimensions and neither is verified by routing/storage.
    gt05_gate = FailClosedCanonRouter()
    user_auth = authority("user", {"WZW"}, {"cross_project_memory"})
    idea = make_record(
        gt05_gate,
        auth=user_auth,
        source="synthetic:gt05:idea",
        subject="possible WZW sale",
        target="WZW",
        kind=KnowledgeType.IDEA,
        status=EpistemicStatus.USER_STATED,
        content="Vielleicht verkaufe ich WZW nächstes Jahr.",
    )
    decision = make_record(
        gt05_gate,
        auth=user_auth,
        source="synthetic:gt05:decision",
        subject="WZW sale decision",
        target="WZW",
        kind=KnowledgeType.DECISION,
        status=EpistemicStatus.USER_STATED,
        content="Ich habe entschieden, WZW zu verkaufen.",
    )
    stored_idea = gt05_gate.write(idea, authority=user_auth)
    stored_decision = gt05_gate.write(decision, authority=user_auth)
    verified_escalation_blocked = False
    try:
        make_record(
            gt05_gate,
            auth=user_auth,
            source="synthetic:gt05:bad-verified",
            subject="forbidden elevation",
            target="WZW",
            kind=KnowledgeType.CLAIM,
            status=EpistemicStatus.VERIFIED,
            content="This should be blocked.",
        )
    except GovernanceError:
        verified_escalation_blocked = True
    gt05_pass = (
        stored_idea.knowledge_type == KnowledgeType.IDEA
        and stored_decision.knowledge_type == KnowledgeType.DECISION
        and stored_idea.epistemic_status == EpistemicStatus.USER_STATED
        and stored_decision.epistemic_status == EpistemicStatus.USER_STATED
        and verified_escalation_blocked
    )
    results["GT-05"] = {
        "pass": gt05_pass,
        "idea": {
            "knowledge_type": stored_idea.knowledge_type.value,
            "epistemic_status": stored_idea.epistemic_status.value,
        },
        "decision": {
            "knowledge_type": stored_decision.knowledge_type.value,
            "epistemic_status": stored_decision.epistemic_status.value,
        },
        "unauthorized_verified_elevation_blocked": verified_escalation_blocked,
    }

    # GT-06 — correction links successor, retains old record and supersedes only with authority.
    gt06_gate = FailClosedCanonRouter()
    correction_auth = authority(
        "trusted-reviewer",
        {"WZW"},
        {"cross_project_memory"},
        correct=True,
    )
    old = gt06_gate.write(
        make_record(
            gt06_gate,
            auth=correction_auth,
            source="synthetic:gt06:old",
            subject="current price",
            target="WZW",
            kind=KnowledgeType.CLAIM,
            status=EpistemicStatus.USER_STATED,
            content="490 Euro",
        ),
        authority=correction_auth,
    )
    correction = make_record(
        gt06_gate,
        auth=correction_auth,
        source="synthetic:gt06:correction",
        subject="current price",
        target="WZW",
        kind=KnowledgeType.CORRECTION,
        status=EpistemicStatus.USER_STATED,
        content="510 Euro",
        predecessor_id=old.record_id,
    )
    successor = gt06_gate.write(correction, authority=correction_auth)
    old_after = gt06_gate.get_internal(old.record_id)
    gt06_pass = (
        old_after.content == "490 Euro"
        and old_after.epistemic_status == EpistemicStatus.SUPERSEDED
        and successor.content == "510 Euro"
        and successor.knowledge_type == KnowledgeType.CORRECTION
        and successor.predecessor_id == old.record_id
        and any(
            event.get("event") == "corrected"
            and event.get("predecessor_id") == old.record_id
            and event.get("successor_id") == successor.record_id
            for event in gt06_gate.history
        )
    )
    results["GT-06"] = {
        "pass": gt06_pass,
        "old_retained": old_after.content == "490 Euro",
        "old_status": old_after.epistemic_status.value,
        "successor_type": successor.knowledge_type.value,
        "successor_predecessor_id": successor.predecessor_id,
        "history": list(gt06_gate.history),
    }

    # GT-08 — contradictory current claims coexist as CONFLICTING; no winner is selected.
    gt08_gate = FailClosedCanonRouter()
    conflict_auth = authority("user", {"WZW"}, {"cross_project_memory"})
    claim_a = gt08_gate.write(
        make_record(
            gt08_gate,
            auth=conflict_auth,
            source="synthetic:gt08:a",
            subject="current implementation language",
            target="WZW",
            kind=KnowledgeType.CLAIM,
            status=EpistemicStatus.USER_STATED,
            content="Python",
        ),
        authority=conflict_auth,
    )
    claim_b = gt08_gate.write(
        make_record(
            gt08_gate,
            auth=conflict_auth,
            source="synthetic:gt08:b",
            subject="current implementation language",
            target="WZW",
            kind=KnowledgeType.CLAIM,
            status=EpistemicStatus.USER_STATED,
            content="Rust",
        ),
        authority=conflict_auth,
    )
    claim_a_after = gt08_gate.get_internal(claim_a.record_id)
    claim_b_after = gt08_gate.get_internal(claim_b.record_id)
    conflict_records = [
        r
        for r in gt08_gate.list_internal()
        if r.subject == "current implementation language"
        and r.epistemic_status == EpistemicStatus.CONFLICTING
    ]
    gt08_pass = (
        claim_a_after.content == "Python"
        and claim_b_after.content == "Rust"
        and claim_a_after.epistemic_status == EpistemicStatus.CONFLICTING
        and claim_b_after.epistemic_status == EpistemicStatus.CONFLICTING
        and len(conflict_records) == 2
    )
    results["GT-08"] = {
        "pass": gt08_pass,
        "records": [
            {
                "record_id": r.record_id,
                "content": r.content,
                "epistemic_status": r.epistemic_status.value,
            }
            for r in conflict_records
        ],
        "current_winner_selected": False,
    }

    # GT-09 — purpose/sensitivity/project checks happen before read; denied read returns no record/metadata.
    gt09_gate = FailClosedCanonRouter()
    writer = authority(
        "writer-a",
        {"Project A"},
        {"project_a_only"},
        Sensitivity.CONFIDENTIAL,
    )
    secret = gt09_gate.write(
        make_record(
            gt09_gate,
            auth=writer,
            source="synthetic:gt09:secret",
            subject="restricted project A fact",
            target="Project A",
            kind=KnowledgeType.CLAIM,
            status=EpistemicStatus.USER_STATED,
            content="SYNTHETIC_SECRET_A",
            sensitivity=Sensitivity.CONFIDENTIAL,
            purpose="project_a_only",
        ),
        authority=writer,
    )
    reader_a = authority(
        "reader-a",
        {"Project A"},
        {"project_a_only"},
        Sensitivity.CONFIDENTIAL,
    )
    reader_b = authority(
        "reader-b",
        {"Project B"},
        {"project_b_only"},
        Sensitivity.CONFIDENTIAL,
    )
    allowed = gt09_gate.read(secret.record_id, authority=reader_a)
    blocked = gt09_gate.read(secret.record_id, authority=reader_b)
    gt09_pass = (
        allowed.allowed
        and allowed.record is not None
        and blocked.allowed is False
        and blocked.status == "BLOCKED"
        and blocked.record is None
        and blocked.reason == "policy_denied"
        and "SYNTHETIC_SECRET_A" not in blocked.reason
        and "CONFIDENTIAL" not in blocked.reason
        and "project_a_only" not in blocked.reason
    )
    results["GT-09"] = {
        "pass": gt09_pass,
        "project_a_allowed": allowed.allowed,
        "project_b_blocked": not blocked.allowed,
        "blocked_record_is_none": blocked.record is None,
        "blocked_reason": blocked.reason,
        "blocked_response_leaks_content_or_policy_metadata": False,
    }

    # GT-12 — recall is side-effect free; promotion requires a distinct authorized operation.
    gt12_gate = FailClosedCanonRouter()
    recall_auth = authority("user", {"WZW"}, {"cross_project_memory"})
    recall_idea = gt12_gate.write(
        make_record(
            gt12_gate,
            auth=recall_auth,
            source="synthetic:gt12:idea",
            subject="future WZW sale idea",
            target="WZW",
            kind=KnowledgeType.IDEA,
            status=EpistemicStatus.USER_STATED,
            content="Vielleicht verkaufe ich WZW nächstes Jahr.",
        ),
        authority=recall_auth,
    )
    recalls = [gt12_gate.read(recall_idea.record_id, authority=recall_auth) for _ in range(3)]
    after_recalls = gt12_gate.get_internal(recall_idea.record_id)
    unauthorized_promotion_blocked = False
    try:
        gt12_gate.promote_idea_to_decision(recall_idea.record_id, authority=recall_auth)
    except GovernanceError:
        unauthorized_promotion_blocked = True
    after_blocked_promotion = gt12_gate.get_internal(recall_idea.record_id)
    promoter = authority(
        "decision-authority",
        {"WZW"},
        {"cross_project_memory"},
        promote=True,
    )
    explicitly_promoted = gt12_gate.promote_idea_to_decision(
        recall_idea.record_id, authority=promoter
    )
    gt12_pass = (
        all(r.allowed and r.record and r.record.knowledge_type == KnowledgeType.IDEA for r in recalls)
        and after_recalls.knowledge_type == KnowledgeType.IDEA
        and after_recalls.epistemic_status == EpistemicStatus.USER_STATED
        and unauthorized_promotion_blocked
        and after_blocked_promotion.knowledge_type == KnowledgeType.IDEA
        and explicitly_promoted.knowledge_type == KnowledgeType.DECISION
        and explicitly_promoted.epistemic_status == EpistemicStatus.USER_STATED
    )
    results["GT-12"] = {
        "pass": gt12_pass,
        "three_recalls_remain_idea": all(
            r.record and r.record.knowledge_type == KnowledgeType.IDEA for r in recalls
        ),
        "epistemic_status_after_recalls": after_recalls.epistemic_status.value,
        "unauthorized_promotion_blocked": unauthorized_promotion_blocked,
        "type_after_blocked_promotion": after_blocked_promotion.knowledge_type.value,
        "explicit_authorized_promotion_type": explicitly_promoted.knowledge_type.value,
        "explicit_authorized_promotion_status": explicitly_promoted.epistemic_status.value,
    }

    passed = sum(1 for item in results.values() if item["pass"])
    report = {
        "schema": "externes-gehirn.product-neutral-governance-critical-gate.v0.1",
        "component": "FailClosedCanonRouter",
        "architecture_role": "SEPARATE_PRODUCT_NEUTRAL_ROUTER_GOVERNANCE_COMPONENT",
        "candidate_product_result": "NOT_APPLICABLE_AND_NOT_CLAIMED",
        "critical_tests": results,
        "passed": passed,
        "total": len(results),
        "result": "PASS" if passed == len(results) else "FAIL",
        "interpretation": (
            "This validates the separate governance component only. It does not convert SLM, MemOS or EverOS native GT-04/GT-08 failures into candidate PASS results. Candidate substrates must later be composed behind this gate and retested end-to-end."
        ),
    }

    out = Path("reports/governance/product_neutral_critical_gate.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
