"""The two regime profiles, side by side.

Maps to: portability/portability-analysis.md.

Reading these two objects next to each other IS the portability analysis. Everything
that differs between healthcare and finance appears below. Everything that does not
appear below is spine, and lives in code that neither profile can reach.
"""
from __future__ import annotations

from .models import ClaimType, DataClass, RiskTier, SourceClass
from .regime import Capability, ConformanceRule, MaterialityRule, Regime

# =============================================================================
# HEALTHCARE — HIPAA
# =============================================================================

HEALTHCARE_FIELDS: dict[str, DataClass] = {
    "patient.name": DataClass.D3, "patient.mrn": DataClass.D3,
    "patient.ssn": DataClass.D3, "patient.phone": DataClass.D3,
    "patient.email": DataClass.D3, "patient.address": DataClass.D3,
    "insurance.member_id": DataClass.D3,
    "patient.dob": DataClass.D1, "encounter.date": DataClass.D1,
    "problem_list[]": DataClass.D2, "medications[]": DataClass.D2,
    "labs[]": DataClass.D2, "allergies[]": DataClass.D2,
    "notes[].text": DataClass.D2, "vitals[]": DataClass.D2,
    "encounter.reason": DataClass.D2, "next_due[]": DataClass.D2,
}

HEALTHCARE_CAPABILITIES = {
    "qa.general": Capability("qa.general", "operations", [], RiskTier.T1, False),
    "qa.record": Capability(
        "qa.record", "treatment",
        ["problem_list[]", "medications[]", "labs[]", "allergies[]", "patient.dob"],
        RiskTier.T2, True),
    "draft.summary": Capability(
        "draft.summary", "treatment",
        ["problem_list[]", "medications[]", "labs[]", "allergies[]", "patient.dob",
         "notes[].text", "encounter.reason", "vitals[]"],
        RiskTier.T3, True),
    "action.schedule": Capability(
        "action.schedule", "treatment",
        ["problem_list[]", "medications[]", "next_due[]", "patient.dob"],
        RiskTier.T2, True, tools=["schedule.book", "refill.request"]),
}

HEALTHCARE_TOOLS = {
    "schedule.book": {"writes_record": False, "reversible": True, "tier": RiskTier.T2},
    "refill.request": {"writes_record": False, "reversible": False, "tier": RiskTier.T3},
}

HEALTHCARE = Regime(
    name="healthcare",
    statutes=("HIPAA Privacy Rule", "HIPAA Security Rule", "HIPAA Breach Notification"),
    field_class=HEALTHCARE_FIELDS,
    strictest_class=DataClass.D3,
    never_crosses=frozenset({DataClass.D3}),
    residency_required=True,
    residency_basis="tenant BAA and state law — HIPAA itself imposes none",
    retention_years={"documentation": 6, "records": 7, "audit": 6},
    relationship_name="care relationship",
    access_model="minimum-necessary",
    consequence_label="affects care or safety",
    t3_claim_types=frozenset({ClaimType.SUBJECT_SPECIFIC_FACT,
                              ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION}),
    owning_roles={RiskTier.T3: "supervising_clinician",
                  RiskTier.T2: "tenant_clinical_informatics_lead",
                  RiskTier.T1: "tenant_operations_manager"},
    #: The requesting clinician is the right person to approve their own referral
    #: draft; requiring a second clinician would be a much heavier control. What is
    #: recorded is that requester and approver were the same identity.
    self_approval_allowed=True,
    dual_approval_over_amount=None,
    compatibility={
        ClaimType.SUBJECT_SPECIFIC_FACT: frozenset({SourceClass.S1}),
        ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION: frozenset(
            {SourceClass.S1, SourceClass.S2, SourceClass.S3}),
        ClaimType.DOMAIN_FACT: frozenset({SourceClass.S2, SourceClass.S3}),
        ClaimType.ORGANISATIONAL_PROCESS: frozenset({SourceClass.S2, SourceClass.S4}),
        ClaimType.COMPLIANCE_ADMIN: frozenset({SourceClass.S4, SourceClass.S5}),
        ClaimType.REPORTED_STATEMENT: frozenset({SourceClass.USER_ASSERTION}),
        ClaimType.NON_FACTUAL: frozenset(),
    },
    source_class_labels={
        SourceClass.S1: "the patient's own record",
        SourceClass.S2: "tenant clinical protocol",
        SourceClass.S3: "licensed clinical reference",
        SourceClass.S4: "tenant operational policy",
        SourceClass.S5: "regulatory text",
    },
    #: EMPTY, and honestly so. Healthcare v1 has no positive output-conformance duty.
    #: The slot exists because finance and public sector need it (OQ-7).
    conformance_rules=(),
    materiality_rules=(
        MaterialityRule(
            "MAT-H1", "draft.summary",
            ("medication_list", "problem_list"),
            "A referral or visit summary that omits current medications or active "
            "problems misleads by omission even when every claim it makes is cited."),
    ),
    transforms={"patient.dob": "T-AGEBAND-v1", "labs[]": "T-RELDATE-v1",
                "notes[].text": "T-REDACT-v1", "encounter.date": "T-RELDATE-v1"},
    degraded_modes={"qa.record": "structured_record_view",
                    "draft.summary": "templated_skeleton",
                    "action.schedule": "manual_scheduling_with_protocol_defaults",
                    "qa.general": "keyword_search_over_policy_corpus"},
    degraded_notices={
        "qa.record": "AI assist is off. Showing the record directly.",
        "draft.summary": "AI assist is off. Here's the standard template with your "
                         "record data filled in.",
        "action.schedule": "AI assist is off. Suggested intervals come from your "
                           "clinic's protocol.",
        "qa.general": "AI assist is off. Here are matching policy documents."},
    degraded_views={
        "qa.record": (("problems", "problem_list[]"), ("medications", "medications[]"),
                      ("labs", "labs[]")),
        "draft.summary": (("problems", "problem_list[]"),
                          ("medications", "medications[]")),
        "action.schedule": (("problems", "problem_list[]"),)},
    degraded_default_docs=("SYN-VS-POL-003 Patient no-show policy",),
    s1_span_rules=(
        ("problem_list[]", "Problem"),
        ("medications[]", "Medication"),
        ("labs[]", "Lab"),
        ("allergies[]", "Allergy"),
    ),
    absence_markers=(
        ("allergy_status_documented", "No known drug allergies documented at intake"),
    ),
    capabilities=HEALTHCARE_CAPABILITIES,
    tool_registry=HEALTHCARE_TOOLS,
)

