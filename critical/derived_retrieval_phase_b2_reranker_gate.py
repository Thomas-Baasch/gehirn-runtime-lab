from __future__ import annotations

import importlib.metadata as metadata
import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from governance.canon_router import Authority, EpistemicStatus, KnowledgeRecord, KnowledgeType, Sensitivity
from governance.direct_qdrant_index import DirectQdrantIndex
from governance.memos_composition import CanonicalSQLiteStore
from governance.memos_recovery import RecoverableGovernedMemOSService
from critical.derived_retrieval_phase_b_gate import (
    BENCHMARK_SHA256,
    DIMENSION,
    FrozenEmbeddingProvider,
    aggregate,
    auth_from_fixture,
    by_direction,
    full_authority,
    load_benchmark,
    load_model_vectors,
    metrics_for_rank,
    record_from_fixture,
)

CONTRACT_DRIVE_ID = "150e64OPwqfFNk96-O0Q38DVD055nVi7ylgNqJ_bAR7E"
CONTRACT_SEMANTIC_SHA256 = "c9de8f61ecabed89138aeae47ae5f6add8e48333f234eb8f7591f222d97a9ffc"
RERANKER = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANKER_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
PURPOSE = "cross_project_memory"
TOP_N = 10
OUT = Path("reports/value/derived_retrieval_phase_b2_reranker.json")
EXPECTED_DENSE = {
    "Recall@5": 1.0,
    "MRR@10": 0.538542,
    "nDCG@10": 0.654845,
    "Top1": 0.229167,
    "Recall@10": 1.0,
}


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def rank_distribution(rows: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row["relevant_rank"]) if row["relevant_rank"] is not None else "missing"
        result[key] = result.get(key, 0) + 1
    return result


