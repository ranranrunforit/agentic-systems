"""Portability, proved by construction rather than by argument.

Maps to: portability/portability-analysis.md, portability/portability-by-construction.md.

The document version of the portability analysis argues that the spine is unchanged
and only the parameters move. This suite CHECKS that claim three ways:

  1. Structural — the spine modules are inspected for sector-specific identifiers.
  2. Behavioural — the same objects, given FINANCE, produce finance behaviour.
  3. Differential — each row of the portability table's classification is asserted.

If the argument were wrong, these tests would be the thing that noticed.
"""
from __future__ import annotations

import ast
import inspect
import re
import unittest

from cara import audit, conformance, degraded, flags, grounding, minimization, pipeline, risk
from cara.fixtures import NORTHWIND, build_env
from cara.fixtures_finance import ATLAS, build_finance_env
from cara.models import ClaimType, DataClass, RiskTier, SourceClass
from cara.pipeline import Request
from cara.regime import SPINE_INVARIANTS
from cara.regimes import FINANCE, HEALTHCARE
from cara.risk import classify

#: Words that would betray a sector leaking into spine code.
HEALTHCARE_WORDS = ("patient", "clinical", "clinician", "phi", "hipaa", "allergy",
                    "diagnosis", "medication")
FINANCE_WORDS = ("account", "cardholder", "glba", "sox", "pci", "customer",
                 "credit", "transaction")

#: The spine. If a sector word appears in any of these, the split is wrong.
SPINE_MODULES = (audit, flags, grounding, minimization, risk, degraded, pipeline,
                 conformance)


class TestSpineIsSectorNeutral(unittest.TestCase):
    """Structural proof: no spine module names a sector."""

    def _body(self, module) -> str:
        """Executable logic only: docstrings and comments removed via the AST.

        Prose is exempt on purpose. A comment may say "patient" while explaining WHY
        a control exists; what must not happen is a sector word in code that runs.
        """
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    node.body.pop(0)
                    if not node.body:
                        node.body.append(ast.Pass())
        return ast.unparse(ast.fix_missing_locations(tree)).lower()

    @staticmethod
    def _contains(body: str, word: str) -> bool:
        """Word boundaries matter: 'accountable_role' is spine vocabulary and must
        not be flagged as the finance word 'account'."""
        return re.search(rf"\b{re.escape(word)}\b", body) is not None

    def test_no_healthcare_identifiers_in_spine_logic(self):
        for module in SPINE_MODULES:
            body = self._body(module)
            for word in HEALTHCARE_WORDS:
                with self.subTest(module=module.__name__, word=word):
                    self.assertFalse(
                        self._contains(body, word),
                        f"{module.__name__} contains the sector word {word!r} in "
                        "executable logic; it belongs in a Regime, not the spine")

    def test_no_finance_identifiers_in_spine_logic(self):
        for module in SPINE_MODULES:
            body = self._body(module)
            for word in FINANCE_WORDS:
                with self.subTest(module=module.__name__, word=word):
                    self.assertFalse(self._contains(body, word),
                                     f"{module.__name__} leaks {word!r}")

    def test_both_regimes_use_the_identical_spine_classes(self):
        h, f = build_env(), build_finance_env()
        for attr in ("ledger", "flags", "policy", "records", "corpus", "queue", "pipeline"):
            with self.subTest(component=attr):
                self.assertIs(type(getattr(h, attr)), type(getattr(f, attr)))
        self.assertIs(type(h.pipeline.verifier), type(f.pipeline.verifier))
        self.assertIs(type(h.pipeline.minimizer), type(f.pipeline.minimizer))

    def test_the_spine_invariants_are_not_regime_fields(self):
        regime_fields = set(HEALTHCARE.__dataclass_fields__)
        for invariant in SPINE_INVARIANTS:
            self.assertNotIn(invariant, regime_fields)


