from __future__ import annotations

import importlib.metadata as metadata
import json
import math
import re
import statistics
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path

from governance.canon_router import (
    Authority,
    EpistemicStatus,
    KnowledgeRecord,
    KnowledgeType,
    Sensitivity,
)
from governance.direct_qdrant_index import DirectQdrantIndex
from governance.memos_composition import CanonicalSQLiteStore
from governance.memos_recovery import (
    RecoverableGovernedMemOSService,
    RecoverablePartitionedMemOSIndex,
)


CONTRACT_DRIVE_ID = "1P_jCU6lC6UB7QHblibDBDWyAVdHThN6T"
CONTRACT_SHA256 = "193c756c8fcb07ed18335874a8b0383da172d6be9dfd37ffb4e0da5b0c87f0c6"
PURPOSE = "cross_project_memory"
BENCH_PROJECT = "Bench"
SECRET_PROJECT = "SecretBench"
CORPUS_SIZE = 240
QUERY_COUNT = 60
TOP_K = 5


class StableVectorEmbedder:
    """Deterministic Phase-A fixture; not a semantic-quality benchmark."""

    pattern = re.compile(r"VEC_(\d{6})")

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            match = self.pattern.search(text)
            if not match:
                raise ValueError(f"missing frozen VEC token in: {text!r}")
            number = int(match.group(1))
            a = ((number * 0.7548776662466927) % 1.0) * math.tau
            b = ((number * 0.5698402909980532) % 1.0) * math.tau
            norm = math.sqrt(2.0)
            vectors.append(
                [
                    math.cos(a) / norm,
                    math.sin(a) / norm,
                    math.cos(b) / norm,
                    math.sin(b) / norm,
                ]
            )
        return vectors


def authority(clearance: Sensitivity = Sensitivity.CONFIDENTIAL) -> Authority:
    return Authority(
        actor_id=f"phase-a-{clearance.value.lower()}",
        allowed_projects=frozenset({BENCH_PROJECT, SECRET_PROJECT}),
        allowed_purposes=frozenset({PURPOSE}),
        sensitivity_clearance=clearance,
    )


def record(number: int, *, project: str = BENCH_PROJECT, sensitivity: Sensitivity = Sensitivity.INTERNAL) -> KnowledgeRecord:
    token = f"VEC_{number:06d}"
    return KnowledgeRecord(
        record_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"externes-gehirn-value-phase-a:{number}:{project}")),
        source_ref=f"synthetic:value-phase-a:{number}",
        observed_at="2026-08-19T00:00:00+00:00",
        subject=f"synthetic benchmark record {number}",
        target_domain=project,
        knowledge_type=KnowledgeType.CLAIM,
        epistemic_status=EpistemicStatus.USER_STATED,
        confidence=1.0,
        sensitivity=sensitivity,
        purpose=PURPOSE,
        content=f"{token} reproducible derived retrieval benchmark payload {number}",
        relations=(),
        predecessor_id=None,
        created_by="phase-a-fixture",
    )


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    fraction = rank - lo
    return ordered[lo] * (1.0 - fraction) + ordered[hi] * fraction


def metrics_ms(samples_ns: list[int]) -> dict:
    values = [sample / 1_000_000.0 for sample in samples_ns]
    return {
        "count": len(values),
        "p50_ms": round(statistics.median(values), 6) if values else 0.0,
        "p95_ms": round(percentile(values, 0.95), 6),
        "p99_ms": round(percentile(values, 0.99), 6),
        "mean_ms": round(statistics.fmean(values), 6) if values else 0.0,
        "max_ms": round(max(values), 6) if values else 0.0,
    }


def timed(callable_):
    start = time.perf_counter_ns()
    result = callable_()
    return result, time.perf_counter_ns() - start


