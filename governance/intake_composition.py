from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from governance.canon_router import Authority, EpistemicStatus, KnowledgeType, RouteStatus, Sensitivity
from governance.intake_router import (
    CandidateDraft,
    DomainReferenceCatalog,
    DomainRegistry,
    ProductNeutralIntakeRouter,
    SafeInbox,
    content_fingerprint,
)
from governance.memos_composition import GovernedMemOSService


class GovernedIntakeService:
    """Product-neutral intake -> governance/canon -> derived MemOS composition."""

    def __init__(
        self,
        *,
        core: GovernedMemOSService,
        registry: DomainRegistry,
        inbox: SafeInbox,
        references: DomainReferenceCatalog,
    ) -> None:
        self.core = core
        self.registry = registry
        self.inbox = inbox
        self.references = references
        self.router = ProductNeutralIntakeRouter(registry)
        self.outcome_log: list[dict] = []

    def ingest_message(
        self,
        message: str,
        *,
        source_ref: str,
        authority: Authority,
        previous_domain: str | None = None,
        purpose: str = "cross_project_memory",
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
    ) -> list[dict]:
        candidates = self.router.analyze_message(
            message,
            source_ref=source_ref,
            previous_domain=previous_domain,
        )
        return [
            self.ingest_candidate(
                candidate,
                authority=authority,
                purpose=purpose,
                sensitivity=sensitivity,
            )
            for candidate in candidates
        ]

    def ingest_explicit(
        self,
        content: str,
        *,
        source_ref: str,
        target_domain: str,
        authority: Authority,
        subject: str | None = None,
        knowledge_type: KnowledgeType = KnowledgeType.CLAIM,
        related_domains: tuple[str, ...] = (),
        purpose: str = "cross_project_memory",
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
    ) -> dict:
        base = self.router.analyze_clause(
            content,
            source_ref=source_ref,
            previous_domain=None,
        )
        candidate = replace(
            base,
            subject=subject or base.subject,
            knowledge_type=knowledge_type,
            route_status=RouteStatus.ROUTED,
            target_domain=target_domain,
            related_domains=related_domains,
            routing_confidence=1.0,
            routing_reason="explicit_target",
        )
        return self.ingest_candidate(
            candidate,
            authority=authority,
            purpose=purpose,
            sensitivity=sensitivity,
        )

    def ingest_candidate(
        self,
        candidate: CandidateDraft,
        *,
        authority: Authority,
        purpose: str,
        sensitivity: Sensitivity,
    ) -> dict:
        if candidate.route_status != RouteStatus.ROUTED or not candidate.target_domain:
            parked_id = self.inbox.park(candidate, reason="candidate_not_safely_routed")
            outcome = {
                "status": candidate.route_status.value,
                "candidate": candidate,
                "record_id": None,
                "parked_id": parked_id,
                "deduplicated": False,
            }
            self._log(outcome)
            return outcome

        route = self.core.route(
            explicit_target=candidate.target_domain,
            target_candidates=(),
            authority=authority,
        )
        if route.status != RouteStatus.ROUTED:
            blocked = replace(
                candidate,
                route_status=RouteStatus.BLOCKED,
                routing_reason=f"governance:{route.reason}",
            )
            parked_id = self.inbox.park(blocked, reason=route.reason)
            outcome = {
                "status": "BLOCKED",
                "candidate": blocked,
                "record_id": None,
                "parked_id": parked_id,
                "deduplicated": False,
            }
            self._log(outcome)
            return outcome

        # Canon existence/availability is a separate gate from routing.
        if not self.registry.read_current_canon(candidate.target_domain):
            blocked = replace(
                candidate,
                route_status=RouteStatus.BLOCKED,
                routing_reason="target_canon_not_loaded",
            )
            parked_id = self.inbox.park(blocked, reason="target_canon_not_loaded")
            outcome = {
                "status": "BLOCKED",
                "candidate": blocked,
                "record_id": None,
                "parked_id": parked_id,
                "deduplicated": False,
            }
            self._log(outcome)
            return outcome

        fingerprint = content_fingerprint(candidate.subject, candidate.content)
        existing_id = self.references.resolve(fingerprint)
        if existing_id:
            existing = self.core.canonical.get(existing_id)
            if existing is None:
                raise RuntimeError("reference_catalog_points_to_missing_canonical_record")
            self.references.add_domain_ref(
                existing_id, candidate.target_domain, "cross_project_duplicate_reference"
            )
            for related in candidate.related_domains:
                self.references.add_domain_ref(existing_id, related, "related_domain")
            outcome = {
                "status": "LINKED_DUPLICATE",
                "candidate": candidate,
                "record_id": existing_id,
                "parked_id": None,
                "deduplicated": True,
                "canonical_record": existing,
            }
            self._log(outcome)
            return outcome

        relations = tuple(f"domain:{domain}" for domain in candidate.related_domains)
        record = self.core.new_record(
            source_ref=candidate.source_ref,
            subject=candidate.subject,
            target_domain=candidate.target_domain,
            knowledge_type=candidate.knowledge_type,
            epistemic_status=candidate.epistemic_status,
            confidence=candidate.routing_confidence,
            sensitivity=sensitivity,
            purpose=purpose,
            content=candidate.content,
            authority=authority,
            relations=relations,
        )
        stored = self.core.write(record, authority=authority)
        self.references.bind(fingerprint, stored.record_id)
        self.references.add_domain_ref(stored.record_id, candidate.target_domain, "primary")
        for related in candidate.related_domains:
            self.references.add_domain_ref(stored.record_id, related, "related_domain")
        outcome = {
            "status": "WRITTEN",
            "candidate": candidate,
            "record_id": stored.record_id,
            "parked_id": None,
            "deduplicated": False,
            "canonical_record": stored,
        }
        self._log(outcome)
        return outcome

    def _log(self, outcome: dict) -> None:
        candidate = outcome["candidate"]
        self.outcome_log.append(
            {
                "status": outcome["status"],
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
                "record_id": outcome.get("record_id"),
                "parked_id": outcome.get("parked_id"),
                "deduplicated": outcome.get("deduplicated", False),
            }
        )
