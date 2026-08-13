"""The regime seam: everything a regulatory regime binds, in one object.

Maps to: portability/portability-analysis.md §8 (the explicit split).

This module IS the portability claim, expressed as code. The architecture asserts
that responsible agentic design has a SPINE (identical in every sector) and a
PARAMETER LAYER (bound per regime). If that is true, then swapping regimes should
require changing this file and nothing else.

`tests/test_portability.py` checks exactly that: it runs the finance regime through
the same pipeline, verifier, classifier, ledger, and queue objects, and asserts the
spine modules contain no sector-specific identifier.

Naming note: the claim types were originally PATIENT_SPECIFIC_FACT and
GENERAL_CLINICAL_FACT. They are now SUBJECT_SPECIFIC_FACT and DOMAIN_FACT, with the
old names kept as enum aliases. The rename is not cosmetic -- it was the first thing
the finance re-derivation forced, and it shows the healthcare names were sector labels
on a sector-neutral concept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .models import ClaimType, DataClass, RiskTier, SourceClass


@dataclass
class Capability:
    """A declared unit of agent functionality.

    Lives here rather than in policy.py so that a Regime can own the registry
    without policy.py and regimes.py importing each other.
    """

    name: str
    purpose: str
    allowlist: list[str]
    tier_floor: RiskTier
    requires_subject: bool
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConformanceRule:
    """A POSITIVE requirement on output form or content.

    Grounding is a negative check: nothing asserted may be unsupported. It is
    structurally blind to something being MISSING. Two of the four menu sectors need
    a positive check (finance disclosure completeness, public-sector accessibility),
    so the spine carries the slot and the regime supplies the rules. Empty for
    healthcare v1 -- that emptiness is the honest state, not an oversight (OQ-7).
    """

    rule_id: str
    applies_to: str            # capability name, or "*"
    description: str
    required_elements: tuple[str, ...]
    citation: str = ""


@dataclass(frozen=True)
class MaterialityRule:
    """Facts whose ABSENCE from an output is itself material (OQ-4).

    Claim-level grounding cannot see omission: every claim can be true and cited
    while the whole misleads by what it leaves out. This does not solve that -- it
    instruments it, by naming the facts a reader would expect and flagging their
    absence for the reviewer rather than blocking release.
    """

    rule_id: str
    applies_to: str
    expected_facts: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class Regime:
    # -- identity ---------------------------------------------------------------
    name: str
    statutes: tuple[str, ...]

    # -- FR-1 data handling [REGIME] --------------------------------------------
    field_class: dict[str, DataClass]
    strictest_class: DataClass
    never_crosses: frozenset[DataClass]
    residency_required: bool
    residency_basis: str
    retention_years: dict[str, float]

    # -- access model [REGIME] --------------------------------------------------
    relationship_name: str          # "care relationship" / "servicing relationship"
    access_model: str               # "minimum-necessary" / "need-to-know + CHD isolation"

    # -- FR-3 risk trigger [REGIME binding of an AGNOSTIC mechanism] ------------
    consequence_label: str          # "affects care" / "moves money or affects credit"
    t3_claim_types: frozenset[ClaimType]
    owning_roles: dict[RiskTier, str]
    self_approval_allowed: bool     # False under SOX segregation of duties
    dual_approval_over_amount: float | None

    # -- FR-4 grounding [REGIME source set on an AGNOSTIC mechanism] ------------
    compatibility: dict[ClaimType, frozenset[SourceClass]]
    source_class_labels: dict[SourceClass, str]

    # -- positive output duties [REGIME; absent in healthcare] ------------------
    conformance_rules: tuple[ConformanceRule, ...] = ()
    materiality_rules: tuple[MaterialityRule, ...] = ()

    #: Field-level transforms, by path. The transform FUNCTIONS are spine; which
    #: paths need them is regime.
    transforms: dict[str, str] = field(default_factory=dict)
    #: Degraded-mode behaviour per capability: mode name, user notice, and the
    #: deterministic view (label -> record path) served when AI is off.
    degraded_modes: dict[str, str] = field(default_factory=dict)
    degraded_notices: dict[str, str] = field(default_factory=dict)
    degraded_views: dict[str, tuple] = field(default_factory=dict)
    degraded_default_docs: tuple[str, ...] = ()

    #: How the subject's own record becomes S1 spans. Found the hard way: the first
    #: version of `record_spans()` hardcoded problem_list/medications/labs/allergies,
    #: which meant a finance customer's balance produced NO S1 span and every
    #: account-specific claim was refused. A spine function with a healthcare field
    #: list in it was a spine leak, and only building the second regime exposed it.
    s1_span_rules: tuple[tuple[str, str], ...] = ()
    #: Record flags that constitute an EXPLICIT documented absence (as opposed to an
    #: empty field, which supports nothing). See the polarity veto.
    absence_markers: tuple[tuple[str, str], ...] = ()

    # -- capability + tool registries -------------------------------------------
    capabilities: dict[str, Any] = field(default_factory=dict)
    tool_registry: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Shared spine constants -- NOT part of any regime.
# =============================================================================

#: Never admissible as grounding, in any sector. The circularity guard is spine.
PROHIBITED_SOURCES = frozenset({SourceClass.MODEL_GENERATED})

#: Tier ordering, max-rule, round-up-on-ambiguity, expire-closed, fail-closed:
#: all spine. None of them appears in a Regime, because none of them varies.
SPINE_INVARIANTS = (
    "tamper_evident_reference_only_audit",
    "named_owning_role_per_decision_class",
    "risk_tiered_hitl_on_irreversibility_and_harm",
    "grounding_or_refuse_with_prohibited_self_grounding",
    "toggleable_ai_conjunctive_fail_closed_with_degraded_mode",
    "minimization_at_the_model_boundary_with_a_manifest",
    "tenant_isolation",
    "no_training_on_tenant_data",
    "fail_closed_everywhere",
)
