"""FC-1 .. FC-10: the fail-closed drill matrix, executed.

Maps to: control-mapping/evidence-index.md §Fail-closed test matrix.
Acceptance criterion: "The system fails closed when grounding, authorization, or a
required human approval is unavailable."
"""
from __future__ import annotations

import unittest

from cara.audit import AuditLedger, ForbiddenPayloadError, LedgerWriteError
from cara.fixtures import NORTHWIND, build_env
from cara.grounding_corpus import RetrievalUnavailable
from cara.models import Claim, ClaimType, RiskTier
from cara.pipeline import Request
from cara.regimes import HEALTHCARE
from cara.risk import classify

USER = "SYN-USR-4471"
ADA = "SYN-MRN-000123"


def req(cap="draft.summary", q="draft referral letter", subject=ADA, tools=()):
    return Request(USER, NORTHWIND, cap, q, subject, tools)


class TestFailClosed(unittest.TestCase):

    def test_fc1_flag_service_unreachable_past_max_stale_means_ai_off(self):
        env = build_env()
        env.flags_service.reachable = False
        env.flags._cache.clear()  # cold start, no cached value
        out = env.pipeline.handle(req())
        self.assertEqual(out.decision, "degraded")
        self.assertEqual(out.reason_code, "FAIL_CLOSED_FLAGS_UNAVAILABLE")
        self.assertTrue(env.ledger.query(action="policy.degraded"))

    def test_fc1b_bounded_stale_cache_is_used_then_expires_closed(self):
        env = build_env()
        env.pipeline.handle(req(cap="qa.record", q="what was the last a1c"))  # warms cache
        env.flags_service.reachable = False
        # Within the window: cached value honoured.
        res = env.flags.resolve(NORTHWIND, "qa.record", ADA)
        self.assertTrue(res.enabled)
        self.assertEqual(res.cause, "STALE_CACHE")
        # Past the window: AI off.
        env.flags.max_stale = -1
        res = env.flags.resolve(NORTHWIND, "qa.record", ADA)
        self.assertFalse(res.enabled)
        self.assertEqual(res.cause, "FAIL_CLOSED_FLAGS_UNAVAILABLE")

    def test_fc2_retrieval_unavailable_refuses_high_risk(self):
        env = build_env()
        env.corpus.available = False
        out = env.pipeline.handle(req())
        self.assertEqual(out.decision, "refused")
        self.assertEqual(out.reason_code, "RETRIEVAL_UNAVAILABLE")
        self.assertTrue(env.ledger.query(action="grounding.failed"))

    def test_fc3_no_supporting_span_refuses_and_audits_the_refusal(self):
        env = build_env()

        def rogue(request, payload):
            return ("Her HbA1c is 5.1 and improving.",
                    [Claim("C1", "HbA1c 5.1 and improving",
                           ClaimType.PATIENT_SPECIFIC_FACT, request.subject_ref)])

        env.pipeline.generator = rogue
        out = env.pipeline.handle(req())
        self.assertEqual(out.decision, "refused")
        # The fabricated 5.1 is not in any span -> numeric veto -> no candidate span.
        self.assertEqual(out.reason_code, "NO_SUPPORTING_SPAN")
        failures = env.ledger.query(action="grounding.failed")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["tier"], 3)
        self.assertIn("searched_scope", failures[0])  # refusals name their scope

    def test_fc4_no_eligible_approver_expires_closed(self):
        env = build_env()
        env.queue.rosters[(NORTHWIND, "supervising_clinician")] = []  # empty roster
        out = env.pipeline.handle(req())
        self.assertEqual(out.decision, "expired")
        self.assertEqual(out.reason_code, "NO_APPROVER")
        ev = env.ledger.query(action="approval.expired")[0]
        self.assertFalse(ev["action_taken"])
        # And nothing was released.
        self.assertEqual(env.ledger.query(action="output.released"), [])

    def test_fc5_policy_engine_unavailable_denies(self):
        env = build_env()
        env.policy.available = False
        out = env.pipeline.handle(req())
        self.assertEqual(out.decision, "denied")
        self.assertEqual(out.reason_code, "POLICY_UNAVAILABLE")

    def test_fc6_ledger_write_failure_aborts_the_action(self):
        ledger = AuditLedger()
        ledger.available = False
        with self.assertRaises(LedgerWriteError):
            ledger.append("output.released", correlation_id="X", tier=2)
        # The attempt survives in the local hash-chained journal...
        self.assertEqual(len(ledger._journal), 1)
        self.assertTrue(ledger._journal[0]["deferred_write"])
        # ...and merges on recovery, keeping its marker.
        ledger.available = True
        self.assertEqual(ledger.merge_journal(), 1)
        self.assertTrue(ledger.verify()["chain_ok"])

    def test_fc8_ambiguous_classification_rounds_up(self):
        r = classify(capability="qa.general", claims=[], tools_invoked=[],
                     subject_in_context=False, ambiguous=True, regime=HEALTHCARE)
        self.assertIs(r.tier, RiskTier.T3)
        self.assertEqual(r.rule, "TIE_ROUND_UP")

    def test_fc10_expired_or_withdrawn_source_excluded_from_retrieval(self):
        env = build_env()
        from cara.models import SourceClass
        spans = env.corpus.retrieve(tenant=NORTHWIND, text="eGFR thresholds superseded",
                                    allowed_classes={SourceClass.S3})
        self.assertEqual([s.doc_id for s in spans], [])  # SYN-VS-REF-019 is withdrawn

    def test_ledger_rejects_raw_sensitive_payloads(self):
        """The retention clocks only reconcile if the log holds references, not content."""
        ledger = AuditLedger()
        with self.assertRaises(ForbiddenPayloadError):
            ledger.append("output.released", name="Ada Fictionalis")
        with self.assertRaises(ForbiddenPayloadError):
            ledger.append("grounding.result", citations=[{"span_text": "Lab: HbA1c 7.4"}])
        # References and hashes are fine.
        ledger.append("output.released", subject_ref=ADA, content_hash="sha256:abc")

    def test_irreversible_tool_forces_tier3(self):
        r = classify(capability="action.schedule", claims=[],
                     tools_invoked=["refill.request"], subject_in_context=True,
                     regime=HEALTHCARE)
        self.assertIs(r.tier, RiskTier.T3)
        self.assertEqual(r.rule, "IRREVERSIBLE_ACTION")

    def test_reversible_tool_stays_tier2(self):
        r = classify(capability="action.schedule", claims=[],
                     tools_invoked=["schedule.book"], subject_in_context=True,
                     regime=HEALTHCARE)
        self.assertIs(r.tier, RiskTier.T2)


