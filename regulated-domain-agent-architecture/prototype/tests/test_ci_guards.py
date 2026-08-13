"""CI guards: invariants that a future change is most likely to break by accident.

Maps to: SELF-ASSESSMENT.md §4 items 1 and 5.

These are not tests of features. They are tests of the properties a well-meaning
optimisation would silently remove, which is the class of regression that compliance
architectures actually suffer from. Each one exists because a plausible future commit
would otherwise break it without failing anything else.
"""
from __future__ import annotations

import ast
import inspect
import unittest

from cara import audit, degraded, flags, grounding, minimization, pipeline, risk
from cara.audit import sha256
from cara.fixtures import NORTHWIND, build_env
from cara.grounding import GroundingVerifier
from cara.models import Claim, ClaimType, RiskTier, SourceClass, Span
from cara.regimes import FINANCE, HEALTHCARE


class TestCacheKeyAudit(unittest.TestCase):
    """T-10, promoted to a CI guard.

    A response cache keyed on prompt content alone looks correct, performs
    beautifully, and serves tenant A's answer to tenant B the first time two prompts
    coincide. It is the single most likely way this system acquires a cross-tenant
    leak, and it would arrive as a performance improvement.
    """

    REQUIRED_KEY_COMPONENTS = ("tenant", "capability", "prompt_hash",
                              "model_version", "corpus_version")

    @staticmethod
    def cache_key(tenant, capability, prompt_hash, model_version, corpus_version):
        return sha256("|".join([tenant, capability, prompt_hash,
                                model_version, corpus_version]))

    def test_identical_prompts_from_different_tenants_do_not_collide(self):
        a = self.cache_key("SYN-TEN-northwind", "qa.record", "h", "m1", "c1")
        b = self.cache_key("SYN-TEN-meridian", "qa.record", "h", "m1", "c1")
        self.assertNotEqual(a, b)

    def test_a_model_change_invalidates_the_cache(self):
        """Otherwise a model upgrade silently serves pre-upgrade answers, and the
        audit trail's `model` field no longer describes what produced the output."""
        a = self.cache_key("t", "c", "h", "m1", "c1")
        b = self.cache_key("t", "c", "h", "m2", "c1")
        self.assertNotEqual(a, b)

    def test_a_corpus_change_invalidates_the_cache(self):
        """Otherwise a withdrawn vetted source keeps grounding cached answers."""
        a = self.cache_key("t", "c", "h", "m1", "c1")
        b = self.cache_key("t", "c", "h", "m1", "c2")
        self.assertNotEqual(a, b)

    def test_the_naive_key_is_demonstrably_unsafe(self):
        """The bug, written down, so nobody has to rediscover it in production."""
        naive = lambda prompt_hash: sha256(prompt_hash)
        self.assertEqual(naive("same-prompt"), naive("same-prompt"))

    def test_every_required_component_changes_the_key(self):
        base = ("t", "c", "h", "m", "co")
        for i, component in enumerate(self.REQUIRED_KEY_COMPONENTS):
            with self.subTest(component=component):
                mutated = list(base)
                mutated[i] = mutated[i] + "-changed"
                self.assertNotEqual(self.cache_key(*base), self.cache_key(*mutated))


class TestVetoSetIsIntact(unittest.TestCase):
    """The red-team's top finding was to EXPAND the deterministic vetoes.

    Each veto below is asserted individually, because a refactor that quietly drops
    one would still pass every functional test -- the entailment scorer would take
    over and the system would look fine while being measurably less safe.
    """

    def setUp(self):
        self.v = GroundingVerifier(build_env().corpus, regime=HEALTHCARE)

    def _veto(self, claim_text, span_text, **kw):
        claim = Claim("C", claim_text, kw.pop("ctype", ClaimType.SUBJECT_SPECIFIC_FACT),
                      kw.pop("subject", "SYN-MRN-000123"), **kw)
        span = Span("RECORD:SYN-MRN-000123", "1", "0:0", span_text, SourceClass.S1,
                    subject_ref="SYN-MRN-000123",
                    asserts_absence=kw.get("span_absence", False))
        return self.v._vetoes(claim, span)

    def test_v1_entity_binding(self):
        claim = Claim("C", "value 7.4", ClaimType.SUBJECT_SPECIFIC_FACT, "SYN-MRN-000123")
        span = Span("RECORD:OTHER", "1", "0:0", "value 7.4", SourceClass.S1,
                    subject_ref="SYN-MRN-999999")
        self.assertEqual(self.v._vetoes(claim, span), "ENTITY_BINDING")

    def test_v2_polarity(self):
        claim = Claim("C", "no known allergies", ClaimType.SUBJECT_SPECIFIC_FACT,
                      "SYN-MRN-000123", asserts_absence=True)
        span = Span("RECORD:SYN-MRN-000123", "1", "0:0", "known allergies",
                    SourceClass.S1, subject_ref="SYN-MRN-000123", asserts_absence=False)
        self.assertEqual(self.v._vetoes(claim, span), "POLARITY")

    def test_v3_numeric_fidelity(self):
        self.assertEqual(self._veto("value 7.5", "value 7.4"), "NUMERIC_FIDELITY")

    def test_v4_temporal_fidelity(self):
        self.assertEqual(self._veto("result on 2026-07-31", "result on 2026-07-30"),
                         "TEMPORAL_FIDELITY")

    def test_v5_unit_fidelity(self):
        """The right number with the wrong unit: a dosing error in healthcare and a
        pricing error in finance. Passes V3 unharmed."""
        self.assertEqual(self._veto("dose 500 mcg", "dose 500 mg"), "UNIT_FIDELITY")

    def test_v6_comparator_direction(self):
        """'above 7.4' and 'below 7.4' share every token and every number."""
        self.assertEqual(self._veto("value above 7.4", "value below 7.4"),
                         "COMPARATOR_DIRECTION")

    def test_v7_quantifier_strength(self):
        self.assertEqual(self._veto("all cases resolve", "some cases resolve"),
                         "QUANTIFIER_STRENGTH")

    def test_v8_modality_strength(self):
        """How a guideline becomes a mandate in a single paraphrase."""
        self.assertEqual(self._veto("treatment must be started",
                                    "treatment may be started"), "MODALITY_STRENGTH")

    def test_v9_negation_parity(self):
        self.assertEqual(self._veto("the result was not elevated",
                                    "the result was elevated"), "NEGATION_PARITY")

    def test_a_faithful_claim_survives_every_veto(self):
        """Vetoes are veto-only. If they fired on faithful output the system would
        over-refuse, and over-refusal produces workarounds."""
        self.assertIsNone(self._veto("HbA1c 7.4 on 2026-07-30",
                                     "Lab: HbA1c 7.4 % on 2026-07-30"))

    def test_the_veto_count_has_not_silently_shrunk(self):
        src = inspect.getsource(GroundingVerifier._vetoes)
        for veto in ("ENTITY_BINDING", "POLARITY", "NUMERIC_FIDELITY",
                     "TEMPORAL_FIDELITY", "UNIT_FIDELITY", "COMPARATOR_DIRECTION",
                     "QUANTIFIER_STRENGTH", "MODALITY_STRENGTH", "NEGATION_PARITY"):
            self.assertIn(veto, src, f"deterministic veto {veto} was removed")


