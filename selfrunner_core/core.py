from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import FrozenSet, Iterable, Sequence
import json


class Decision(str, Enum):
    ALLOW = "ALLOW"
    HOLD = "HOLD"
    DENY = "DENY"


class PathMode(str, Enum):
    FAST = "FAST"
    DEEP = "DEEP"


class EffectClass(str, Enum):
    READ = "READ"
    SAFE_INTERNAL = "SAFE_INTERNAL"
    PROTECTED_EXTERNAL = "PROTECTED_EXTERNAL"


class SourceClass(str, Enum):
    CUSTOMER_LOCAL = "CUSTOMER_LOCAL"
    PROVIDER_CONFIDENTIAL = "PROVIDER_CONFIDENTIAL"
    CORE_SECRET = "CORE_SECRET"


@dataclass(frozen=True)
class SourceBinding:
    alias: str
    tenant_id: str
    source_class: SourceClass
    capabilities: FrozenSet[str]
    evidence_roles: FrozenSet[str]
    current: bool = True
    integrity_ok: bool = True


@dataclass(frozen=True)
class BoundSourceHandle:
    alias: str
    tenant_id: str
    capability: str
    evidence_roles: FrozenSet[str]


@dataclass(frozen=True)
class AuthorizationResult:
    decision: Decision
    reason: str
    handle: BoundSourceHandle | None = None
    provider_content_reads: int = 0


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    required_evidence_roles: tuple[FrozenSet[str], ...] = ()
    max_source_handles: int = 4


@dataclass
class RequestTrace:
    mode: PathMode
    control_steps: list[str] = field(default_factory=list)
    provider_content_reads: int = 0


@dataclass(frozen=True)
class CommunicationEvent:
    direction: str
    timestamp: str
    participant: str
    semantic_key: str
    message_id: str


@dataclass(frozen=True)
class CommunicationState:
    complete: bool
    status: str
    latest_outbound: CommunicationEvent | None
    later_inbound: CommunicationEvent | None
    reason: str


@dataclass(frozen=True)
class ActionUnit:
    tenant_id: str
    action_type: str
    recipient: str
    semantic_key: str
    body: str
    attachments: tuple[str, ...] = ()

    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "tenant": self.tenant_id,
                "type": self.action_type,
                "recipient": self.recipient,
                "semantic_key": self.semantic_key,
                "body": self.body,
                "attachments": self.attachments,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return sha256(payload).hexdigest()


@dataclass(frozen=True)
class ActionDecision:
    decision: Decision
    reason: str
    idempotency_key: str
    requires_human_approval: bool


@dataclass(frozen=True)
class PublicManifest:
    protocol_version: str
    product_version: str
    policy_version: str
    capabilities: tuple[str, ...]


