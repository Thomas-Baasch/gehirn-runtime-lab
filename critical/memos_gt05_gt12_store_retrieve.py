from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from memos.configs.vec_db import QdrantVecDBConfig
from memos.memories.textual.general import GeneralTextMemory
from memos.memories.textual.item import TextualMemoryItem, TextualMemoryMetadata
from memos.vec_dbs.qdrant import QdrantVecDB


class DeterministicEmbedder:
    """Test fixture only: deterministic vectors; no semantic policy is implemented here."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for text in texts:
            normalized = text.lower()
            if "vielleicht" in normalized or "idea" in normalized:
                result.append([1.0, 0.0, 0.0])
            elif "entschieden" in normalized or "decision" in normalized:
                result.append([0.0, 1.0, 0.0])
            else:
                result.append([0.0, 0.0, 1.0])
        return result


def contract_metadata(knowledge_type: str, source_ref: str) -> TextualMemoryMetadata:
    return TextualMemoryMetadata(
        type="cross_project_contract_record",
        source_ref=source_ref,
        observed_at=datetime(2026, 8, 19, 17, 0, tzinfo=UTC).isoformat(),
        subject="WZW sale consideration",
        target_domain="WZW",
        knowledge_type=knowledge_type,
        epistemic_status="USER_STATED",
        confidence=1.0,
        sensitivity="INTERNAL",
        purpose="cross_project_memory_test",
        relations=[],
    )


def contract_view(item: TextualMemoryItem) -> dict:
    md = item.metadata.model_dump()
    keys = [
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
    ]
    return {key: md.get(key) for key in keys}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eg-memos-gt05-gt12-") as td:
        vec_cfg = QdrantVecDBConfig(
            collection_name="gt05_gt12_contract_records",
            vector_dimension=3,
            distance_metric="cosine",
            path=str(Path(td) / "qdrant"),
        )
        vector_db = QdrantVecDB(vec_cfg)

        # Use the product's native GeneralTextMemory add/get/search paths.
        # Only the embedder is a deterministic fixture; it adds no routing,
        # epistemic, promotion, or conflict behavior.
        memory = GeneralTextMemory.__new__(GeneralTextMemory)
        memory.vector_db = vector_db
        memory.embedder = DeterministicEmbedder()

        idea = TextualMemoryItem(
            memory="Vielleicht verkaufe ich WZW nächstes Jahr.",
            metadata=contract_metadata("IDEA", "synthetic:gt05:idea"),
        )
        decision = TextualMemoryItem(
            memory="Ich habe entschieden, WZW zu verkaufen.",
            metadata=contract_metadata("DECISION", "synthetic:gt05:decision"),
        )

        original_idea = contract_view(idea)
        original_decision = contract_view(decision)

        memory.add([idea, decision])

        idea_get = memory.get(idea.id)
        decision_get = memory.get(decision.id)
        idea_search_first = memory.search("idea", top_k=2)[0]
        decision_search_first = memory.search("decision", top_k=2)[0]

        # GT-12 promotion protection: repeated recall must not mutate/promote IDEA.
        repeated_recall = []
        for _ in range(3):
            top = memory.search("idea", top_k=2)[0]
            repeated_recall.append(contract_view(top))
        idea_after_recall = memory.get(idea.id)

        all_records = {record.id: contract_view(record) for record in memory.get_all()}

        idea_get_exact = contract_view(idea_get) == original_idea
        decision_get_exact = contract_view(decision_get) == original_decision
        idea_search_exact = contract_view(idea_search_first) == original_idea
        decision_search_exact = contract_view(decision_search_first) == original_decision
        idea_stays_idea = all(
            record.get("knowledge_type") == "IDEA"
            and record.get("epistemic_status") == "USER_STATED"
            for record in repeated_recall
        ) and contract_view(idea_after_recall) == original_idea
        decision_stays_decision = (
            contract_view(decision_get).get("knowledge_type") == "DECISION"
            and contract_view(decision_get).get("epistemic_status") == "USER_STATED"
        )
        separate_records = idea.id != decision.id and len(all_records) == 2

        component_pass = all(
            [
                idea_get_exact,
                decision_get_exact,
                idea_search_exact,
                decision_search_exact,
                idea_stays_idea,
                decision_stays_decision,
                separate_records,
            ]
        )

        report = {
            "schema": "externes-gehirn.component-runtime-evidence.v0.1",
            "candidate": "MemTensor/MemOS",
            "distribution": "MemoryOS",
            "version": "2.0.30",
            "release_commit": "f4db521214c29337164ec788bafede7eab236c25",
            "tested_role": "MEMORY_SUBSTRATE_CONTRACT_ENVELOPE_PERSISTENCE",
            "golden_tests_informed_but_not_fully_claimed": ["GT-05", "GT-12"],
            "backend": "native GeneralTextMemory + native QdrantVecDB local embedded mode",
            "qdrant_version_pin": "1.16.0",
            "input_contract_views": {
                "idea": original_idea,
                "decision": original_decision,
            },
            "observations": {
                "idea_get_exact": idea_get_exact,
                "decision_get_exact": decision_get_exact,
                "idea_search_exact": idea_search_exact,
                "decision_search_exact": decision_search_exact,
                "idea_remains_idea_after_three_search_recalls": idea_stays_idea,
                "decision_remains_decision": decision_stays_decision,
                "idea_and_decision_remain_separate_records": separate_records,
                "idea_after_recall": contract_view(idea_after_recall),
                "repeated_idea_recall": repeated_recall,
                "all_record_contract_views": all_records,
            },
            "component_result": "PASS" if component_pass else "FAIL",
            "full_gt05_gt12_result": "NOT_CLAIMED",
            "reason": (
                "MemOS native GeneralTextMemory persisted and retrieved the separate contract dimensions without mutation; repeated recall did not promote IDEA to DECISION or change epistemic_status. This validates the memory-substrate role only. Classification/routing and promotion authorization remain responsibilities of a separate product-neutral governance layer."
                if component_pass
                else "The native MemOS persistence/retrieval path mutated or lost one or more contract dimensions."
            ),
        }

        out = Path("reports/critical/memos_gt05_gt12_store_retrieve.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if component_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
