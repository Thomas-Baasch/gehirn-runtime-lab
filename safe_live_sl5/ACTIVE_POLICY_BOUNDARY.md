# SAFE-LIVE SL5-01 ACTIVE POLICY BOUNDARY

Status: ACTIVATION PREPARED FROM OWNER AUTHORITY 2026-08-25

This file defines only the narrow recurring action authority for SAFE_LIVE_SL5_01_MATERIAL_MILESTONE_LOGGING.

Allowed effect:
- exactly one ISSUE_COMMENT on Thomas-Baasch/gehirn-runtime-lab Issue #42 per unique material Safe-Live milestone_key.

Required before every effect:
- policy status ACTIVE and not expired;
- exact repository, issue number, title and open state;
- current canonical evidence for a genuinely material Safe-Live main milestone;
- no current conflict/unknown on the claimed milestone;
- milestone_key not already present;
- deterministic fixed template only;
- commit-time re-read immediately before posting;
- post-commit readback immediately after posting.

Always forbidden:
- comments for minor progress, green subtests, retries or repair chatter;
- free-form/speculative status claims;
- Issue close/body/label/assignee changes;
- PR, merge, code, policy, send, pay, delete, contract or rights effects;
- sensitive/personal/business data;
- authority inheritance to another issue, role or action class.

Kill switch:
- any target drift, duplicate ambiguity, stale/conflicting canon, uncertain commit outcome, policy expiry or unexpected effect pauses the policy fail-closed.

Bootstrap rule:
- activation of this policy itself does not auto-create a milestone comment. The first recurring effect may occur only on a later newly completed qualifying material milestone.

Initial review-by: 2026-09-01. After that date the policy must pause unless explicitly renewed or revalidated under the same boundaries.
