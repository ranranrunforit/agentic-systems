# Obligation Inventory — Healthcare / HIPAA

Phase 1 output. This is the *input* to the control-mapping matrix: what the regime asks
of a system like CARA, before any architecture exists. Citations are to the regulation
structure (45 CFR Parts 160/164) for traceability; this is an architecture document, not
legal advice, and open interpretive questions are recorded rather than papered over
([ADR-010](../adrs/ADR-010-open-compliance-questions.md)).

## Who we are in the regime

CARA is deployed as a **business associate** of covered-entity tenants (ambulatory care
organisations). That single fact drives more of the design than any other: it means
(a) a BAA governs every tenant relationship, (b) our subcontractors — notably the
inference provider — are **subcontractor business associates** and need flow-down
agreements, and (c) we inherit Security Rule obligations directly, not merely by contract.

## A. Privacy Rule obligations

| ID | Obligation | Source (structure) | Architectural pressure |
|----|-----------|--------------------|------------------------|
| O-P1 | Use/disclose PHI only as permitted; treatment/payment/operations basis | §164.502 | Capability model must bind each agent capability to a permitted purpose |
| O-P2 | **Minimum necessary** for uses and disclosures | §164.502(b), §164.514(d) | The model boundary is a disclosure surface ⇒ field-level minimization must be enforced, not advised |
| O-P3 | Individual right of **access** to designated record set | §164.524 | Agent-produced content stored in the record must be retrievable and exportable |
| O-P4 | Right to **amend** | §164.526 | Agent output that entered the record must be amendable, with the amendment linked |
| O-P5 | **Accounting of disclosures** | §164.528 | Disclosures made via the agent must be enumerable per patient |
| O-P6 | Right to request **restrictions** / confidential communications | §164.522 | Per-patient restriction flags must suppress agent processing for that patient |
| O-P7 | **De-identification** standard if data is to be treated as non-PHI | §164.514(a)-(b) | Anything claimed "de-identified" must meet Safe Harbor or expert determination — no informal scrubbing claims |
| O-P8 | **Business associate contracts**; subcontractor flow-down | §164.502(e), §164.504(e) | Inference provider terms must include zero-retention, zero-training, region commitments |

## B. Security Rule obligations

| ID | Obligation | Source | Architectural pressure |
|----|-----------|--------|------------------------|
| O-S1 | Risk analysis and risk management | §164.308(a)(1) | Documented threat model incl. agent-specific threats (injection, exfiltration via prompts) |
| O-S2 | Workforce/role-based access management | §164.308(a)(3)-(4) | RBAC + care-relationship checks; scoped, revocable tokens |
| O-S3 | Information system activity review | §164.308(a)(1)(ii)(D) | Queryable audit trail; periodic review procedure |
| O-S4 | Incident response / security incident procedures | §164.308(a)(6) | Kill switch + degraded mode + audited toggle |
| O-S5 | Contingency plan / emergency mode operation | §164.308(a)(7) | Degraded mode must keep the product functional without AI |
| O-S6 | **Audit controls** on systems containing ePHI | §164.312(b) | Tamper-evident, append-only ledger |
| O-S7 | **Integrity** of ePHI | §164.312(c) | Hash-chaining, content hashes, no autonomous writes to the record |
| O-S8 | **Person/entity authentication** | §164.312(d) | OIDC + per-request capability tokens |
| O-S9 | **Transmission security** / encryption | §164.312(a)(2)(iv), (e) | TLS 1.3 in transit, AES-256 + tenant CMK at rest |
| O-S10 | Access control incl. unique user ID, automatic logoff | §164.312(a) | Unique subject IDs in every audit event; session and token TTLs |
| O-S11 | Policies/procedures and **documentation retention (6 years)** | §164.316 | Audit and control documentation retention clock ≥ 6 years |

## C. Breach Notification obligations

| ID | Obligation | Source | Architectural pressure |
|----|-----------|--------|------------------------|
| O-B1 | Notify covered entity of a breach without unreasonable delay (BA duty) | §164.410 | Detection + scoping must be possible from the ledger fast enough to support 60-day outer limits |
| O-B2 | Risk assessment to determine breach vs. exception | §164.402 | Need per-request record of *which fields* were exposed — the minimization manifest is the artefact that makes this answerable |
| O-B3 | Content/timeliness of notification | §164.404, §164.408 | Ledger queries must produce affected-individual lists by record reference |

## D. Retention obligations (note the split)

| ID | Obligation | Clock | Owner |
|----|-----------|-------|-------|
| O-R1 | HIPAA **documentation** retention: 6 years from creation or last effective date | 6 years | Us (BA) — applies to policies, audit documentation |
| O-R2 | **Medical record** retention: set by **state law and tenant policy**, not HIPAA | Tenant-configured (commonly 6–10 yrs adult; longer for minors) | Tenant (covered entity) |

O-R1/O-R2 being different clocks with different owners is why retention is configured
per tenant and why the audit trail must not embed PHI — see
[`data-handling/retention-and-deletion.md`](../data-handling/retention-and-deletion.md).

## E. Adjacent regimes we deliberately scope out (and why)

| Regime | Why relevant | Decision |
|--------|--------------|----------|
| 42 CFR Part 2 (substance-use-disorder records) | Stricter consent for SUD records | **Excluded from scope v1**: tenants must not enable CARA on Part 2 program data. Enforced by a tenant-level data-source allow-list. Open question OQ-2. |
| FDA clinical-decision-support rules | Diagnosis/dosing output could be a regulated device function | Design excludes diagnostic/dosing recommendations; Tier-3 gate plus a capability-level prohibition. Open question OQ-3. |
| State privacy laws (e.g. consumer health data acts) | May add consent/deletion duties beyond HIPAA | Deletion pipeline built to accept an external erasure trigger — see [consent & data-subject rights](../stretch/consent-and-data-subject-rights.md). |
| GDPR (if a tenant has EU data subjects) | Residency, DSR, DPIA | Residency mechanism already region-parameterised; treated as a config binding, not a redesign. |

## What this inventory shows about the sector menu

Two thirds of the pressures above (audit controls, integrity, authentication, activity
review, contingency operation) are stated in HIPAA but would be stated *somewhere* in any
of the four menu regimes — they are the regime's local name for controls that responsible
agentic design needs anyway. The genuinely HIPAA-shaped items are narrower than they look:
**minimum-necessary**, **BAA/subcontractor flow-down**, **accounting of disclosures**, the
**de-identification standard**, and the **breach-notification clock**. That split is the
hypothesis the [portability analysis](../portability/portability-analysis.md) tests.