def load_reranker():
    from huggingface_hub import model_info
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    info = model_info(RERANKER, revision=RERANKER_REVISION)
    if info.sha != RERANKER_REVISION:
        raise RuntimeError(f"reranker_revision_mismatch:{info.sha}")
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        RERANKER,
        revision=RERANKER_REVISION,
        trust_remote_code=False,
        use_fast=True,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        RERANKER,
        revision=RERANKER_REVISION,
        trust_remote_code=False,
        use_safetensors=True,
    )
    model.eval()
    return tokenizer, model, {
        "repository": RERANKER,
        "verified_revision": info.sha,
        "license_from_frozen_contract": "apache-2.0",
        "load_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def score_pairs(tokenizer, model, pairs: list[tuple[str, str]], batch_size: int = 32) -> tuple[list[float], dict]:
    import torch

    scores: list[float] = []
    batch_latencies: list[float] = []
    started_all = time.perf_counter()
    with torch.no_grad():
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            q = [item[0] for item in batch]
            d = [item[1] for item in batch]
            encoded = tokenizer(
                q,
                d,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            started = time.perf_counter()
            logits = model(**encoded).logits
            batch_latencies.append((time.perf_counter() - started) * 1000.0)
            flat = logits.reshape(logits.shape[0], -1)
            if flat.shape[1] != 1:
                raise RuntimeError(f"unexpected_reranker_logits_shape:{tuple(logits.shape)}")
            scores.extend(float(value) for value in flat[:, 0].cpu().tolist())
    total_ms = (time.perf_counter() - started_all) * 1000.0
    return scores, {
        "pairs": len(pairs),
        "batch_size": batch_size,
        "total_score_ms": round(total_ms, 3),
        "batch_p50_ms": round(statistics.median(batch_latencies), 3),
        "batch_p95_ms": round(pct(batch_latencies, 0.95), 3),
    }


def row_for(query: dict, records: list[KnowledgeRecord], latency_ms: float) -> dict:
    ranked_ids = [record.record_id for record in records]
    relevant = set(query["relevant_record_ids"])
    rank = next((idx for idx, record_id in enumerate(ranked_ids, start=1) if record_id in relevant), None)
    return {
        "query_id": query["query_id"],
        "direction": query["direction"],
        "query": query["query"],
        "ranked_ids": ranked_ids,
        "relevant_record_ids": query["relevant_record_ids"],
        "relevant_rank": rank,
        "metrics": metrics_for_rank(rank),
        "latency_ms": round(latency_ms, 6),
    }


def make_policy_record(raw: dict) -> KnowledgeRecord:
    return record_from_fixture(raw)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    benchmark = load_benchmark()
    if BENCHMARK_SHA256 != "8e06db355e7d53dda3774c38029b78112d1789ab354eff273e079c844f6bd869":
        raise RuntimeError("phase_b_benchmark_binding_changed")

    versions = {
        "qdrant-client": metadata.version("qdrant-client"),
        "sentence-transformers": metadata.version("sentence-transformers"),
    }
    if versions != {"qdrant-client": "1.16.0", "sentence-transformers": "5.7.0"}:
        raise RuntimeError(f"runtime_version_mismatch:{versions}")

    all_texts = [record["text"] for record in benchmark["records"]]
    all_texts += [query["query"] for query in benchmark["queries"]]
    all_texts += [control["record"]["text"] for control in benchmark["policy_controls"]]
    all_texts += [control["query"] for control in benchmark["policy_controls"]]
    all_texts += [
        "A derived-only rogue record claims the emergency color is violet.",
        "What emergency color does the rogue record claim?",
    ]

    try:
        vectors, dense_model_evidence = load_model_vectors(all_texts)
        tokenizer, reranker, reranker_evidence = load_reranker()
    except Exception as exc:
        report = {
            "schema": "externes-gehirn.derived-retrieval-phase-b2-reranker-evidence",
            "version": "0.1.0",
            "result": "BLOCKED_EXACT_MODEL_REVISION_UNAVAILABLE",
            "error": f"{type(exc).__name__}:{exc}",
            "contract": {"drive_id": CONTRACT_DRIVE_ID, "semantic_sha256": CONTRACT_SEMANTIC_SHA256},
            "benchmark_sha256": BENCHMARK_SHA256,
            "runtime_versions": versions,
            "stack_decision": "NOT_MADE",
        }
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    embedder = FrozenEmbeddingProvider(vectors)
    with tempfile.TemporaryDirectory(prefix="eg-phase-b2-") as td:
        root = Path(td)
        canonical = CanonicalSQLiteStore(root / "canon.sqlite")
        for fixture in benchmark["records"]:
            canonical.put(record_from_fixture(fixture))
        for control in benchmark["policy_controls"]:
            canonical.put(make_policy_record(control["record"]))
        index = DirectQdrantIndex(root / "direct_index", embedder, vector_dimension=DIMENSION)
        service = RecoverableGovernedMemOSService(canonical, index)
        build_started = time.perf_counter()
        projected = service.rebuild_index_from_canonical()
        build_ms = (time.perf_counter() - build_started) * 1000.0
        auth = full_authority()

        dense_rows: list[dict] = []
        dense_hits_by_query: dict[str, list[KnowledgeRecord]] = {}
        for query in benchmark["queries"]:
            started = time.perf_counter_ns()
            status, hits = service.search(
                query=query["query"],
                target_project="Bench",
                purpose=PURPOSE,
                authority=auth,
                top_k=TOP_N,
            )
            latency_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            if status != "ALLOWED":
                raise RuntimeError(f"unexpected_dense_status:{query['query_id']}:{status}")
            dense_hits_by_query[query["query_id"]] = hits
            dense_rows.append(row_for(query, hits, latency_ms))

        dense_aggregate = aggregate(dense_rows)
        dense_drift = {
            name: round(dense_aggregate[name] - expected, 6)
            for name, expected in EXPECTED_DENSE.items()
        }
        if any(value != 0.0 for value in dense_drift.values()):
            report = {
                "schema": "externes-gehirn.derived-retrieval-phase-b2-reranker-evidence",
                "version": "0.1.0",
                "result": "BLOCKED_DENSE_BASELINE_DRIFT",
                "expected_dense": EXPECTED_DENSE,
                "actual_dense": dense_aggregate,
                "drift": dense_drift,
                "contract": {"drive_id": CONTRACT_DRIVE_ID, "semantic_sha256": CONTRACT_SEMANTIC_SHA256},
                "stack_decision": "NOT_MADE",
            }
            OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2, ensure_ascii=False))
            index.close()
            return 2

        pairs: list[tuple[str, str]] = []
        pair_meta: list[tuple[str, KnowledgeRecord]] = []
        for query in benchmark["queries"]:
            for record in dense_hits_by_query[query["query_id"]]:
                pairs.append((query["query"], record.content))
                pair_meta.append((query["query_id"], record))
        scores, scoring_evidence = score_pairs(tokenizer, reranker, pairs)
        scores_by_query: dict[str, list[tuple[float, KnowledgeRecord]]] = {}
        for score, (query_id, record) in zip(scores, pair_meta, strict=True):
            scores_by_query.setdefault(query_id, []).append((score, record))

        reranked_rows: list[dict] = []
        rerank_query_latencies: list[float] = []
        for query in benchmark["queries"]:
            started = time.perf_counter_ns()
            ranked = [record for _score, record in sorted(scores_by_query[query["query_id"]], key=lambda item: item[0], reverse=True)]
            latency_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            rerank_query_latencies.append(latency_ms)
            reranked_rows.append(row_for(query, ranked, latency_ms))

        # Safety 1: project deny must stop before dense query; therefore reranker gets no candidates.
        p01, p02 = benchmark["policy_controls"]
        query_log_before = len(index.query_log)
        p01_status, p01_hits = service.search(
            query=p01["query"],
            target_project=p01["record"]["target_domain"],
            purpose=PURPOSE,
            authority=auth_from_fixture(p01["unauthorized_authority"]),
            top_k=TOP_N,
        )
        project_denied_before_dense_or_reranker = (
            p01_status == "BLOCKED" and p01_hits == [] and len(index.query_log) == query_log_before
        )

        # Safety 2: low clearance may only produce candidates from allowed partitions.
        query_log_before = len(index.query_log)
        p02_status, p02_hits = service.search(
            query=p02["query"],
            target_project="Bench",
            purpose=PURPOSE,
            authority=auth_from_fixture(p02["unauthorized_authority"]),
            top_k=TOP_N,
        )
        p02_queries = index.query_log[query_log_before:]
        confidential_id = p02["record"]["record_id"]
        low_clearance_never_exposes_confidential_candidate = (
            p02_status == "ALLOWED"
            and all(item["sensitivity_partition"] not in {"CONFIDENTIAL", "RESTRICTED"} for item in p02_queries)
            and all(record.record_id != confidential_id for record in p02_hits)
        )

        # Safety 3: index-only rogue item is discarded by Canon hydration before reranking.
        rogue = KnowledgeRecord(
            record_id="11111111-2222-5333-8444-555555555555",
            source_ref="synthetic:phase-b2:rogue-index-only",
            observed_at="2026-08-21T00:00:00+00:00",
            subject="rogue derived truth",
            target_domain="Bench",
            knowledge_type=KnowledgeType.DECISION,
            epistemic_status=EpistemicStatus.USER_STATED,
            confidence=1.0,
            sensitivity=Sensitivity.INTERNAL,
            purpose=PURPOSE,
            content="A derived-only rogue record claims the emergency color is violet.",
            relations=(),
            predecessor_id=None,
            created_by="phase-b2-rogue",
        )
        index.put(rogue)
        rogue_status, rogue_hits = service.search(
            query="What emergency color does the rogue record claim?",
            target_project="Bench",
            purpose=PURPOSE,
            authority=auth,
            top_k=TOP_N,
        )
        index_only_never_reaches_reranker = (
            rogue_status == "ALLOWED"
            and canonical.get(rogue.record_id) is None
            and all(record.record_id != rogue.record_id for record in rogue_hits)
        )

        # Safety 4: repeated reranking must not mutate canonical truth or history.
        canonical_count_before = canonical.count()
        events_before = canonical.events()
        anchor_id = benchmark["queries"][0]["relevant_record_ids"][0]
        anchor_before = canonical.get(anchor_id)
        probe_pairs = [(benchmark["queries"][0]["query"], record.content) for record in dense_hits_by_query[benchmark["queries"][0]["query_id"]]]
        for _ in range(3):
            score_pairs(tokenizer, reranker, probe_pairs, batch_size=10)
        rerank_side_effect_free = (
            canonical.count() == canonical_count_before
            and canonical.events() == events_before
            and canonical.get(anchor_id) == anchor_before
        )
        index.close()

    reranked_aggregate = aggregate(reranked_rows)
    floors = {
        "Recall@5": reranked_aggregate["Recall@5"] >= 0.90,
        "MRR@10": reranked_aggregate["MRR@10"] >= 0.80,
        "nDCG@10": reranked_aggregate["nDCG@10"] >= 0.85,
    }
    safety = {
        "project_denied_before_dense_or_reranker": project_denied_before_dense_or_reranker,
        "low_clearance_never_exposes_confidential_candidate": low_clearance_never_exposes_confidential_candidate,
        "index_only_record_never_reaches_reranker": index_only_never_reaches_reranker,
        "reranking_side_effect_free": rerank_side_effect_free,
    }
    eligible = all(floors.values()) and all(safety.values())
    report = {
        "schema": "externes-gehirn.derived-retrieval-phase-b2-reranker-evidence",
        "version": "0.1.0",
        "result": "PASS" if eligible else "FAIL_RERANKER_CANDIDATE",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "semantic_sha256": CONTRACT_SEMANTIC_SHA256},
        "phase_b_benchmark_sha256": BENCHMARK_SHA256,
        "runtime_versions": versions,
        "dense_embedding": dense_model_evidence,
        "reranker": reranker_evidence,
        "architecture": "policy -> DirectQdrant dense top10 -> mMARCO cross-encoder rerank -> Canon records",
        "projected_records": projected,
        "dense_index_build_ms": round(build_ms, 3),
        "dense_baseline": {
            "aggregate": dense_aggregate,
            "by_direction": by_direction(dense_rows),
            "rank_distribution": rank_distribution(dense_rows),
            "drift_from_frozen_phase_b": dense_drift,
        },
        "reranked": {
            "aggregate": reranked_aggregate,
            "by_direction": by_direction(reranked_rows),
            "rank_distribution": rank_distribution(reranked_rows),
            "quality_floors": floors,
        },
        "improvement_reranked_minus_dense": {
            name: round(reranked_aggregate[name] - dense_aggregate[name], 6)
            for name in ("Recall@5", "MRR@10", "nDCG@10", "Top1", "Recall@10")
        },
        "safety": safety,
        "scoring": scoring_evidence,
        "rerank_sort_only_latency": {
            "p50_ms": round(statistics.median(rerank_query_latencies), 6),
            "p95_ms": round(pct(rerank_query_latencies, 0.95), 6),
        },
        "eligible_for_derived_role": eligible,
        "role_decision": "PREFER_DIRECT_QDRANT_PLUS_MMARCO_RERANKER_DERIVED_ROLE" if eligible else "NO_SELECTION_RERANKER_MISSED_FROZEN_GATE",
        "scope_limit": "Derived retrieval role only; no final External Brain stack decision. Latencies are GitHub-runner evidence, not production SLA.",
        "stack_decision": "NOT_MADE",
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": report["result"],
        "dense": dense_aggregate,
        "reranked": reranked_aggregate,
        "improvement": report["improvement_reranked_minus_dense"],
        "safety": safety,
        "role_decision": report["role_decision"],
    }, indent=2, ensure_ascii=False))
    return 0 if eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
