from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governance.canon_router import Authority, EpistemicStatus, KnowledgeType, Sensitivity
from governance.memos_composition import CanonicalSQLiteStore
from governance.memos_recovery import (
    RecoverableGovernedMemOSService,
    RecoverablePartitionedMemOSIndex,
)


class DeterministicEmbedder:
    """Synthetic embedding fixture only; no routing or governance semantics."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            t = text.upper()
            if "RECOVERY_LANG" in t:
                out.append([1.0, 0.0, 0.0, 0.0])
            elif "RECOVERY_IDEA" in t:
                out.append([0.0, 1.0, 0.0, 0.0])
            elif "RECOVERY_SECRET" in t:
                out.append([0.0, 0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 0.0, 1.0])
        return out


class FailOnceIndex(RecoverablePartitionedMemOSIndex):
    def __init__(self, root: str | Path, embedder) -> None:
        super().__init__(root, embedder)
        self.fail_record_id: str | None = None
        self.failure_count = 0

    def arm(self, record_id: str) -> None:
        self.fail_record_id = record_id

    def put(self, record) -> None:
        if self.fail_record_id == record.record_id:
            self.fail_record_id = None
            self.failure_count += 1
            raise RuntimeError("synthetic_index_projection_failure_after_canon_commit")
        super().put(record)


def auth(
    actor: str,
    *,
    clearance: Sensitivity = Sensitivity.CONFIDENTIAL,
) -> Authority:
    return Authority(
        actor_id=actor,
        allowed_projects=frozenset({"WZW"}),
        allowed_purposes=frozenset({"cross_project_memory"}),
        sensitivity_clearance=clearance,
    )


def make(
    service: RecoverableGovernedMemOSService,
    *,
    authority: Authority,
    source: str,
    subject: str,
    kind: KnowledgeType,
    content: str,
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
):
    return service.new_record(
        source_ref=source,
        subject=subject,
        target_domain="WZW",
        knowledge_type=kind,
        epistemic_status=EpistemicStatus.USER_STATED,
        confidence=1.0,
        sensitivity=sensitivity,
        purpose="cross_project_memory",
        content=content,
        authority=authority,
    )


def find_record(service, *, token: str, record_id: str, authority: Authority):
    status, hits = service.search(
        query=token,
        target_project="WZW",
        purpose="cross_project_memory",
        authority=authority,
        top_k=20,
    )
    return status, next((record for record in hits if record.record_id == record_id), None), hits


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eg-composed-recovery-") as td:
        root = Path(td)
        canonical = CanonicalSQLiteStore(root / "canon" / "canon.sqlite")
        embedder = DeterministicEmbedder()
        first_index = FailOnceIndex(root / "index_before_fault", embedder)
        service = RecoverableGovernedMemOSService(canonical, first_index)
        full = auth("user-full")
        low = auth("user-low", clearance=Sensitivity.INTERNAL)

        # Establish critical semantic state before fault injection.
        lang_a = service.write(
            make(
                service,
                authority=full,
                source="synthetic:recovery:lang:a",
                subject="current language",
                kind=KnowledgeType.CLAIM,
                content="RECOVERY_LANG Python",
            ),
            authority=full,
        )
        lang_b = service.write(
            make(
                service,
                authority=full,
                source="synthetic:recovery:lang:b",
                subject="current language",
                kind=KnowledgeType.CLAIM,
                content="RECOVERY_LANG Rust",
            ),
            authority=full,
        )
        idea = service.write(
            make(
                service,
                authority=full,
                source="synthetic:recovery:idea",
                subject="possible future sale",
                kind=KnowledgeType.IDEA,
                content="RECOVERY_IDEA Vielleicht verkaufen wir später.",
            ),
            authority=full,
        )
        secret = service.write(
            make(
                service,
                authority=full,
                source="synthetic:recovery:secret",
                subject="confidential project note",
                kind=KnowledgeType.CLAIM,
                content="RECOVERY_SECRET SYNTHETIC_CONFIDENTIAL_VALUE",
                sensitivity=Sensitivity.CONFIDENTIAL,
            ),
            authority=full,
        )

        baseline_count = canonical.count()
        baseline_events = len(canonical.events())

        # FI-02: fault occurs after durable Canon+history commit but before index projection.
        crash_record = make(
            service,
            authority=full,
            source="synthetic:recovery:crash",
            subject="crash boundary record",
            kind=KnowledgeType.TASK,
            content="RECOVERY_CRASH Canon committed before derived projection.",
        )
        first_index.arm(crash_record.record_id)
        fault_raised = False
        try:
            service.write(crash_record, authority=full)
        except RuntimeError as exc:
            fault_raised = str(exc) == "synthetic_index_projection_failure_after_canon_commit"

        canon_after_fault = canonical.get(crash_record.record_id)
        crash_events_after_fault = [
            event
            for event in canonical.events()
            if event.get("record_id") == crash_record.record_id
        ]
        fi02_pass = (
            fault_raised
            and first_index.failure_count == 1
            and canon_after_fault == crash_record
            and canonical.count() == baseline_count + 1
            and len(canonical.events()) == baseline_events + 1
            and len(crash_events_after_fault) == 1
            and not first_index.contains_current(crash_record)
        )

        # Lost acknowledgement retry: exact same record must not duplicate Canon/history.
        count_before_retry = canonical.count()
        events_before_retry = len(canonical.events())
        writes_before_retry = len(first_index.write_log)
        retry_result = service.write(crash_record, authority=full)
        retry_index_delta = len(first_index.write_log) - writes_before_retry
        crash_events_after_retry = [
            event
            for event in canonical.events()
            if event.get("record_id") == crash_record.record_id
        ]
        retry_pass = (
            retry_result == crash_record
            and canonical.count() == count_before_retry
            and len(canonical.events()) == events_before_retry
            and len(crash_events_after_retry) == 1
            and first_index.contains_current(crash_record)
            and retry_index_delta == 1
        )

        # FI-03: ignore the complete old index and rebuild into a brand-new empty one.
        rebuilt_index = RecoverablePartitionedMemOSIndex(root / "index_after_total_loss", embedder)
        restarted = RecoverableGovernedMemOSService(canonical, rebuilt_index)
        rebuilt_count = restarted.rebuild_index_from_canonical()
        all_canon = canonical.all()
        rebuild_complete = (
            rebuilt_count == len(all_canon)
            and all(rebuilt_index.contains_current(record) for record in all_canon)
        )

        crash_status, crash_hit, _ = find_record(
            restarted,
            token="RECOVERY_CRASH",
            record_id=crash_record.record_id,
            authority=full,
        )
        restart_recall_pass = crash_status == "ALLOWED" and crash_hit == crash_record

        # GT-08 invariant after rebuild: conflicting claims coexist; no winner appears.
        _status_a, hit_a, _ = find_record(
            restarted, token="RECOVERY_LANG", record_id=lang_a.record_id, authority=full
        )
        _status_b, hit_b, _ = find_record(
            restarted, token="RECOVERY_LANG", record_id=lang_b.record_id, authority=full
        )
        canon_a = canonical.get(lang_a.record_id)
        canon_b = canonical.get(lang_b.record_id)
        conflict_pass = (
            canon_a is not None
            and canon_b is not None
            and hit_a is not None
            and hit_b is not None
            and canon_a.epistemic_status == EpistemicStatus.CONFLICTING
            and canon_b.epistemic_status == EpistemicStatus.CONFLICTING
            and hit_a.epistemic_status == EpistemicStatus.CONFLICTING
            and hit_b.epistemic_status == EpistemicStatus.CONFLICTING
        )

        # GT-09 invariant after rebuild: low clearance never queries confidential partition.
        low_query_start = len(rebuilt_index.query_log)
        low_status, low_hits = restarted.search(
            query="RECOVERY_SECRET",
            target_project="WZW",
            purpose="cross_project_memory",
            authority=low,
            top_k=20,
        )
        low_queries = rebuilt_index.query_log[low_query_start:]
        touched_confidential = any(
            query["sensitivity_partition"] in {"CONFIDENTIAL", "RESTRICTED"}
            for query in low_queries
        )
        full_status, full_secret, _ = find_record(
            restarted,
            token="RECOVERY_SECRET",
            record_id=secret.record_id,
            authority=full,
        )
        policy_pass = (
            low_status == "ALLOWED"
            and all(record.record_id != secret.record_id for record in low_hits)
            and not touched_confidential
            and full_status == "ALLOWED"
            and full_secret is not None
        )

        # GT-12 invariant after rebuild: repeated recall cannot promote IDEA.
        recall_states: list[list[str]] = []
        idea_found_each_time = True
        for _ in range(3):
            status, hit, _ = find_record(
                restarted,
                token="RECOVERY_IDEA",
                record_id=idea.record_id,
                authority=full,
            )
            idea_found_each_time = idea_found_each_time and status == "ALLOWED" and hit is not None
            if hit is not None:
                recall_states.append([hit.knowledge_type.value, hit.epistemic_status.value])
        idea_after_recall = canonical.get(idea.record_id)
        no_promotion_pass = (
            idea_found_each_time
            and recall_states == [["IDEA", "USER_STATED"]] * 3
            and idea_after_recall is not None
            and idea_after_recall.knowledge_type == KnowledgeType.IDEA
        )

        # Corrupted/rogue derived item cannot become truth because search hydrates from Canon.
        rogue = make(
            restarted,
            authority=full,
            source="synthetic:recovery:rogue-index-only",
            subject="rogue derived payload",
            kind=KnowledgeType.DECISION,
            content="RECOVERY_ROGUE INDEX_ONLY_FAKE_DECISION",
        )
        rebuilt_index.put(rogue)
        rogue_status, rogue_hits = restarted.search(
            query="RECOVERY_ROGUE",
            target_project="WZW",
            purpose="cross_project_memory",
            authority=full,
            top_k=20,
        )
        rogue_pass = (
            rogue_status == "ALLOWED"
            and canonical.get(rogue.record_id) is None
            and all(record.record_id != rogue.record_id for record in rogue_hits)
        )

        # A second clean rebuild proves the rogue index-only state is disposable.
        clean_index = RecoverablePartitionedMemOSIndex(root / "index_clean_rebuild", embedder)
        clean_service = RecoverableGovernedMemOSService(canonical, clean_index)
        clean_count = clean_service.rebuild_index_from_canonical()
        clean_rogue_status, clean_rogue_hits = clean_service.search(
            query="RECOVERY_ROGUE",
            target_project="WZW",
            purpose="cross_project_memory",
            authority=full,
            top_k=20,
        )
        clean_rebuild_pass = (
            clean_count == canonical.count()
            and clean_rogue_status == "ALLOWED"
            and all(record.record_id != rogue.record_id for record in clean_rogue_hits)
        )

        tests = {
            "FI-02_CANON_COMMIT_BEFORE_INDEX_FAULT": {
                "pass": fi02_pass,
                "fault_raised": fault_raised,
                "canonical_record_survived": canon_after_fault == crash_record,
                "canonical_history_event_survived": len(crash_events_after_fault) == 1,
                "derived_projection_missing_after_fault": not first_index.contains_current(crash_record),
            },
            "RECOVERY_RETRY_IDEMPOTENCY": {
                "pass": retry_pass,
                "canonical_count_delta": canonical.count() - count_before_retry,
                "canonical_event_delta": len(canonical.events()) - events_before_retry,
                "derived_write_delta": retry_index_delta,
            },
            "FI-03_TOTAL_DERIVED_INDEX_LOSS_REBUILD": {
                "pass": rebuild_complete and restart_recall_pass,
                "canonical_records": len(all_canon),
                "rebuilt_records": rebuilt_count,
                "crash_record_recalled_after_rebuild": restart_recall_pass,
            },
            "RECOVERY_GT08_NO_WINNER": {
                "pass": conflict_pass,
                "canon_statuses": [
                    canon_a.epistemic_status.value if canon_a else None,
                    canon_b.epistemic_status.value if canon_b else None,
                ],
            },
            "RECOVERY_GT09_POLICY_NO_LEAK": {
                "pass": policy_pass,
                "low_clearance_touched_confidential_partition": touched_confidential,
                "low_clearance_returned_secret": any(
                    record.record_id == secret.record_id for record in low_hits
                ),
                "full_clearance_found_secret": full_secret is not None,
            },
            "RECOVERY_GT12_RECALL_NO_PROMOTION": {
                "pass": no_promotion_pass,
                "recall_states": recall_states,
            },
            "CORRUPT_DERIVED_ROGUE_PAYLOAD_NOT_TRUTH": {
                "pass": rogue_pass,
                "rogue_present_in_canon": canonical.get(rogue.record_id) is not None,
                "rogue_returned_as_truth": any(
                    record.record_id == rogue.record_id for record in rogue_hits
                ),
            },
            "CLEAN_REBUILD_DISCARDS_ROGUE_DERIVED_STATE": {
                "pass": clean_rebuild_pass,
                "clean_rebuild_count": clean_count,
                "canonical_count": canonical.count(),
            },
        }

        passed = sum(1 for result in tests.values() if result["pass"])
        report = {
            "schema": "externes-gehirn.composed-recovery-runtime-evidence.v0.1",
            "architecture": "Recoverable product-neutral Canon/History -> derived MemOS/Qdrant projection",
            "canon_truth": "SQLite product-neutral canonical store",
            "candidate_substrate": "MemTensor/MemOS",
            "candidate_distribution": "MemoryOS",
            "candidate_version": "2.0.30",
            "candidate_release_commit": "f4db521214c29337164ec788bafede7eab236c25",
            "qdrant_client_pin": "1.16.0",
            "index_truth_status": "DERIVED_RECONSTRUCTABLE_NOT_CANONICAL",
            "passed": passed,
            "total": len(tests),
            "result": "PASS" if passed == len(tests) else "FAIL",
            "tests": tests,
            "interpretation": (
                "Recovery/fault-injection evidence for the composed architecture only. "
                "It does not approve MemOS as native Canon, does not close direct REST auth, "
                "does not prove whole-system disaster recovery, and is not a final stack decision."
            ),
        }
        out = Path("reports/composed/governance_memos_recovery.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
