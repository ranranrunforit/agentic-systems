# Obligation Inventory — Finance (GLBA / PCI DSS / SOX)

The [portability analysis](portability-analysis.md) re-derived the *controls* for
finance. This document does the step before that, which the analysis skipped: the full
**obligation inventory**, built from the regime outward, the same way
[the healthcare one](../control-mapping/obligation-inventory.md) was.

Why it matters: a re-derivation that starts from the healthcare controls and asks "what
changes?" can only ever find deltas to things healthcare already had. Starting from the
regime instead is what surfaces obligations with **no healthcare counterpart at all** —
and two of the three most interesting findings in this package came from exactly there.

## Who we are in the regime

Under GLBA we are a **service provider** to financial-institution tenants, contractually
bound under the Safeguards Rule. Under SOX we are a **service organisation** whose
controls form part of the tenant's internal control over financial reporting — which is
why a SOC 1-style report, not merely a BAA-equivalent, is the governing artefact. Under
PCI we aim to be **out of scope entirely**, which is a different posture from either.

Those three postures are not variations on the HIPAA business-associate relationship.
They are three simultaneous relationships with three different evidentiary regimes.

## A. GLBA — Safeguards Rule and Privacy Rule

| ID | Obligation | Architectural pressure |
|----|-----------|------------------------|
| F-G1 | Written security programme with a qualified individual accountable | Named ownership per decision class already exists (C-29); needs a designated individual at the programme level |
| F-G2 | Risk assessment covering foreseeable internal/external risks | Agent-specific threat model (C-09) |
| F-G3 | Access controls limiting NPI to those with a business need | Servicing-relationship predicate replaces the care-relationship predicate |
| F-G4 | Inventory of data, personnel, devices, systems | Capability registry + subprocessor register + field catalogue |
| F-G5 | Encryption of NPI in transit and at rest | C-17, unchanged |
| F-G6 | Secure development practices for in-house applications | CI guards, review gates |
| F-G7 | MFA for anyone accessing information systems | Authentication layer; stricter than HIPAA's general requirement |
| F-G8 | Change management procedures | Versioned allow-lists, ADR amendments, model-change records |
| F-G9 | Monitoring and logging of authorised user activity | The ledger, unchanged |
| F-G10 | Service-provider oversight and contractual requirements | Subprocessor register + flow-down |
| F-G11 | Incident response plan | Kill switch + degraded mode + incident runbook |
| F-G12 | **Privacy notice and opt-out for sharing with nonaffiliated third parties** | **No HIPAA counterpart.** A per-customer sharing preference gates certain processing |

F-G12 is the first genuinely new obligation: a **preference** that is neither consent
(edtech) nor restriction (HIPAA §164.522) but an opt-out with a defined scope. Our
subject-scope toggle handles it mechanically, which is the third time that mechanism has
turned out to cover an obligation it was not built for.

## B. PCI DSS — and the scope decision

| ID | Obligation | Architectural pressure |
|----|-----------|------------------------|
| F-P1 | Protect stored cardholder data; render PAN unreadable | **Avoided**: no CHD in the environment |
| F-P2 | Restrict access to CHD by business need to know | Avoided by the same route |
| F-P3 | Segment the Cardholder Data Environment | The agent environment is outside the CDE by construction |
| F-P4 | Do not store sensitive authentication data after authorisation | Avoided |
| F-P5 | Track and monitor all access to CHD | Avoided |
| F-P6 | Annual assessment / SAQ scope determination | Scope statement asserting the agent is out of scope, evidenced by the D4 exclusion |

**The whole PCI column is a scope-avoidance decision, not a control set**, and that is
the point. Under HIPAA, touching more PHI means applying more care to it. Under PCI,
touching CHD changes *which assessment regime the component lives under*. The
architectural response is therefore categorically different: tokenise upstream, classify
card data D4, and make D4 unreachable — so the correct evidence is an *absence* of
cardholder data rather than a set of controls over it.

