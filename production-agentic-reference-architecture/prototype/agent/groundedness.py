"""Semantic groundedness — closes threat-model R3 / ADR-012 cut 4.

The output guardrail previously checked only that a claim bullet *carried* a citation
marker. That is structural: `- The sky is green [S1]` passed. Three failures slipped
through:

  * **misattribution** — the claim is true of some source, but not of the one cited;
  * **fabrication** — the claim's content appears in no source at all;
  * **numeric drift** — the source says twenty percent, the claim says fifty.

This module checks that each claim is actually *supported by the specific source it
cites*, against the fetched document text (not the summary, so a bad summary cannot
launder a bad claim).

## Why lexical support rather than an NLI model

An entailment model is the better instrument and remains the production
recommendation. It is not used here because it would mean a model download, a
non-deterministic gate (ADR-014), and an inference cost on every claim. What is
implemented instead is a **conservative lexical support test**, chosen because it is
deterministic, explainable in a trace event, and — importantly — its failure mode is
the safe one: it flags claims a human should check rather than silently passing them.

Three signals, each catching a different failure:

  1. **Content-word coverage.** The claim's content words must be substantially present
     in the cited document. Catches fabrication and misattribution.
  2. **Numeric grounding.** Every number in the claim — **digits or spelled out** —
     must appear in the cited document. Catches numeric drift, which coverage alone
     misses because "twenty" and "ninety" are both single ordinary-looking tokens.
  3. **Invented negation.** A claim that negates ("cannot", "never", "does not") while
     the source sentence it most closely matches does not is flagged. Catches polarity
     inversion, where a claim borrows a source's vocabulary and reverses its meaning.

     Deliberately one-directional. Flagging the reverse case (source negated, claim
     not) was tried and produced false positives immediately: sources contain
     incidental negations in neighbouring clauses ("cost is *not* a standard
     attribute"), and a whole-sentence polarity comparison attributes them to the
     claim. Checking only the single best-matching sentence, and only for negations the
     claim introduces, keeps the control useful without making it cry wolf.

## What this does NOT establish

It does not establish truth, and it does not establish entailment in the logical
sense. A claim that copies its source faithfully passes even if the source is wrong,
and a correctly-paraphrased claim using different vocabulary can be flagged
(a false positive, which is the direction to err in). The honest summary: this closes
the gap between "has a citation" and "is traceable to the cited text", and leaves the
gap between that and "is true" explicitly open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Function words carry no support signal; including them would let any grammatical
# sentence score well against any document.
_STOP = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "is", "are", "was",
    "were", "be", "been", "being", "with", "as", "at", "by", "from", "that", "this",
    "these", "those", "it", "its", "their", "there", "which", "who", "whom", "what",
    "when", "where", "how", "why", "than", "then", "so", "but", "if", "into", "over",
    "under", "more", "most", "less", "least", "can", "will", "would", "should", "may",
    "might", "must", "also", "only", "such", "because", "while", "both", "each",
    "other", "some", "any", "all", "not", "no", "does", "do", "did", "has", "have",
    "had", "one", "two", "per", "up", "out", "about", "between", "through", "during",
}

_NEGATIONS = {
    "not", "never", "no", "cannot", "cant", "won't", "wont", "doesn't", "doesnt",
    "isn't", "isnt", "aren't", "arent", "without", "fails", "fail", "unable",
    "neither", "nor", "rarely", "seldom",
}

# Claim bullets, excluding the Sources list (whose bullets start with a citation).
_CLAIM_LINE = re.compile(r"^\s*[-*]\s+(?!\[S)(.+?)\s*\[(S\d+|SYSTEM)\]\s*$")
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")

#: Spelled-out numbers must be graded too. "twenty to forty percent" versus "ninety to
#: ninety-nine percent" is numeric drift, but coverage alone scores it as ordinary
#: vocabulary variation — found by testing the check against its own claims.
_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "half", "third", "quarter", "double", "triple",
}


def numeric_tokens(text: str) -> set[str]:
    """Digits and number words, so drift is caught in either notation."""
    lowered = text.lower()
    found = set(_NUMBER.findall(lowered))
    # split on hyphens too: "ninety-nine" is two number words
    for word in re.findall(r"[a-z]+", lowered):
        if word in _NUMBER_WORDS:
            found.add(word)
    return found

#: A claim must have at least this share of its content words present in the cited
#: source. 0.6 rather than 1.0 because extractive claims are lightly edited
#: (pluralisation, dropped clauses) and demanding total coverage would flag every
#: legitimate claim. Tuning this is a governed change — it is a gate threshold.
COVERAGE_THRESHOLD = 0.6

#: Claims shorter than this have too few content words for coverage to mean anything;
#: they are checked for numeric and negation parity only.
MIN_CONTENT_WORDS = 3


def content_words(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]*", text.lower())
    return [w for w in words if w not in _STOP and len(w) > 2]


def _stem(word: str) -> str:
    """Crude suffix stripping so `topologies` matches `topology`.

    Not a real stemmer. It exists so that ordinary morphological variation does not
    produce false positives; being crude costs recall of true positives, which is the
    right direction for a control that flags rather than blocks.
    """
    for suffix in ("ations", "ation", "ingly", "ing", "ies", "ied", "es", "ed", "s", "ly"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            base = word[: -len(suffix)]
            return base[:-1] if suffix in ("ies", "ied") else base
    return word


def _stems(words: list[str]) -> set[str]:
    return {_stem(w) for w in words}


@dataclass
class ClaimVerdict:
    claim: str
    citation: str
    supported: bool
    coverage: float
    reasons: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)

    def as_event(self) -> dict[str, Any]:
        return {
            "claim": self.claim[:140],
            "citation": self.citation,
            "supported": self.supported,
            "coverage": round(self.coverage, 3),
            "reasons": self.reasons,
            "missing_terms": self.missing_terms[:6],
        }


@dataclass
class GroundednessReport:
    verdicts: list[ClaimVerdict]

    @property
    def unsupported(self) -> list[ClaimVerdict]:
        return [v for v in self.verdicts if not v.supported]

    @property
    def support_rate(self) -> float:
        return 1.0 if not self.verdicts else sum(v.supported for v in self.verdicts) / len(self.verdicts)

    def metrics(self) -> dict[str, Any]:
        return {
            "claims_checked": len(self.verdicts),
            "claims_unsupported": len(self.unsupported),
            "support_rate": round(self.support_rate, 4),
            "mean_coverage": round(
                sum(v.coverage for v in self.verdicts) / len(self.verdicts), 3
            ) if self.verdicts else 1.0,
        }


def parse_claims(report_markdown: str) -> list[tuple[str, str]]:
    """Return (claim_text, citation_id) for every cited claim bullet."""
    body = report_markdown.split("## Sources")[0]
    out: list[tuple[str, str]] = []
    for line in body.splitlines():
        m = _CLAIM_LINE.match(line)
        if m:
            out.append((m.group(1).strip(), m.group(2)))
    return out


#: The best-matching sentence must share at least this share of the claim's terms
#: before its polarity is treated as the claim's reference point. Below it, "closest
#: sentence" is not a meaningful notion and the comparison would be noise.
_NEGATION_MATCH_THRESHOLD = 0.5


def _best_supporting_sentence(claim_terms: set[str], source_text: str) -> str | None:
    """The single source sentence that most closely matches the claim, if any does."""
    if not claim_terms:
        return None
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", source_text) if s.strip()]
    best_score, best = 0.0, None
    for sentence in sentences:
        overlap = len(claim_terms & _stems(content_words(sentence))) / len(claim_terms)
        if overlap > best_score:
            best_score, best = overlap, sentence
    return best if best_score >= _NEGATION_MATCH_THRESHOLD else None


def check_claim(claim: str, citation: str, source_text: str) -> ClaimVerdict:
    reasons: list[str] = []
    claim_words = content_words(claim)
    claim_terms = _stems(claim_words)
    source_terms = _stems(content_words(source_text))

    if claim_terms:
        present = claim_terms & source_terms
        coverage = len(present) / len(claim_terms)
        missing = sorted(claim_terms - source_terms)
    else:
        coverage, missing = 1.0, []

    if len(claim_words) >= MIN_CONTENT_WORDS and coverage < COVERAGE_THRESHOLD:
        reasons.append("insufficient_lexical_support")

    # numeric grounding — every number in the claim, digit or spelled out, must
    # appear in the source
    claim_numbers = numeric_tokens(claim)
    source_numbers = numeric_tokens(source_text)
    ungrounded_numbers = claim_numbers - source_numbers
    if ungrounded_numbers:
        reasons.append("ungrounded_number")
        missing = missing + sorted(ungrounded_numbers)

    # invented negation — a negation the claim adds that its closest source sentence
    # does not have. One-directional and best-match-only; see the module docstring.
    claim_neg = bool(set(re.findall(r"[a-z']+", claim.lower())) & _NEGATIONS)
    if claim_neg:
        best = _best_supporting_sentence(claim_terms, source_text)
        if best is not None and not (set(re.findall(r"[a-z']+", best.lower())) & _NEGATIONS):
            reasons.append("invented_negation")

    return ClaimVerdict(
        claim=claim,
        citation=citation,
        supported=not reasons,
        coverage=coverage,
        reasons=reasons,
        missing_terms=missing,
    )


def check_report(
    report_markdown: str, source_texts: dict[str, str]
) -> GroundednessReport:
    """Verify every cited claim against the text of the source it cites.

    `source_texts` maps citation id -> the *fetched document text*, deliberately not
    the summary: checking a claim against a summary that the same model produced would
    verify internal consistency rather than grounding.

    A claim citing an id with no known source is unsupported, not skipped. Skipping it
    would make a dangling citation the easiest way to bypass this control.
    """
    verdicts: list[ClaimVerdict] = []
    for claim, citation in parse_claims(report_markdown):
        if citation == "SYSTEM":
            continue  # system-authored coverage notes cite no external source
        text = source_texts.get(citation)
        if text is None:
            verdicts.append(
                ClaimVerdict(claim, citation, False, 0.0, ["unknown_citation"], [])
            )
            continue
        verdicts.append(check_claim(claim, citation, text))
    return GroundednessReport(verdicts)
