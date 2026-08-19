from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from memos.configs.memory import TreeTextMemoryConfig
from memos.memories.textual.item import TextualMemoryItem, TreeNodeTextualMemoryMetadata
from memos.memories.textual.tree_text_memory.organize.handler import NodeHandler
from memos.memories.textual.tree_text_memory.organize.reorganizer import GraphStructureReorganizer


class FakeGraphStore:
    def __init__(self, existing: TextualMemoryItem | None = None):
        self.existing = existing
        self.deleted: list[str] = []
        self.added_nodes: list[dict] = []
        self.updated_nodes: list[tuple[str, dict]] = []
        self.added_edges: list[tuple[str, str, str]] = []

    def search_by_embedding(self, embedding, top_k=5, scope=None, threshold=None, user_name=None):
        if self.existing is None:
            return []
        return [{"id": self.existing.id, "score": 0.99}]

    def get_nodes(self, ids, user_name=None):
        if self.existing is None or self.existing.id not in ids:
            return []
        return [self.existing.to_dict()]

    def delete_node(self, node_id, user_name=None):
        self.deleted.append(node_id)

    def get_edges(self, node_id, type="ANY", direction="ANY", user_name=None):
        return []

    def add_node(self, node_id, memory, metadata, user_name=None):
        self.added_nodes.append({"id": node_id, "memory": memory, "metadata": metadata})

    def edge_exists(self, source, target, edge_type, direction="ANY", user_name=None):
        return False

    def add_edge(self, source, target, edge_type=None, type=None, user_name=None):
        rel = edge_type if edge_type is not None else type
        self.added_edges.append((source, target, rel))

    def update_node(self, node_id, changes, user_name=None):
        self.updated_nodes.append((node_id, changes))


class SequenceLLM:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[object] = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("No deterministic LLM response left")
        return self.responses.pop(0)


class FakeEmbedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


def item(text: str, updated_at: str) -> TextualMemoryItem:
    return TextualMemoryItem(
        id=str(uuid4()),
        memory=text,
        metadata=TreeNodeTextualMemoryMetadata(
            memory_type="LongTermMemory",
            embedding=[0.1, 0.2, 0.3],
            updated_at=updated_at,
            created_at=updated_at,
            key="price",
            background="synthetic GT-08 contradiction",
            confidence=90.0,
            sources=[{"type": "chat", "role": "user", "content": text}],
        ),
    )


def hard_update_control() -> dict:
    old = item("The current price is 490 Euro", "2026-08-01T00:00:00+00:00")
    new = item("The current price is 510 Euro", "2026-08-02T00:00:00+00:00")
    graph = FakeGraphStore(existing=old)
    llm = SequenceLLM(["contradictory", "<answer>no</answer>"])
    handler = NodeHandler(graph, llm, FakeEmbedder())

    relationships = handler.detect(new, scope="LongTermMemory", user_name="synthetic")
    for a, b, relation in relationships:
        handler.resolve(a, b, relation, user_name="synthetic")

    return {
        "relationship_detected": [r[2] for r in relationships],
        "deleted_node_ids": graph.deleted,
        "old_node_id": old.id,
        "new_node_id": new.id,
        "older_node_deleted": graph.deleted == [old.id],
        "both_current_preserved": not graph.deleted,
    }


def fusion_control() -> dict:
    old = item("The current price is 490 Euro", "2026-08-01T00:00:00+00:00")
    new = item("The current price is 510 Euro", "2026-08-02T00:00:00+00:00")
    graph = FakeGraphStore(existing=old)
    llm = SequenceLLM(
        ["contradictory", "<answer>The price record contains a reconciled current value of 510 Euro.</answer>"]
    )
    handler = NodeHandler(graph, llm, FakeEmbedder())

    relationships = handler.detect(new, scope="LongTermMemory", user_name="synthetic")
    for a, b, relation in relationships:
        handler.resolve(a, b, relation, user_name="synthetic")

    archived = {
        node_id for node_id, changes in graph.updated_nodes if changes.get("status") == "archived"
    }
    merged_to_sources = {
        source for source, _target, rel in graph.added_edges if rel == "MERGED_TO"
    }
    return {
        "relationship_detected": [r[2] for r in relationships],
        "added_node_count": len(graph.added_nodes),
        "archived_original_ids": sorted(archived),
        "expected_original_ids": sorted([old.id, new.id]),
        "both_originals_archived": archived == {old.id, new.id},
        "merged_to_from_both": merged_to_sources == {old.id, new.id},
        "both_current_preserved": not archived,
    }


