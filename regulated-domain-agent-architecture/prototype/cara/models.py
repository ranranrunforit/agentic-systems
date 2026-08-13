"""Core domain types.

Maps to: data-handling/data-classification.md, hitl/risk-taxonomy.md,
grounding/vetted-sources.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DataClass(str, Enum):
    """Sensitivity classes. The SCHEME is spine; the CONTENTS are regime-bound.

    data-handling/data-classification.md §Classes, and the finance re-derivation in
    portability/portability-analysis.md §2a, which adds D4.
    """

    D0 = "D0"  # non-sensitive
    D1 = "D1"  # quasi-identifier — transform required before the model boundary
    D2 = "D2"  # sensitive domain data (PHI clinical / NPI) — allow-list gated
    D3 = "D3"  # direct identifier — never crosses the model boundary
    #: D4 exists only under PCI. It is NOT "D3 with a different name": PCI restricts
    #: the SCOPE OF THE ENVIRONMENT that touches cardholder data, so the design move
    #: is scope avoidance (tokenise upstream, never admit it) rather than
    #: minimization. See portability/portability-analysis.md §2a.
    D4 = "D4"  # cardholder data — out of scope by construction

    @staticmethod
    def default() -> "DataClass":
        """Unclassified fields default to the strictest class. Deliberate friction."""
        return DataClass.D3


class RiskTier(int, Enum):
    """hitl/risk-taxonomy.md. Ordered so max() implements the max-rule."""

    T1 = 1  # general, non-individual, informational
    T2 = 2  # individual record restatement / reversible proposal
    T3 = 3  # clinical assertion, care action, or irreversible


class ClaimType(str, Enum):
    """grounding/vetted-sources.md §4 compatibility matrix.

    Sector-neutral names. The healthcare-flavoured names below them are ENUM
    ALIASES, kept so nothing that predates the finance re-derivation had to change.

    The rename is itself a finding: "patient-specific fact" and "account-specific
    fact" are the same concept wearing a sector's clothes. Discovering that the
    original names were regime-bound is the kind of thing a portability analysis is
    supposed to surface, and it only surfaced once a second regime was built.
    """

    SUBJECT_SPECIFIC_FACT = "subject_specific_fact"
    SUBJECT_SPECIFIC_RECOMMENDATION = "subject_specific_recommendation"
    DOMAIN_FACT = "domain_fact"
    ORGANISATIONAL_PROCESS = "organisational_process"
    COMPLIANCE_ADMIN = "compliance_admin"
    REPORTED_STATEMENT = "reported_statement"  # attributed, not asserted as record fact
    NON_FACTUAL = "non_factual"  # greetings, structure — exempt but recorded

    # -- aliases (same values => same members) ---------------------------------
    PATIENT_SPECIFIC_FACT = "subject_specific_fact"
    PATIENT_SPECIFIC_RECOMMENDATION = "subject_specific_recommendation"
    GENERAL_CLINICAL_FACT = "domain_fact"


class SourceClass(str, Enum):
    S1 = "S1"  # the patient's own record
    S2 = "S2"  # tenant clinical protocol
    S3 = "S3"  # licensed clinical reference
    S4 = "S4"  # tenant operational policy
    S5 = "S5"  # regulatory / statutory text
    MODEL_GENERATED = "model_generated"  # NEVER admissible — circularity guard
    USER_ASSERTION = "user_assertion"  # NEVER admissible as record fact


#: grounding/vetted-sources.md §4. A claim may only be grounded on a source class
#: authoritative for that KIND of claim. Similarity is not authority.
COMPATIBILITY: dict[ClaimType, set[SourceClass]] = {
    ClaimType.SUBJECT_SPECIFIC_FACT: {SourceClass.S1},
    ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION: {SourceClass.S1, SourceClass.S2, SourceClass.S3},
    ClaimType.DOMAIN_FACT: {SourceClass.S2, SourceClass.S3},
    ClaimType.ORGANISATIONAL_PROCESS: {SourceClass.S2, SourceClass.S4},
    ClaimType.COMPLIANCE_ADMIN: {SourceClass.S4, SourceClass.S5},
    ClaimType.REPORTED_STATEMENT: {SourceClass.USER_ASSERTION},
    ClaimType.NON_FACTUAL: set(),
}

#: Never admissible as grounding, in any sector. grounding/vetted-sources.md §3.
PROHIBITED_SOURCES = {SourceClass.MODEL_GENERATED}


@dataclass
class Claim:
    """One atomic, independently checkable assertion extracted from candidate output."""

    id: str
    text: str
    type: ClaimType
    subject_ref: str | None = None
    #: True when the claim asserts that something is absent ("no known allergy").
    #: Absence claims need a POSITIVE span; an empty field never supports one.
    asserts_absence: bool = False
    #: True when the claim ranges over everything not present ("nothing contraindicates").
    is_universal_negative: bool = False


@dataclass
class Span:
    """A retrieved passage, cited by reference — never copied into the audit ledger."""

    doc_id: str
    version: str
    offsets: str
    text: str
    source_class: SourceClass
    subject_ref: str | None = None  # set for S1 spans; used for entity binding
    asserts_absence: bool = False  # an explicit "no known drug allergies" entry
    content_hash: str = ""


@dataclass
class ClaimVerdict:
    claim_id: str
    supported: bool
    score: float = 0.0
    citation: dict[str, Any] | None = None
    reason_code: str = ""
    weakly_supported: bool = False


@dataclass
class Manifest:
    """data-handling/minimization-and-residency.md §The minimization_manifest.

    Field PATHS and counts, never values. This makes the manifest D0, so it can be
    retained on the longer audit clock and used for breach scoping (O-B2).
    """

    correlation_id: str
    tenant: str
    capability: str
    allowlist_version: str
    subject_ref: str | None
    subject_alias: str | None
    fields_included: list[dict[str, Any]] = field(default_factory=list)
    fields_excluded_by_class: list[str] = field(default_factory=list)
    prompt_hash: str = ""
    boundary: dict[str, str] = field(default_factory=dict)


@dataclass
class Outcome:
    """The result of a request through the pipeline."""

    decision: str  # released | refused | queued | expired | degraded | denied
    correlation_id: str
    tier: RiskTier | None = None
    text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    reason_code: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def released(self) -> bool:
        return self.decision == "released"