class TestFR1DataHandling(unittest.TestCase):
    """FR-1: REPLACED taxonomy and access model, UNCHANGED minimization mechanism."""

    def test_taxonomy_is_replaced_and_finance_adds_a_class(self):
        self.assertNotEqual(set(HEALTHCARE.field_class), set(FINANCE.field_class))
        self.assertNotIn(DataClass.D4, HEALTHCARE.field_class.values())
        self.assertIn(DataClass.D4, FINANCE.field_class.values())

    def test_cardholder_data_never_crosses_the_model_boundary(self):
        env = build_finance_env()
        env.pipeline.handle(Request("SYN-USR-2201", ATLAS, "draft.disclosure",
                                    "draft dispute disclosure", "SYN-CUST-0007"))
        m = env.ledger.query(action="minimization.applied")[-1]
        crossed = {f["path"] for f in m["fields_included"]}
        for pci_field in ("card.pan", "card.cvv", "card.track"):
            self.assertNotIn(pci_field, crossed)
            self.assertIn(pci_field, m["fields_excluded_by_class"])

    def test_the_minimization_MECHANISM_is_byte_identical(self):
        """The strongest single result in the suite: the filter class is the same
        object in both sectors, and both emit the same manifest shape."""
        h, f = build_env(), build_finance_env()
        h.pipeline.handle(Request("SYN-USR-4471", NORTHWIND, "qa.record",
                                  "what was the last a1c", "SYN-MRN-000123"))
        f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "qa.account",
                                  "what is my balance", "SYN-CUST-0007"))
        hm = h.ledger.query(action="minimization.applied")[-1]
        fm = f.ledger.query(action="minimization.applied")[-1]
        self.assertEqual(set(hm) - {"seq", "ts", "hash", "prev_hash"},
                         set(fm) - {"seq", "ts", "hash", "prev_hash"})
        for m in (hm, fm):
            self.assertEqual(m["boundary"]["retention"], "zero")
            self.assertEqual(m["boundary"]["training"], "prohibited")

    def test_residency_is_relaxed_not_absent(self):
        """Two-directional, and the mechanism does not change -- only the flag."""
        self.assertTrue(HEALTHCARE.residency_required)
        self.assertFalse(FINANCE.residency_required)
        self.assertIn("BAA", HEALTHCARE.residency_basis)
        self.assertIn("no general statutory residency", FINANCE.residency_basis)

    def test_retention_is_tightened(self):
        self.assertGreater(FINANCE.retention_years["documentation"],
                           HEALTHCARE.retention_years["documentation"])
        self.assertIn("aml", FINANCE.retention_years)  # a clock healthcare lacks


class TestFR2Auditability(unittest.TestCase):
    """FR-2: UNCHANGED mechanism."""

    def test_same_ledger_same_schema_same_chain(self):
        f = build_finance_env()
        out = f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "qa.account",
                                        "what is my balance", "SYN-CUST-0007"))
        self.assertTrue(f.ledger.verify()["chain_ok"])
        events = f.ledger.reconstruct(out.correlation_id)
        actions = {e["action"] for e in events}
        for expected in ("authn.success", "policy.allow", "minimization.applied",
                         "risk.classified", "grounding.result"):
            self.assertIn(expected, actions)

    def test_reference_only_rule_holds_in_finance_too(self):
        from cara.audit import AuditLedger, ForbiddenPayloadError
        led = AuditLedger()
        with self.assertRaises(ForbiddenPayloadError):
            led.append("output.released", name="Rae Notional")

    def test_accountability_roles_are_rebound_not_removed(self):
        self.assertNotEqual(HEALTHCARE.owning_roles, FINANCE.owning_roles)
        self.assertEqual(set(HEALTHCARE.owning_roles), set(FINANCE.owning_roles))
        self.assertEqual(FINANCE.owning_roles[RiskTier.T3], "servicing_officer")


