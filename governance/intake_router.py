from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from governance.canon_router import EpistemicStatus, KnowledgeType, RouteStatus


_WORD_RE = re.compile(r"[\wÄÖÜäöüß-]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\wäöüß]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def content_fingerprint(subject: str, content: str) -> str:
    payload = f"{normalize_text(subject)}\n{normalize_text(content)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class DomainDefinition:
    domain_id: str
    aliases: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()
    canon_exists: bool = True
    canon_available: bool = True


@dataclass(frozen=True)
class CandidateDraft:
    content: str
    subject: str
    knowledge_type: KnowledgeType
    epistemic_status: EpistemicStatus
    route_status: RouteStatus
    target_domain: str | None
    related_domains: tuple[str, ...]
    routing_confidence: float
    routing_reason: str
    source_ref: str


class DomainRegistry:
    """External-Canon availability registry used before writes.

    The router may identify a likely domain, but a write is allowed only after
    this registry confirms the target exists and its current Canon can be read.
    """

    def __init__(self, definitions: Iterable[DomainDefinition]) -> None:
        self._definitions = {d.domain_id: d for d in definitions}
        self.read_log: list[dict] = []

    @property
    def definitions(self) -> tuple[DomainDefinition, ...]:
        return tuple(self._definitions.values())

    def get(self, domain_id: str) -> DomainDefinition | None:
        return self._definitions.get(domain_id)

    def read_current_canon(self, domain_id: str) -> bool:
        definition = self._definitions.get(domain_id)
        if definition is None:
            self.read_log.append(
                {"domain": domain_id, "result": "MISSING_TARGET_CANON"}
            )
            return False
        if not definition.canon_exists:
            self.read_log.append(
                {"domain": domain_id, "result": "TARGET_CANON_DOES_NOT_EXIST"}
            )
            return False
        if not definition.canon_available:
            self.read_log.append(
                {"domain": domain_id, "result": "TARGET_CANON_UNAVAILABLE"}
            )
            return False
        self.read_log.append({"domain": domain_id, "result": "CANON_READ_OK"})
        return True


class SafeInbox:
    """Durable parking area for ambiguous/blocked candidates."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS parked_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_ref TEXT NOT NULL,
                    content TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    route_status TEXT NOT NULL,
                    proposed_target TEXT,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def park(self, candidate: CandidateDraft, *, reason: str) -> int:
        payload = {
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
            "park_reason": reason,
        }
        with sqlite3.connect(self.path) as conn:
            cur = conn.execute(
                """
                INSERT INTO parked_candidates(
                    source_ref, content, subject, route_status,
                    proposed_target, reason, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.source_ref,
                    candidate.content,
                    candidate.subject,
                    candidate.route_status.value,
                    candidate.target_domain,
                    reason,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            return int(cur.lastrowid)

    def all(self) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT id, source_ref, content, subject, route_status, proposed_target, reason, payload_json "
                "FROM parked_candidates ORDER BY id"
            ).fetchall()
        return [
            {
                "id": row[0],
                "source_ref": row[1],
                "content": row[2],
                "subject": row[3],
                "route_status": row[4],
                "proposed_target": row[5],
                "reason": row[6],
                "payload": json.loads(row[7]),
            }
            for row in rows
        ]


class DomainReferenceCatalog:
    """Cross-domain references and dedupe identities independent of the index."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS content_identity (
                    fingerprint TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS domain_refs (
                    record_id TEXT NOT NULL,
                    domain_id TEXT NOT NULL,
                    relation_kind TEXT NOT NULL,
                    PRIMARY KEY(record_id, domain_id, relation_kind)
                );
                """
            )

    def resolve(self, fingerprint: str) -> str | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT record_id FROM content_identity WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
        return str(row[0]) if row else None

    def bind(self, fingerprint: str, record_id: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO content_identity(fingerprint, record_id) VALUES (?, ?)",
                (fingerprint, record_id),
            )

    def add_domain_ref(self, record_id: str, domain_id: str, relation_kind: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO domain_refs(record_id, domain_id, relation_kind) VALUES (?, ?, ?)",
                (record_id, domain_id, relation_kind),
            )

    def refs(self, record_id: str) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT domain_id, relation_kind FROM domain_refs WHERE record_id=? ORDER BY domain_id, relation_kind",
                (record_id,),
            ).fetchall()
        return [{"domain_id": row[0], "relation_kind": row[1]} for row in rows]


