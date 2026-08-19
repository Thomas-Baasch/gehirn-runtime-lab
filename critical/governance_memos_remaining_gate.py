from __future__ import annotations

import json
import tempfile
from pathlib import Path

from governance.canon_router import Authority, KnowledgeType, Sensitivity
from governance.intake_composition import GovernedIntakeService
from governance.intake_router import (
    DomainDefinition,
    DomainReferenceCatalog,
    DomainRegistry,
    SafeInbox,
)
from governance.memos_composition import (
    CanonicalSQLiteStore,
    GovernedMemOSService,
    PartitionedMemOSIndex,
)


class DeterministicEmbedder:
    """Search/index fixture only; contains no routing or governance policy."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            value = sum(ord(ch) for ch in text) % 997
            vectors.append(
                [
                    ((value * 3) % 101) / 100.0,
                    ((value * 5) % 103) / 102.0,
                    ((value * 7) % 107) / 106.0,
                    ((value * 11) % 109) / 108.0,
                ]
            )
        return vectors


def definitions() -> list[DomainDefinition]:
    return [
        DomainDefinition(
            "USCHI",
            aliases=("USCHI",),
            context_terms=("voice", "desktop", "assistant", "cockpit"),
        ),
        DomainDefinition(
            "Rechnungen",
            aliases=("Rechnungen",),
            context_terms=("rechnung", "lieferant", "beleg", "invoice"),
        ),
        DomainDefinition(
            "WZW",
            aliases=("WZW",),
            context_terms=("zimmer 12", "möblieren", "möbel", "renovierung"),
        ),
        DomainDefinition(
            "WG Rostock",
            aliases=("WG", "WG Rostock"),
            context_terms=("wg", "vermieten", "mieter", "besichtigung", "zimmer 3"),
        ),
        DomainDefinition(
            "Reise/Fahrt",
            aliases=("Reise",),
            context_terms=("fahrt", "route", "fahren", "reise", "zug"),
        ),
        DomainDefinition(
            "Ideen",
            aliases=("Ideenprojekt", "Ideen"),
            context_terms=("brainstorming", "ideenliste"),
        ),
        DomainDefinition(
            "Unavailable",
            aliases=("Unavailable",),
            context_terms=(),
            canon_exists=True,
            canon_available=False,
        ),
    ]


def build(root: Path):
    registry = DomainRegistry(definitions())
    canonical = CanonicalSQLiteStore(root / "canon" / "canon.sqlite")
    index = PartitionedMemOSIndex(root / "memos", DeterministicEmbedder())
    core = GovernedMemOSService(canonical, index)
    inbox = SafeInbox(root / "inbox" / "inbox.sqlite")
    refs = DomainReferenceCatalog(root / "refs" / "refs.sqlite")
    intake = GovernedIntakeService(
        core=core,
        registry=registry,
        inbox=inbox,
        references=refs,
    )
    allowed_domains = {d.domain_id for d in definitions()}
    authority = Authority(
        actor_id="synthetic-user",
        allowed_projects=frozenset(allowed_domains),
        allowed_purposes=frozenset({"cross_project_memory"}),
        sensitivity_clearance=Sensitivity.CONFIDENTIAL,
    )
    return intake, core, registry, inbox, refs, authority


def compact_outcome(outcome: dict) -> dict:
    candidate = outcome["candidate"]
    return {
        "status": outcome["status"],
        "record_id": outcome.get("record_id"),
        "parked_id": outcome.get("parked_id"),
        "deduplicated": outcome.get("deduplicated", False),
        "source_ref": candidate.source_ref,
        "content": candidate.content,
        "subject": candidate.subject,
        "knowledge_type": candidate.knowledge_type.value,
        "epistemic_status": candidate.epistemic_status.value,
        "route_status": candidate.route_status.value,
        "target_domain": candidate.target_domain,
        "related_domains": list(candidate.related_domains),
        "routing_confidence": candidate.routing_confidence,
        "routing_reason": candidate.routing_reason,
    }


def gt01(root: Path) -> dict:
    intake, core, registry, inbox, refs, authority = build(root)
    text = (
        "Bei USCHI sollten wir Voice später prüfen. "
        "Die Rechnung von Lieferant X muss ich noch kontrollieren. "
        "Für WZW könnten wir Zimmer 12 neu möblieren."
    )
    outcomes = intake.ingest_message(
        text,
        source_ref="synthetic:gt01",
        authority=authority,
    )
    compact = [compact_outcome(o) for o in outcomes]
    targets = [o["target_domain"] for o in compact]
    no_decision = all(o["knowledge_type"] != "DECISION" for o in compact)
    statuses_unchanged = all(o["epistemic_status"] == "USER_STATED" for o in compact)
    registry_reads = list(registry.read_log)
    passed = (
        len(outcomes) == 3
        and targets == ["USCHI", "Rechnungen", "WZW"]
        and all(o["status"] == "WRITTEN" for o in compact)
        and no_decision
        and statuses_unchanged
        and core.canonical.count() == 3
        and len(core.index.write_log) == 3
        and len(inbox.all()) == 0
        and [r["result"] for r in registry_reads] == ["CANON_READ_OK"] * 3
    )
    return {
        "input": text,
        "expected": "three separate candidates routed USCHI / Rechnungen / WZW; no invented decision",
        "actual_candidates": compact,
        "canonical_record_count": core.canonical.count(),
        "memos_index_write_count": len(core.index.write_log),
        "canon_read_before_write_log": registry_reads,
        "parked_count": len(inbox.all()),
        "pass": passed,
    }


def gt02(root: Path) -> dict:
    intake, core, registry, inbox, refs, authority = build(root)
    text = (
        "Für WZW brauchen wir neue Möbel für Zimmer 12. "
        "Die Rechnung von Lieferant X muss ich noch kontrollieren."
    )
    outcomes = intake.ingest_message(
        text,
        source_ref="synthetic:gt02",
        authority=authority,
        previous_domain="USCHI",
    )
    compact = [compact_outcome(o) for o in outcomes]
    targets = [o["target_domain"] for o in compact]
    passed = (
        targets == ["WZW", "Rechnungen"]
        and "USCHI" not in targets
        and all(o["status"] == "WRITTEN" for o in compact)
        and core.canonical.count() == 2
        and len(core.index.write_log) == 2
    )
    return {
        "previous_conversation_domain": "USCHI",
        "input": text,
        "expected": "new explicit/current evidence routes independently and is not swallowed by previous USCHI context",
        "actual_candidates": compact,
        "canonical_record_count": core.canonical.count(),
        "memos_index_write_count": len(core.index.write_log),
        "pass": passed,
    }


def gt03(root: Path) -> dict:
    intake, core, registry, inbox, refs, authority = build(root)
    wg_text = "Für die WG in Rostock muss Zimmer 3 neu vermietet werden."
    trip_text = "Für die Fahrt nach Rostock sollten wir die Route planen."
    wg = intake.ingest_message(
        wg_text,
        source_ref="synthetic:gt03:wg",
        authority=authority,
    )
    trip = intake.ingest_message(
        trip_text,
        source_ref="synthetic:gt03:trip",
        authority=authority,
    )
    wg_c = compact_outcome(wg[0])
    trip_c = compact_outcome(trip[0])
    passed = (
        wg_c["target_domain"] == "WG Rostock"
        and trip_c["target_domain"] == "Reise/Fahrt"
        and wg_c["status"] == "WRITTEN"
        and trip_c["status"] == "WRITTEN"
        and core.canonical.count() == 2
    )
    return {
        "input_wg": wg_text,
        "input_trip": trip_text,
        "expected": "same location token Rostock routes by context, not location name alone",
        "wg_candidate": wg_c,
        "trip_candidate": trip_c,
        "pass": passed,
    }


def gt07(root: Path) -> dict:
    intake, core, registry, inbox, refs, authority = build(root)
    text = "Zimmer 12 bekommt einen neuen Schreibtisch."
    first = intake.ingest_explicit(
        text,
        source_ref="synthetic:gt07:ideas",
        target_domain="Ideen",
        authority=authority,
        subject="Zimmer 12 Möblierung",
        knowledge_type=KnowledgeType.IDEA,
    )
    count_after_first = core.canonical.count()
    writes_after_first = len(core.index.write_log)
    second = intake.ingest_explicit(
        text,
        source_ref="synthetic:gt07:wzw",
        target_domain="WZW",
        authority=authority,
        subject="Zimmer 12 Möblierung",
        knowledge_type=KnowledgeType.IDEA,
    )
    count_after_second = core.canonical.count()
    writes_after_second = len(core.index.write_log)
    record_id = first.get("record_id")
    domain_refs = refs.refs(record_id) if record_id else []
    passed = (
        first["status"] == "WRITTEN"
        and second["status"] == "LINKED_DUPLICATE"
        and first["record_id"] == second["record_id"]
        and count_after_first == 1
        and count_after_second == 1
        and writes_after_first == 1
        and writes_after_second == 1
        and {r["domain_id"] for r in domain_refs} == {"Ideen", "WZW"}
    )
    return {
        "input_first": {"domain": "Ideen", "content": text},
        "input_second": {"domain": "WZW", "content": text},
        "expected": "link/deduplicate; one canonical truth, cross-domain references",
        "first": compact_outcome(first),
        "second": compact_outcome(second),
        "canonical_count_after_first": count_after_first,
        "canonical_count_after_second": count_after_second,
        "memos_index_writes_after_first": writes_after_first,
        "memos_index_writes_after_second": writes_after_second,
        "domain_references": domain_refs,
        "pass": passed,
    }


def gt10(root: Path) -> dict:
    intake, core, registry, inbox, refs, authority = build(root)
    text = "Diese Information gehört in den aktuell nicht ladbaren Ziel-Canon."
    canon_before = core.canonical.count()
    writes_before = len(core.index.write_log)
    outcome = intake.ingest_explicit(
        text,
        source_ref="synthetic:gt10",
        target_domain="Unavailable",
        authority=authority,
        subject="nicht ladbarer Ziel-Canon",
        knowledge_type=KnowledgeType.CLAIM,
    )
    parked = inbox.all()
    canon_after = core.canonical.count()
    writes_after = len(core.index.write_log)
    passed = (
        outcome["status"] == "BLOCKED"
        and canon_after == canon_before
        and writes_after == writes_before
        and len(parked) == 1
        and parked[0]["route_status"] == "BLOCKED"
        and registry.read_log[-1]["result"] == "TARGET_CANON_UNAVAILABLE"
    )
    return {
        "input": text,
        "target": "Unavailable",
        "expected": "fail closed, park in durable inbox/journal, no Canon or index write",
        "outcome": compact_outcome(outcome),
        "canon_read_log": registry.read_log,
        "parked_candidates": parked,
        "canonical_write_delta": canon_after - canon_before,
        "memos_index_write_delta": writes_after - writes_before,
        "pass": passed,
    }


def gt11(root: Path) -> dict:
    intake, core, registry, inbox, refs, authority = build(root)
    text = "Die WZW-Rechnung von Firma X gehört zur Renovierung Zimmer 12."
    outcomes = intake.ingest_message(
        text,
        source_ref="synthetic:gt11",
        authority=authority,
    )
    outcome = outcomes[0]
    compact = compact_outcome(outcome)
    record = core.canonical.get(outcome["record_id"]) if outcome.get("record_id") else None
    domain_refs = refs.refs(outcome["record_id"]) if outcome.get("record_id") else []
    passed = (
        len(outcomes) == 1
        and compact["status"] == "WRITTEN"
        and compact["target_domain"] == "WZW"
        and compact["related_domains"] == ["Rechnungen"]
        and core.canonical.count() == 1
        and len(core.index.write_log) == 1
        and record is not None
        and "domain:Rechnungen" in record.relations
        and {r["domain_id"] for r in domain_refs} == {"WZW", "Rechnungen"}
    )
    return {
        "input": text,
        "expected": "one canonical candidate, WZW primary with traceable Rechnungen relation; no duplicated content",
        "candidate": compact,
        "canonical_record_count": core.canonical.count(),
        "memos_index_write_count": len(core.index.write_log),
        "canonical_relations": list(record.relations) if record else [],
        "domain_references": domain_refs,
        "pass": passed,
    }


def run_test(name: str, fn) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"eg-{name.lower()}-") as td:
        result = fn(Path(td))
    return result


def main() -> int:
    tests = {
        "GT-01": run_test("GT01", gt01),
        "GT-02": run_test("GT02", gt02),
        "GT-03": run_test("GT03", gt03),
        "GT-07": run_test("GT07", gt07),
        "GT-10": run_test("GT10", gt10),
        "GT-11": run_test("GT11", gt11),
    }
    passed = sum(1 for result in tests.values() if result["pass"])
    report = {
        "schema": "externes-gehirn.composed-remaining-runtime-evidence.v0.1",
        "architecture": (
            "ProductNeutralIntakeRouter + DomainRegistry/SafeInbox/DomainReferenceCatalog -> "
            "FailClosedCanonRouter -> CanonicalSQLiteStore -> policy-partitioned MemOS/Qdrant derived index"
        ),
        "candidate_substrate": "MemTensor/MemOS",
        "candidate_distribution": "MemoryOS",
        "candidate_version": "2.0.30",
        "candidate_release_commit": "f4db521214c29337164ec788bafede7eab236c25",
        "qdrant_client_pin": "1.16.0",
        "canon_truth": "product-neutral SQLite canonical records + product-neutral domain reference/inbox stores",
        "index_truth_status": "DERIVED_RECONSTRUCTABLE_NOT_CANONICAL",
        "tests": tests,
        "passed": passed,
        "total": len(tests),
        "result": "PASS" if passed == len(tests) else "FAIL",
        "interpretation": (
            "These are the six non-critical Golden Tests, executed only after the composed critical gate passed. "
            "A PASS completes remaining functional evidence for this composition but does not by itself replace "
            "the previously recorded critical artifacts or make MemOS a native Canon router."
        ),
    }
    out = Path("reports/composed/governance_memos_remaining.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
