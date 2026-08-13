# Sector Deltas — Public Sector and Edtech

Stretch goal: extend the portability analysis to the remaining two menu sectors, and
surface the controls that differ across **all four**. Less depth than the
[finance re-derivation](portability-analysis.md), but each of the five FRs is re-derived
and classified.

---

## Part 1 — Public sector

**Scenario:** CARA-P, an agentic assistant inside a state benefits agency (fictitious
`SYN-TEN-stateagency`), answering caseworker questions over case files, drafting
determination notices, and taking bounded case actions.

Regime shape: records-retention schedules, public-records/FOIA-style disclosure,
accessibility (Section 508 / WCAG), authorization-to-operate (FedRAMP/StateRAMP-style),
and — because these are government determinations affecting rights — **due-process
obligations**.

### FR-1 Data handling
| Element | Change | Class |
|---|---|---|
| Taxonomy | PHI → PII in case files, plus **FOIA-exempt categories** (deliberative process, law-enforcement, personal-privacy exemptions) as a first-class label | **Replaced** |
| Access model | Minimum-necessary → role-based case assignment, **plus a disclosure posture per field** (is this releasable on request?) | **Replaced** |
| Minimization mechanism | Filter + manifest | **Unchanged** |
| Residency | **Tightened** — ATO boundary defines an authorised environment; components outside it cannot process data at all, and the model endpoint must be inside the authorisation boundary | **Tightened** |
| Retention | **Replaced** — records schedules are *mandatory minimums with mandatory disposition*: records must be kept **and** destroyed on schedule, with archival transfer for permanent records. "Delete on request" is often prohibited | **Replaced** |

The retention inversion is worth pausing on: in healthcare and edtech, deletion rights push
toward erasure; in public sector, a records schedule can make erasure **unlawful**. The
same deletion pipeline is therefore configured with a `disposition` action
(destroy / transfer-to-archive / retain-permanently) rather than a simple delete, and
legal hold is replaced by a broader records-hold concept.

