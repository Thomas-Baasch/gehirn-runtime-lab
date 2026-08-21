from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from governance.canon_router import Authority, EpistemicStatus, KnowledgeRecord, ReadDecision, Sensitivity
from governance.memos_recovery import RecoverableGovernedMemOSService

_GENERIC_SUBJECT_TOKENS = {
    "project", "projekt", "contract", "vertrag", "service", "dienst", "system",
    "status", "date", "datum", "time", "uhrzeit", "subject", "thema", "site",
    "standort", "warehouse", "lager", "house", "haus", "regular", "daily",
    "täglich", "current", "aktuell", "test", "channel", "kanal", "policy",
}


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[0-9A-Za-zÄÖÜäöüß]+", text)}


def subject_identity_matches(query: str, subject: str) -> bool:
    """Conservatively confirm that a retrieved subject is named in the query.

    Exact token overlap is preferred. For German compounds, the fallback is
    deliberately stricter: at least TWO distinctive canonical subject tokens
    (>=5 chars) must each be fully contained in query tokens. This accepts
    `Mieter` + `Übergabe` inside `Mieterübergabe`, but a generic fragment such
    as `Datum` or a lone `Wochen` can never confirm an unrelated subject.
    This guard may reject an anchor; it never creates or changes canonical truth.
    """
    query_tokens = _tokens(query)
    subject_tokens = _tokens(subject) - _GENERIC_SUBJECT_TOKENS
    if not subject_tokens:
        return False
    if query_tokens & subject_tokens:
        return True
    distinctive_subject = {token for token in subject_tokens if len(token) >= 5}
    distinctive_query = {token for token in query_tokens if len(token) >= 5}
    matched_subject_tokens = {
        subject_token
        for subject_token in distinctive_subject
        if any(subject_token in query_token for query_token in distinctive_query)
    }
    return len(matched_subject_tokens) >= 2


@dataclass(frozen=True)
class LocatedCandidate:
    record: KnowledgeRecord
    score: float


@dataclass(frozen=True)
class AnswerSet:
    status: str
    subject: str | None
    records: tuple[KnowledgeRecord, ...]
    winner_record_id: str | None = None
    locator_candidates: tuple[LocatedCandidate, ...] = ()
    reason: str = ""


