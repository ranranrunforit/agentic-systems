"""Two controls the portability analysis discovered were missing from the spine.

Maps to: portability/sector-deltas.md §4 findings 2 and 3, OQ-4 and OQ-7.

Both address the same blind spot from opposite sides. Grounding is a NEGATIVE check:
nothing asserted may be unsupported. It is structurally incapable of noticing that
something required is ABSENT.

  - `ConformanceVerifier` (OQ-7) — a POSITIVE check that mandated elements are
    present. Blocking, because a legally-mandated disclosure element is not optional.
  - `OmissionDetector` (OQ-4) — a WEAKER check that materially expected facts are
    present. Advisory, because "what a reader would expect" is a judgement, and
    blocking on a heuristic judgement would produce exactly the over-refusal the
    red-team warned about.

The asymmetry between them is the point. One is a rule; the other is a hint to a
human. Pretending the second is as strong as the first would be the dishonest move.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .regime import ConformanceRule, MaterialityRule, Regime


@dataclass
class ConformanceReport:
    ok: bool = True
    rule_id: str = ""
    missing: tuple[str, ...] = ()
    reason_code: str = ""


class ConformanceVerifier:
    """Positive output-conformance. Empty rule set => always passes.

    Healthcare v1 has no rules, so this is a no-op there. That is the correct
    behaviour for a spine slot with nothing bound to it -- not a reason to omit
    the slot.
    """

    def __init__(self, regime: Regime) -> None:
        self.regime = regime

    def rules_for(self, capability: str) -> list[ConformanceRule]:
        return [r for r in self.regime.conformance_rules
                if r.applies_to in (capability, "*")]

    def check(self, capability: str, elements_present: set[str]) -> ConformanceReport:
        for rule in self.rules_for(capability):
            missing = tuple(e for e in rule.required_elements
                            if e not in elements_present)
            if missing:
                # Fails CLOSED. A mandated disclosure element is not a nice-to-have,
                # and releasing a notice missing its dispute-rights language is a
                # compliance event regardless of how well-grounded the rest is.
                return ConformanceReport(False, rule.rule_id, missing,
                                         "MANDATED_ELEMENT_MISSING")
        return ConformanceReport(True)


@dataclass
class OmissionReport:
    complete: bool = True
    rule_id: str = ""
    absent_facts: tuple[str, ...] = ()
    note: str = ""


class OmissionDetector:
    """Advisory materiality check. Flags, never blocks.

    What this genuinely buys: a Tier-3 reviewer sees "this summary does not mention
    current medications" in the review panel, next to the citations. That is a real
    improvement over the previous state, which was nothing.

    What it does NOT do: solve misleading-by-omission. It checks a NAMED list of
    expected facts per capability. An omission nobody thought to name is still
    invisible, and the general problem -- every claim true, the whole misleading --
    remains open (OQ-4). Instrumenting a residual risk is not closing it, and the
    report says so rather than implying coverage it does not have.
    """

    def __init__(self, regime: Regime) -> None:
        self.regime = regime

    def rules_for(self, capability: str) -> list[MaterialityRule]:
        return [r for r in self.regime.materiality_rules
                if r.applies_to in (capability, "*")]

    def check(self, capability: str, facts_present: set[str]) -> OmissionReport:
        for rule in self.rules_for(capability):
            absent = tuple(f for f in rule.expected_facts if f not in facts_present)
            if absent:
                return OmissionReport(
                    False, rule.rule_id, absent,
                    "Flagged for the reviewer; not blocking. Only NAMED expectations "
                    "are checked, so this is instrumentation of OQ-4, not a solution.")
        return OmissionReport(True)
