from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
from uuid import uuid4


class KnowledgeType(str, Enum):
    IDEA = "IDEA"
    QUESTION = "QUESTION"
    OBSERVATION = "OBSERVATION"
    CLAIM = "CLAIM"
    DECISION = "DECISION"
    CORRECTION = "CORRECTION"
    TASK = "TASK"


class EpistemicStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    USER_STATED = "USER_STATED"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTING = "CONFLICTING"


class Sensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class RouteStatus(str, Enum):
    ROUTED = "ROUTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNROUTED = "UNROUTED"
    BLOCKED = "BLOCKED"


_SENSITIVITY_RANK = {
    Sensitivity.PUBLIC: 0,
    Sensitivity.INTERNAL: 1,
    Sensitivity.CONFIDENTIAL: 2,
    Sensitivity.RESTRICTED: 3,
}


@dataclass(frozen=True)
class RouteDecision:
    status: RouteStatus
    target_domain: str | None
    reason: str
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Authority:
    actor_id: str
    allowed_projects: frozenset[str]
    allowed_purposes: frozenset[str]
    sensitivity_clearance: Sensitivity = Sensitivity.INTERNAL
    can_verify: bool = False
    can_correct: bool = False
    can_promote_decision: bool = False


@dataclass(frozen=True)
class KnowledgeRecord:
    record_id: str
    source_ref: str
    observed_at: str
    subject: str
    target_domain: str
    knowledge_type: KnowledgeType
    epistemic_status: EpistemicStatus
    confidence: float
    sensitivity: Sensitivity
    purpose: str
    content: str
    relations: tuple[str, ...] = ()
    predecessor_id: str | None = None
    created_by: str = ""


@dataclass(frozen=True)
class ReadDecision:
    allowed: bool
    status: str
    reason: str
    record: KnowledgeRecord | None = None


class GovernanceError(RuntimeError):
    pass


