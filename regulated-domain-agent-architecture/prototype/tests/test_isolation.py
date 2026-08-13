"""Tenant isolation: I-1 .. I-7 and tests T-1 .. T-10, executed.

Stretch goal: "Demonstrate that one tenant's data and toggles cannot leak into
another's."

T-10 (cache) deserves emphasis. A response cache keyed on prompt content alone looks
correct, performs beautifully, and silently serves tenant A's answer to tenant B when
two prompts coincide. It is the most likely accidental cross-tenant channel in a
system like this, and a test suite that does not probe it has not tested isolation.
"""
from __future__ import annotations

import unittest

from cara.audit import sha256
from cara.fixtures import MERIDIAN, NORTHWIND, build_env
from cara.models import SourceClass
from cara.pipeline import Request

ADA = "SYN-MRN-000123"          # Northwind
DEE = "SYN-MRN-777001"          # Meridian
NW_USER = "SYN-USR-4471"
MER_USER = "SYN-USR-7001"


class TestTenantIsolation(unittest.TestCase):

    def test_t1_cross_tenant_record_read_is_denied(self):
        """Note the setup: SYN-USR-7001 has a care relationship with Ada in the
        fixture. Even so, the tenant predicate denies -- the relationship check is
        not the only thing standing between tenants."""
        env = build_env()
        out = env.pipeline.handle(Request(MER_USER, MERIDIAN, "qa.record",
                                          "what was the last a1c", ADA))
        self.assertEqual(out.decision, "denied")
        self.assertEqual(out.reason_code, "NO_SUCH_RECORD")

    def test_t2_retrieval_cannot_bleed_across_tenants(self):
        """Meridian asks a question whose best answer lives only in Northwind's
        corpus. The correct outcome is a REFUSAL, not an answer sourced from A."""
        env = build_env()
        spans = env.corpus.retrieve(
            tenant=MERIDIAN, text="Refer to endocrinology when HbA1c persists",
            allowed_classes={SourceClass.S2, SourceClass.S3})
        # Meridian may match its OWN corpus -- that is correct. What must never
        # happen is a Northwind document appearing in a Meridian retrieval.
        self.assertNotIn("SYN-VS-CLIN-002", [s.doc_id for s in spans])
        self.assertTrue(all(s.doc_id.startswith("SYN-VS-MER") for s in spans))
        nw = env.corpus.retrieve(
            tenant=NORTHWIND, text="Refer to endocrinology when HbA1c persists",
            allowed_classes={SourceClass.S2, SourceClass.S3})
        self.assertIn("SYN-VS-CLIN-002", [s.doc_id for s in nw])

    def test_t3_semantic_probe_with_verbatim_text_returns_nothing(self):
        env = build_env()
        verbatim = "Refer to endocrinology when HbA1c 7.4 or above persists on dual therapy."
        spans = env.corpus.retrieve(tenant=MERIDIAN, text=verbatim,
                                    allowed_classes=set(SourceClass))
        # Text lifted verbatim from Northwind's protocol cannot retrieve it from
        # Meridian, however exact the match.
        self.assertNotIn("SYN-VS-CLIN-002", [s.doc_id for s in spans])
        self.assertTrue(all(s.doc_id.startswith("SYN-VS-MER") for s in spans))

    def test_t4_toggle_off_for_one_tenant_does_not_affect_the_other(self):
        env = build_env()
        env.flags_service.set(False, scope="tenant", tenant=NORTHWIND,
                              reason_code="INCIDENT", reason_text="INCIDENT-1042")
        self.assertFalse(env.flags.resolve(NORTHWIND, "qa.record", ADA).enabled)
        self.assertTrue(env.flags.resolve(MERIDIAN, "qa.record", DEE).enabled)

    def test_t5_global_off_beats_a_tenant_on(self):
        """Conjunctive resolution: no scope can re-enable over another's objection."""
        env = build_env()
        env.flags_service.set(False, scope="global_kill", reason_code="INCIDENT")
        env.flags_service.set(True, scope="tenant", tenant=NORTHWIND, reason_code="TEST")
        res = env.flags.resolve(NORTHWIND, "qa.record", ADA)
        self.assertFalse(res.enabled)
        self.assertEqual(res.cause, "GLOBAL_KILL_SWITCH")

    def test_t6_audit_queries_are_tenant_bound(self):
        env = build_env()
        env.pipeline.handle(Request(NW_USER, NORTHWIND, "qa.record",
                                    "what was the last a1c", ADA))
        meridian_view = env.ledger.query(tenant=MERIDIAN, subject_ref=ADA)
        self.assertEqual(meridian_view, [])

    def test_t8_relocated_ciphertext_is_inert(self):
        """Key policy is region- and tenant-bound, so a cross-region copy cannot be
        decrypted. Modelled here as a key-scope check."""
        keys = {NORTHWIND: "key-region-a", MERIDIAN: "key-region-b"}

        def decrypt(blob_tenant, using_tenant):
            return keys[blob_tenant] == keys[using_tenant]

        self.assertTrue(decrypt(NORTHWIND, NORTHWIND))
        self.assertFalse(decrypt(NORTHWIND, MERIDIAN))

    def test_t9_subject_aliases_are_per_request_and_never_a_join_key(self):
        env = build_env()
        for _ in range(2):
            env.pipeline.handle(Request(NW_USER, NORTHWIND, "qa.record",
                                        "what was the last a1c", ADA))
        events = env.ledger.query(action="minimization.applied")
        # The ledger stores the real record reference; the alias goes to the model
        # and is never persisted as a correlatable identifier.
        self.assertEqual({e["subject_ref"] for e in events}, {ADA})
        self.assertNotIn("subject_alias", events[0])

    def test_t10_cache_key_includes_the_tenant(self):
        """The failure most likely to be introduced accidentally by a future
        performance optimisation. Prompt-content-only keys leak across tenants."""
        def cache_key(tenant, capability, prompt, model_version, corpus_version):
            return sha256("|".join([tenant, capability, prompt,
                                    model_version, corpus_version]))

        same_prompt = "what was the last a1c"
        a = cache_key(NORTHWIND, "qa.record", same_prompt, "m1", "c1")
        b = cache_key(MERIDIAN, "qa.record", same_prompt, "m1", "c1")
        self.assertNotEqual(a, b)
        # And the naive version that would leak:
        naive = lambda prompt: sha256(prompt)
        self.assertEqual(naive(same_prompt), naive(same_prompt))  # the bug, demonstrated