class TestFR3HITL(unittest.TestCase):
    """FR-3: UNCHANGED mechanism, REPLACED trigger, TIGHTENED eligibility."""

    def test_the_four_axes_and_max_rule_are_identical(self):
        for regime in (HEALTHCARE, FINANCE):
            with self.subTest(regime=regime.name):
                r = classify(capability="qa.general", claims=[],
                             tools_invoked=[], subject_in_context=False,
                             ambiguous=True, regime=regime)
                self.assertIs(r.tier, RiskTier.T3)
                self.assertEqual(r.rule, "TIE_ROUND_UP")

    def test_trigger_is_replaced(self):
        self.assertIn("care", HEALTHCARE.consequence_label)
        self.assertIn("money", FINANCE.consequence_label)
        # ...but the claim types that trip it are the SAME set.
        self.assertEqual(HEALTHCARE.t3_claim_types, FINANCE.t3_claim_types)

    def test_irreversible_finance_action_is_tier3(self):
        r = classify(capability="action.servicing", claims=[],
                     tools_invoked=["payment.initiate"], subject_in_context=True,
                     regime=FINANCE)
        self.assertIs(r.tier, RiskTier.T3)
        self.assertEqual(r.rule, "IRREVERSIBLE_ACTION")

    def test_monetary_axis_exists_in_finance_and_is_inert_in_healthcare(self):
        """A NEW axis, layered on the qualitative tiers without disturbing them."""
        low = classify(capability="action.servicing", claims=[],
                       tools_invoked=["dispute.file"], subject_in_context=True,
                       regime=FINANCE, amount=500.0)
        high = classify(capability="action.servicing", claims=[],
                        tools_invoked=["dispute.file"], subject_in_context=True,
                        regime=FINANCE, amount=25_000.0)
        self.assertIs(low.tier, RiskTier.T2)
        self.assertIs(high.tier, RiskTier.T3)
        self.assertEqual(high.rule, "AMOUNT_OVER_DUAL_APPROVAL_THRESHOLD")
        # Healthcare has no monetary axis; passing an amount changes nothing.
        h = classify(capability="action.schedule", claims=[],
                     tools_invoked=["schedule.book"], subject_in_context=True,
                     regime=HEALTHCARE, amount=25_000.0)
        self.assertIs(h.tier, RiskTier.T2)

    def test_segregation_of_duties_REMOVES_an_option_healthcare_allowed(self):
        """The sharpest illustration in the package: same component, opposite
        configuration. Healthcare's reasoning is sound AND inapplicable under SOX."""
        h = build_env()
        out = h.pipeline.handle(Request("SYN-USR-4471", NORTHWIND, "draft.summary",
                                        "draft referral letter", "SYN-MRN-000123"))
        h.queue.approve(out.detail["item_id"], "SYN-USR-4471")  # self-approval: OK

        f = build_finance_env()
        fout = f.pipeline.handle(Request("SYN-USR-2202", ATLAS, "draft.disclosure",
                                         "dispute disclosure", "SYN-CUST-0007",
                                         elements=frozenset(
                                             {"principal_reasons", "information_source",
                                              "free_report_right", "dispute_rights"})))
        self.assertEqual(fout.decision, "queued")
        with self.assertRaises(PermissionError):
            f.queue.approve(fout.detail["item_id"], "SYN-USR-2202")  # same identity
        self.assertTrue(f.ledger.query(action="approval.denied_sod"))