class FailClosedCanonRouter:
    """Product-neutral Canon routing/governance policy boundary.

    This is intentionally a separate architecture component, not a candidate
    adapter. Candidate products remain responsible only for the capabilities
    they natively provide. This gate owns fail-closed target selection,
    epistemic/promotion policy, conflict preservation, correction lineage and
    sensitivity/purpose authorization before reads/writes.
    """

    def __init__(self) -> None:
        self._records: dict[str, KnowledgeRecord] = {}
        self._history: list[dict] = []

    @property
    def history(self) -> tuple[dict, ...]:
        return tuple(self._history)

    def route(
        self,
        *,
        explicit_target: str | None,
        target_candidates: Iterable[str] = (),
        authority: Authority,
    ) -> RouteDecision:
        candidates = tuple(dict.fromkeys(c for c in target_candidates if c))

        if explicit_target:
            if explicit_target not in authority.allowed_projects:
                return RouteDecision(
                    status=RouteStatus.BLOCKED,
                    target_domain=None,
                    reason="target_not_authorized",
                    candidates=candidates,
                )
            return RouteDecision(
                status=RouteStatus.ROUTED,
                target_domain=explicit_target,
                reason="explicit_authorized_target",
                candidates=candidates,
            )

        authorized_candidates = tuple(c for c in candidates if c in authority.allowed_projects)
        if len(candidates) > 1:
            return RouteDecision(
                status=RouteStatus.AMBIGUOUS,
                target_domain=None,
                reason="multiple_plausible_targets_no_explicit_target",
                candidates=candidates,
            )
        if len(candidates) == 1:
            candidate = candidates[0]
            if candidate not in authority.allowed_projects:
                return RouteDecision(
                    status=RouteStatus.BLOCKED,
                    target_domain=None,
                    reason="single_candidate_not_authorized",
                    candidates=candidates,
                )
            return RouteDecision(
                status=RouteStatus.ROUTED,
                target_domain=candidate,
                reason="single_authorized_candidate",
                candidates=candidates,
            )
        if authorized_candidates:
            raise AssertionError("unreachable")
        return RouteDecision(
            status=RouteStatus.UNROUTED,
            target_domain=None,
            reason="no_target_evidence",
            candidates=candidates,
        )

    def new_record(
        self,
        *,
        source_ref: str,
        subject: str,
        target_domain: str,
        knowledge_type: KnowledgeType,
        epistemic_status: EpistemicStatus,
        confidence: float,
        sensitivity: Sensitivity,
        purpose: str,
        content: str,
        authority: Authority,
        relations: Iterable[str] = (),
        predecessor_id: str | None = None,
        observed_at: str | None = None,
    ) -> KnowledgeRecord:
        if target_domain not in authority.allowed_projects:
            raise GovernanceError("write_blocked_target_not_authorized")
        if purpose not in authority.allowed_purposes:
            raise GovernanceError("write_blocked_purpose_not_authorized")
        if _SENSITIVITY_RANK[sensitivity] > _SENSITIVITY_RANK[authority.sensitivity_clearance]:
            raise GovernanceError("write_blocked_sensitivity_clearance")
        if epistemic_status == EpistemicStatus.VERIFIED and not authority.can_verify:
            raise GovernanceError("status_elevation_requires_verify_authority")
        if epistemic_status in {EpistemicStatus.SUPERSEDED, EpistemicStatus.CONFLICTING}:
            raise GovernanceError("internal_epistemic_status_cannot_be_claimed_on_ingest")
        if knowledge_type == KnowledgeType.CORRECTION and not predecessor_id:
            raise GovernanceError("correction_requires_predecessor")
        if knowledge_type == KnowledgeType.CORRECTION and not authority.can_correct:
            raise GovernanceError("correction_requires_authority")

        record = KnowledgeRecord(
            record_id=str(uuid4()),
            source_ref=source_ref,
            observed_at=observed_at or datetime.now(timezone.utc).isoformat(),
            subject=subject,
            target_domain=target_domain,
            knowledge_type=knowledge_type,
            epistemic_status=epistemic_status,
            confidence=float(confidence),
            sensitivity=sensitivity,
            purpose=purpose,
            content=content,
            relations=tuple(relations),
            predecessor_id=predecessor_id,
            created_by=authority.actor_id,
        )
        return record

    def write(self, record: KnowledgeRecord, *, authority: Authority) -> KnowledgeRecord:
        self._pre_write_policy(record, authority)

        if record.knowledge_type == KnowledgeType.CORRECTION:
            return self._write_correction(record, authority=authority)

        conflicting_ids = [
            existing.record_id
            for existing in self._records.values()
            if existing.target_domain == record.target_domain
            and existing.subject == record.subject
            and existing.content != record.content
            and existing.knowledge_type != KnowledgeType.CORRECTION
            and existing.epistemic_status
            not in {EpistemicStatus.SUPERSEDED}
        ]

        if conflicting_ids:
            for record_id in conflicting_ids:
                existing = self._records[record_id]
                if existing.epistemic_status != EpistemicStatus.CONFLICTING:
                    self._records[record_id] = replace(
                        existing, epistemic_status=EpistemicStatus.CONFLICTING
                    )
            stored = replace(record, epistemic_status=EpistemicStatus.CONFLICTING)
            self._records[stored.record_id] = stored
            self._history.append(
                {
                    "event": "conflict_detected",
                    "record_id": stored.record_id,
                    "conflicts_with": tuple(conflicting_ids),
                    "actor_id": authority.actor_id,
                }
            )
            return stored

        self._records[record.record_id] = record
        self._history.append(
            {
                "event": "written",
                "record_id": record.record_id,
                "actor_id": authority.actor_id,
                "epistemic_status": record.epistemic_status.value,
                "knowledge_type": record.knowledge_type.value,
            }
        )
        return record

    def read(self, record_id: str, *, authority: Authority) -> ReadDecision:
        record = self._records.get(record_id)
        if record is None:
            return ReadDecision(False, "NOT_FOUND", "not_found", None)

        if record.target_domain not in authority.allowed_projects:
            return ReadDecision(False, "BLOCKED", "policy_denied", None)
        if record.purpose not in authority.allowed_purposes:
            return ReadDecision(False, "BLOCKED", "policy_denied", None)
        if _SENSITIVITY_RANK[record.sensitivity] > _SENSITIVITY_RANK[authority.sensitivity_clearance]:
            return ReadDecision(False, "BLOCKED", "policy_denied", None)

        # Retrieval is deliberately side-effect free: no type/status promotion.
        return ReadDecision(True, "ALLOWED", "policy_allowed", record)

    def get_internal(self, record_id: str) -> KnowledgeRecord:
        return self._records[record_id]

    def list_internal(self) -> tuple[KnowledgeRecord, ...]:
        return tuple(self._records.values())

    def verify(self, record_id: str, *, authority: Authority) -> KnowledgeRecord:
        if not authority.can_verify:
            raise GovernanceError("verify_requires_authority")
        existing = self._records[record_id]
        if existing.target_domain not in authority.allowed_projects:
            raise GovernanceError("verify_blocked_target_not_authorized")
        updated = replace(existing, epistemic_status=EpistemicStatus.VERIFIED)
        self._records[record_id] = updated
        self._history.append(
            {"event": "verified", "record_id": record_id, "actor_id": authority.actor_id}
        )
        return updated

    def promote_idea_to_decision(self, record_id: str, *, authority: Authority) -> KnowledgeRecord:
        if not authority.can_promote_decision:
            raise GovernanceError("decision_promotion_requires_authority")
        existing = self._records[record_id]
        if existing.knowledge_type != KnowledgeType.IDEA:
            raise GovernanceError("only_idea_can_use_decision_promotion")
        updated = replace(existing, knowledge_type=KnowledgeType.DECISION)
        self._records[record_id] = updated
        self._history.append(
            {
                "event": "knowledge_type_promoted",
                "record_id": record_id,
                "from": KnowledgeType.IDEA.value,
                "to": KnowledgeType.DECISION.value,
                "actor_id": authority.actor_id,
            }
        )
        return updated

    def _pre_write_policy(self, record: KnowledgeRecord, authority: Authority) -> None:
        if record.target_domain not in authority.allowed_projects:
            raise GovernanceError("write_blocked_target_not_authorized")
        if record.purpose not in authority.allowed_purposes:
            raise GovernanceError("write_blocked_purpose_not_authorized")
        if _SENSITIVITY_RANK[record.sensitivity] > _SENSITIVITY_RANK[authority.sensitivity_clearance]:
            raise GovernanceError("write_blocked_sensitivity_clearance")
        if record.epistemic_status == EpistemicStatus.VERIFIED and not authority.can_verify:
            raise GovernanceError("status_elevation_requires_verify_authority")
        if record.knowledge_type == KnowledgeType.CORRECTION and not authority.can_correct:
            raise GovernanceError("correction_requires_authority")

    def _write_correction(self, record: KnowledgeRecord, *, authority: Authority) -> KnowledgeRecord:
        if not record.predecessor_id or record.predecessor_id not in self._records:
            raise GovernanceError("correction_predecessor_missing")
        old = self._records[record.predecessor_id]
        if old.target_domain != record.target_domain or old.subject != record.subject:
            raise GovernanceError("correction_predecessor_scope_mismatch")

        self._records[old.record_id] = replace(
            old, epistemic_status=EpistemicStatus.SUPERSEDED
        )
        self._records[record.record_id] = record
        self._history.append(
            {
                "event": "corrected",
                "predecessor_id": old.record_id,
                "successor_id": record.record_id,
                "actor_id": authority.actor_id,
                "source_ref": record.source_ref,
            }
        )
        return record