class TestFailClosedDefaultsCannotDrift(unittest.TestCase):
    """Every fail-closed default, asserted as a value rather than as behaviour.

    Behavioural tests catch a broken path. These catch the subtler regression: a
    default flipped from closed to open by someone fixing an availability incident.
    """

    def test_unknown_flag_is_off(self):
        env = build_env()
        env.flags_service.delete_flag(NORTHWIND, "qa.record")
        self.assertFalse(env.flags.resolve(NORTHWIND, "qa.record", None).enabled)

    def test_max_stale_window_is_bounded_and_short(self):
        from cara.flags import MAX_STALE_SECONDS
        self.assertGreater(MAX_STALE_SECONDS, 0)
        self.assertLessEqual(MAX_STALE_SECONDS, 120,
                             "a long stale window makes the kill switch advisory")

    def test_thresholds_are_ordered_and_recall_biased(self):
        from cara.grounding import TAU_HARD, TAU_SOFT
        self.assertGreater(TAU_HARD, TAU_SOFT)
        self.assertGreaterEqual(TAU_HARD, 0.8,
                                "a low hard threshold silently admits weak grounding")

    def test_consequential_events_still_block(self):
        from cara.audit import CONSEQUENTIAL
        for action in ("output.released", "action.executed", "approval.granted",
                       "grounding.failed", "toggle.changed", "deletion.executed"):
            self.assertIn(action, CONSEQUENTIAL,
                          f"{action} was downgraded to a non-blocking write")

    def test_no_tool_may_write_to_the_system_of_record(self):
        for regime in (HEALTHCARE, FINANCE):
            for tool, meta in regime.tool_registry.items():
                with self.subTest(regime=regime.name, tool=tool):
                    self.assertFalse(meta["writes_record"],
                                     "ADR-008: the agent proposes, never writes")

    def test_ledger_still_has_no_mutation_verbs(self):
        for verb in ("update", "delete", "edit", "remove", "truncate", "purge"):
            self.assertFalse(hasattr(audit.AuditLedger, verb))


class TestRegimeCompleteness(unittest.TestCase):
    """A new regime must bind every parameter. A missing binding should fail at
    construction, not produce quiet healthcare-shaped behaviour in another sector."""

    REQUIRED = ("field_class", "strictest_class", "never_crosses", "residency_required",
                "retention_years", "relationship_name", "access_model",
                "consequence_label", "t3_claim_types", "owning_roles",
                "self_approval_allowed", "compatibility", "source_class_labels",
                "capabilities", "tool_registry", "s1_span_rules", "transforms",
                "degraded_modes", "degraded_views")

    def test_every_regime_binds_every_parameter(self):
        for regime in (HEALTHCARE, FINANCE):
            for field_name in self.REQUIRED:
                with self.subTest(regime=regime.name, field=field_name):
                    value = getattr(regime, field_name, None)
                    self.assertIsNotNone(value)
                    if isinstance(value, (dict, tuple, frozenset)):
                        self.assertTrue(value, f"{field_name} is empty in {regime.name}")

    def test_every_capability_has_a_degraded_mode(self):
        """Otherwise turning AI off becomes a product outage for that capability --
        which means the kill switch never gets used in a real incident."""
        for regime in (HEALTHCARE, FINANCE):
            for cap in regime.capabilities:
                with self.subTest(regime=regime.name, capability=cap):
                    self.assertIn(cap, regime.degraded_modes)
                    self.assertIn(cap, regime.degraded_notices)

    def test_every_capability_has_an_owning_role_for_its_floor_tier(self):
        for regime in (HEALTHCARE, FINANCE):
            for cap in regime.capabilities.values():
                with self.subTest(regime=regime.name, capability=cap.name):
                    self.assertIn(cap.tier_floor, regime.owning_roles)

    def test_every_conformance_rule_targets_a_real_capability(self):
        for regime in (HEALTHCARE, FINANCE):
            for rule in regime.conformance_rules:
                with self.subTest(regime=regime.name, rule=rule.rule_id):
                    self.assertIn(rule.applies_to, set(regime.capabilities) | {"*"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