class TruthAwareAnswerSetService:
    """Product-neutral truth projection over an authorized derived subject locator.

    The derived locator proposes IDs only. Every candidate and every sibling is
    rehydrated and re-authorized from Canon. Conflict/correction semantics come
    exclusively from canonical epistemic state. Retrieval never promotes truth.
    """

    def __init__(self, governed: RecoverableGovernedMemOSService, locator: Any) -> None:
        self.governed = governed
        self.locator = locator

    def locate(
        self,
        *,
        query: str,
        target_project: str,
        purpose: str,
        authority: Authority,
        top_k: int = 10,
    ) -> tuple[str, tuple[LocatedCandidate, ...]]:
        route = self.governed.gate.route(
            explicit_target=target_project, target_candidates=(), authority=authority
        )
        if route.status.value != "ROUTED":
            return "BLOCKED", ()
        if purpose not in authority.allowed_purposes:
            return "BLOCKED", ()

        raw = self.locator.search_scored_allowed(
            query=query,
            project=target_project,
            purpose=purpose,
            clearance=authority.sensitivity_clearance,
            top_k=top_k,
        )
        located: list[LocatedCandidate] = []
        seen: set[str] = set()
        for item in raw:
            if item.id in seen:
                continue
            seen.add(item.id)
            canonical = self.governed.canonical.get(item.id)
            if canonical is None:
                continue
            decision: ReadDecision = self.governed.gate.read(item.id, authority=authority)
            if not decision.allowed or decision.record is None:
                continue
            located.append(LocatedCandidate(canonical, float(item.score)))
        return "ALLOWED", tuple(located)

    def answer(
        self,
        *,
        query: str,
        target_project: str,
        purpose: str,
        authority: Authority,
        top_k: int = 10,
        history: bool = False,
    ) -> AnswerSet:
        locate_status, candidates = self.locate(
            query=query,
            target_project=target_project,
            purpose=purpose,
            authority=authority,
            top_k=top_k,
        )
        if locate_status == "BLOCKED":
            return AnswerSet("BLOCKED", None, (), locator_candidates=(), reason="policy_denied_before_locator")

        matching = tuple(c for c in candidates if subject_identity_matches(query, c.record.subject))
        if not matching:
            return AnswerSet("EMPTY", None, (), locator_candidates=candidates, reason="no_confirmed_subject_anchor")

        anchor = max(matching, key=lambda item: item.score)
        siblings = self._authorized_siblings(anchor.record, authority=authority)
        if not siblings:
            return AnswerSet("EMPTY", anchor.record.subject, (), locator_candidates=candidates, reason="no_authorized_canonical_siblings")

        if history:
            return AnswerSet(
                "HISTORY",
                anchor.record.subject,
                tuple(sorted(siblings, key=lambda r: (r.observed_at, r.record_id))),
                locator_candidates=candidates,
                reason="authorized_history_projection",
            )

        current = tuple(r for r in siblings if r.epistemic_status != EpistemicStatus.SUPERSEDED)
        if not current:
            return AnswerSet("EMPTY", anchor.record.subject, (), locator_candidates=candidates, reason="no_current_canonical_record")
        if any(r.epistemic_status == EpistemicStatus.CONFLICTING for r in current):
            return AnswerSet(
                "CONFLICTING",
                anchor.record.subject,
                tuple(sorted(current, key=lambda r: r.record_id)),
                winner_record_id=None,
                locator_candidates=candidates,
                reason="canonical_conflict_preserved",
            )
        return AnswerSet(
            "CURRENT",
            anchor.record.subject,
            tuple(sorted(current, key=lambda r: r.record_id)),
            winner_record_id=None,
            locator_candidates=candidates,
            reason="canonical_current_projection",
        )

    def project_from_anchor_ids(
        self,
        *,
        anchor_ids: list[str],
        authority: Authority,
        history: bool = False,
    ) -> AnswerSet:
        """Prove that one authorized derived anchor can recover full Canon siblings."""
        anchor: KnowledgeRecord | None = None
        for record_id in anchor_ids:
            canonical = self.governed.canonical.get(record_id)
            if canonical is None:
                continue
            decision = self.governed.gate.read(record_id, authority=authority)
            if decision.allowed and decision.record is not None:
                anchor = canonical
                break
        if anchor is None:
            return AnswerSet("EMPTY", None, (), reason="no_authorized_canonical_anchor")
        siblings = self._authorized_siblings(anchor, authority=authority)
        if history:
            return AnswerSet("HISTORY", anchor.subject, siblings, reason="authorized_history_projection")
        current = tuple(r for r in siblings if r.epistemic_status != EpistemicStatus.SUPERSEDED)
        if any(r.epistemic_status == EpistemicStatus.CONFLICTING for r in current):
            return AnswerSet("CONFLICTING", anchor.subject, current, winner_record_id=None, reason="canonical_conflict_preserved")
        if current:
            return AnswerSet("CURRENT", anchor.subject, current, winner_record_id=None, reason="canonical_current_projection")
        return AnswerSet("EMPTY", anchor.subject, (), reason="no_current_canonical_record")

    def _authorized_siblings(self, anchor: KnowledgeRecord, *, authority: Authority) -> tuple[KnowledgeRecord, ...]:
        allowed: list[KnowledgeRecord] = []
        for record in self.governed.canonical.all():
            if record.target_domain != anchor.target_domain:
                continue
            if record.purpose != anchor.purpose:
                continue
            if record.subject != anchor.subject:
                continue
            decision = self.governed.gate.read(record.record_id, authority=authority)
            if decision.allowed and decision.record is not None:
                allowed.append(record)
        return tuple(allowed)
