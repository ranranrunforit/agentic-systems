"""Toggles and degraded mode: the verification points from SOLUTION.md, executed.

"Flipping the AI toggle off at global, tenant, and feature scope each leaves the
product in the defined degraded mode, and each flip is audited; an unreachable flag
service results in AI off."
"""
from __future__ import annotations

import unittest

from cara.fixtures import MERIDIAN, NORTHWIND, build_env
from cara.flags import FlagServiceUnavailable
from cara.models import RiskTier
from cara.pipeline import Request

USER = "SYN-USR-4471"
ADA = "SYN-MRN-000123"


def qa(env, cap="qa.record", q="what was the last a1c", subject=ADA):
    return env.pipeline.handle(Request(USER, NORTHWIND, cap, q, subject))


class TestToggleScopes(unittest.TestCase):

    def test_each_scope_produces_degraded_mode(self):
        for scope, kwargs in [
            ("global_kill", {}),
            ("global", {"feature": "qa.record"}),
            ("tenant", {"tenant": NORTHWIND}),
            ("feature", {"tenant": NORTHWIND, "feature": "qa.record"}),
            ("subject", {"subject": ADA}),
        ]:
            with self.subTest(scope=scope):
                env = build_env()
                env.flags_service.set(False, scope=scope, reason_code="INCIDENT", **kwargs)
                out = qa(env)
                self.assertEqual(out.decision, "degraded")
                self.assertEqual(out.detail["mode"], "structured_record_view")
                # The product stays up: the deterministic path still returns the data.
                self.assertIn("problems", out.detail["content"])

    def test_every_flip_is_audited_with_actor_scope_and_reason(self):
        env = build_env()
        env.flags_service.set(False, scope="feature", tenant=NORTHWIND,
                              feature="draft.summary", actor="SYN-USR-9001",
                              reason_code="INCIDENT", reason_text="INCIDENT-1042")
        ev = env.ledger.query(action="toggle.changed")[-1]
        self.assertEqual(ev["scope"], "feature")
        self.assertEqual(ev["scope_tenant"], NORTHWIND)
        self.assertEqual(ev["previous_state"], "on")
        self.assertEqual(ev["state"], "off")
        self.assertEqual(ev["actor_id"], "SYN-USR-9001")
        self.assertEqual(ev["reason_code"], "INCIDENT")

    def test_reason_code_is_mandatory(self):
        env = build_env()
        with self.assertRaises(ValueError):
            env.flags_service.set(False, scope="tenant", tenant=NORTHWIND,
                                  reason_code="BECAUSE_I_SAID_SO")

    def test_unknown_flag_means_off_not_default_on(self):
        env = build_env()
        env.flags_service.delete_flag(NORTHWIND, "qa.record")
        res = env.flags.resolve(NORTHWIND, "qa.record", ADA)
        self.assertFalse(res.enabled)
        self.assertEqual(res.cause, "UNKNOWN_FLAG_FEATURE")

    def test_no_scope_can_re_enable_over_another(self):
        env = build_env()
        env.flags_service.set(False, scope="feature", tenant=NORTHWIND,
                              feature="qa.record", reason_code="QUALITY")
        env.flags_service.set(True, scope="global", feature="qa.record", reason_code="TEST")
        env.flags_service.set(True, scope="tenant", tenant=NORTHWIND, reason_code="TEST")
        self.assertFalse(env.flags.resolve(NORTHWIND, "qa.record", ADA).enabled)

    def test_toggle_is_evaluated_server_side_on_the_request_path(self):
        """Not a UI hide: the endpoint itself refuses to run the AI path."""
        env = build_env()
        env.flags_service.set(False, scope="tenant", tenant=NORTHWIND, reason_code="INCIDENT")
        env.pipeline.generator = lambda r, p: (_ for _ in ()).throw(
            AssertionError("the model must never be called when AI is off"))
        out = qa(env)
        self.assertEqual(out.decision, "degraded")

    def test_queued_tier3_items_are_held_not_auto_released(self):
        """The toggle stops AI PROCESSING, not human decisions already pending."""
        env = build_env()
        out = env.pipeline.handle(Request(USER, NORTHWIND, "draft.summary",
                                          "draft referral letter", ADA))
        self.assertEqual(out.decision, "queued")
        env.flags_service.set(False, scope="tenant", tenant=NORTHWIND, reason_code="INCIDENT")
        held = env.queue.hold_for_toggle(NORTHWIND)
        self.assertEqual(len(held), 1)
        self.assertTrue(held[0].held_by_toggle)
        self.assertEqual(held[0].state, "queued")  # not released, not dropped
        self.assertTrue(env.ledger.query(action="queue.held"))
        # A human may still approve text a human can read.
        env.queue.approve(held[0].item_id, USER, dwell_ms=120000)
        self.assertEqual(held[0].state, "approved")

    def test_degraded_volume_is_measurable_not_just_the_flip(self):
        env = build_env()
        env.flags_service.set(False, scope="tenant", tenant=NORTHWIND, reason_code="INCIDENT")
        for _ in range(3):
            qa(env)
        self.assertEqual(len(env.ledger.query(action="degraded.served")), 3)

    def test_no_ai_component_is_load_bearing_for_the_degraded_path(self):
        """The CI journey suite from toggles/degraded-mode.md §6, in miniature."""
        env = build_env()
        env.flags_service.set(False, scope="global_kill", reason_code="INCIDENT")
        env.corpus.available = False          # grounding stubbed out
        env.pipeline.generator = None         # model stubbed out entirely
        for cap, q, subj in [("qa.record", "last a1c", ADA),
                             ("draft.summary", "draft", ADA),
                             ("qa.general", "no-show policy", None)]:
            with self.subTest(capability=cap):
                out = env.pipeline.handle(Request(USER, NORTHWIND, cap, q, subj))
                self.assertEqual(out.decision, "degraded")