# =============================================================================
# FINANCE — GLBA / PCI DSS / SOX  (the portability peer, re-derived)
# =============================================================================

FINANCE_FIELDS: dict[str, DataClass] = {
    "customer.name": DataClass.D3, "customer.tin": DataClass.D3,
    "customer.ssn": DataClass.D3, "customer.phone": DataClass.D3,
    "customer.email": DataClass.D3, "customer.address": DataClass.D3,
    "account.number": DataClass.D3,
    # D4: cardholder data. Not merely "very sensitive" -- admitting it would pull the
    # whole agent environment into the PCI Cardholder Data Environment and its
    # assessment regime. So the design AVOIDS SCOPE rather than controlling access.
    "card.pan": DataClass.D4, "card.cvv": DataClass.D4, "card.track": DataClass.D4,
    "customer.dob": DataClass.D1, "transaction.date": DataClass.D1,
    "account.balance": DataClass.D2, "transactions[]": DataClass.D2,
    "credit.score_band": DataClass.D2, "products[]": DataClass.D2,
    "disputes[]": DataClass.D2, "notes[].text": DataClass.D2,
    "card.token": DataClass.D2,   # tokenised upstream -- this is what the agent sees
}

FINANCE_CAPABILITIES = {
    "qa.general": Capability("qa.general", "servicing", [], RiskTier.T1, False),
    "qa.account": Capability(
        "qa.account", "servicing",
        ["account.balance", "transactions[]", "products[]", "customer.dob"],
        RiskTier.T2, True),
    "draft.disclosure": Capability(
        "draft.disclosure", "servicing",
        ["account.balance", "transactions[]", "products[]", "credit.score_band",
         "customer.dob", "notes[].text", "disputes[]"],
        RiskTier.T3, True),
    "action.servicing": Capability(
        "action.servicing", "servicing",
        ["account.balance", "products[]", "customer.dob"],
        RiskTier.T2, True, tools=["dispute.file", "payment.initiate", "limit.change"]),
}

FINANCE_TOOLS = {
    "dispute.file": {"writes_record": False, "reversible": True, "tier": RiskTier.T2},
    "payment.initiate": {"writes_record": False, "reversible": False, "tier": RiskTier.T3},
    "limit.change": {"writes_record": False, "reversible": False, "tier": RiskTier.T3},
}

