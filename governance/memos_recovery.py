from __future__ import annotations

from governance.canon_router import Authority, GovernanceError, KnowledgeRecord, KnowledgeType
from governance.memos_composition import GovernedMemOSService, PartitionedMemOSIndex


class RecoverablePartitionedMemOSIndex(PartitionedMemOSIndex):
    """Derived index helper for safe reconciliation from Canon.

    The index remains non-authoritative. Equality checks only decide whether a
    canonical record needs to be projected again; reads are still hydrated and
    authorized from Canon by GovernedMemOSService.
    """

    _METADATA_FIELDS = (
        "source_ref",
        "observed_at",
        "subject",
        "target_domain",
        "knowledge_type",
        "epistemic_status",
        "confidence",
        "sensitivity",
        "purpose",
        "relations",
        "predecessor_id",
        "created_by",
    )

    def contains_current(self, record: KnowledgeRecord) -> bool:
        partition = self._partition(record)
        memory = self._memory(partition)
        try:
            actual = memory.get(record.record_id)
        except ValueError:
            return False
        expected = self._to_item(record)
        if actual.memory != expected.memory:
            return False
        for field in self._METADATA_FIELDS:
            if getattr(actual.metadata, field, None) != getattr(expected.metadata, field, None):
                return False
        return True


class RecoverableGovernedMemOSService(GovernedMemOSService):
    """Crash/retry-safe projection discipline around the existing composition.

    Durable ordering is deliberately Canon first:
      1. persist every changed canonical record;
      2. persist the corresponding canonical history events;
      3. advance the in-process history cursor;
      4. only then project changed records into the derived MemOS index.

    Therefore an index failure may leave the derived index behind, but it must
    not leave Canon or the canonical event trail behind the accepted write.
    Recovery reconciles only from Canon; candidate-index state is never used to
    reconstruct truth.
    """

    index: RecoverablePartitionedMemOSIndex

    def write(self, record: KnowledgeRecord, *, authority: Authority) -> KnowledgeRecord:
        existing = self.canonical.get(record.record_id)
        if existing is not None:
            if existing != record:
                raise GovernanceError("idempotency_conflict_existing_record")
            self.reconcile_index_from_canonical()
            return existing
        stored = self.gate.write(record, authority=authority)
        self._sync()
        return stored

    def promote_idea_to_decision(self, record_id: str, *, authority: Authority) -> KnowledgeRecord:
        existing = self.canonical.get(record_id)
        if existing is not None and existing.knowledge_type == KnowledgeType.DECISION:
            if not authority.can_promote_decision:
                raise GovernanceError("decision_promotion_requires_authority")
            self.reconcile_index_from_canonical()
            return existing
        return super().promote_idea_to_decision(record_id, authority=authority)

    def reconcile_index_from_canonical(self) -> int:
        projected = 0
        for record in self.canonical.all():
            if self.index.contains_current(record):
                continue
            self.index.put(record)
            projected += 1
        return projected

    def rebuild_index_from_canonical(self) -> int:
        """Populate an empty/fresh derived index strictly from canonical truth."""
        projected = 0
        for record in self.canonical.all():
            self.index.put(record)
            projected += 1
        return projected

    def _sync(self) -> None:
        changed: list[KnowledgeRecord] = []
        for record in self.gate.list_internal():
            persisted = self.canonical.get(record.record_id)
            if persisted == record:
                continue
            self.canonical.put(record)
            changed.append(record)

        # Canonical event history is committed before the fallible derived
        # projection. Advancing the cursor before index work also prevents an
        # in-process retry from duplicating durable history after an index fault.
        history = list(self.gate.history)
        for event in history[self._history_cursor :]:
            self.canonical.append_event(event)
        self._history_cursor = len(history)

        for record in changed:
            self.index.put(record)