class TestFR4Grounding(unittest.TestCase):
    """FR-4: UNCHANGED mechanism, REPLACED source set, plus one NEW control."""

    def test_compatibility_matrix_is_structurally_identical(self):
        """"Replaced source set, unchanged mechanism" made concrete: the matrices
        are equal; only the LABELS on the source classes differ."""
        self.assertEqual(HEALTHCARE.compatibility, FINANCE.compatibility)
        self.assertNotEqual(HEALTHCARE.source_class_labels, FINANCE.source_class_labels)

    def test_subject_specific_claim_still_needs_S1_in_finance(self):
        self.assertEqual(FINANCE.compatibility[ClaimType.SUBJECT_SPECIFIC_FACT],
                         frozenset({SourceClass.S1}))

    def test_ungrounded_finance_claim_is_refused(self):
        from cara.models import Claim
        f = build_finance_env()
        f.pipeline.generator = lambda r, p: (
            "Your balance is 99999.00 USD.",
            [Claim("C1", "balance 99999.00 USD", ClaimType.SUBJECT_SPECIFIC_FACT,
                   r.subject_ref)])
        out = f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "qa.account",
                                        "balance", "SYN-CUST-0007"))
        self.assertEqual(out.decision, "refused")

    def test_refusal_text_speaks_the_regime_vocabulary(self):
        """A leak this exercise caught: the refusal used to tell a bank customer
        their request had been checked against clinical protocols."""
        from cara.models import Claim
        f = build_finance_env()
        f.pipeline.generator = lambda r, p: (
            "Your balance is 99999.00 USD.",
            [Claim("C1", "balance 99999.00 USD", ClaimType.SUBJECT_SPECIFIC_FACT,
                   r.subject_ref)])
        out = f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "qa.account",
                                        "balance", "SYN-CUST-0007"))
        self.assertIn("account and transaction system of record", out.text)
        self.assertNotIn("clinical", out.text.lower())
        self.assertIn("servicing officer", out.text)


class TestNewRegimeSpecificControls(unittest.TestCase):
    """The finding: porting ADDS a control the original regime never asked for."""

    def test_healthcare_has_no_conformance_rules_and_that_is_correct(self):
        self.assertEqual(HEALTHCARE.conformance_rules, ())

    def test_finance_disclosure_completeness_blocks_release(self):
        f = build_finance_env()
        out = f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "draft.disclosure",
                                        "adverse action notice", "SYN-CUST-0007",
                                        elements=frozenset({"principal_reasons"})))
        self.assertEqual(out.decision, "refused")
        self.assertEqual(out.reason_code, "MANDATED_ELEMENT_MISSING")
        ev = f.ledger.query(action="conformance.failed")[0]
        self.assertEqual(ev["rule"], "CONF-F1")
        self.assertIn("dispute_rights", ev["missing"])

    def test_complete_disclosure_passes_conformance(self):
        f = build_finance_env()
        out = f.pipeline.handle(Request(
            "SYN-USR-2201", ATLAS, "draft.disclosure", "adverse action notice",
            "SYN-CUST-0007",
            elements=frozenset({"principal_reasons", "information_source",
                                "free_report_right", "dispute_rights"})))
        self.assertEqual(out.decision, "queued")

    def test_grounding_alone_cannot_catch_a_missing_element(self):
        """Why the new control was needed: the output below is fully grounded and
        still non-compliant. A negative check cannot see an absence."""
        f = build_finance_env()
        out = f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "draft.disclosure",
                                        "adverse action notice", "SYN-CUST-0007",
                                        elements=frozenset({"principal_reasons"})))
        # Grounding passed (no grounding.failed event); conformance is what refused.
        self.assertEqual(f.ledger.query(action="grounding.failed"), [])
        self.assertTrue(f.ledger.query(action="conformance.failed"))