def root_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def close_memos(index: RecoverablePartitionedMemOSIndex) -> None:
    for memory in index._memories.values():
        client = getattr(getattr(memory, "vector_db", None), "client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()
    index._memories.clear()


def distribution_size(dist_name: str) -> int | None:
    try:
        dist = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        return None
    total = 0
    for file in dist.files or []:
        try:
            path = dist.locate_file(file)
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            pass
    return total


def load_same_workflow_regression() -> dict:
    paths = {
        "critical": Path("reports/composed/governance_memos_critical.json"),
        "remaining": Path("reports/composed/governance_memos_remaining.json"),
        "recovery": Path("reports/composed/governance_memos_recovery.json"),
    }
    data = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    passed = (
        data["critical"].get("result") == "PASS"
        and data["critical"].get("passed") == 6
        and data["remaining"].get("result") == "PASS"
        and data["remaining"].get("passed") == 6
        and data["recovery"].get("result") == "PASS"
        and data["recovery"].get("passed") == 8
    )
    return {
        "pass": passed,
        "critical": f"{data['critical'].get('passed')}/{data['critical'].get('total')}",
        "remaining": f"{data['remaining'].get('passed')}/{data['remaining'].get('total')}",
        "recovery": f"{data['recovery'].get('passed')}/{data['recovery'].get('total')}",
    }


def search_target(service, target: KnowledgeRecord, auth: Authority):
    status, hits = service.search(
        query=f"VEC_{int(target.source_ref.rsplit(':', 1)[-1]):06d}",
        target_project=target.target_domain,
        purpose=PURPOSE,
        authority=auth,
        top_k=TOP_K,
    )
    return status, hits


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eg-derived-value-a-") as td:
        root = Path(td)
        embedder = StableVectorEmbedder()
        canonical = CanonicalSQLiteStore(root / "canon" / "canon.sqlite")
        records = [record(number) for number in range(CORPUS_SIZE)]
        secret = record(888888, project=SECRET_PROJECT, sensitivity=Sensitivity.CONFIDENTIAL)
        for item in [*records, secret]:
            canonical.put(item)

        memos_root = root / "memos_qdrant"
        direct_root = root / "direct_qdrant"
        memos_index = RecoverablePartitionedMemOSIndex(memos_root, embedder)
        direct_index = DirectQdrantIndex(direct_root, embedder)

        memos_write_ns: list[int] = []
        direct_write_ns: list[int] = []
        initial_records = [*records, secret]
        for idx, item in enumerate(initial_records):
            if idx % 2 == 0:
                _, elapsed = timed(lambda item=item: memos_index.put(item))
                memos_write_ns.append(elapsed)
                _, elapsed = timed(lambda item=item: direct_index.put(item))
                direct_write_ns.append(elapsed)
            else:
                _, elapsed = timed(lambda item=item: direct_index.put(item))
                direct_write_ns.append(elapsed)
                _, elapsed = timed(lambda item=item: memos_index.put(item))
                memos_write_ns.append(elapsed)

        memos_service = RecoverableGovernedMemOSService(canonical, memos_index)
        direct_service = RecoverableGovernedMemOSService(canonical, direct_index)  # duck-typed index contract
        full = authority()
        low = authority(Sensitivity.INTERNAL)

        # Warm both candidates with identical queries before timing.
        for item in records[:10]:
            search_target(memos_service, item, full)
            search_target(direct_service, item, full)

        query_targets = [records[(i * 37) % CORPUS_SIZE] for i in range(QUERY_COUNT)]
        memos_query_ns: list[int] = []
        direct_query_ns: list[int] = []
        memos_correct = 0
        direct_correct = 0
        parity_count = 0
        query_evidence: list[dict] = []

        for idx, target in enumerate(query_targets):
            if idx % 2 == 0:
                (m_status, m_hits), m_elapsed = timed(lambda target=target: search_target(memos_service, target, full))
                (d_status, d_hits), d_elapsed = timed(lambda target=target: search_target(direct_service, target, full))
            else:
                (d_status, d_hits), d_elapsed = timed(lambda target=target: search_target(direct_service, target, full))
                (m_status, m_hits), m_elapsed = timed(lambda target=target: search_target(memos_service, target, full))
            memos_query_ns.append(m_elapsed)
            direct_query_ns.append(d_elapsed)
            expected = target.record_id
            m_top = m_hits[0].record_id if m_hits else None
            d_top = d_hits[0].record_id if d_hits else None
            memos_ok = m_status == "ALLOWED" and m_top == expected
            direct_ok = d_status == "ALLOWED" and d_top == expected
            memos_correct += int(memos_ok)
            direct_correct += int(direct_ok)
            parity_count += int(m_top == d_top)
            query_evidence.append(
                {
                    "expected": expected,
                    "memos_top1": m_top,
                    "direct_top1": d_top,
                    "memos_pass": memos_ok,
                    "direct_pass": direct_ok,
                }
            )

        v01_memos = memos_correct == QUERY_COUNT
        v01_direct = direct_correct == QUERY_COUNT

        # V-02: same external policy; low clearance must never touch confidential partition.
        m_start = len(memos_index.query_log)
        d_start = len(direct_index.query_log)
        m_low_status, m_low_hits = memos_service.search(
            query="VEC_888888",
            target_project=SECRET_PROJECT,
            purpose=PURPOSE,
            authority=low,
            top_k=TOP_K,
        )
        d_low_status, d_low_hits = direct_service.search(
            query="VEC_888888",
            target_project=SECRET_PROJECT,
            purpose=PURPOSE,
            authority=low,
            top_k=TOP_K,
        )
        m_low_queries = memos_index.query_log[m_start:]
        d_low_queries = direct_index.query_log[d_start:]
        m_touched_confidential = any(q["sensitivity_partition"] == "CONFIDENTIAL" for q in m_low_queries)
        d_touched_confidential = any(q["sensitivity_partition"] == "CONFIDENTIAL" for q in d_low_queries)
        v02_memos = m_low_status == "ALLOWED" and not m_low_hits and not m_touched_confidential
        v02_direct = d_low_status == "ALLOWED" and not d_low_hits and not d_touched_confidential

        m_full_status, m_full_hits = memos_service.search(
            query="VEC_888888",
            target_project=SECRET_PROJECT,
            purpose=PURPOSE,
            authority=full,
            top_k=TOP_K,
        )
        d_full_status, d_full_hits = direct_service.search(
            query="VEC_888888",
            target_project=SECRET_PROJECT,
            purpose=PURPOSE,
            authority=full,
            top_k=TOP_K,
        )
        v02_memos = v02_memos and m_full_status == "ALLOWED" and bool(m_full_hits) and m_full_hits[0].record_id == secret.record_id
        v02_direct = v02_direct and d_full_status == "ALLOWED" and bool(d_full_hits) and d_full_hits[0].record_id == secret.record_id

        # V-03: derived-only rogue record may be nearest but must never hydrate to truth.
        rogue = record(777777)
        memos_index.put(rogue)
        direct_index.put(rogue)
        m_rogue_status, m_rogue_hits = memos_service.search(
            query="VEC_777777",
            target_project=BENCH_PROJECT,
            purpose=PURPOSE,
            authority=full,
            top_k=TOP_K,
        )
        d_rogue_status, d_rogue_hits = direct_service.search(
            query="VEC_777777",
            target_project=BENCH_PROJECT,
            purpose=PURPOSE,
            authority=full,
            top_k=TOP_K,
        )
        v03_memos = m_rogue_status == "ALLOWED" and all(hit.record_id != rogue.record_id for hit in m_rogue_hits) and canonical.get(rogue.record_id) is None
        v03_direct = d_rogue_status == "ALLOWED" and all(hit.record_id != rogue.record_id for hit in d_rogue_hits) and canonical.get(rogue.record_id) is None

        # V-05: changed canonical representation updates one derived identity, not Canon cardinality.
        original = records[0]
        updated = replace(original, content="VEC_999999 updated canonical representation for the same stable identity")
        canon_count_before_update = canonical.count()
        canonical.put(updated)
        _, m_update_ns = timed(lambda: memos_index.put(updated))
        _, d_update_ns = timed(lambda: direct_index.put(updated))
        canon_count_after_update = canonical.count()
        m_update_status, m_update_hits = memos_service.search(
            query="VEC_999999",
            target_project=BENCH_PROJECT,
            purpose=PURPOSE,
            authority=full,
            top_k=TOP_K,
        )
        d_update_status, d_update_hits = direct_service.search(
            query="VEC_999999",
            target_project=BENCH_PROJECT,
            purpose=PURPOSE,
            authority=full,
            top_k=TOP_K,
        )
        v05_memos = (
            canon_count_after_update == canon_count_before_update
            and memos_index.contains_current(updated)
            and m_update_status == "ALLOWED"
            and bool(m_update_hits)
            and m_update_hits[0].record_id == updated.record_id
        )
        v05_direct = (
            canon_count_after_update == canon_count_before_update
            and direct_index.contains_current(updated)
            and d_update_status == "ALLOWED"
            and bool(d_update_hits)
            and d_update_hits[0].record_id == updated.record_id
        )

        # V-04: throw both candidate indexes away and rebuild solely from Canon.
        rebuild_memos_root = root / "memos_rebuild"
        rebuild_direct_root = root / "direct_rebuild"
        rebuild_memos = RecoverablePartitionedMemOSIndex(rebuild_memos_root, embedder)
        rebuild_direct = DirectQdrantIndex(rebuild_direct_root, embedder)
        rebuild_records = canonical.all()
        start = time.perf_counter_ns()
        for item in rebuild_records:
            rebuild_memos.put(item)
        memos_rebuild_ns = time.perf_counter_ns() - start
        start = time.perf_counter_ns()
        for item in rebuild_records:
            rebuild_direct.put(item)
        direct_rebuild_ns = time.perf_counter_ns() - start
        v04_memos = all(rebuild_memos.contains_current(item) for item in rebuild_records)
        v04_direct = all(rebuild_direct.contains_current(item) for item in rebuild_records)
        # The rogue was never Canon and therefore must not exist after clean rebuild.
        v04_memos = v04_memos and not rebuild_memos.contains_current(rogue)
        v04_direct = v04_direct and not rebuild_direct.contains_current(rogue)

        same_workflow_regression = load_same_workflow_regression()
        v06 = same_workflow_regression["pass"]

        memos_hard = all([v01_memos, v02_memos, v03_memos, v04_memos, v05_memos, v06])
        direct_hard = all([v01_direct, v02_direct, v03_direct, v04_direct, v05_direct, v06])

        # Close before storage-size observation to flush local state where supported.
        close_memos(memos_index)
        direct_index.close()
        close_memos(rebuild_memos)
        rebuild_direct.close()

        memos_query = metrics_ms(memos_query_ns)
        direct_query = metrics_ms(direct_query_ns)
        memos_write = metrics_ms(memos_write_ns)
        direct_write = metrics_ms(direct_write_ns)

        memos_requirements = metadata.requires("MemoryOS") or []
        qdrant_requirements = metadata.requires("qdrant-client") or []

        if memos_hard and direct_hard and memos_correct == direct_correct == QUERY_COUNT:
            conclusion = "PHASE_A_NO_UNIQUE_MEMOS_FUNCTIONAL_VALUE_DEMONSTRATED"
        elif memos_hard and not direct_hard:
            conclusion = "PHASE_A_MEMOS_FUNCTIONAL_VALUE_DEMONSTRATED_DIRECT_BASELINE_FAILED_HARD_INVARIANT"
        elif direct_hard and not memos_hard:
            conclusion = "PHASE_A_DIRECT_QDRANT_STRONGER_MEMOS_FAILED_HARD_INVARIANT"
        else:
            conclusion = "PHASE_A_INCONCLUSIVE_OR_BOTH_FAILED"

        report = {
            "schema": "externes-gehirn.derived-retrieval-substrate-value-evidence.v0.1",
            "phase": "A_STRUCTURAL_ONLY",
            "contract": {"drive_id": CONTRACT_DRIVE_ID, "sha256": CONTRACT_SHA256},
            "canon_truth": "same product-neutral CanonicalSQLiteStore",
            "candidate_a": "MemoryOS/MemTensor MemOS 2.0.30 + qdrant-client 1.16.0",
            "candidate_b": "direct qdrant-client 1.16.0",
            "corpus": {"bench_records": CORPUS_SIZE, "secret_records": 1, "query_count": QUERY_COUNT, "top_k": TOP_K},
            "hard_invariants": {
                "V-01_expected_top1": {
                    "memos_pass": v01_memos,
                    "direct_pass": v01_direct,
                    "memos_correct": memos_correct,
                    "direct_correct": direct_correct,
                    "parity_top1": parity_count,
                    "total": QUERY_COUNT,
                },
                "V-02_policy_before_forbidden_partition": {
                    "memos_pass": v02_memos,
                    "direct_pass": v02_direct,
                    "memos_low_touched_confidential": m_touched_confidential,
                    "direct_low_touched_confidential": d_touched_confidential,
                },
                "V-03_index_only_rogue_not_truth": {"memos_pass": v03_memos, "direct_pass": v03_direct},
                "V-04_clean_rebuild_from_canon": {
                    "memos_pass": v04_memos,
                    "direct_pass": v04_direct,
                    "canon_records": len(rebuild_records),
                },
                "V-05_stable_identity_update": {
                    "memos_pass": v05_memos,
                    "direct_pass": v05_direct,
                    "canon_count_before": canon_count_before_update,
                    "canon_count_after": canon_count_after_update,
                    "memos_update_ms": round(m_update_ns / 1_000_000.0, 6),
                    "direct_update_ms": round(d_update_ns / 1_000_000.0, 6),
                },
                "V-06_existing_semantics_regression_same_workflow": same_workflow_regression,
            },
            "hard_gate": {"memos_pass": memos_hard, "direct_pass": direct_hard},
            "paired_performance": {
                "warning": "GitHub-hosted runner paired measurements only; not production SLA evidence.",
                "write": {"memos": memos_write, "direct": direct_write},
                "query_end_to_end_canon_hydrated": {"memos": memos_query, "direct": direct_query},
                "clean_rebuild_total_ms": {
                    "memos": round(memos_rebuild_ns / 1_000_000.0, 6),
                    "direct": round(direct_rebuild_ns / 1_000_000.0, 6),
                },
                "ratio_memos_over_direct": {
                    "write_p50": round(memos_write["p50_ms"] / direct_write["p50_ms"], 6) if direct_write["p50_ms"] else None,
                    "write_p95": round(memos_write["p95_ms"] / direct_write["p95_ms"], 6) if direct_write["p95_ms"] else None,
                    "query_p50": round(memos_query["p50_ms"] / direct_query["p50_ms"], 6) if direct_query["p50_ms"] else None,
                    "query_p95": round(memos_query["p95_ms"] / direct_query["p95_ms"], 6) if direct_query["p95_ms"] else None,
                    "rebuild_total": round(memos_rebuild_ns / direct_rebuild_ns, 6) if direct_rebuild_ns else None,
                },
            },
            "operability_surface": {
                "memos_layers_in_derived_role": [
                    "RecoverablePartitionedMemOSIndex adapter",
                    "MemoryOS GeneralTextMemory",
                    "MemoryOS QdrantVecDB wrapper",
                    "qdrant-client local engine",
                ],
                "direct_layers_in_derived_role": ["DirectQdrantIndex adapter", "qdrant-client local engine"],
                "declared_requirement_entries": {
                    "MemoryOS": len(memos_requirements),
                    "qdrant-client": len(qdrant_requirements),
                },
                "distribution_bytes_approx": {
                    "MemoryOS": distribution_size("MemoryOS"),
                    "qdrant-client": distribution_size("qdrant-client"),
                },
                "initial_storage_bytes": {
                    "memos": root_bytes(memos_root),
                    "direct": root_bytes(direct_root),
                },
                "clean_rebuild_storage_bytes": {
                    "memos": root_bytes(rebuild_memos_root),
                    "direct": root_bytes(rebuild_direct_root),
                },
            },
            "phase_a_conclusion": conclusion,
            "interpretation": (
                "Phase A isolates structural derived-index equivalence and wrapper overhead with deterministic vectors. "
                "It cannot establish real-world semantic retrieval quality. A direct-Qdrant structural pass means the extra "
                "MemOS layer still needs a reproducible actually-used benefit to justify itself in this derived role."
            ),
            "query_evidence": query_evidence,
        }

        out = Path("reports/value/derived_retrieval_phase_a.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ["hard_gate", "paired_performance", "operability_surface", "phase_a_conclusion"]}, ensure_ascii=False, indent=2))
        return 0 if memos_hard and direct_hard else 1


if __name__ == "__main__":
    raise SystemExit(main())
