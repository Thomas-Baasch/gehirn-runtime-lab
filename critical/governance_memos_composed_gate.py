from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governance.canon_router import (
    Authority,
    EpistemicStatus,
    GovernanceError,
    KnowledgeType,
    RouteStatus,
    Sensitivity,
)
from governance.memos_composition import (
    CanonicalSQLiteStore,
    GovernedMemOSService,
    PartitionedMemOSIndex,
)


class DeterministicEmbedder:
    """Embedding fixture only; contains no routing/governance semantics."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            t = text.upper()
            if "IDEA_TOKEN" in t or "RECALL_IDEA_TOKEN" in t:
                out.append([1.0, 0.0, 0.0, 0.0])
            elif "DECISION_TOKEN" in t:
                out.append([0.0, 1.0, 0.0, 0.0])
            elif "PRICE_TOKEN" in t:
                out.append([0.0, 0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 0.0, 1.0])
        return out


def auth(
    actor: str,
    projects: set[str],
    purposes: set[str],
    clearance: Sensitivity = Sensitivity.CONFIDENTIAL,
    *,
    correct: bool = False,
    promote: bool = False,
) -> Authority:
    return Authority(
        actor_id=actor,
        allowed_projects=frozenset(projects),
        allowed_purposes=frozenset(purposes),
        sensitivity_clearance=clearance,
        can_correct=correct,
        can_promote_decision=promote,
    )


def make(
    service: GovernedMemOSService,
    *,
    authority: Authority,
    source: str,
    subject: str,
    project: str,
    kind: KnowledgeType,
    content: str,
    purpose: str = "cross_project_memory",
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
    predecessor_id: str | None = None,
):
    return service.new_record(
        source_ref=source,
        subject=subject,
        target_domain=project,
        knowledge_type=kind,
        epistemic_status=EpistemicStatus.USER_STATED,
        confidence=1.0,
        sensitivity=sensitivity,
        purpose=purpose,
        content=content,
        authority=authority,
        predecessor_id=predecessor_id,
    )


def record_summary(record):
    return {
        "record_id": record.record_id,
        "content": record.content,
        "target_domain": record.target_domain,
        "knowledge_type": record.knowledge_type.value,
        "epistemic_status": record.epistemic_status.value,
        "sensitivity": record.sensitivity.value,
        "purpose": record.purpose,
        "predecessor_id": record.predecessor_id,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eg-governance-memos-") as td:
        root = Path(td)
        canonical = CanonicalSQLiteStore(root / "canon" / "canon.sqlite")
        index = PartitionedMemOSIndex(root / "memos_index", DeterministicEmbedder())
        service = GovernedMemOSService(canonical, index)
        results: dict[str, dict] = {}

        standard = auth(
            "user",
            {"WZW", "Externes Gehirn", "Project A"},
            {"cross_project_memory", "project_a_only"},
        )

        # GT-04: ambiguity is resolved before any canonical or MemOS write.
        canon_before = canonical.count()
        index_writes_before = len(index.write_log)
        route = service.route(
            explicit_target=None,
            target_candidates=["WZW", "Externes Gehirn"],
            authority=standard,
        )
        gt04_pass = (
            route.status == RouteStatus.AMBIGUOUS
            and route.target_domain is None
            and canonical.count() == canon_before
            and len(index.write_log) == index_writes_before
        )
        results["GT-04"] = {
            "pass": gt04_pass,
            "route_status": route.status.value,
            "target_domain": route.target_domain,
            "canonical_write_delta": canonical.count() - canon_before,
            "memos_index_write_delta": len(index.write_log) - index_writes_before,
        }

        # GT-05: separate IDEA/DECISION survive canonical -> MemOS -> canonical hydration.
        idea = service.write(
            make(
                service,
                authority=standard,
                source="synthetic:composed:gt05:idea",
                subject="possible WZW sale",
                project="WZW",
                kind=KnowledgeType.IDEA,
                content="IDEA_TOKEN Vielleicht verkaufe ich WZW nächstes Jahr.",
            ),
            authority=standard,
        )
        decision = service.write(
            make(
                service,
                authority=standard,
                source="synthetic:composed:gt05:decision",
                subject="WZW sale decision",
                project="WZW",
                kind=KnowledgeType.DECISION,
                content="DECISION_TOKEN Ich habe entschieden, WZW zu verkaufen.",
            ),
            authority=standard,
        )
        idea_status, idea_hits = service.search(
            query="IDEA_TOKEN",
            target_project="WZW",
            purpose="cross_project_memory",
            authority=standard,
            top_k=10,
        )
        decision_status, decision_hits = service.search(
            query="DECISION_TOKEN",
            target_project="WZW",
            purpose="cross_project_memory",
            authority=standard,
            top_k=10,
        )
        idea_hit = next((r for r in idea_hits if r.record_id == idea.record_id), None)
        decision_hit = next((r for r in decision_hits if r.record_id == decision.record_id), None)
        gt05_pass = (
            idea_status == "ALLOWED"
            and decision_status == "ALLOWED"
            and idea_hit is not None
            and decision_hit is not None
            and idea_hit.knowledge_type == KnowledgeType.IDEA
            and decision_hit.knowledge_type == KnowledgeType.DECISION
            and idea_hit.epistemic_status == EpistemicStatus.USER_STATED
            and decision_hit.epistemic_status == EpistemicStatus.USER_STATED
        )
        results["GT-05"] = {
            "pass": gt05_pass,
            "idea": record_summary(idea_hit) if idea_hit else None,
            "decision": record_summary(decision_hit) if decision_hit else None,
        }

        # GT-06: correction mutates Canon lineage/status first, then projects both states to MemOS.
        correction_auth = auth(
            "trusted-reviewer", {"WZW"}, {"cross_project_memory"}, correct=True
        )
        old_price = service.write(
            make(
                service,
                authority=correction_auth,
                source="synthetic:composed:gt06:old",
                subject="current price",
                project="WZW",
                kind=KnowledgeType.CLAIM,
                content="PRICE_TOKEN 490 Euro",
            ),
            authority=correction_auth,
        )
        correction = service.write(
            make(
                service,
                authority=correction_auth,
                source="synthetic:composed:gt06:correction",
                subject="current price",
                project="WZW",
                kind=KnowledgeType.CORRECTION,
                content="PRICE_TOKEN 510 Euro",
                predecessor_id=old_price.record_id,
            ),
            authority=correction_auth,
        )
        old_canon = canonical.get(old_price.record_id)
        new_canon = canonical.get(correction.record_id)
        _price_status, price_hits = service.search(
            query="PRICE_TOKEN",
            target_project="WZW",
            purpose="cross_project_memory",
            authority=correction_auth,
            top_k=10,
        )
        indexed_price_ids = {r.record_id for r in price_hits}
        gt06_pass = (
            old_canon is not None
            and new_canon is not None
            and old_canon.epistemic_status == EpistemicStatus.SUPERSEDED
            and new_canon.knowledge_type == KnowledgeType.CORRECTION
            and new_canon.predecessor_id == old_canon.record_id
            and {old_canon.record_id, new_canon.record_id}.issubset(indexed_price_ids)
            and any(e.get("event") == "corrected" for e in canonical.events())
        )
        results["GT-06"] = {
            "pass": gt06_pass,
            "old_canonical": record_summary(old_canon) if old_canon else None,
            "new_canonical": record_summary(new_canon) if new_canon else None,
            "both_records_retrievable_through_memos_index": {old_price.record_id, correction.record_id}.issubset(indexed_price_ids),
        }

        # GT-08: both contradictory current claims remain CONFLICTING in Canon and projected index.
        lang_a = service.write(
            make(
                service,
                authority=standard,
                source="synthetic:composed:gt08:a",
                subject="current language",
                project="WZW",
                kind=KnowledgeType.CLAIM,
                content="LANG_TOKEN Python",
            ),
            authority=standard,
        )
        lang_b = service.write(
            make(
                service,
                authority=standard,
                source="synthetic:composed:gt08:b",
                subject="current language",
                project="WZW",
                kind=KnowledgeType.CLAIM,
                content="LANG_TOKEN Rust",
            ),
            authority=standard,
        )
        canon_lang_a = canonical.get(lang_a.record_id)
        canon_lang_b = canonical.get(lang_b.record_id)
        _lang_status, lang_hits = service.search(
            query="LANG_TOKEN",
            target_project="WZW",
            purpose="cross_project_memory",
            authority=standard,
            top_k=10,
        )
        lang_by_id = {r.record_id: r for r in lang_hits}
        gt08_pass = (
            canon_lang_a is not None
            and canon_lang_b is not None
            and canon_lang_a.epistemic_status == EpistemicStatus.CONFLICTING
            and canon_lang_b.epistemic_status == EpistemicStatus.CONFLICTING
            and lang_by_id.get(lang_a.record_id) is not None
            and lang_by_id.get(lang_b.record_id) is not None
            and lang_by_id[lang_a.record_id].epistemic_status == EpistemicStatus.CONFLICTING
            and lang_by_id[lang_b.record_id].epistemic_status == EpistemicStatus.CONFLICTING
        )
        results["GT-08"] = {
            "pass": gt08_pass,
            "canonical_records": [record_summary(canon_lang_a), record_summary(canon_lang_b)],
            "memos_retrieved_records": [
                record_summary(lang_by_id[rid]) for rid in (lang_a.record_id, lang_b.record_id) if rid in lang_by_id
            ],
            "winner_selected": False,
        }

        # GT-09: project/purpose/sensitivity gates prevent forbidden partition retrieval.
        secret_writer = auth(
            "writer-a", {"Project A"}, {"project_a_only"}, Sensitivity.CONFIDENTIAL
        )
        secret = service.write(
            make(
                service,
                authority=secret_writer,
                source="synthetic:composed:gt09:secret",
                subject="project A secret",
                project="Project A",
                kind=KnowledgeType.CLAIM,
                content="SECRET_TOKEN SYNTHETIC_SECRET_PROJECT_A",
                purpose="project_a_only",
                sensitivity=Sensitivity.CONFIDENTIAL,
            ),
            authority=secret_writer,
        )
        reader_b = auth(
            "reader-b", {"Project B"}, {"project_b_only"}, Sensitivity.CONFIDENTIAL
        )
        query_count_before_b = len(index.query_log)
        b_status, b_hits = service.search(
            query="SECRET_TOKEN",
            target_project="Project A",
            purpose="project_a_only",
            authority=reader_b,
        )
        query_count_after_b = len(index.query_log)

        reader_a_low = auth(
            "reader-a-low", {"Project A"}, {"project_a_only"}, Sensitivity.INTERNAL
        )
        low_start = len(index.query_log)
        low_status, low_hits = service.search(
            query="SECRET_TOKEN",
            target_project="Project A",
            purpose="project_a_only",
            authority=reader_a_low,
        )
        low_delta = index.query_log[low_start:]
        low_touched_confidential = any(
            q["sensitivity_partition"] in {"CONFIDENTIAL", "RESTRICTED"} for q in low_delta
        )

        reader_a_full = auth(
            "reader-a-full", {"Project A"}, {"project_a_only"}, Sensitivity.CONFIDENTIAL
        )
        full_status, full_hits = service.search(
            query="SECRET_TOKEN",
            target_project="Project A",
            purpose="project_a_only",
            authority=reader_a_full,
        )
        full_secret = next((r for r in full_hits if r.record_id == secret.record_id), None)
        gt09_pass = (
            b_status == "BLOCKED"
            and b_hits == []
            and query_count_after_b == query_count_before_b
            and low_status == "ALLOWED"
            and low_hits == []
            and not low_touched_confidential
            and full_status == "ALLOWED"
            and full_secret is not None
        )
        results["GT-09"] = {
            "pass": gt09_pass,
            "project_b_blocked_before_any_index_query": query_count_after_b == query_count_before_b,
            "project_b_returned_records": len(b_hits),
            "low_clearance_touched_confidential_partition": low_touched_confidential,
            "low_clearance_returned_records": len(low_hits),
            "authorized_confidential_read_found_secret": full_secret is not None,
        }

        # GT-12: rebuild governance state from canonical SQLite, then repeat MemOS recall.
        recall_idea = service.write(
            make(
                service,
                authority=standard,
                source="synthetic:composed:gt12:idea",
                subject="future WZW sale idea after restart",
                project="WZW",
                kind=KnowledgeType.IDEA,
                content="RECALL_IDEA_TOKEN Vielleicht verkaufen wir später.",
            ),
            authority=standard,
        )
        restarted = GovernedMemOSService(canonical, index)
        recalled_states = []
        found_each_time = True
        for _ in range(3):
            status, hits = restarted.search(
                query="RECALL_IDEA_TOKEN",
                target_project="WZW",
                purpose="cross_project_memory",
                authority=standard,
                top_k=10,
            )
            hit = next((r for r in hits if r.record_id == recall_idea.record_id), None)
            found_each_time = found_each_time and status == "ALLOWED" and hit is not None
            if hit:
                recalled_states.append(
                    [hit.knowledge_type.value, hit.epistemic_status.value]
                )
        after_recall = canonical.get(recall_idea.record_id)
        unauthorized_blocked = False
        try:
            restarted.promote_idea_to_decision(recall_idea.record_id, authority=standard)
        except GovernanceError:
            unauthorized_blocked = True
        after_blocked = canonical.get(recall_idea.record_id)
        promoter = auth(
            "decision-authority", {"WZW"}, {"cross_project_memory"}, promote=True
        )
        promoted = restarted.promote_idea_to_decision(
            recall_idea.record_id, authority=promoter
        )
        after_promoted = canonical.get(recall_idea.record_id)
        gt12_pass = (
            found_each_time
            and recalled_states == [["IDEA", "USER_STATED"]] * 3
            and after_recall is not None
            and after_recall.knowledge_type == KnowledgeType.IDEA
            and unauthorized_blocked
            and after_blocked is not None
            and after_blocked.knowledge_type == KnowledgeType.IDEA
            and promoted.knowledge_type == KnowledgeType.DECISION
            and after_promoted is not None
            and after_promoted.knowledge_type == KnowledgeType.DECISION
            and after_promoted.epistemic_status == EpistemicStatus.USER_STATED
        )
        results["GT-12"] = {
            "pass": gt12_pass,
            "governance_reconstructed_from_canonical_sqlite": restarted.gate.get_internal(recall_idea.record_id).record_id == recall_idea.record_id,
            "three_recall_states": recalled_states,
            "unauthorized_promotion_blocked": unauthorized_blocked,
            "type_after_blocked_promotion": after_blocked.knowledge_type.value if after_blocked else None,
            "type_after_explicit_authorized_promotion": after_promoted.knowledge_type.value if after_promoted else None,
        }

        passed = sum(1 for item in results.values() if item["pass"])
        report = {
            "schema": "externes-gehirn.composed-critical-runtime-evidence.v0.1",
            "architecture": "FailClosedCanonRouter -> CanonicalSQLiteStore -> partitioned MemOS derived index",
            "candidate_substrate": "MemTensor/MemOS",
            "candidate_distribution": "MemoryOS",
            "candidate_version": "2.0.30",
            "candidate_release_commit": "f4db521214c29337164ec788bafede7eab236c25",
            "qdrant_client_pin": "1.16.0",
            "reorganize_policy": "NOT_USED; candidate is derived GeneralTextMemory/Qdrant index only",
            "canon_truth": "SQLite product-neutral canonical store",
            "index_truth_status": "DERIVED_RECONSTRUCTABLE_NOT_CANONICAL",
            "critical_tests": results,
            "passed": passed,
            "total": len(results),
            "result": "PASS" if passed == len(results) else "FAIL",
            "interpretation": (
                "This is an end-to-end composed architecture result for the six critical tests, not a native MemOS product PASS. The separate governance/canonical layer supplies routing, epistemic, conflict, correction and policy semantics; MemOS is exercised only as the real derived search/memory substrate. Full GT-01..GT-12 remains unclaimed."
            ),
            "canonical_event_count": len(canonical.events()),
            "memos_index_write_count": len(index.write_log),
            "memos_index_query_count": len(index.query_log),
        }
        out = Path("reports/composed/governance_memos_critical.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
