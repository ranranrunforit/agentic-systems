"""Grounding verifier: claim decomposition, retrieval, entailment, deterministic vetoes.

Maps to: grounding/hallucination-containment.md, ADR-002.

The control is grounding-or-refuse. It is NOT model confidence. A confident wrong
answer and a confident right answer are indistinguishable from the inside, so the
containment lives outside the model.

The red-team found (stretch/red-team-grounding.md §A1) that the DETERMINISTIC VETOES,
not the entailment scorer, caught the most dangerous case. The vetoes are therefore
the load-bearing part of this module, and they are veto-only: they can fail a claim
the scorer passed, never the reverse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .grounding_corpus import CorpusStore, RetrievalUnavailable, record_spans
from .models import (COMPATIBILITY, PROHIBITED_SOURCES, Claim, ClaimVerdict,
                     ClaimType, RiskTier, Span)

TAU_HARD = 0.85
TAU_SOFT = 0.60


@dataclass
class GroundingReport:
    verdicts: list[ClaimVerdict] = field(default_factory=list)
    ok: bool = True
    reason_code: str = ""

    @property
    def citations(self) -> list[dict[str, Any]]:
        return [v.citation for v in self.verdicts if v.citation]

    @property
    def unsupported(self) -> list[ClaimVerdict]:
        return [v for v in self.verdicts if not v.supported]


class GroundingVerifier:
    def __init__(self, corpus: CorpusStore, tau_hard: float = TAU_HARD,
                 tau_soft: float = TAU_SOFT, regime=None) -> None:
        self.corpus = corpus
        self.tau_hard = tau_hard
        self.tau_soft = tau_soft
        self.regime = regime
        #: Regime supplies the matrix; the ENFORCEMENT of it is spine. Note that
        #: healthcare's and finance's matrices are structurally identical -- only
        #: the source-class LABELS differ. That is what "replaced source set,
        #: unchanged mechanism" means concretely.
        self.compatibility = regime.compatibility if regime else COMPATIBILITY

    # -- public API -------------------------------------------------------------

    def verify(self, claims: list[Claim], *, tenant: str, record: dict | None,
               tier: RiskTier) -> GroundingReport:
        report = GroundingReport()
        for claim in claims:
            if claim.type is ClaimType.NON_FACTUAL:
                # Exempt -- but the exemption is RECORDED, so nothing is quietly excused.
                report.verdicts.append(
                    ClaimVerdict(claim.id, True, 1.0, None, "NON_FACTUAL_EXEMPT"))
                continue
            report.verdicts.append(self._verify_claim(claim, tenant, record))

        unsupported = report.unsupported
        if not unsupported:
            return report

        # Policy by tier. grounding/hallucination-containment.md §6.
        if tier is RiskTier.T3:
            report.ok = False
            report.reason_code = unsupported[0].reason_code
        else:
            report.ok = True  # claim is stripped by the caller; output survives
            report.reason_code = "CLAIMS_STRIPPED"
        return report

    # -- per-claim --------------------------------------------------------------

    def _verify_claim(self, claim: Claim, tenant: str, record: dict | None) -> ClaimVerdict:
        allowed = set(self.compatibility.get(claim.type, set()))
        if not allowed:
            return ClaimVerdict(claim.id, False, 0.0, None, "NO_COMPATIBLE_SOURCE_CLASS")

        if claim.type is ClaimType.REPORTED_STATEMENT:
            # A patient's reported statement is legitimate content when ATTRIBUTED.
            # A containment that refused this would be over-tuned, and over-tuning
            # produces workarounds (red-team C2).
            return ClaimVerdict(claim.id, True, 1.0,
                                {"doc": "USER_ASSERTION", "attributed": True},
                                "ATTRIBUTED_NOT_ASSERTED")

        # A universal negative ranges over everything absent from the record. No span
        # can support it (red-team A2).
        if claim.is_universal_negative:
            return ClaimVerdict(claim.id, False, 0.0, None, "UNIVERSAL_NEGATIVE_UNPROVABLE")

        try:
            spans = self.corpus.retrieve(
                tenant=tenant, text=claim.text,
                allowed_classes=allowed - PROHIBITED_SOURCES)
        except RetrievalUnavailable:
            return ClaimVerdict(claim.id, False, 0.0, None, "RETRIEVAL_UNAVAILABLE")

        if record is not None:
            spans += [s for s in record_spans(record, self.regime)
                      if s.source_class in allowed and _overlap(claim.text, s.text)]

        best: tuple[float, Span | None] = (0.0, None)
        for span in spans:
            if span.source_class in PROHIBITED_SOURCES:
                continue  # circularity guard -- structural, not a prompt instruction
            veto = self._vetoes(claim, span)
            if veto:
                continue
            score = _entailment(claim.text, span.text)
            if score > best[0]:
                best = (score, span)

        score, span = best
        if span is None or score < self.tau_soft:
            return ClaimVerdict(claim.id, False, score, None, self._why_none(claim, spans))
        citation = {"doc": span.doc_id, "version": span.version, "span": span.offsets,
                    "hash": span.content_hash, "source_class": span.source_class.value}
        if score < self.tau_hard:
            # Kept, but flagged. Tier-3 reviewers see these highlighted, so attention
            # goes to the shakiest content rather than being spread evenly.
            return ClaimVerdict(claim.id, True, score, citation, "WEAKLY_SUPPORTED", True)
        return ClaimVerdict(claim.id, True, score, citation, "SUPPORTED")

    def _why_none(self, claim: Claim, spans: list[Span]) -> str:
        if claim.asserts_absence:
            return "ABSENCE_REQUIRES_POSITIVE_SPAN"
        if spans:
            return "NO_SUPPORTING_SPAN"
        return "NO_SUPPORTING_SPAN"

    # -- deterministic vetoes (veto-only: can fail, never pass) -----------------

    def _vetoes(self, claim: Claim, span: Span) -> str | None:
        """Nine checks. The red-team's top finding was to EXPAND this set rather
        than tune the thresholds: V2 caught an absence claim the entailment scorer
        rated 0.71 (above tau_soft, i.e. it would have been kept and flagged).

        Every check here is one where a learned verifier is unreliable exactly where
        the stakes are highest -- a transposed digit, a dropped negation, a swapped
        comparator are all small semantic distances and large real ones.
        """
        # V1 entity binding: a subject-specific claim must be grounded on THIS
        # subject's record. A span from another subject fails regardless of similarity.
        if claim.type in (ClaimType.SUBJECT_SPECIFIC_FACT,
                          ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION):
            if span.source_class.value == "S1" and span.subject_ref != claim.subject_ref:
                return "ENTITY_BINDING"

        # V2 polarity: an absence claim needs a POSITIVE span asserting the absence.
        # An empty field never supports "no known allergy" / "no prior disputes".
        if claim.asserts_absence and not span.asserts_absence:
            return "POLARITY"

        # V3 temporal fidelity: a claimed date must appear in the span. Checked
        # BEFORE the numeric check, because a date is also a bag of digits and the
        # numeric veto would otherwise fire first with a less informative reason
        # code. Reason codes are read by humans during incidents; precision matters.
        claim_dates = set(_DATE_RE.findall(claim.text))
        if claim_dates and not claim_dates <= set(_DATE_RE.findall(span.text)):
            return "TEMPORAL_FIDELITY"

        # V4 numeric fidelity: every number in the claim must appear in the span.
        # Date digits are excluded, having already been checked above.
        claim_nums = _numbers(_DATE_RE.sub(" ", claim.text))
        span_nums = _numbers(_DATE_RE.sub(" ", span.text))
        if claim_nums and not claim_nums <= span_nums:
            return "NUMERIC_FIDELITY"

        # -- added after the red-team (stretch/red-team-grounding.md §What it taught)

        # V5 unit fidelity: the right number with the wrong unit is a dosing error in
        # healthcare and a pricing error in finance. "500 mg" vs "500 mcg" passes V3.
        claim_units = _units(claim.text)
        if claim_units and not claim_units <= _units(span.text):
            return "UNIT_FIDELITY"

        # V6 comparator direction: "above 7.4" and "below 7.4" share every token and
        # every number. Token overlap cannot separate them; this can.
        c_cmp, s_cmp = _comparators(claim.text), _comparators(span.text)
        if c_cmp and s_cmp and not (c_cmp & s_cmp):
            return "COMPARATOR_DIRECTION"

        # V7 quantifier strength: a span saying "some patients" cannot support a
        # claim saying "all patients". Strengthening a quantifier is fabrication.
        if _quantifier_rank(claim.text) > _quantifier_rank(span.text):
            return "QUANTIFIER_STRENGTH"

        # V8 modality: a span expressing possibility ("may", "can") cannot support a
        # claim expressing necessity ("must", "requires"). This is how a guideline
        # becomes a mandate in a single paraphrase.
        if _modality_rank(claim.text) > _modality_rank(span.text):
            return "MODALITY_STRENGTH"

        # V9 negation parity: an odd/even mismatch in negation markers between claim
        # and span, when they otherwise overlap heavily, means the paraphrase flipped
        # the sentence. Cheap, and catches the most embarrassing class of error.
        if _negations(claim.text) != _negations(span.text) and not claim.asserts_absence:
            if _toks(claim.text) & _toks(span.text):
                return "NEGATION_PARITY"
        return None


def _entailment(claim: str, span: str) -> float:
    """Stand-in for a verifier model run SEPARATELY from the generator.

    Independence is the point, not model quality: a generator asked to check itself
    shares its errors. Token-overlap here keeps the tests deterministic; the control
    logic around it is what the prototype demonstrates.
    """
    c = _toks(claim)
    s = _toks(span)
    if not c:
        return 0.0
    return len(c & s) / len(c)


def _overlap(a: str, b: str) -> bool:
    return bool(_toks(a) & _toks(b))


def _toks(text: str) -> set[str]:
    #: Generic function words only. An earlier version had "patient" in here, which
    #: silently made every claim about a patient slightly easier to ground -- a
    #: sector assumption hiding in a stopword list.
    stop = {"the", "is", "was", "her", "his", "and", "for", "with", "has", "have",
            "this", "that", "she", "he", "on", "at", "in", "of", "a", "an", "their"}
    return {t.strip(".,:;()%").lower() for t in text.split()
            if len(t) > 2 and t.lower() not in stop}


# -- helpers for the deterministic vetoes -------------------------------------
# Deliberately dumb and readable. Each is a rule an auditor can check by eye,
# which is the property that makes a veto trustworthy where a score is not.

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_UNIT_RE = re.compile(r"\b(mg|mcg|g|kg|ml|l|%|bpm|mmhg|units?|usd|eur|gbp|bps)\b", re.I)
_CMP_UP = {"above", "over", "greater", "exceeds", "higher", "at least", "or above", "≥"}
_CMP_DOWN = {"below", "under", "less", "lower", "beneath", "at most", "or below", "≤"}
_QUANT = {"none": 0, "no": 0, "rarely": 1, "some": 2, "several": 2, "many": 3,
          "most": 4, "usually": 4, "typically": 4, "all": 5, "every": 5, "always": 5}
_MODAL = {"may": 1, "might": 1, "can": 1, "could": 1, "should": 2, "recommended": 2,
          "must": 3, "requires": 3, "required": 3, "shall": 3}
_NEG = {"no", "not", "never", "without", "denies", "absent", "excluded"}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+\.?\d*", text))


def _units(text: str) -> set[str]:
    return {u.lower() for u in _UNIT_RE.findall(text)}


def _comparators(text: str) -> set[str]:
    low = text.lower()
    out = set()
    if any(w in low for w in _CMP_UP):
        out.add("up")
    if any(w in low for w in _CMP_DOWN):
        out.add("down")
    return out


def _quantifier_rank(text: str) -> int:
    ranks = [_QUANT[w] for w in _toks(text) | set(text.lower().split()) if w in _QUANT]
    return max(ranks) if ranks else -1


def _modality_rank(text: str) -> int:
    ranks = [_MODAL[w] for w in text.lower().split() if w in _MODAL]
    return max(ranks) if ranks else -1


def _negations(text: str) -> int:
    """Parity, not count: two negations cancel, one flips."""
    return sum(1 for w in text.lower().split() if w.strip(".,") in _NEG) % 2