def safe_mode_control() -> dict:
    default_reorganize = TreeTextMemoryConfig.model_fields["reorganize"].default
    graph = FakeGraphStore()
    reorganizer = GraphStructureReorganizer(graph, SequenceLLM([]), FakeEmbedder(), False)
    before_queue_size = reorganizer.queue.qsize()
    result = reorganizer.wait_until_current_task_done()
    return {
        "config_default_reorganize": default_reorganize,
        "instance_is_reorganize": reorganizer.is_reorganize,
        "worker_thread_created": hasattr(reorganizer, "thread"),
        "optimizer_thread_created": hasattr(reorganizer, "structure_optimizer_thread"),
        "queue_size": before_queue_size,
        "wait_returns_without_processing": result is None,
        "safe_control_flow": (
            default_reorganize is False
            and reorganizer.is_reorganize is False
            and not hasattr(reorganizer, "thread")
            and not hasattr(reorganizer, "structure_optimizer_thread")
        ),
    }


def main() -> int:
    safe = safe_mode_control()
    hard = hard_update_control()
    fusion = fusion_control()

    negative_control_unsafe = (
        hard["relationship_detected"] == ["contradictory"]
        and hard["older_node_deleted"]
        and fusion["relationship_detected"] == ["contradictory"]
        and fusion["both_originals_archived"]
        and fusion["added_node_count"] == 1
    )

    # GT-08 strict PASS requires two current conflicting claims to remain simultaneously
    # represented as CONFLICTING without choosing/fusing a winner. Safe mode prevents the
    # unsafe reorganizer, but this surface exposes no native CONFLICTING epistemic state.
    strict_gt08_pass = False

    report = {
        "schema": "externes-gehirn.cross-project-runtime-evidence.v0.1",
        "candidate": "MemTensor/MemOS",
        "distribution": "MemoryOS",
        "version": "2.0.30",
        "release_commit": "f4db521214c29337164ec788bafede7eab236c25",
        "golden_test": "GT-08",
        "controls": {
            "safe_mode_reorganize_false": safe,
            "negative_control_unresolved_conflict": hard,
            "negative_control_fused_conflict": fusion,
        },
        "observations": {
            "safe_mode_disables_native_reorganizer_control_flow": safe["safe_control_flow"],
            "native_reorganizer_negative_control_demonstrates_unsafe_canon_behavior": negative_control_unsafe,
            "native_first_class_conflicting_epistemic_state_on_tested_surface": False,
        },
        "result": "PASS" if strict_gt08_pass else "FAIL",
        "critical_fail": not strict_gt08_pass,
        "reason": (
            "Native MemOS surface preserved both current contradictions as first-class CONFLICTING records."
            if strict_gt08_pass
            else "reorganize=false safely disables the destructive/fusing Reorganizer, but does not itself provide the contract's first-class CONFLICTING state. When Reorganizer is enabled, native conflict resolution either deletes the older claim after an unresolved fusion or archives both originals behind a merged winner. Therefore MemOS v2.0.30 does not satisfy strict GT-08 unchanged as the Canon router."
        ),
        "scope_note": "Deterministic LLM responses are observation fixtures only; all delete/archive/merge decisions are executed by MemOS native NodeHandler code. No adapter conflict policy is added.",
    }

    out = Path("reports/critical/memos_gt08_controls.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
