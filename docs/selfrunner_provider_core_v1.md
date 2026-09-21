# SelfRunner Provider Core V1 — lab implementation

This branch implements the smallest real control seam derived from the GEN7 failures.

## Why this exists

GEN7 showed that a static client bootstrap can improve isolation while losing provider-side capability. The solution is not a larger client prompt. It is a thin customer shell backed by a provider-controlled capability gateway.

## Architecture

Customer UI -> Capability Gateway -> Tenant/Authority check -> purpose-bounded source handles -> provider core -> egress/action gate -> customer UI.

The customer project never receives the provider method core. The gateway decides access before content retrieval.

## Speed

The fast path is the default. Simple conversation uses zero source reads and one control step. A capability loads only its minimum evidence roles. Deep evaluation is triggered only by material risk or ambiguity.

## Quality

Capabilities define completion, not just tools. Example: communication review is incomplete until the relevant inbound and sent sides are available. An inbox-only read therefore cannot produce a confident “not answered” conclusion.

## Security

Cross-tenant and provider-core source attempts are denied before provider content read. Protected external effects use an immutable action unit, exact approval hash, and semantic duplicate check.

## Scope

Synthetic lab only. No customer data, secrets, provider calls or live effects. This branch proves the runtime contract and regression tests; it is not a production deployment.