class TestNoPathToRelease(unittest.TestCase):
    """The absence of an edge from any state to `released` for Tier 3 IS the control."""

    def test_tier3_cannot_be_released_without_approval(self):
        env = build_env()
        out = env.pipeline.handle(req())
        self.assertEqual(out.decision, "queued")
        with self.assertRaises(PermissionError):
            env.pipeline.release_approved(out.detail["item_id"])

    def test_ineligible_approver_is_rejected(self):
        env = build_env()
        out = env.pipeline.handle(req())
        with self.assertRaises(PermissionError):
            env.queue.approve(out.detail["item_id"], "SYN-USR-4472")  # nurse, wrong role
        self.assertTrue(env.ledger.query(action="approval.denied_ineligible"))

    def test_population_query_tier3_without_approval_is_empty(self):
        """The single most important control test in the whole package."""
        env = build_env()
        for q in ("draft referral letter", "what was the last a1c", "no-show policy"):
            cap = "qa.general" if "policy" in q else "draft.summary"
            subject = None if cap == "qa.general" else ADA
            out = env.pipeline.handle(Request(USER, NORTHWIND, cap, q, subject))
            if out.decision == "queued":
                env.queue.approve(out.detail["item_id"], USER, dwell_ms=184000)
                env.pipeline.release_approved(out.detail["item_id"])
        self.assertEqual(env.ledger.tier3_without_approval(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