### FR-2 Auditability
| Element | Change | Class |
|---|---|---|
| Hash-chained ledger, schema, inputs capture | **Unchanged** | **Unchanged** |
| **Disclosability of the log itself** | The audit trail may be a **public record** subject to disclosure requests | **New property — unique on this menu** |
| Accountability roles | Clinician → **determining official**; agency records officer owns disposition | Re-bound |
| **Due process / reason-giving** | A determination affecting a benefit must state its reasons to the affected person | **New (extends FR-2's audience again)** |

The disclosability property has a real architectural consequence: the reference-only design
(no raw sensitive content in the ledger) shifts from being a *retention* convenience to
being a *disclosure* safeguard. If the log can be released, embedding case content in it
would be a privacy incident, not merely a retention violation. Note that the FCRA finding
in finance and the due-process finding here are the same shape — the log gains a
consumer-facing audience — reached from two unrelated regimes. That convergence is weak
evidence that "explainability to the affected individual" belongs closer to the spine than
this design initially placed it. Recorded as OQ-6.

### FR-3 HITL
| Element | Change | Class |
|---|---|---|
| Axes, max-rule, round-up, expire-closed | **Unchanged** | **Unchanged** |
| Trigger | "affects care" → **"affects a right, benefit, eligibility, or an official record"** | **Replaced** |
| **New:** appealability | Any Tier-3 determination must be traceable to a named human and appealable; an unappealable automated determination is not permissible | **Tightened** |

### FR-4 Grounding
| Element | Change | Class |
|---|---|---|
| Pipeline, thresholds, prohibitions, refuse-or-escalate | **Unchanged** | **Unchanged** |
| Source classes | S1 = the official case file; S2/S3 = statute, regulation, published agency policy, precedent decisions | **Replaced** |
| **New:** accessibility of output | Output must meet accessibility standards (structure, alt text, plain-language reading level, screen-reader compatibility) | **New (regime-specific output duty)** |

Accessibility is the public-sector analogue of finance's disclosure-completeness: a
**positive** requirement on output form, which grounding (a negative check on content) does
not cover. Two of four sectors adding a positive output-conformance control suggests the
spine should probably include a generic *output-conformance verifier* slot, with the rules
supplied per regime. Recorded as OQ-7.

### FR-5 Toggles
**Unchanged**, with one addition: an ATO'd system typically requires that a change in
authorised components be reported, so *enabling* an AI feature may require a security
authorisation step. Turning it **off** remains one click — the safe direction is never
gated, in any sector.

---

## Part 2 — Education technology

**Scenario:** CARA-E, an agentic assistant inside a school district's learning platform
(fictitious `SYN-TEN-districtsixty`), answering staff questions over student records,
drafting progress narratives, and suggesting interventions. Some users are **under 13**.

Regime shape: **FERPA** (education records, parental rights, school-official exception,
directory information), **COPPA** (verifiable parental consent under 13), **PPRA**
(surveys), plus state student-privacy laws that impose direct vendor-data-use limits.

### FR-1 Data handling
| Element | Change | Class |
|---|---|---|
| Taxonomy | PHI → **education records** + directory information (a category with a *different default*: disclosable unless opted out) + behavioural/telemetry data | **Replaced** |
| Access model | Minimum-necessary → **legitimate educational interest** under the school-official exception | **Replaced** |
| Minimization mechanism | Filter + manifest | **Unchanged** |
| **Consent / age-gating** | **NEW AND STRUCTURAL** — verifiable parental consent for under-13 users; consent state gates processing *before* it starts | **New** |
| Vendor data-use limits | **Tightened** — state laws frequently prohibit vendor use of student data for product improvement, profiling, or advertising, and require deletion on district request | **Tightened** |
| Residency | Usually **relaxed** vs. healthcare (often contractual rather than statutory), though some states mandate in-country storage | **Relaxed (context-dependent)** |
| Retention | **Replaced** — district-set schedules plus deletion-on-request rights exercisable by parents or eligible students | **Replaced** |

**Consent is the single biggest structural difference across the whole menu.** In
healthcare, finance, and public sector, the lawful basis for processing is largely
established by the relationship (treatment, servicing, statutory duty) and the controls
constrain processing that is already permitted. In edtech, consent is a **precondition**:
the Policy Engine must resolve consent state *before* any allow-list is issued, and an
unresolved or withdrawn consent means the request never reaches the Minimization Filter at
all.

Architecturally this is a **new gate upstream of the existing gates** — the one place in
this analysis where a sector adds a step to the request path rather than re-parameterising
an existing one:

```
authn → tenant → [CONSENT GATE — edtech only] → policy/RBAC → flags → minimization → agent
```

Our existing subject-scope restriction flag (`ai_processing_restricted`, built for HIPAA
§164.522) is the closest existing mechanism and does most of the work — an accidental
piece of portability, since it was built for a different reason. It needs extending from a
binary restriction to a consent *record* (who consented, when, to what scope, verification
method, withdrawal state).

### FR-2 Auditability
**Unchanged** mechanism. Additions: FERPA's disclosure-record obligation maps onto the
existing `disclosures_by_subject` query almost exactly (it was built for §164.528 — the
same query, different statute), and the accountability roles re-bind to school officials.
**Unchanged / re-bound.**

### FR-3 HITL
| Element | Change | Class |
|---|---|---|
| Axes, max-rule, round-up, expire-closed | **Unchanged** | **Unchanged** |
| Trigger | "affects care" → **"affects a student's record, placement, discipline, or eligibility"** | **Replaced** |
| **New:** minor-specific caution | Output *directed to* a minor gets a lower automation threshold than output *about* a minor sent to staff — audience, not just subject, raises the tier | **Tightened** |

That last row adds a fifth axis the healthcare taxonomy did not need: **audience**. In
CARA every consumer is a clinician or the patient themselves; in CARA-E the consumer may
be a child, which changes the risk of the same content. A truly portable taxonomy should
carry `audience` as an axis from the start with a null binding where it doesn't apply.
Recorded as OQ-8.

### FR-4 Grounding
Pipeline **unchanged**. Source classes **replaced**: S1 = the student's education record;
S2 = district curriculum and policy; S3 = curriculum standards. New consideration: outputs
directed to minors have an **appropriateness** requirement layered on grounding — a claim
can be perfectly grounded and still be inappropriate for its audience. Another positive
output-conformance control (cf. OQ-7).

### FR-5 Toggles
**Unchanged**, plus a genuinely new scope: **per-guardian**. A parent may withdraw consent
for their child while the district keeps AI on for everyone else. Our subject-scope
restriction covers this once it carries a consent record rather than a boolean.

---

## Part 3 — What differs across all four

| Control | Healthcare | Finance | Public sector | Edtech |
|---|---|---|---|---|
| **Sensitive taxonomy** | PHI | NPI + **CHD (scope semantics)** | PII + FOIA-exempt categories | Education records + directory info |
| **Access model** | Minimum-necessary + care relationship | Need-to-know + CHD isolation + **SoD** | Case assignment + disclosure posture | Legitimate educational interest |
| **Consent** | Not a gate (treatment basis) | Not a gate (GLBA notice/opt-out for sharing) | Not a gate (statutory duty) | **Prerequisite gate (COPPA)** |
| **Residency** | Contractual (BAA), commonly pinned | Usually none; cross-border rules bite | **ATO boundary — tightest** | Usually contractual; some state mandates |
| **Retention** | State/tenant, deletion on expiry | SOX ~7 yr, BSA 5 yr, longer | **Mandatory disposition; deletion may be prohibited** | District schedule + deletion rights |
| **Audit log's audience** | Regulator, auditor, tenant | + external auditor, + **consumer (FCRA)** | + **the public (disclosable record)** | + parents/eligible students |
| **HITL trigger** | Affects care | Moves money / affects credit | Affects a right or benefit | Affects a student's record |
| **Extra HITL constraint** | — | SoD + dual approval over amount | Appealability | Audience is a minor |
| **Positive output duty** | — | Disclosure completeness | **Accessibility** | Age-appropriateness |
| **Attestation regime** | — | SOX ICFR + model risk validation | **ATO** | State privacy pledges/contracts |

Constant across all four columns — the spine, now tested four ways:

- Tamper-evident, reference-only, append-only audit with inputs captured.
- Named human ownership of every automated decision class.
- Risk-tiered HITL on irreversibility and harm, fail-closed, expire-closed.
- Grounding-or-refuse against vetted sources with prohibited self-grounding.
- Toggleable AI, conjunctive scopes, fail-closed, with a tested degraded mode.
- Minimization at the model boundary with a per-request manifest.
- Tenant isolation; no training on tenant data.

## Part 4 — Three findings the four-way comparison produced

1. **Consent is a gate, not a control.** Only edtech makes it a precondition, and it sits
   *upstream* of everything else. A design that models consent as "another policy check"
   will get the ordering wrong. The generalised architecture should carry a lawful-basis
   gate before the policy step, bound to `always_satisfied` in regimes where the
   relationship supplies the basis.
2. **Positive output-conformance is missing from the spine.** Finance wants mandated
   disclosures present, public sector wants accessibility, edtech wants
   age-appropriateness. Grounding only checks that what *is* said is supported. The
   generalised architecture should include an output-conformance verifier slot with
   per-regime rule sets — empty for healthcare v1.
3. **The audit log keeps acquiring new audiences.** Regulator (all), external auditor
   (finance), the affected individual (FCRA, due process), and the public (FOIA). Since
   three of four sectors extend it beyond the auditor, "explainable to the affected
   person" is probably a spine property that this design under-weighted by treating the
   `why` field as an internal artefact.

Findings 1–3 are recorded as open questions OQ-6, OQ-7, OQ-8 in
[SELF-ASSESSMENT.md](../SELF-ASSESSMENT.md) rather than retrofitted silently into the
healthcare design — the point of a portability analysis is to *discover* things, and a
discovery that is quietly back-ported leaves no evidence the analysis did any work.
