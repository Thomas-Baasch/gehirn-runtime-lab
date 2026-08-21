from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import math
import random
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from governance.canon_router import Authority, EpistemicStatus, KnowledgeRecord, KnowledgeType, Sensitivity
from governance.direct_qdrant_index import DirectQdrantIndex
from governance.memos_composition import CanonicalSQLiteStore
from governance.memos_recovery import RecoverableGovernedMemOSService, RecoverablePartitionedMemOSIndex

CONTRACT_DRIVE_ID = "1MZvw0Hn4FBciejld4pm0vHGzJo-9WYWN"
CONTRACT_SHA256 = "0569c29f3c30981dc0965715f740d204e6e129bb89dbb61fb1891fe764b889de"
BENCHMARK_PATH = Path("contracts/derived_retrieval_phase_b_benchmark_v0.1.py")
BENCHMARK_SHA256 = "8e06db355e7d53dda3774c38029b78112d1789ab354eff273e079c844f6bd869"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
ST_VERSION = "5.7.0"
QDRANT_VERSION = "1.16.0"
MEMOS_VERSION = "2.0.30"
DIMENSION = 384
PURPOSE = "cross_project_memory"
TOP_K = 10
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260821
OUT = Path("reports/value/derived_retrieval_phase_b.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_benchmark() -> dict:
    actual = sha256_file(BENCHMARK_PATH)
    if actual != BENCHMARK_SHA256:
        raise RuntimeError(f"benchmark_hash_mismatch:{actual}")
    spec = importlib.util.spec_from_file_location("phase_b_frozen_benchmark", BENCHMARK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("benchmark_import_spec_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    benchmark = module.BENCHMARK
    if benchmark["contract_drive_id"] != CONTRACT_DRIVE_ID or benchmark["contract_sha256"] != CONTRACT_SHA256:
        raise RuntimeError("benchmark_contract_binding_mismatch")
    if benchmark["corpus_count"] != 120 or benchmark["query_count"] != 48 or benchmark["hard_distractor_count"] < 24:
        raise RuntimeError("benchmark_shape_mismatch")
    directions = {name: sum(1 for query in benchmark["queries"] if query["direction"] == name) for name in ("de_to_de", "en_to_en", "de_to_en", "en_to_de")}
    if directions != {"de_to_de": 12, "en_to_en": 12, "de_to_en": 12, "en_to_de": 12}:
        raise RuntimeError(f"benchmark_direction_mismatch:{directions}")
    return benchmark


class FrozenEmbeddingProvider:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        missing = [text for text in texts if text not in self.vectors]
        if missing:
            raise KeyError(f"embedding_not_prefrozen:{missing[0]!r}")
        return [self.vectors[text] for text in texts]


class PhaseBMemOSIndex(RecoverablePartitionedMemOSIndex):
    """Benchmark-only dimension override; semantics are the existing MemOS projection path."""

    def _memory(self, partition):
        if partition in self._memories:
            return self._memories[partition]
        from memos.configs.vec_db import QdrantVecDBConfig
        from memos.memories.textual.general import GeneralTextMemory
        from memos.vec_dbs.qdrant import QdrantVecDB

        project, purpose, sensitivity = partition
        path = self.root / self._slug(project) / self._slug(purpose) / sensitivity.value.lower()
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = QdrantVecDBConfig(
            collection_name="canon_contract_index",
            vector_dimension=DIMENSION,
            distance_metric="cosine",
            path=str(path),
        )
        memory = GeneralTextMemory.__new__(GeneralTextMemory)
        memory.vector_db = QdrantVecDB(cfg)
        memory.embedder = self.embedder
        self._memories[partition] = memory
        return memory

    def close(self) -> None:
        for memory in self._memories.values():
            client = getattr(getattr(memory, "vector_db", None), "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
        self._memories.clear()

    def storage_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())


def record_from_fixture(item: dict) -> KnowledgeRecord:
    return KnowledgeRecord(
        record_id=item["record_id"],
        source_ref=f"synthetic:phase-b:{item.get('record_key', item['record_id'])}",
        observed_at="2026-08-21T00:00:00+00:00",
        subject=f"phase-b benchmark {item.get('group', 'policy')}",
        target_domain=item.get("target_domain", "Bench"),
        knowledge_type=KnowledgeType.CLAIM,
        epistemic_status=EpistemicStatus.USER_STATED,
        confidence=1.0,
        sensitivity=Sensitivity(item.get("sensitivity", "INTERNAL")),
        purpose=item.get("purpose", PURPOSE),
        content=item["text"],
        relations=(),
        predecessor_id=None,
        created_by="phase-b-fixture",
    )


def full_authority() -> Authority:
    return Authority(
        actor_id="phase-b-full",
        allowed_projects=frozenset({"Bench", "SecretBench"}),
        allowed_purposes=frozenset({PURPOSE}),
        sensitivity_clearance=Sensitivity.CONFIDENTIAL,
    )


def auth_from_fixture(raw: dict) -> Authority:
    return Authority(
        actor_id="phase-b-negative-control",
        allowed_projects=frozenset(raw["projects"]),
        allowed_purposes=frozenset(raw["purposes"]),
        sensitivity_clearance=Sensitivity(raw["clearance"]),
    )


def metrics_for_rank(rank: int | None) -> dict[str, float]:
    return {
        "recall_at_5": 1.0 if rank is not None and rank <= 5 else 0.0,
        "mrr_at_10": 1.0 / rank if rank is not None and rank <= 10 else 0.0,
        "ndcg_at_10": 1.0 / math.log2(rank + 1) if rank is not None and rank <= 10 else 0.0,
        "top1": 1.0 if rank == 1 else 0.0,
        "recall_at_10": 1.0 if rank is not None and rank <= 10 else 0.0,
    }


def aggregate(rows: list[dict]) -> dict:
    def mean(name: str) -> float:
        return statistics.fmean(row["metrics"][name] for row in rows)

    latencies = sorted(row["latency_ms"] for row in rows)

    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        pos = (len(latencies) - 1) * p
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return latencies[lo]
        return latencies[lo] * (hi - pos) + latencies[hi] * (pos - lo)

    return {
        "Recall@5": round(mean("recall_at_5"), 6),
        "MRR@10": round(mean("mrr_at_10"), 6),
        "nDCG@10": round(mean("ndcg_at_10"), 6),
        "Top1": round(mean("top1"), 6),
        "Recall@10": round(mean("recall_at_10"), 6),
        "query_p50_ms": round(statistics.median(latencies), 6),
        "query_p95_ms": round(pct(0.95), 6),
    }


def by_direction(rows: list[dict]) -> dict:
    result = {}
    for direction in ("de_to_de", "en_to_en", "de_to_en", "en_to_de"):
        subset = [row for row in rows if row["direction"] == direction]
        result[direction] = aggregate(subset)
    return result


def paired_bootstrap(deltas: list[float]) -> dict:
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(deltas)
    samples = []
    for _ in range(BOOTSTRAP_SAMPLES):
        samples.append(statistics.fmean(deltas[rng.randrange(n)] for _ in range(n)))
    samples.sort()
    lo = samples[int(0.025 * (len(samples) - 1))]
    hi = samples[int(0.975 * (len(samples) - 1))]
    return {"mean": round(statistics.fmean(deltas), 6), "ci95": [round(lo, 6), round(hi, 6)], "samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED}


def distribution_bytes(name: str) -> int | None:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    total = 0
    for file in dist.files or []:
        path = dist.locate_file(file)
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            pass
    return total


def load_preconditions() -> dict:
    direct_candidates = list(Path("preconditions").rglob("direct_qdrant_no_memoryos_summary.json"))
    if len(direct_candidates) != 1:
        raise RuntimeError(f"direct_precondition_count:{len(direct_candidates)}")
    direct = json.loads(direct_candidates[0].read_text(encoding="utf-8"))
    critical = json.loads(Path("reports/composed/governance_memos_critical.json").read_text(encoding="utf-8"))
    remaining = json.loads(Path("reports/composed/governance_memos_remaining.json").read_text(encoding="utf-8"))
    recovery = json.loads(Path("reports/composed/governance_memos_recovery.json").read_text(encoding="utf-8"))
    checks = {
        "direct_no_memoryos": direct.get("result") == "PASS" and direct.get("critical") == "6/6" and direct.get("remaining") == "6/6" and direct.get("recovery") == "8/8",
        "memos_critical": critical.get("result") == "PASS" and critical.get("passed") == 6,
        "memos_remaining": remaining.get("result") == "PASS" and remaining.get("passed") == 6,
        "memos_recovery": recovery.get("result") == "PASS" and recovery.get("passed") == 8,
    }
    return {"pass": all(checks.values()), "checks": checks}


def load_model_vectors(texts: list[str]) -> tuple[dict[str, list[float]], dict]:
    from huggingface_hub import model_info
    from sentence_transformers import SentenceTransformer

    info = model_info(MODEL, revision=MODEL_REVISION)
    if info.sha != MODEL_REVISION:
        raise RuntimeError(f"model_revision_mismatch:{info.sha}")
    started = time.perf_counter()
    model = SentenceTransformer(MODEL, revision=MODEL_REVISION, trust_remote_code=False)
    unique = list(dict.fromkeys(texts))
    vectors = model.encode(unique, batch_size=32, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
    elapsed = (time.perf_counter() - started) * 1000.0
    if vectors.shape[1] != DIMENSION:
        raise RuntimeError(f"embedding_dimension_mismatch:{vectors.shape}")
    frozen = {text: vector.astype(float).tolist() for text, vector in zip(unique, vectors, strict=True)}
    return frozen, {"verified_revision": info.sha, "unique_texts": len(unique), "load_and_encode_ms": round(elapsed, 3)}


def evaluate_candidate(name: str, canonical: CanonicalSQLiteStore, index: Any, benchmark: dict) -> dict:
    service = RecoverableGovernedMemOSService(canonical, index)
    build_started = time.perf_counter()
    projected = service.rebuild_index_from_canonical()
    build_ms = (time.perf_counter() - build_started) * 1000.0
    auth = full_authority()
    rows = []
    for query in benchmark["queries"]:
        started = time.perf_counter_ns()
        status, hits = service.search(query=query["query"], target_project="Bench", purpose=PURPOSE, authority=auth, top_k=TOP_K)
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        ranked_ids = [record.record_id for record in hits]
        relevant = set(query["relevant_record_ids"])
        rank = next((idx for idx, record_id in enumerate(ranked_ids, start=1) if record_id in relevant), None)
        rows.append({
            "query_id": query["query_id"], "direction": query["direction"], "query": query["query"],
            "status": status, "ranked_ids": ranked_ids, "relevant_record_ids": query["relevant_record_ids"],
            "relevant_rank": rank, "metrics": metrics_for_rank(rank), "latency_ms": round(latency_ms, 6),
        })

    safety = {}
    p01, p02 = benchmark["policy_controls"]
    before = len(index.query_log)
    p01_status, p01_hits = service.search(query=p01["query"], target_project=p01["record"]["target_domain"], purpose=PURPOSE, authority=auth_from_fixture(p01["unauthorized_authority"]), top_k=TOP_K)
    safety["project_denied_before_index"] = p01_status == "BLOCKED" and p01_hits == [] and len(index.query_log) == before

    before = len(index.query_log)
    p02_status, p02_hits = service.search(query=p02["query"], target_project="Bench", purpose=PURPOSE, authority=auth_from_fixture(p02["unauthorized_authority"]), top_k=TOP_K)
    delta = index.query_log[before:]
    safety["low_clearance_never_queries_confidential"] = p02_status == "ALLOWED" and all(item["sensitivity_partition"] not in {"CONFIDENTIAL", "RESTRICTED"} for item in delta) and all(record.record_id != p02["record"]["record_id"] for record in p02_hits)

    rogue = KnowledgeRecord(
        record_id="11111111-2222-5333-8444-555555555555",
        source_ref="synthetic:phase-b:rogue-index-only", observed_at="2026-08-21T00:00:00+00:00",
        subject="rogue derived truth", target_domain="Bench", knowledge_type=KnowledgeType.DECISION,
        epistemic_status=EpistemicStatus.USER_STATED, confidence=1.0, sensitivity=Sensitivity.INTERNAL,
        purpose=PURPOSE, content="A derived-only rogue record claims the emergency color is violet.",
        relations=(), predecessor_id=None, created_by="phase-b-rogue",
    )
    index.put(rogue)
    rogue_status, rogue_hits = service.search(query="What emergency color does the rogue record claim?", target_project="Bench", purpose=PURPOSE, authority=auth, top_k=TOP_K)
    safety["index_only_payload_never_becomes_truth"] = rogue_status == "ALLOWED" and canonical.get(rogue.record_id) is None and all(record.record_id != rogue.record_id for record in rogue_hits)

    aggregates = aggregate(rows)
    floors = {
        "Recall@5": aggregates["Recall@5"] >= 0.9,
        "MRR@10": aggregates["MRR@10"] >= 0.8,
        "nDCG@10": aggregates["nDCG@10"] >= 0.85,
    }
    return {
        "name": name,
        "projected_records": projected,
        "index_build_ms": round(build_ms, 3),
        "storage_bytes": index.storage_bytes(),
        "per_query": rows,
        "aggregate": aggregates,
        "by_direction": by_direction(rows),
        "quality_floors": floors,
        "safety": safety,
        "eligible": all(floors.values()) and all(safety.values()),
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    benchmark = load_benchmark()
    preconditions = load_preconditions()
    if not preconditions["pass"]:
        report = {"schema": "externes-gehirn.derived-retrieval-phase-b-evidence", "version": "0.1.0", "result": "BLOCKED_REGRESSION_PRECONDITION", "preconditions": preconditions, "stack_decision": "NOT_MADE"}
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return 2

    versions = {
        "MemoryOS": metadata.version("MemoryOS"),
        "qdrant-client": metadata.version("qdrant-client"),
        "sentence-transformers": metadata.version("sentence-transformers"),
    }
    if versions != {"MemoryOS": MEMOS_VERSION, "qdrant-client": QDRANT_VERSION, "sentence-transformers": ST_VERSION}:
        raise RuntimeError(f"runtime_version_mismatch:{versions}")

    all_texts = [record["text"] for record in benchmark["records"]]
    all_texts += [query["query"] for query in benchmark["queries"]]
    all_texts += [control["record"]["text"] for control in benchmark["policy_controls"]]
    all_texts += [control["query"] for control in benchmark["policy_controls"]]
    all_texts += ["A derived-only rogue record claims the emergency color is violet.", "What emergency color does the rogue record claim?"]

    try:
        vectors, model_evidence = load_model_vectors(all_texts)
    except Exception as exc:
        report = {
            "schema": "externes-gehirn.derived-retrieval-phase-b-evidence", "version": "0.1.0",
            "result": "BLOCKED_EXACT_MODEL_REVISION_UNAVAILABLE", "error": f"{type(exc).__name__}:{exc}",
            "contract_drive_id": CONTRACT_DRIVE_ID, "contract_sha256": CONTRACT_SHA256,
            "benchmark_sha256": BENCHMARK_SHA256, "preconditions": preconditions, "runtime_versions": versions,
            "stack_decision": "NOT_MADE",
        }
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    embedder = FrozenEmbeddingProvider(vectors)
    with tempfile.TemporaryDirectory(prefix="eg-phase-b-") as td:
        root = Path(td)
        candidates = {}
        for candidate_name in ("memos_qdrant", "direct_qdrant"):
            canonical = CanonicalSQLiteStore(root / candidate_name / "canon.sqlite")
            for fixture in benchmark["records"]:
                canonical.put(record_from_fixture(fixture))
            for control in benchmark["policy_controls"]:
                canonical.put(record_from_fixture(control["record"]))
            if candidate_name == "memos_qdrant":
                index = PhaseBMemOSIndex(root / candidate_name / "index", embedder)
            else:
                index = DirectQdrantIndex(root / candidate_name / "index", embedder, vector_dimension=DIMENSION)
            candidates[candidate_name] = evaluate_candidate(candidate_name, canonical, index, benchmark)
            index.close()

    memos = candidates["memos_qdrant"]
    direct = candidates["direct_qdrant"]
    primary_names = ("Recall@5", "MRR@10", "nDCG@10")
    differences = {name: round(memos["aggregate"][name] - direct["aggregate"][name], 6) for name in primary_names}
    quality_parity = all(abs(value) <= 0.01 for value in differences.values())

    memos_by_id = {row["query_id"]: row for row in memos["per_query"]}
    direct_by_id = {row["query_id"]: row for row in direct["per_query"]}
    mrr_deltas = [memos_by_id[qid]["metrics"]["mrr_at_10"] - direct_by_id[qid]["metrics"]["mrr_at_10"] for qid in memos_by_id]
    ndcg_deltas = [memos_by_id[qid]["metrics"]["ndcg_at_10"] - direct_by_id[qid]["metrics"]["ndcg_at_10"] for qid in memos_by_id]
    bootstrap = {"memos_minus_direct_mrr": paired_bootstrap(mrr_deltas), "memos_minus_direct_ndcg": paired_bootstrap(ndcg_deltas)}

    memos_unique = differences["MRR@10"] >= 0.02 and differences["nDCG@10"] >= 0.02 and bootstrap["memos_minus_direct_mrr"]["ci95"][0] > 0 and bootstrap["memos_minus_direct_ndcg"]["ci95"][0] > 0 and memos["eligible"]
    direct_unique = differences["MRR@10"] <= -0.02 and differences["nDCG@10"] <= -0.02 and bootstrap["memos_minus_direct_mrr"]["ci95"][1] < 0 and bootstrap["memos_minus_direct_ndcg"]["ci95"][1] < 0 and direct["eligible"]

    if memos["eligible"] and not direct["eligible"]:
        role_decision = "PREFER_MEMOS_QDRANT_DERIVED_ROLE_DIRECT_MISSED_GATE"
    elif direct["eligible"] and not memos["eligible"]:
        role_decision = "PREFER_DIRECT_QDRANT_DERIVED_ROLE_MEMOS_MISSED_GATE"
    elif memos["eligible"] and direct["eligible"] and memos_unique:
        role_decision = "PREFER_MEMOS_QDRANT_DERIVED_ROLE_UNIQUE_QUALITY_ADVANTAGE"
    elif memos["eligible"] and direct["eligible"] and direct_unique:
        role_decision = "PREFER_DIRECT_QDRANT_DERIVED_ROLE_UNIQUE_QUALITY_ADVANTAGE"
    elif memos["eligible"] and direct["eligible"] and quality_parity:
        role_decision = "PREFER_DIRECT_QDRANT_DERIVED_ROLE_QUALITY_TIED_SIMPLER_LAYER"
    else:
        role_decision = "NO_DERIVED_ROLE_SELECTION_INCONCLUSIVE"

    report = {
        "schema": "externes-gehirn.derived-retrieval-phase-b-evidence",
        "version": "0.1.0",
        "result": "PASS" if memos["eligible"] or direct["eligible"] else "FAIL_BOTH_CANDIDATES",
        "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256},
        "benchmark": {"path": str(BENCHMARK_PATH), "sha256": BENCHMARK_SHA256, "corpus_records": 120, "queries": 48, "hard_distractors": benchmark["hard_distractor_count"]},
        "embedding": {"model": MODEL, "revision": MODEL_REVISION, "dimension": DIMENSION, **model_evidence},
        "runtime_versions": versions,
        "preconditions": preconditions,
        "candidates": candidates,
        "primary_metric_memos_minus_direct": differences,
        "quality_parity": quality_parity,
        "paired_bootstrap": bootstrap,
        "unique_quality_advantage": {"memos": memos_unique, "direct": direct_unique},
        "role_decision": role_decision,
        "package_bytes": {"MemoryOS": distribution_bytes("MemoryOS"), "qdrant-client": distribution_bytes("qdrant-client"), "sentence-transformers": distribution_bytes("sentence-transformers")},
        "scope_limit": "selects at most the derived retrieval role; deterministic runner latency is secondary evidence and not a production SLA; no final External Brain stack decision",
        "stack_decision": "NOT_MADE",
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": report["result"], "role_decision": role_decision,
        "memos": memos["aggregate"], "direct": direct["aggregate"],
        "quality_parity": quality_parity, "safety_memos": memos["safety"], "safety_direct": direct["safety"],
    }, indent=2, ensure_ascii=False))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