FINANCE = Regime(
    name="finance",
    statutes=("GLBA Safeguards + Privacy", "PCI DSS", "SOX §302/§404",
              "FCRA", "Reg E", "Reg Z"),
    field_class=FINANCE_FIELDS,
    strictest_class=DataClass.D4,
    #: TIGHTENED: two classes never cross, and D4 never enters the environment at all.
    never_crosses=frozenset({DataClass.D3, DataClass.D4}),
    #: RELAXED then TIGHTENED, context-dependent: neither GLBA nor PCI imposes general
    #: residency, but cross-border banking-secrecy and outsourcing rules can bite
    #: harder than a BAA. The MECHANISM is identical; only this flag moves.
    residency_required=False,
    residency_basis="no general statutory residency; cross-border/outsourcing rules "
                    "and PCI segmentation apply where relevant",
    #: TIGHTENED: more clocks, generally longer, and the audit trail itself becomes a
    #: retained business record because it evidences ICFR.
    retention_years={"documentation": 7, "records": 7, "audit": 7, "aml": 5},
    relationship_name="servicing relationship",
    access_model="need-to-know + cardholder-data isolation + segregation of duties",
    consequence_label="moves money or affects credit, eligibility, or account access",
    t3_claim_types=frozenset({ClaimType.SUBJECT_SPECIFIC_FACT,
                              ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION}),
    owning_roles={RiskTier.T3: "servicing_officer",
                  RiskTier.T2: "operations_lead",
                  RiskTier.T1: "product_operations_manager"},
    #: TIGHTENED -- and it REMOVES an option healthcare allowed. Under SOX, the same
    #: actor may not both initiate and approve a reporting-relevant transaction. Same
    #: component, opposite configuration: the clearest single illustration of a
    #: parameter that looks agnostic until the regime changes.
    self_approval_allowed=False,
    #: NEW AXIS: finance layers a QUANTITATIVE threshold on the qualitative tiers.
    #: Healthcare has no natural monetary axis, so this is None there.
    dual_approval_over_amount=10_000.0,
    compatibility={
        ClaimType.SUBJECT_SPECIFIC_FACT: frozenset({SourceClass.S1}),
        ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION: frozenset(
            {SourceClass.S1, SourceClass.S2, SourceClass.S3}),
        ClaimType.DOMAIN_FACT: frozenset({SourceClass.S2, SourceClass.S3}),
        ClaimType.ORGANISATIONAL_PROCESS: frozenset({SourceClass.S2, SourceClass.S4}),
        ClaimType.COMPLIANCE_ADMIN: frozenset({SourceClass.S4, SourceClass.S5}),
        ClaimType.REPORTED_STATEMENT: frozenset({SourceClass.USER_ASSERTION}),
        ClaimType.NON_FACTUAL: frozenset(),
    },
    #: REPLACED source set, IDENTICAL structure. Note the compatibility matrix above
    #: is byte-for-byte the same as healthcare's -- only the LABELS below change.
    source_class_labels={
        SourceClass.S1: "the customer's account and transaction system of record",
        SourceClass.S2: "product terms, fee schedules, servicing procedures",
        SourceClass.S3: "regulatory text, rate tables, published indices",
        SourceClass.S4: "complaint-handling and dispute procedures",
        SourceClass.S5: "Reg E / Reg Z / FCRA statutory text",
    },
    #: NEW CONTROL -- the finding the portability analysis produced. Healthcare does
    #: not have this and does not need it. Reg Z/E and FCRA mandate that certain
    #: output CONTAINS prescribed elements. Grounding checks that what IS said is
    #: supported; it cannot check that something required is PRESENT.
    conformance_rules=(
        ConformanceRule(
            "CONF-F1", "draft.disclosure",
            "An adverse-action notice must state the principal reasons, the source of "
            "the information relied on, and the consumer's right to a free report.",
            required_elements=("principal_reasons", "information_source",
                               "free_report_right", "dispute_rights"),
            citation="FCRA §615(a)"),
        ConformanceRule(
            "CONF-F2", "action.servicing",
            "Error-resolution communications must state the investigation timeline and "
            "the customer's provisional-credit rights.",
            required_elements=("investigation_timeline", "provisional_credit_rights"),
            citation="Reg E §1005.11"),
    ),
    materiality_rules=(
        MaterialityRule(
            "MAT-F1", "draft.disclosure",
            ("fees_applicable", "apr_or_rate"),
            "A disclosure that omits applicable fees or the rate misleads by omission "
            "even when every claim it makes is cited."),
    ),
    transforms={"customer.dob": "T-AGEBAND-v1", "transactions[]": "T-RELDATE-v1",
                "notes[].text": "T-REDACT-v1", "transaction.date": "T-RELDATE-v1"},
    degraded_modes={"qa.account": "structured_account_view",
                    "draft.disclosure": "templated_disclosure",
                    "action.servicing": "manual_servicing_forms",
                    "qa.general": "keyword_search_over_policy_corpus"},
    degraded_notices={
        "qa.account": "AI assist is off. Showing your account details directly.",
        "draft.disclosure": "AI assist is off. Here's the standard disclosure template.",
        "action.servicing": "AI assist is off. Please use the servicing forms.",
        "qa.general": "AI assist is off. Here are matching product documents."},
    degraded_views={
        "qa.account": (("balance", "account.balance"),
                       ("transactions", "transactions[]"), ("products", "products[]")),
        "draft.disclosure": (("balance", "account.balance"),
                             ("disputes", "disputes[]")),
        "action.servicing": (("products", "products[]"),)},
    degraded_default_docs=("SYN-VS-FIN-TERMS-001 Everyday Checking product terms",),
    s1_span_rules=(
        ("account.balance", "Balance"),
        ("transactions[]", "Transaction"),
        ("products[]", "Product"),
        ("disputes[]", "Dispute"),
        ("credit.score_band", "Credit band"),
    ),
    absence_markers=(
        ("no_prior_disputes_documented", "No prior disputes recorded for this account"),
    ),
    capabilities=FINANCE_CAPABILITIES,
    tool_registry=FINANCE_TOOLS,
)

REGIMES = {"healthcare": HEALTHCARE, "finance": FINANCE}