class ProductNeutralIntakeRouter:
    """Generic clause decomposition + registry-driven domain scoring.

    Domain knowledge is data supplied through DomainDefinition. The algorithm
    contains no candidate-product or Golden-Test-specific domain branch.
    """

    def __init__(self, registry: DomainRegistry) -> None:
        self.registry = registry

    def analyze_message(
        self,
        message: str,
        *,
        source_ref: str,
        previous_domain: str | None = None,
    ) -> list[CandidateDraft]:
        clauses = [c.strip() for c in _SENTENCE_RE.split(message.strip()) if c.strip()]
        if not clauses:
            return []
        return [
            self.analyze_clause(
                clause,
                source_ref=f"{source_ref}#candidate-{idx + 1}",
                previous_domain=previous_domain,
            )
            for idx, clause in enumerate(clauses)
        ]

    def analyze_clause(
        self,
        clause: str,
        *,
        source_ref: str,
        previous_domain: str | None = None,
    ) -> CandidateDraft:
        normalized = normalize_text(clause)
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}

        for definition in self.registry.definitions:
            score = 0.0
            reasons: list[str] = []
            for alias in definition.aliases:
                a = normalize_text(alias)
                if a and self._contains_phrase(normalized, a):
                    score += 10.0
                    reasons.append(f"alias:{alias}")
            for term in definition.context_terms:
                t = normalize_text(term)
                if t and self._contains_phrase(normalized, t):
                    score += 2.0
                    reasons.append(f"context:{term}")
            if score > 0:
                scores[definition.domain_id] = score
                evidence[definition.domain_id] = reasons

        # Prior conversational context is only a weak fallback; it may never
        # override explicit/current evidence for another domain.
        if not scores and previous_domain and self.registry.get(previous_domain):
            scores[previous_domain] = 0.25
            evidence[previous_domain] = ["previous_context_fallback"]

        if not scores:
            route_status = RouteStatus.UNROUTED
            target = None
            related: tuple[str, ...] = ()
            confidence = 0.0
            reason = "no_domain_evidence"
        else:
            max_score = max(scores.values())
            winners = [d for d, score in scores.items() if score == max_score]
            if len(winners) != 1:
                route_status = RouteStatus.AMBIGUOUS
                target = None
                related = tuple(sorted(scores))
                confidence = 0.0
                reason = "equal_top_domain_evidence"
            else:
                target = winners[0]
                route_status = RouteStatus.ROUTED
                related = tuple(
                    sorted(d for d, score in scores.items() if d != target and score > 0)
                )
                total = sum(scores.values())
                confidence = round(max_score / total, 6) if total else 0.0
                reason = ";".join(evidence.get(target, [])) or "registry_score"

        return CandidateDraft(
            content=clause,
            subject=self._subject(clause),
            knowledge_type=self._knowledge_type(normalized),
            epistemic_status=EpistemicStatus.USER_STATED,
            route_status=route_status,
            target_domain=target,
            related_domains=related,
            routing_confidence=confidence,
            routing_reason=reason,
            source_ref=source_ref,
        )

    @staticmethod
    def _contains_phrase(normalized: str, phrase: str) -> bool:
        return f" {phrase} " in f" {normalized} "

    @staticmethod
    def _subject(clause: str) -> str:
        tokens = _WORD_RE.findall(clause)
        return " ".join(tokens[:8]).strip() or "unspecified"

    @staticmethod
    def _knowledge_type(normalized: str) -> KnowledgeType:
        decision_markers = (
            "ich habe entschieden",
            "wir haben entschieden",
            "ist beschlossen",
            "haben beschlossen",
        )
        if any(marker in normalized for marker in decision_markers):
            return KnowledgeType.DECISION
        if any(marker in normalized for marker in ("war falsch", "richtig sind", "korrektur")):
            return KnowledgeType.CORRECTION
        if any(marker in normalized for marker in ("muss ich", "müssen wir", "noch kontrollieren", "zu erledigen")):
            return KnowledgeType.TASK
        if any(marker in normalized for marker in ("vielleicht", "könnten wir", "könnte", "sollten wir")):
            return KnowledgeType.IDEA
        if "?" in normalized:
            return KnowledgeType.QUESTION
        return KnowledgeType.CLAIM
