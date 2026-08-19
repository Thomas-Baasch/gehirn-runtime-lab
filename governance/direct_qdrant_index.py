from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from governance.canon_router import KnowledgeRecord, Sensitivity, _SENSITIVITY_RANK


@dataclass(frozen=True)
class DirectSearchItem:
    id: str


class DirectQdrantIndex:
    """Minimal direct-Qdrant implementation of the derived-index contract.

    It intentionally owns no routing, truth, epistemic, conflict, correction,
    authorization or recovery semantics. Those remain in the same product-neutral
    layers used by the MemOS/Qdrant candidate.
    """

    COLLECTION = "canon_contract_index"

    def __init__(self, root: str | Path, embedder, *, vector_dimension: int = 4) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.vector_dimension = vector_dimension
        self._clients: dict[tuple[str, str, Sensitivity], object] = {}
        self.query_log: list[dict] = []
        self.write_log: list[dict] = []

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "default"

    @staticmethod
    def _partition(record: KnowledgeRecord) -> tuple[str, str, Sensitivity]:
        return (record.target_domain, record.purpose, record.sensitivity)

    def _client(self, partition: tuple[str, str, Sensitivity]):
        if partition in self._clients:
            return self._clients[partition]
        from qdrant_client import QdrantClient, models

        project, purpose, sensitivity = partition
        path = self.root / self._slug(project) / self._slug(purpose) / sensitivity.value.lower()
        path.parent.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(path))
        try:
            client.get_collection(self.COLLECTION)
        except Exception:
            client.create_collection(
                collection_name=self.COLLECTION,
                vectors_config=models.VectorParams(
                    size=self.vector_dimension,
                    distance=models.Distance.COSINE,
                ),
            )
        self._clients[partition] = client
        return client

    @staticmethod
    def _payload(record: KnowledgeRecord) -> dict:
        return {
            "content": record.content,
            "source_ref": record.source_ref,
            "observed_at": record.observed_at,
            "subject": record.subject,
            "target_domain": record.target_domain,
            "knowledge_type": record.knowledge_type.value,
            "epistemic_status": record.epistemic_status.value,
            "confidence": record.confidence,
            "sensitivity": record.sensitivity.value,
            "purpose": record.purpose,
            "relations": list(record.relations),
            "predecessor_id": record.predecessor_id,
            "created_by": record.created_by,
        }

    def put(self, record: KnowledgeRecord) -> None:
        from qdrant_client import models

        partition = self._partition(record)
        client = self._client(partition)
        existing = client.retrieve(
            collection_name=self.COLLECTION,
            ids=[record.record_id],
            with_payload=False,
            with_vectors=False,
        )
        vector = self.embedder.embed([record.content])[0]
        client.upsert(
            collection_name=self.COLLECTION,
            points=[
                models.PointStruct(
                    id=record.record_id,
                    vector=vector,
                    payload=self._payload(record),
                )
            ],
        )
        self.write_log.append(
            {
                "record_id": record.record_id,
                "partition": [partition[0], partition[1], partition[2].value],
                "action": "update" if existing else "add",
                "epistemic_status": record.epistemic_status.value,
                "knowledge_type": record.knowledge_type.value,
            }
        )

    def contains_current(self, record: KnowledgeRecord) -> bool:
        partition = self._partition(record)
        client = self._client(partition)
        points = client.retrieve(
            collection_name=self.COLLECTION,
            ids=[record.record_id],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return False
        return points[0].payload == self._payload(record)

    def search_allowed(
        self,
        *,
        query: str,
        project: str,
        purpose: str,
        clearance: Sensitivity,
        top_k: int = 10,
    ) -> list[DirectSearchItem]:
        query_vector = self.embedder.embed([query])[0]
        results: list[DirectSearchItem] = []
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
            if partition not in self._clients:
                continue
            client = self._clients[partition]
            points = client.query_points(
                collection_name=self.COLLECTION,
                query=query_vector,
                limit=top_k,
                with_payload=False,
                with_vectors=False,
            ).points
            results.extend(DirectSearchItem(id=str(point.id)) for point in points)
        return results[:top_k]

    def close(self) -> None:
        for client in self._clients.values():
            close = getattr(client, "close", None)
            if callable(close):
                close()
        self._clients.clear()

    def storage_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