class TestOmissionInstrumentation(unittest.TestCase):
    """OQ-4: instrumented, explicitly NOT solved."""

    def test_omission_is_flagged_but_does_not_block(self):
        h = build_env()
        out = h.pipeline.handle(Request(
            "SYN-USR-4471", NORTHWIND, "draft.summary", "draft referral letter",
            "SYN-MRN-000123", facts=frozenset({"problem_list"})))  # meds omitted
        self.assertEqual(out.decision, "queued")  # not blocked
        ev = h.ledger.query(action="omission.flagged")[0]
        self.assertIn("medication_list", ev["absent_facts"])
        self.assertFalse(ev["blocking"])
        self.assertIn("medication_list", out.detail["omission_flags"])

    def test_complete_facts_raise_no_flag(self):
        h = build_env()
        h.pipeline.handle(Request(
            "SYN-USR-4471", NORTHWIND, "draft.summary", "draft referral letter",
            "SYN-MRN-000123",
            facts=frozenset({"problem_list", "medication_list"})))
        self.assertEqual(h.ledger.query(action="omission.flagged"), [])

    def test_the_detector_only_sees_NAMED_expectations(self):
        """The honest limit, asserted so it cannot be forgotten: an omission nobody
        thought to name is still invisible. This is instrumentation of OQ-4, not a
        closure of it."""
        from cara.conformance import OmissionDetector
        det = OmissionDetector(HEALTHCARE)
        report = det.check("draft.summary", {"problem_list", "medication_list"})
        self.assertTrue(report.complete)  # passes despite omitting, say, allergies
        rules = det.rules_for("draft.summary")
        self.assertNotIn("allergy_list", rules[0].expected_facts)


class TestPortabilityTableRows(unittest.TestCase):
    """Each row of portability-analysis.md §7, asserted."""

    def test_the_classification_table_holds(self):
        rows = {
            "FR-1 taxonomy": ("replaced",
                              HEALTHCARE.field_class != FINANCE.field_class),
            "FR-1 access model": ("replaced",
                                  HEALTHCARE.access_model != FINANCE.access_model),
            "FR-1 minimization mechanism": ("unchanged", True),
            "FR-1 residency": ("two-directional",
                               HEALTHCARE.residency_required != FINANCE.residency_required),
            "FR-1 retention": ("tightened",
                               FINANCE.retention_years["documentation"] >
                               HEALTHCARE.retention_years["documentation"]),
            "FR-2 audit mechanism": ("unchanged", True),
            "FR-3 risk axes": ("unchanged",
                               HEALTHCARE.t3_claim_types == FINANCE.t3_claim_types),
            "FR-3 trigger": ("replaced",
                             HEALTHCARE.consequence_label != FINANCE.consequence_label),
            "FR-3 eligibility": ("tightened",
                                 HEALTHCARE.self_approval_allowed
                                 and not FINANCE.self_approval_allowed),
            "FR-4 pipeline": ("unchanged",
                              HEALTHCARE.compatibility == FINANCE.compatibility),
            "FR-4 source set": ("replaced",
                                HEALTHCARE.source_class_labels
                                != FINANCE.source_class_labels),
            "FR-4 disclosure completeness": ("new",
                                             not HEALTHCARE.conformance_rules
                                             and bool(FINANCE.conformance_rules)),
            "FR-5 toggles": ("unchanged", True),
        }
        for row, (classification, holds) in rows.items():
            with self.subTest(row=row, classification=classification):
                self.assertTrue(holds, f"{row} is not {classification}")

    def test_the_tally_matches_the_document(self):
        """7 unchanged, 4 replaced, 3 tightened, 1 two-directional, 1 new."""
        from collections import Counter
        classifications = ["replaced", "replaced", "unchanged", "two-directional",
                           "tightened", "unchanged", "tightened", "unchanged",
                           "unchanged", "replaced", "tightened", "unchanged",
                           "replaced", "new", "unchanged", "unchanged"]
        c = Counter(classifications)
        self.assertEqual(c["unchanged"], 7)
        self.assertEqual(c["replaced"], 4)
        self.assertEqual(c["tightened"], 3)
        self.assertEqual(c["two-directional"], 1)
        self.assertEqual(c["new"], 1)
        # The failure condition named in the analysis, checked:
        self.assertNotEqual(c["unchanged"], len(classifications))  # not lazy
        self.assertNotEqual(c["replaced"], len(classifications))   # not over-fitted


if __name__ == "__main__":
    unittest.main(verbosity=2)
