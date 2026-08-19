from __future__ import annotations

import argparse
import json
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path


def slm_probe() -> dict:
    from superlocalmemory.storage.models import AtomicFact, FactType, MemoryRecord

    envelope = {
        "knowledge_type": "IDEA",
        "epistemic_status": "USER_STATED",
        "target_domain": "WZW",
    }
    raw = MemoryRecord(content="Vielleicht verkaufe ich WZW nächstes Jahr.", metadata=envelope)
    raw_roundtrip = MemoryRecord(**asdict(raw))
    fact_fields = {f.name for f in fields(AtomicFact)}
    memory_fields = {f.name for f in fields(MemoryRecord)}
    fact_types = [v.value for v in FactType]
    primary_retrieval_claim = "PRIMARY retrieval unit" in (AtomicFact.__doc__ or "")

    return {
        "candidate": "SuperLocalMemory",
        "version": "4.0.8",
        "release_commit": "a5438ee6028c9bd7ca30959a3d61d133c24592ed",
        "raw_memory_metadata_roundtrip_preserves_contract_envelope": raw_roundtrip.metadata == envelope,
        "memory_record_has_free_metadata": "metadata" in memory_fields,
        "atomic_fact_is_documented_primary_retrieval_unit": primary_retrieval_claim,
        "atomic_fact_fields": sorted(fact_fields),
        "atomic_fact_has_knowledge_type": "knowledge_type" in fact_fields,
        "atomic_fact_has_epistemic_status": "epistemic_status" in fact_fields,
        "atomic_fact_has_free_metadata": "metadata" in fact_fields,
        "native_fact_type_values": fact_types,
        "idea_decision_are_native_fact_types": "IDEA" in fact_types or "DECISION" in fact_types,
        "prerequisite_status": "PARTIAL",
        "reason": "Raw MemoryRecord metadata can preserve the contract envelope, but SLM documents AtomicFact as the primary retrieval unit and that model carries neither free metadata nor separate knowledge_type/epistemic_status fields. A join/sidecar adapter may be possible, but full GT-05/GT-12 roundtrip is not proven by the unchanged native retrieval surface.",
    }


def memos_probe() -> dict:
    from memos.memories.textual.item import TextualMemoryItem, TextualMemoryMetadata

    def roundtrip(kind: str, content: str) -> dict:
        meta = TextualMemoryMetadata(
            type="contract_candidate",
            knowledge_type=kind,
            epistemic_status="USER_STATED",
            target_domain="WZW",
        )
        original = TextualMemoryItem(memory=content, metadata=meta)
        first = TextualMemoryItem.from_dict(original.to_dict())
        second = TextualMemoryItem.from_dict(first.to_dict())
        dump = second.to_dict()["metadata"]
        return {
            "knowledge_type": dump.get("knowledge_type"),
            "epistemic_status": dump.get("epistemic_status"),
            "target_domain": dump.get("target_domain"),
            "preserved": dump.get("knowledge_type") == kind
            and dump.get("epistemic_status") == "USER_STATED"
            and dump.get("target_domain") == "WZW",
        }

    idea = roundtrip("IDEA", "Vielleicht verkaufe ich WZW nächstes Jahr.")
    decision = roundtrip("DECISION", "Ich habe entschieden, WZW zu verkaufen.")
    config_extra = TextualMemoryMetadata.model_config.get("extra")

    return {
        "candidate": "MemTensor/MemOS",
        "distribution": "MemoryOS",
        "version": "2.0.30",
        "release_commit": "f4db521214c29337164ec788bafede7eab236c25",
        "metadata_extra_policy": config_extra,
        "idea_double_serialization_roundtrip": idea,
        "decision_double_serialization_roundtrip": decision,
        "separate_contract_dimensions_can_be_carried_in_native_metadata_model": idea["preserved"] and decision["preserved"],
        "idea_remains_idea_across_repeated_model_roundtrip": idea["knowledge_type"] == "IDEA",
        "prerequisite_status": "PASS_MODEL_ROUNDTRIP" if idea["preserved"] and decision["preserved"] else "FAIL_MODEL_ROUNDTRIP",
        "reason": "MemOS TextualMemoryMetadata explicitly allows extra fields, and the exact contract fields survive repeated native TextualMemoryItem serialization/deserialization. This is positive component evidence, but it is not yet an end-to-end store/search GT-05/GT-12 PASS.",
    }


def everos_probe() -> dict:
    from everos.infra.persistence.lancedb.tables.episode import Episode

    fields_set = set(Episode.model_fields)
    kwargs = dict(
        id="synthetic_ep",
        entry_id="ep_20260819_0001",
        owner_id="synthetic_user",
        owner_type="user",
        app_id="synthetic_app",
        project_id="WZW",
        timestamp=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        parent_id="synthetic_parent",
        sender_ids=["synthetic_user"],
        episode="Vielleicht verkaufe ich WZW nächstes Jahr.",
        episode_tokens="Vielleicht verkaufe ich WZW nächstes Jahr",
        md_path="synthetic.md",
        content_sha256="0" * 64,
        knowledge_type="IDEA",
        epistemic_status="USER_STATED",
    )
    validation_error = None
    dumped = {}
    try:
        episode = Episode(**kwargs)
        dumped = episode.model_dump()
    except Exception as exc:
        validation_error = f"{type(exc).__name__}: {exc}"

    carries = dumped.get("knowledge_type") == "IDEA" and dumped.get("epistemic_status") == "USER_STATED"
    return {
        "candidate": "EverOS",
        "version": "1.2.3",
        "release_commit": "48fc9084888bc17100053227284f939a5aca5e91",
        "episode_schema_has_knowledge_type": "knowledge_type" in fields_set,
        "episode_schema_has_epistemic_status": "epistemic_status" in fields_set,
        "episode_schema_has_free_metadata_field": "metadata" in fields_set or "info" in fields_set,
        "extra_contract_fields_survive_model_dump": carries,
        "validation_error_if_any": validation_error,
        "dump_contains_knowledge_type": "knowledge_type" in dumped,
        "dump_contains_epistemic_status": "epistemic_status" in dumped,
        "prerequisite_status": "PASS_MODEL_ROUNDTRIP" if carries else "FAIL_NATIVE_EPISODE_ROUNDTRIP",
        "reason": "EverOS Episode has fixed retrieval fields for owner/app/project and deprecation, but the tested native Episode row does not retain the separate knowledge_type and epistemic_status contract fields when supplied as extras. An external envelope/sidecar would therefore be required before full GT-05/GT-12 can pass.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=["slm", "memos", "everos"], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fn = {"slm": slm_probe, "memos": memos_probe, "everos": everos_probe}[args.candidate]
    report = {
        "schema": "externes-gehirn.gt05-gt12-contract-roundtrip-prerequisite.v0.1",
        "scope": "PREREQUISITE_ONLY_NOT_FINAL_GOLDEN_TEST_RESULT",
        "golden_tests_informed": ["GT-05", "GT-12"],
        **fn(),
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