This distinction does not exist anywhere in the healthcare inventory, and a delta-based
re-derivation would have rendered it as "minimum-necessary, but stricter". That would
have been wrong.

## C. SOX — internal control over financial reporting

| ID | Obligation | Architectural pressure |
|----|-----------|------------------------|
| F-S1 | Management assessment of ICFR (§404) | The ledger becomes evidence in an attestation, not merely an inspection artefact |
| F-S2 | Disclosure controls and procedures (§302) | Output affecting reported figures needs traceable approval |
| F-S3 | **Segregation of duties** | Initiator ≠ approver. **Removes an option healthcare allows** |
| F-S4 | Change control over financial systems | Model/threshold/allow-list changes become auditable changes to a financial system |
| F-S5 | Record retention supporting the financial statements | Longer clocks; the audit trail is itself a retained business record |
| F-S6 | Evidence of operating effectiveness over a period | Control-effectiveness sampling, not just design review |

F-S6 is the second structurally new obligation. HIPAA asks whether a control *exists and
is documented*. SOX asks whether it *operated effectively across a period*, which turns
things like approval dwell-time distributions and refusal rates from useful telemetry
into **required evidence**. Our anti-rubber-stamp instrumentation was built as a
governance nicety; under SOX it is closer to mandatory.

## D. Consumer-facing obligations with no healthcare counterpart

| ID | Obligation | Architectural pressure |
|----|-----------|------------------------|
| F-C1 | **FCRA adverse action**: state principal reasons, the information source, and the right to a free report | The audit trail acquires a **consumer** audience; structured `why.reason_code` becomes externally visible |
| F-C2 | **Reg E** error resolution: investigation timelines, provisional credit | Output must *contain* prescribed elements |
| F-C3 | **Reg Z** disclosure content and timing | Same |
| F-C4 | Prohibition on unfair, deceptive, or abusive acts | Misleading-by-omission stops being a quality concern and becomes a legal one |
| F-C5 | Complaint handling and response tracking | Escalation paths must produce a complaint record |

F-C1 through F-C3 are what produced the **output-conformance verifier** (OQ-7): a
positive check that mandated elements are present. Grounding cannot do this; it is a
negative check by construction.

F-C4 is the uncomfortable one. Under HIPAA, misleading-by-omission is a clinical-quality
risk we instrument and flag (OQ-4). Under UDAAP it is potentially a violation. The same
unsolved problem carries materially higher stakes in the second sector — which is worth
recording precisely because the honest answer is that the design does not solve it in
either.

## E. Model risk governance (supervisory expectation, not statute)

| ID | Expectation | Architectural pressure |
|----|-------------|------------------------|
| F-M1 | Model inventory | The model registry and version records exist |
| F-M2 | **Independent validation** before use and periodically | New: a validation function separate from the builders |
| F-M3 | Ongoing performance monitoring | Refusal rates, weak-support rates, override rates |
| F-M4 | Documentation sufficient for a third party to understand the model | This package, roughly |

F-M2 has no HIPAA analogue and cannot be satisfied by architecture alone — it requires an
organisational function. Recorded as an open question for the finance port.

## What the two inventories, compared, actually show

| | Healthcare | Finance |
|---|---|---|
| Obligations inventoried | 22 | 33 |
| Satisfiable by architecture alone | ~18 | ~24 |
| Requiring an organisational function | 4 (privacy officer, workforce training, BAAs, incident response) | 9 (+ independent validation, attestation, complaint handling, sharing preferences, scope assessment) |
| Obligations with **no counterpart** in the other sector | Minimum-necessary; accounting of disclosures; de-identification standard | PCI scope semantics; segregation of duties; FCRA/Reg E/Z content duties; operating-effectiveness evidence; model validation |

The bottom row is the honest summary of what porting costs. The **spine transferred
completely** — [the prototype proves that by construction](../prototype/tests/test_portability.py) —
and finance still brought five obligation families that healthcare never raised. Portable
does not mean free.
