from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from governance.canon_router import Authority, EpistemicStatus, KnowledgeRecord, KnowledgeType, Sensitivity, _SENSITIVITY_RANK
from governance.direct_qdrant_index import DirectQdrantIndex
from governance.memos_composition import CanonicalSQLiteStore
from governance.memos_recovery import RecoverableGovernedMemOSService
from governance.truth_aware_answer_set import TruthAwareAnswerSetService
from critical.derived_retrieval_phase_b_gate import FrozenEmbeddingProvider, load_model_vectors

CONTRACT_DRIVE_ID = "1sF5t2XKJJywjuaRMfaUKodUR_OAwGuZfybstXeqitM8"
CONTRACT_FILE_SHA256 = "1e1e56ff6fc52484af8e198c36e32554642dab21b0e777bb33f7ba6dea9b6768"
BENCHMARK_PATH = Path("contracts/derived_retrieval_phase_c_benchmark_v0.1.py")
BINDING_PATH = Path("contracts/derived_retrieval_phase_c_binding_v0.1.json")
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
DIMENSION = 384
OUT = Path("reports/value/derived_retrieval_phase_c_truth_aware.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_benchmark() -> tuple[dict, dict]:
    binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    actual = sha256_file(BENCHMARK_PATH)
    if actual != binding["benchmark_sha256"]:
        raise RuntimeError(f"benchmark_hash_mismatch:{actual}")
    if binding["external_contract_drive_id"] != CONTRACT_DRIVE_ID:
        raise RuntimeError("contract_drive_id_mismatch")
    if binding["external_contract_file_sha256"] != CONTRACT_FILE_SHA256:
        raise RuntimeError("contract_file_hash_mismatch")
    spec = importlib.util.spec_from_file_location("phase_c_frozen_benchmark", BENCHMARK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("benchmark_import_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    benchmark = module.BENCHMARK
    if benchmark["group_counts"] != {"conflict": 8, "correction": 8, "current": 4, "empty": 4}:
        raise RuntimeError(f"benchmark_group_shape:{benchmark['group_counts']}")
    if benchmark["query_count"] != 48 or benchmark["background_count"] != 48:
        raise RuntimeError("benchmark_count_mismatch")
    return benchmark, binding


@dataclass(frozen=True)
class ScoredItem:
    id: str
    score: float


class ScoredDirectQdrantIndex(DirectQdrantIndex):
    def search_scored_allowed(self, *, query: str, project: str, purpose: str, clearance: Sensitivity, top_k: int = 10) -> list[ScoredItem]:
        query_vector = self.embedder.embed([query])[0]
        results: list[ScoredItem] = []
        for sensitivity in Sensitivity:
            if _SENSITIVITY_RANK[sensitivity] > _SENSITIVITY_RANK[clearance]:
                continue
            partition = (project, purpose, sensitivity)
            self.query_log.append({"project": project, "purpose": purpose, "sensitivity_partition": sensitivity.value, "query": query, "scored": True})
            if partition not in self._clients:
                continue
            client = self._clients[partition]
            points = client.query_points(collection_name=self.COLLECTION, query=query_vector, limit=top_k, with_payload=False, with_vectors=False).points
            results.extend(ScoredItem(id=str(point.id), score=float(point.score)) for point in points)
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]


def full_authority() -> Authority:
    return Authority(actor_id="phase-c-full", allowed_projects=frozenset({"Bench", "SecretBench"}), allowed_purposes=frozenset({"cross_project_memory"}), sensitivity_clearance=Sensitivity.CONFIDENTIAL, can_correct=True)


def internal_authority() -> Authority:
    return Authority(actor_id="phase-c-internal", allowed_projects=frozenset({"Bench"}), allowed_purposes=frozenset({"cross_project_memory"}), sensitivity_clearance=Sensitivity.INTERNAL)


def make_record(service: RecoverableGovernedMemOSService, *, subject: str, content: str, authority: Authority, target: str = "Bench", sensitivity: Sensitivity = Sensitivity.INTERNAL, knowledge_type: KnowledgeType = KnowledgeType.CLAIM, predecessor_id: str | None = None) -> KnowledgeRecord:
    return service.new_record(source_ref=f"synthetic:phase-c:{subject}:{knowledge_type.value}", subject=subject, target_domain=target, knowledge_type=knowledge_type, epistemic_status=EpistemicStatus.USER_STATED, confidence=1.0, sensitivity=sensitivity, purpose="cross_project_memory", content=content, authority=authority, predecessor_id=predecessor_id, observed_at="2026-08-21T00:00:00+00:00")


def load_direct_precondition() -> bool:
    matches = list(Path("preconditions").rglob("direct_qdrant_no_memoryos_summary.json"))
    if len(matches) != 1:
        return False
    report = json.loads(matches[0].read_text(encoding="utf-8"))
    return report.get("result") == "PASS" and report.get("critical") == "6/6" and report.get("remaining") == "6/6" and report.get("recovery") == "8/8"


def main() -> int:
    benchmark, binding = load_benchmark()
    texts: list[str] = []
    for group in benchmark["groups"]:
        texts.extend(group["records"]); texts.extend(group["queries"])
    texts.extend(item["text"] for item in benchmark["background"])
    texts.extend([
        "SecretBench stores a confidential launch code under subject Secret launch code.", "What is the SecretBench launch code?",
        "The confidential vault code is amber.", "What is the confidential vault code?",
        "Internal policy says the shared-scope value is alpha.", "Confidential policy says the shared-scope value is beta.", "What is the shared-scope value?",
        "A rogue derived-only record claims the emergency color is violet.", "What emergency color is defined for Rogue Violet?",
        "The design idea proposes a blue status badge.", "What does the design idea propose?",
    ])
    try:
        vectors, model_info = load_model_vectors(texts)
    except Exception as exc:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"schema":"externes-gehirn.phase-c-evidence","version":"0.1.0","result":"BLOCKED_EXACT_MODEL_REVISION_UNAVAILABLE","error":repr(exc),"contract_drive_id":CONTRACT_DRIVE_ID,"stack_decision":"NOT_MADE"}, indent=2) + "\n", encoding="utf-8")
        return 2

    with tempfile.TemporaryDirectory(prefix="phase-c-") as tmp:
        root = Path(tmp)
        canonical = CanonicalSQLiteStore(root / "canon.sqlite")
        index = ScoredDirectQdrantIndex(root / "qdrant", FrozenEmbeddingProvider(vectors), vector_dimension=DIMENSION)
        governed = RecoverableGovernedMemOSService(canonical, index)
        truth = TruthAwareAnswerSetService(governed, index)
        auth = full_authority()
        ids: dict[str, list[str]] = {}

        for bg in benchmark["background"]:
            rec = make_record(governed, subject=bg["subject"], content=bg["text"], authority=auth)
            governed.write(rec, authority=auth)

        for group in benchmark["groups"]:
            ids[group["id"]] = []
            if group["kind"] == "conflict":
                for text in group["records"]:
                    rec = make_record(governed, subject=group["subject"], content=text, authority=auth)
                    stored = governed.write(rec, authority=auth); ids[group["id"]].append(stored.record_id)
            elif group["kind"] == "correction":
                old = make_record(governed, subject=group["subject"], content=group["records"][0], authority=auth)
                old = governed.write(old, authority=auth); ids[group["id"]].append(old.record_id)
                new = make_record(governed, subject=group["subject"], content=group["records"][1], authority=auth, knowledge_type=KnowledgeType.CORRECTION, predecessor_id=old.record_id)
                new = governed.write(new, authority=auth); ids[group["id"]].append(new.record_id)
            elif group["kind"] == "current":
                rec = make_record(governed, subject=group["subject"], content=group["records"][0], authority=auth)
                rec = governed.write(rec, authority=auth); ids[group["id"]].append(rec.record_id)

        rows: list[dict] = []
        checks = {"conflict": [], "correction": [], "current": [], "empty": []}
        locator_hits = 0; locator_total = 0
        for group in benchmark["groups"]:
            for qi, query in enumerate(group["queries"], start=1):
                locate_status, located = truth.locate(query=query, target_project="Bench", purpose="cross_project_memory", authority=auth, top_k=5)
                locator_hit = any(item.record.subject == group["subject"] for item in located) if group["kind"] != "empty" else None
                if group["kind"] != "empty":
                    locator_total += 1; locator_hits += int(bool(locator_hit))
                answer = truth.answer(query=query, target_project="Bench", purpose="cross_project_memory", authority=auth, top_k=10)
                row = {"group":group["id"],"kind":group["kind"],"query_no":qi,"query":query,"locate_status":locate_status,"locator_hit":locator_hit,"answer_status":answer.status,"subject":answer.subject,"record_ids":[r.record_id for r in answer.records],"winner":answer.winner_record_id}
                if group["kind"] == "conflict":
                    ok = answer.status == "CONFLICTING" and set(row["record_ids"]) == set(ids[group["id"]]) and answer.winner_record_id is None
                elif group["kind"] == "correction":
                    history = truth.answer(query=query, target_project="Bench", purpose="cross_project_memory", authority=auth, top_k=10, history=True)
                    old_id, new_id = ids[group["id"]]
                    old_now = canonical.get(old_id)
                    ok = answer.status == "CURRENT" and new_id in row["record_ids"] and old_id not in row["record_ids"] and set(r.record_id for r in history.records) == {old_id,new_id} and old_now is not None and old_now.epistemic_status == EpistemicStatus.SUPERSEDED
                    row["history_ids"] = [r.record_id for r in history.records]
                elif group["kind"] == "current":
                    ok = answer.status == "CURRENT" and set(row["record_ids"]) == set(ids[group["id"]])
                else:
                    ok = answer.status == "EMPTY" and row["record_ids"] == []
                checks[group["kind"]].append(ok); row["pass"] = ok; rows.append(row)

        first_conflict = next(g for g in benchmark["groups"] if g["kind"] == "conflict")
        one_anchor = truth.project_from_anchor_ids(anchor_ids=[ids[first_conflict["id"]][0]], authority=auth)
        stale_complete = one_anchor.status == "CONFLICTING" and set(r.record_id for r in one_anchor.records) == set(ids[first_conflict["id"]]) and one_anchor.winner_record_id is None

        safety: dict[str, bool] = {}
        secret = make_record(governed, subject="Secret launch code", content="SecretBench stores a confidential launch code under subject Secret launch code.", authority=auth, target="SecretBench", sensitivity=Sensitivity.CONFIDENTIAL)
        governed.write(secret, authority=auth)
        denied = Authority(actor_id="deny", allowed_projects=frozenset({"Bench"}), allowed_purposes=frozenset({"cross_project_memory"}), sensitivity_clearance=Sensitivity.CONFIDENTIAL)
        before = len(index.query_log)
        denied_answer = truth.answer(query="What is the SecretBench launch code?", target_project="SecretBench", purpose="cross_project_memory", authority=denied)
        safety["unauthorized_project_blocked_before_derived_query"] = denied_answer.status == "BLOCKED" and len(index.query_log) == before

        confidential = make_record(governed, subject="Confidential vault / Vertraulicher Tresor", content="The confidential vault code is amber.", authority=auth, sensitivity=Sensitivity.CONFIDENTIAL)
        governed.write(confidential, authority=auth)
        low = internal_authority(); before = len(index.query_log)
        low_answer = truth.answer(query="What is the confidential vault code?", target_project="Bench", purpose="cross_project_memory", authority=low)
        delta = index.query_log[before:]
        safety["low_clearance_never_queries_or_exposes_confidential"] = low_answer.status == "EMPTY" and all(item["sensitivity_partition"] not in {"CONFIDENTIAL","RESTRICTED"} for item in delta)

        internal_shared = make_record(governed, subject="Shared scope value / gemeinsamer Wert", content="Internal policy says the shared-scope value is alpha.", authority=auth, sensitivity=Sensitivity.INTERNAL)
        internal_shared = governed.write(internal_shared, authority=auth)
        conf_shared = make_record(governed, subject="Shared scope value / gemeinsamer Wert", content="Confidential policy says the shared-scope value is beta.", authority=auth, sensitivity=Sensitivity.CONFIDENTIAL)
        conf_shared = governed.write(conf_shared, authority=auth)
        shared_answer = truth.answer(query="What is the shared-scope value?", target_project="Bench", purpose="cross_project_memory", authority=low)
        safety["authorization_rechecked_during_sibling_expansion"] = shared_answer.status == "CONFLICTING" and [r.record_id for r in shared_answer.records] == [internal_shared.record_id]

        rogue = KnowledgeRecord(record_id="11111111-2222-5333-8444-555555555555", source_ref="synthetic:phase-c:rogue", observed_at="2026-08-21T00:00:00+00:00", subject="Rogue Violet emergency color", target_domain="Bench", knowledge_type=KnowledgeType.DECISION, epistemic_status=EpistemicStatus.USER_STATED, confidence=1.0, sensitivity=Sensitivity.INTERNAL, purpose="cross_project_memory", content="A rogue derived-only record claims the emergency color is violet.", relations=(), predecessor_id=None, created_by="rogue")
        index.put(rogue)
        rogue_answer = truth.answer(query="What emergency color is defined for Rogue Violet?", target_project="Bench", purpose="cross_project_memory", authority=auth)
        safety["index_only_rogue_never_becomes_answer_truth"] = canonical.get(rogue.record_id) is None and rogue_answer.status == "EMPTY"

        before_count = canonical.count(); before_events = canonical.events(); before_records = canonical.all()
        sample_query = benchmark["groups"][0]["queries"][0]
        truth.answer(query=sample_query, target_project="Bench", purpose="cross_project_memory", authority=auth)
        truth.answer(query=sample_query, target_project="Bench", purpose="cross_project_memory", authority=auth)
        safety["repeated_projection_side_effect_free"] = canonical.count() == before_count and canonical.events() == before_events and canonical.all() == before_records

        idea = make_record(governed, subject="Design idea blue status badge / Entwurf blaue Statusmarke", content="The design idea proposes a blue status badge.", authority=auth, knowledge_type=KnowledgeType.IDEA)
        idea = governed.write(idea, authority=auth)
        idea_answer = truth.answer(query="What does the design idea propose?", target_project="Bench", purpose="cross_project_memory", authority=auth)
        idea_after = canonical.get(idea.record_id)
        safety["retrieval_cannot_promote_idea_or_epistemic_status"] = idea_answer.status == "CURRENT" and idea_after is not None and idea_after.knowledge_type == KnowledgeType.IDEA and idea_after.epistemic_status == EpistemicStatus.USER_STATED

        correction_id = next(g["id"] for g in benchmark["groups"] if g["kind"] == "correction")
        old_id,new_id = ids[correction_id]
        safety["correction_history_intact"] = canonical.get(old_id).epistemic_status == EpistemicStatus.SUPERSEDED and canonical.get(new_id).predecessor_id == old_id

        locator_recall = locator_hits / locator_total if locator_total else 0.0
        acceptance = {
            "locator_recall_at_5": locator_recall >= 0.95,
            "conflict_16_of_16": len(checks["conflict"]) == 16 and all(checks["conflict"]),
            "correction_16_of_16": len(checks["correction"]) == 16 and all(checks["correction"]),
            "current_8_of_8": len(checks["current"]) == 8 and all(checks["current"]),
            "empty_8_of_8": len(checks["empty"]) == 8 and all(checks["empty"]),
            "stale_index_conflict_completeness": stale_complete,
            "policy_and_integrity": all(safety.values()),
            "direct_no_memoryos_regression": load_direct_precondition(),
        }
        passed = all(acceptance.values())
        report = {
            "schema":"externes-gehirn.phase-c-evidence","version":"0.1.0",
            "contract":{"drive_id":CONTRACT_DRIVE_ID,"file_sha256":CONTRACT_FILE_SHA256,"benchmark_sha256":binding["benchmark_sha256"]},
            "model":{"repository":MODEL,"revision":MODEL_REVISION,**model_info},
            "locator":{"non_empty_queries":locator_total,"hits_at_5":locator_hits,"Recall@5":round(locator_recall,6)},
            "acceptance":acceptance,"safety":safety,"rows":rows,
            "result":"PASS" if passed else "FAIL",
            "role_decision":"DIRECT_QDRANT_QUALIFIED_AS_DERIVED_SUBJECT_LOCATOR_WITH_PRODUCT_NEUTRAL_TRUTH_AWARE_ANSWER_SET" if passed else "NO_ROLE_QUALIFICATION",
            "stack_decision":"NOT_MADE",
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k != "rows"}, indent=2, ensure_ascii=False))
        index.close()
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
