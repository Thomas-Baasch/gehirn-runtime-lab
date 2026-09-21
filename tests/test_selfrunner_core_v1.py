import unittest

from selfrunner_core import (
    ActionUnit,
    CommunicationEvent,
    Decision,
    EffectClass,
    PathMode,
    SelfRunnerGateway,
    SourceBinding,
    SourceClass,
)


def gateway() -> SelfRunnerGateway:
    return SelfRunnerGateway(
        [
            SourceBinding(
                alias="mail_in",
                tenant_id="TENANT_A",
                source_class=SourceClass.CUSTOMER_LOCAL,
                capabilities=frozenset({"communication.review"}),
                evidence_roles=frozenset({"MAIL_INBOUND"}),
            ),
            SourceBinding(
                alias="mail_sent",
                tenant_id="TENANT_A",
                source_class=SourceClass.CUSTOMER_LOCAL,
                capabilities=frozenset({"communication.review"}),
                evidence_roles=frozenset({"MAIL_SENT"}),
            ),
            SourceBinding(
                alias="calendar",
                tenant_id="TENANT_A",
                source_class=SourceClass.CUSTOMER_LOCAL,
                capabilities=frozenset({"calendar.status"}),
                evidence_roles=frozenset({"CALENDAR_CURRENT"}),
            ),
            SourceBinding(
                alias="provider_core",
                tenant_id="TENANT_A",
                source_class=SourceClass.CORE_SECRET,
                capabilities=frozenset({"communication.review"}),
                evidence_roles=frozenset({"MAIL_SENT"}),
            ),
            SourceBinding(
                alias="tenant_b_mail",
                tenant_id="TENANT_B",
                source_class=SourceClass.CUSTOMER_LOCAL,
                capabilities=frozenset({"communication.review"}),
                evidence_roles=frozenset({"MAIL_SENT"}),
            ),
        ]
    )