class TestAuditChain(unittest.TestCase):

    def test_chain_verifies_and_anchors_match(self):
        env = build_env()
        qa(env)
        env.ledger.anchor("2026-08-13")
        result = env.ledger.verify()
        self.assertTrue(result["chain_ok"])
        self.assertEqual(result["deferred_writes_pending"], 0)

    def test_tampering_with_an_entry_is_detected(self):
        env = build_env()
        qa(env)
        env.ledger._entries[2]["reason_code"] = "TAMPERED"
        result = env.ledger.verify()
        self.assertFalse(result["chain_ok"])
        self.assertEqual(result["cause"], "HASH_MISMATCH")
        self.assertEqual(result["first_bad_seq"], 2)

    def test_removing_an_entry_is_detected(self):
        """Tamper evidence is mostly about REMOVAL -- convenient forgetting is the
        likelier failure than alteration."""
        env = build_env()
        qa(env)
        del env.ledger._entries[3]
        self.assertFalse(env.ledger.verify()["chain_ok"])

    def test_ledger_has_no_update_or_delete_verb(self):
        env = build_env()
        for verb in ("update", "delete", "edit", "remove", "truncate"):
            self.assertFalse(hasattr(env.ledger, verb), f"ledger exposes {verb}()")

    def test_who_what_when_why_and_inputs_are_all_captured(self):
        env = build_env()
        out = env.pipeline.handle(Request(USER, NORTHWIND, "draft.summary",
                                          "draft referral letter", ADA))
        events = env.ledger.reconstruct(out.correlation_id)
        actions = [e["action"] for e in events]
        for expected in ("authn.success", "policy.allow", "minimization.applied",
                         "risk.classified", "grounding.result", "approval.queued"):
            self.assertIn(expected, actions)

        policy_ev = next(e for e in events if e["action"] == "policy.allow")
        self.assertIn("actor_id", policy_ev)          # who
        self.assertIn("capability", policy_ev)        # what
        self.assertIn("ts", policy_ev)                # when
        self.assertIn("reason_code", policy_ev)       # why
        self.assertIn("flags_snapshot", policy_ev)    # inputs: flag state at decision time

        minim = next(e for e in events if e["action"] == "minimization.applied")
        self.assertIn("prompt_hash", minim)           # inputs: the prompt, by hash
        self.assertIn("fields_included", minim)       # inputs: what crossed the boundary

        risk_ev = next(e for e in events if e["action"] == "risk.classified")
        self.assertIn("accountable_role", risk_ev)    # named human ownership

    def test_accountability_is_recorded_even_for_auto_flowed_output(self):
        """Auto-flow is not unowned; it is owned in advance by whoever set the policy."""
        env = build_env()
        out = env.pipeline.handle(Request(USER, NORTHWIND, "qa.general",
                                          "no-show policy", None))
        self.assertEqual(out.decision, "released")
        self.assertIs(out.tier, RiskTier.T1)
        released = env.ledger.query(action="output.released")[-1]
        self.assertEqual(released["accountable_role"], "tenant_operations_manager")

    def test_accounting_of_disclosures_query(self):
        env = build_env()
        out = env.pipeline.handle(Request(USER, NORTHWIND, "draft.summary",
                                          "draft referral letter", ADA))
        env.queue.approve(out.detail["item_id"], USER, dwell_ms=184000)
        env.pipeline.release_approved(out.detail["item_id"])
        disclosures = env.ledger.disclosures_by_subject(ADA)
        self.assertEqual(len(disclosures), 1)
        self.assertEqual(disclosures[0]["action"], "output.released")

    def test_deletion_leaves_the_chain_verifiable(self):
        """The retention paradox resolved: content goes, the chain still verifies,
        the FACT of each decision survives."""
        env = build_env()
        out = env.pipeline.handle(Request(USER, NORTHWIND, "qa.record",
                                          "what was the last a1c", ADA))
        self.assertTrue(env.records.delete(NORTHWIND, ADA))
        env.ledger.append("deletion.executed", subject_ref=ADA, scope="all",
                          method="hard_delete+crypto_shred", verified_at="2026-08-13",
                          actor_id="SYN-USR-9001")
        self.assertTrue(env.ledger.verify()["chain_ok"])
        self.assertTrue(env.ledger.reconstruct(out.correlation_id))  # decision survives
        self.assertIsNone(env.records.get(NORTHWIND, ADA))          # content is gone

    def test_withdrawn_source_flags_dependent_prior_outputs(self):
        env = build_env()
        env.pipeline.handle(Request(USER, NORTHWIND, "draft.summary",
                                    "draft referral letter", ADA))
        env.corpus.withdraw("SYN-VS-CLIN-002")
        affected = env.corpus.citing_outputs(env.ledger, "SYN-VS-CLIN-002")
        self.assertTrue(affected, "a withdrawal must surface the outputs that cited it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