class SelfRunnerGateway:
    """Small provider-side contract surface for a future SelfRunner runtime.

    This lab implementation intentionally contains no customer data, credentials,
    provider calls, model prompts, or live action execution. It proves the
    control seam only: outcome-aware source completeness, pre-retrieval scope,
    fast/deep routing, and send-once action gating.
    """

    def __init__(
        self,
        bindings: Sequence[SourceBinding],
        *,
        product_version: str = "provider-core-v1",
        policy_version: str = "policy-v1",
    ):
        self.bindings = {b.alias: b for b in bindings}
        self.product_version = product_version
        self.policy_version = policy_version
        self.capabilities = {
            "conversation": CapabilitySpec("conversation"),
            "communication.review": CapabilitySpec(
                "communication.review",
                required_evidence_roles=(
                    frozenset({"MAIL_INBOUND"}),
                    frozenset({"MAIL_SENT"}),
                ),
                max_source_handles=2,
            ),
            "calendar.status": CapabilitySpec(
                "calendar.status",
                required_evidence_roles=(frozenset({"CALENDAR_CURRENT"}),),
                max_source_handles=1,
            ),
            "document.decision": CapabilitySpec(
                "document.decision",
                required_evidence_roles=(frozenset({"DOCUMENT_CURRENT"}),),
                max_source_handles=1,
            ),
        }

    def public_manifest(self) -> PublicManifest:
        """Return only client-safe version/capability metadata.

        A stable client shell can fetch this at session start, so capability and
        policy updates do not require copying provider logic into the customer
        project.
        """
        return PublicManifest(
            protocol_version="selfrunner-client-v1",
            product_version=self.product_version,
            policy_version=self.policy_version,
            capabilities=tuple(sorted(self.capabilities)),
        )

    @staticmethod
    def choose_path(
        *,
        material: bool = False,
        protected_effect: bool = False,
        high_risk: bool = False,
        conflicting_sources: bool = False,
        repeated_failure: bool = False,
    ) -> PathMode:
        return (
            PathMode.DEEP
            if any(
                (
                    material,
                    protected_effect,
                    high_risk,
                    conflicting_sources,
                    repeated_failure,
                )
            )
            else PathMode.FAST
        )

    def authorize_source(
        self, *, tenant_id: str, capability: str, alias: str
    ) -> AuthorizationResult:
        """Authorize before content retrieval.

        A DENY/HOLD result guarantees zero provider content reads at this layer.
        """
        binding = self.bindings.get(alias)
        if binding is None:
            return AuthorizationResult(Decision.HOLD, "SOURCE_UNBOUND")

        if binding.tenant_id != tenant_id:
            return AuthorizationResult(Decision.DENY, "CROSS_TENANT_ZERO_READ_DENY")

        if binding.source_class != SourceClass.CUSTOMER_LOCAL:
            return AuthorizationResult(Decision.DENY, "PROVIDER_CORE_ZERO_READ_DENY")

        if not binding.current:
            return AuthorizationResult(Decision.HOLD, "SOURCE_CURRENTNESS_UNKNOWN")

        if not binding.integrity_ok:
            return AuthorizationResult(Decision.HOLD, "SOURCE_INTEGRITY_HOLD")

        if capability not in binding.capabilities:
            return AuthorizationResult(
                Decision.DENY, "CAPABILITY_NOT_ALLOWED_FOR_SOURCE"
            )

        return AuthorizationResult(
            Decision.ALLOW,
            "BOUND_SOURCE_HANDLE",
            BoundSourceHandle(
                alias=binding.alias,
                tenant_id=binding.tenant_id,
                capability=capability,
                evidence_roles=binding.evidence_roles,
            ),
        )

    def plan_sources(
        self,
        *,
        tenant_id: str,
        capability: str,
        candidate_aliases: Sequence[str],
        deep: bool = False,
    ) -> tuple[Decision, list[BoundSourceHandle], RequestTrace, str]:
        """Choose the minimum complete source set for the capability."""
        spec = self.capabilities[capability]
        trace = RequestTrace(PathMode.DEEP if deep else PathMode.FAST)

        if capability == "conversation":
            trace.control_steps.append("NO_SOURCE_NEEDED")
            return Decision.ALLOW, [], trace, "COMPLETE"

        trace.control_steps.append("CAPABILITY_BOUND")
        handles: list[BoundSourceHandle] = []
        roles: set[str] = set()

        for alias in candidate_aliases:
            if len(handles) >= spec.max_source_handles:
                break
            result = self.authorize_source(
                tenant_id=tenant_id, capability=capability, alias=alias
            )
            trace.control_steps.append(
                f"AUTH:{alias}:{result.decision.value}"
            )
            if result.decision == Decision.ALLOW and result.handle:
                handles.append(result.handle)
                roles.update(result.handle.evidence_roles)

        missing = [
            "|".join(sorted(required))
            for required in spec.required_evidence_roles
            if not (roles & set(required))
        ]
        if missing:
            return (
                Decision.HOLD,
                handles,
                trace,
                "MISSING_EVIDENCE_ROLE:" + ",".join(missing),
            )

        return Decision.ALLOW, handles, trace, "COMPLETE"

    @staticmethod
    def reconcile_communication(
        events: Sequence[CommunicationEvent],
        *,
        sent_access_complete: bool,
        inbound_access_complete: bool,
    ) -> CommunicationState:
        """Reconcile the case, not just one inbox/thread."""
        if not sent_access_complete:
            return CommunicationState(
                False,
                "UNKNOWN",
                None,
                None,
                "SENT_HISTORY_NOT_VERIFIED",
            )
        if not inbound_access_complete:
            return CommunicationState(
                False,
                "UNKNOWN",
                None,
                None,
                "INBOUND_HISTORY_NOT_VERIFIED",
            )

        relevant = sorted(events, key=lambda event: event.timestamp)
        outbound = [event for event in relevant if event.direction == "OUTBOUND"]
        latest_outbound = outbound[-1] if outbound else None
        later_inbound = None

        if latest_outbound:
            for event in relevant:
                if (
                    event.direction == "INBOUND"
                    and event.timestamp > latest_outbound.timestamp
                ):
                    later_inbound = event

        if later_inbound:
            status = "REPLIED_AFTER_OUTBOUND"
        elif latest_outbound:
            status = "WAITING_FOR_REPLY"
        else:
            status = "NO_OUTBOUND_FOUND"

        return CommunicationState(
            True,
            status,
            latest_outbound,
            later_inbound,
            "COMPLETE",
        )

    @staticmethod
    def decide_action(
        action: ActionUnit,
        *,
        approved_hash: str | None,
        prior_sent_semantic_keys: Iterable[str],
        effect: EffectClass,
    ) -> ActionDecision:
        """Immutable action-unit + dedupe + human gate for protected effects."""
        key = action.content_hash()

        if action.semantic_key in set(prior_sent_semantic_keys):
            return ActionDecision(
                Decision.DENY,
                "DUPLICATE_SEMANTIC_ACTION",
                key,
                effect == EffectClass.PROTECTED_EXTERNAL,
            )

        if effect == EffectClass.PROTECTED_EXTERNAL and approved_hash != key:
            return ActionDecision(
                Decision.HOLD,
                "HUMAN_APPROVAL_REQUIRED_FOR_EXACT_ACTION_UNIT",
                key,
                True,
            )

        return ActionDecision(
            Decision.ALLOW,
            "ACTION_ALLOWED",
            key,
            effect == EffectClass.PROTECTED_EXTERNAL,
        )