class SelfRunnerCoreV1Tests(unittest.TestCase):
    def test_simple_conversation_uses_fast_path_and_zero_sources(self):
        gw = gateway()
        self.assertEqual(gw.choose_path(), PathMode.FAST)
        decision, handles, trace, reason = gw.plan_sources(
            tenant_id="TENANT_A",
            capability="conversation",
            candidate_aliases=[],
        )
        self.assertEqual(decision, Decision.ALLOW)
        self.assertEqual(handles, [])
        self.assertEqual(reason, "COMPLETE")
        self.assertEqual(trace.control_steps, ["NO_SOURCE_NEEDED"])

    def test_email_request_binds_outcome_not_literal_inbox_action(self):
        gw = gateway()
        contract = gw.create_outcome_contract(
            user_goal="Schau dir mal meine E-Mails an",
            capability="communication.review",
        )
        self.assertEqual(contract.capability, "communication.review")
        roles = set().union(*contract.required_evidence_roles)
        self.assertEqual(roles, {"MAIL_INBOUND", "MAIL_SENT"})
        self.assertEqual(contract.complete_when, "REQUIRED_EVIDENCE_COMPLETE")

    def test_public_manifest_updates_without_shipping_provider_core(self):
        gw = SelfRunnerGateway(
            gateway().bindings.values(),
            product_version="provider-core-v1.1",
            policy_version="policy-v2",
        )
        manifest = gw.public_manifest()
        self.assertEqual(manifest.protocol_version, "selfrunner-client-v1")
        self.assertEqual(manifest.product_version, "provider-core-v1.1")
        self.assertEqual(manifest.policy_version, "policy-v2")
        self.assertIn("communication.review", manifest.capabilities)
        self.assertFalse(hasattr(manifest, "bindings"))

    def test_deep_path_only_on_material_trigger(self):
        gw = gateway()
        self.assertEqual(gw.choose_path(high_risk=True), PathMode.DEEP)
        self.assertEqual(gw.choose_path(repeated_failure=True), PathMode.DEEP)

    def test_mail_review_requires_inbound_and_sent(self):
        gw = gateway()
        decision, handles, trace, reason = gw.plan_sources(
            tenant_id="TENANT_A",
            capability="communication.review",
            candidate_aliases=["mail_in", "mail_sent"],
        )
        self.assertEqual(decision, Decision.ALLOW)
        self.assertEqual(reason, "COMPLETE")
        self.assertEqual(len(handles), 2)
        self.assertLessEqual(len(trace.control_steps), 3)

    def test_inbox_only_is_hold_not_false_complete(self):
        gw = gateway()
        decision, handles, _trace, reason = gw.plan_sources(
            tenant_id="TENANT_A",
            capability="communication.review",
            candidate_aliases=["mail_in"],
        )
        self.assertEqual(decision, Decision.HOLD)
        self.assertEqual(len(handles), 1)
        self.assertIn("MAIL_SENT", reason)

    def test_forbidden_source_candidates_do_not_consume_mail_evidence_budget(self):
        gw = gateway()
        decision, handles, trace, reason = gw.plan_sources(
            tenant_id="TENANT_A",
            capability="communication.review",
            candidate_aliases=["provider_core", "tenant_b_mail", "mail_in", "mail_sent"],
        )
        self.assertEqual(decision, Decision.ALLOW)
        self.assertEqual(reason, "COMPLETE")
        self.assertEqual([h.alias for h in handles], ["mail_in", "mail_sent"])
        self.assertIn("AUTH:provider_core:DENY", trace.control_steps)
        self.assertIn("AUTH:tenant_b_mail:DENY", trace.control_steps)

    def test_provider_core_is_zero_read_denied(self):
        gw = gateway()
        result = gw.authorize_source(
            tenant_id="TENANT_A",
            capability="communication.review",
            alias="provider_core",
        )
        self.assertEqual(result.decision, Decision.DENY)
        self.assertEqual(result.reason, "PROVIDER_CORE_ZERO_READ_DENY")
        self.assertEqual(result.provider_content_reads, 0)

    def test_cross_tenant_is_zero_read_denied(self):
        gw = gateway()
        result = gw.authorize_source(
            tenant_id="TENANT_A",
            capability="communication.review",
            alias="tenant_b_mail",
        )
        self.assertEqual(result.decision, Decision.DENY)
        self.assertEqual(result.reason, "CROSS_TENANT_ZERO_READ_DENY")
        self.assertEqual(result.provider_content_reads, 0)

    def test_sent_access_missing_yields_unknown(self):
        state = SelfRunnerGateway.reconcile_communication(
            [],
            sent_access_complete=False,
            inbound_access_complete=True,
        )
        self.assertFalse(state.complete)
        self.assertEqual(state.status, "UNKNOWN")
        self.assertEqual(state.reason, "SENT_HISTORY_NOT_VERIFIED")

    def test_later_inbound_after_latest_outbound_is_detected(self):
        events = [
            CommunicationEvent(
                "INBOUND", "2026-09-21T08:00:00+02:00", "a@example.com", "CASE1", "m1"
            ),
            CommunicationEvent(
                "OUTBOUND", "2026-09-21T09:00:00+02:00", "a@example.com", "CASE1", "m2"
            ),
            CommunicationEvent(
                "INBOUND", "2026-09-21T10:00:00+02:00", "a@example.com", "CASE1", "m3"
            ),
        ]
        state = SelfRunnerGateway.reconcile_communication(
            events,
            sent_access_complete=True,
            inbound_access_complete=True,
        )
        self.assertTrue(state.complete)
        self.assertEqual(state.status, "REPLIED_AFTER_OUTBOUND")
        self.assertEqual(state.latest_outbound.message_id, "m2")
        self.assertEqual(state.later_inbound.message_id, "m3")

    def test_duplicate_semantic_send_is_denied(self):
        action = ActionUnit(
            tenant_id="TENANT_A",
            action_type="EMAIL_SEND",
            recipient="a@example.com",
            semantic_key="CASE1:FOLLOWUP1",
            body="Hallo",
        )
        decision = SelfRunnerGateway.decide_action(
            action,
            approved_hash=action.content_hash(),
            prior_sent_semantic_keys={"CASE1:FOLLOWUP1"},
            effect=EffectClass.PROTECTED_EXTERNAL,
        )
        self.assertEqual(decision.decision, Decision.DENY)
        self.assertEqual(decision.reason, "DUPLICATE_SEMANTIC_ACTION")

    def test_protected_effect_requires_exact_action_approval(self):
        action = ActionUnit(
            tenant_id="TENANT_A",
            action_type="EMAIL_SEND",
            recipient="a@example.com",
            semantic_key="CASE2:FOLLOWUP1",
            body="Hallo",
        )
        hold = SelfRunnerGateway.decide_action(
            action,
            approved_hash=None,
            prior_sent_semantic_keys=set(),
            effect=EffectClass.PROTECTED_EXTERNAL,
        )
        self.assertEqual(hold.decision, Decision.HOLD)

        allow = SelfRunnerGateway.decide_action(
            action,
            approved_hash=action.content_hash(),
            prior_sent_semantic_keys=set(),
            effect=EffectClass.PROTECTED_EXTERNAL,
        )
        self.assertEqual(allow.decision, Decision.ALLOW)


if __name__ == "__main__":
    unittest.main()
