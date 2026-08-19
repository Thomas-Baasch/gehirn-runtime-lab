from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from governance.canon_router import (
    Authority,
    EpistemicStatus,
    FailClosedCanonRouter,
    KnowledgeRecord,
    KnowledgeType,
    ReadDecision,
    RouteDecision,
    Sensitivity,
    _SENSITIVITY_RANK,
)

from memos.configs.vec_db import QdrantVecDBConfig
from memos.memories.textual.general import GeneralTextMemory
from memos.memories.textual.item import TextualMemoryItem, TextualMemoryMetadata
from memos.vec_dbs.qdrant import QdrantVecDB


class CanonicalSQLiteStore:
    """Durable canonical truth. MemOS is never authoritative here."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT PRIMARY KEY,
                    source_ref TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    target_domain TEXT NOT NULL,
                    knowledge_type TEXT NOT NULL,
                    epistemic_status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    sensitivity TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    content TEXT NOT NULL,
                    relations_json TEXT NOT NULL,
                    predecessor_id TEXT,
                    created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def put(self, record: KnowledgeRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO records (
                    record_id, source_ref, observed_at, subject, target_domain,
                    knowledge_type, epistemic_status, confidence, sensitivity,
                    purpose, content, relations_json, predecessor_id, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    source_ref=excluded.source_ref,
                    observed_at=excluded.observed_at,
                    subject=excluded.subject,
                    target_domain=excluded.target_domain,
                    knowledge_type=excluded.knowledge_type,
                    epistemic_status=excluded.epistemic_status,
                    confidence=excluded.confidence,
                    sensitivity=excluded.sensitivity,
                    purpose=excluded.purpose,
                    content=excluded.content,
                    relations_json=excluded.relations_json,
                    predecessor_id=excluded.predecessor_id,
                    created_by=excluded.created_by
                """,
                (
                    record.record_id,
                    record.source_ref,
                    record.observed_at,
                    record.subject,
                    record.target_domain,
                    record.knowledge_type.value,
                    record.epistemic_status.value,
                    record.confidence,
                    record.sensitivity.value,
                    record.purpose,
                    record.content,
                    json.dumps(list(record.relations), ensure_ascii=False),
                    record.predecessor_id,
                    record.created_by,
                ),
            )

    def get(self, record_id: str) -> KnowledgeRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT record_id, source_ref, observed_at, subject, target_domain, "
                "knowledge_type, epistemic_status, confidence, sensitivity, purpose, content, "
                "relations_json, predecessor_id, created_by FROM records WHERE record_id=?",
                (record_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def all(self) -> list[KnowledgeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record_id, source_ref, observed_at, subject, target_domain, "
                "knowledge_type, epistemic_status, confidence, sensitivity, purpose, content, "
                "relations_json, predecessor_id, created_by FROM records ORDER BY rowid"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def append_event(self, event: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events(payload_json) VALUES (?)",
                (json.dumps(event, ensure_ascii=False, sort_keys=True, default=str),),
            )

    def events(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM events ORDER BY event_no").fetchall()
        return [json.loads(row[0]) for row in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    @staticmethod
    def _from_row(row) -> KnowledgeRecord:
        return KnowledgeRecord(
            record_id=row[0],
            source_ref=row[1],
            observed_at=row[2],
            subject=row[3],
            target_domain=row[4],
            knowledge_type=KnowledgeType(row[5]),
            epistemic_status=EpistemicStatus(row[6]),
            confidence=float(row[7]),
            sensitivity=Sensitivity(row[8]),
            purpose=row[9],
            content=row[10],
            relations=tuple(json.loads(row[11])),
            predecessor_id=row[12],
            created_by=row[13],
        )


class PartitionedMemOSIndex:
    """Derived MemOS index partitioned before retrieval by policy dimensions."""

    def __init__(self, root: str | Path, embedder) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self._memories: dict[tuple[str, str, Sensitivity], GeneralTextMemory] = {}
        self.query_log: list[dict] = []
        self.write_log: list[dict] = []

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "default"

    def _partition(self, record: KnowledgeRecord) -> tuple[str, str, Sensitivity]:
        return (record.target_domain, record.purpose, record.sensitivity)

    def _memory(self, partition: tuple[str, str, Sensitivity]) -> GeneralTextMemory:
        if partition in self._memories:
            return self._memories[partition]
        project, purpose, sensitivity = partition
        path = self.root / self._slug(project) / self._slug(purpose) / sensitivity.value.lower()
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = QdrantVecDBConfig(
            collection_name="canon_contract_index",
            vector_dimension=4,
            distance_metric="cosine",
            path=str(path),
        )
        memory = GeneralTextMemory.__new__(GeneralTextMemory)
        memory.vector_db = QdrantVecDB(cfg)
        memory.embedder = self.embedder
        self._memories[partition] = memory
        return memory

    @staticmethod
    def _to_item(record: KnowledgeRecord) -> TextualMemoryItem:
        metadata = TextualMemoryMetadata(
            type="canon_contract_index_projection",
            source_ref=record.source_ref,
            observed_at=record.observed_at,
            subject=record.subject,
            target_domain=record.target_domain,
            knowledge_type=record.knowledge_type.value,
            epistemic_status=record.epistemic_status.value,
            confidence=record.confidence,
            sensitivity=record.sensitivity.value,
            purpose=record.purpose,
            relations=list(record.relations),
            predecessor_id=record.predecessor_id,
            created_by=record.created_by,
        )
        return TextualMemoryItem(id=record.record_id, memory=record.content, metadata=metadata)

    def put(self, record: KnowledgeRecord) -> None:
        partition = self._partition(record)
        memory = self._memory(partition)
        item = self._to_item(record)
        try:
            memory.get(record.record_id)
        except ValueError:
            memory.add([item])
            action = "add"
        else:
            memory.update(record.record_id, item)
            action = "update"
        self.write_log.append(
            {
                "record_id": record.record_id,
                "partition": [partition[0], partition[1], partition[2].value],
                "action": action,
                "epistemic_status": record.epistemic_status.value,
                "knowledge_type": record.knowledge_type.value,
            }
        )

    def search_allowed(
        self,
        *,
        query: str,
        project: str,
        purpose: str,
        clearance: Sensitivity,
        top_k: int = 10,
    ) -> list[TextualMemoryItem]:
        results: list[TextualMemoryItem] = []
        for sensitivity in Sensitivity:
            if _SENSITIVITY_RANK[sensitivity] > _SENSITIVITY_RANK[clearance]:
                continue
            partition = (project, purpose, sensitivity)
            self.query_log.append(
                {
                    "project": project,
                    "purpose": purpose,
                    "sensitivity_partition": sensitivity.value,
                    "query": query,
                }
            )
            if partition not in self._memories:
                continue
            results.extend(self._memories[partition].search(query, top_k=top_k))
        return results[:top_k]


class GovernedMemOSService:
    """Governance + canonical truth + derived MemOS index composition."""

    def __init__(
        self,
        canonical: CanonicalSQLiteStore,
        index: PartitionedMemOSIndex,
    ) -> None:
        self.canonical = canonical
        self.index = index
        self.gate = FailClosedCanonRouter()
        # Canonical truth reconstructs governance state; index is not consulted.
        restored = canonical.all()
        self.gate._records = {record.record_id: record for record in restored}
        self._history_cursor = 0

    def route(
        self,
        *,
        explicit_target: str | None,
        target_candidates: Iterable[str],
        authority: Authority,
    ) -> RouteDecision:
        return self.gate.route(
            explicit_target=explicit_target,
            target_candidates=target_candidates,
            authority=authority,
        )

    def new_record(self, **kwargs) -> KnowledgeRecord:
        return self.gate.new_record(**kwargs)

    def write(self, record: KnowledgeRecord, *, authority: Authority) -> KnowledgeRecord:
        stored = self.gate.write(record, authority=authority)
        self._sync()
        return stored

    def promote_idea_to_decision(self, record_id: str, *, authority: Authority) -> KnowledgeRecord:
        promoted = self.gate.promote_idea_to_decision(record_id, authority=authority)
        self._sync()
        return promoted

    def search(
        self,
        *,
        query: str,
        target_project: str,
        purpose: str,
        authority: Authority,
        top_k: int = 10,
    ) -> tuple[str, list[KnowledgeRecord]]:
        # Policy gates run before any candidate-index retrieval.
        route = self.gate.route(
            explicit_target=target_project,
            target_candidates=(),
            authority=authority,
        )
        if route.status.value != "ROUTED":
            return ("BLOCKED", [])
        if purpose not in authority.allowed_purposes:
            return ("BLOCKED", [])

        indexed = self.index.search_allowed(
            query=query,
            project=target_project,
            purpose=purpose,
            clearance=authority.sensitivity_clearance,
            top_k=top_k,
        )
        allowed: list[KnowledgeRecord] = []
        seen: set[str] = set()
        for item in indexed:
            if item.id in seen:
                continue
            seen.add(item.id)
            canonical_record = self.canonical.get(item.id)
            if canonical_record is None:
                continue
            decision: ReadDecision = self.gate.read(item.id, authority=authority)
            if decision.allowed and decision.record is not None:
                # Hydrate from canonical truth, never return candidate-index payload as truth.
                allowed.append(canonical_record)
        return ("ALLOWED", allowed)

    def _sync(self) -> None:
        # Project only records whose canonical representation is new or changed.
        # This avoids rewriting unchanged Canon records into the derived MemOS index,
        # while still re-projecting status/content changes caused by conflict,
        # correction or explicit promotion.
        for record in self.gate.list_internal():
            persisted = self.canonical.get(record.record_id)
            if persisted == record:
                continue
            self.canonical.put(record)
            self.index.put(record)
        history = list(self.gate.history)
        for event in history[self._history_cursor :]:
            self.canonical.append_event(event)
        self._history_cursor = len(history)