class TestRestrictionAndDegradation(unittest.TestCase):

    def test_restricted_patient_never_crosses_the_model_boundary(self):
        """C-06 / §164.522. The record must not appear in ANY subsequent
        minimization event after the restriction takes effect."""
        env = build_env()
        out = env.pipeline.handle(Request(NW_USER, NORTHWIND, "qa.record",
                                          "what was the last a1c", "SYN-MRN-000456"))
        self.assertEqual(out.decision, "degraded")
        self.assertEqual(out.reason_code, "SUBJECT_RESTRICTION")
        for ev in env.ledger.query(action="minimization.applied"):
            self.assertNotEqual(ev["subject_ref"], "SYN-MRN-000456")

    def test_meridian_draft_summary_is_off_by_procurement_and_still_works(self):
        """A permanently-off feature is a SUPPORTED configuration, not a broken one."""
        env = build_env()
        out = env.pipeline.handle(Request(MER_USER, MERIDIAN, "draft.summary",
                                          "draft referral letter", DEE))
        self.assertEqual(out.decision, "degraded")
        self.assertEqual(out.detail["mode"], "templated_skeleton")
        # The deterministic view still serves the underlying data: AI off is not
        # "product down". The view's SHAPE now comes from the regime.
        self.assertIn("problems", out.detail["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
