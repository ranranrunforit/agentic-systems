# Project 302 — Regulated-Domain Agentic Architecture

**System name:** CARA — *Clinical Assistance & Records Agent* 
**Primary sector:** Healthcare (HIPAA) — see [ADR-001](adrs/ADR-001-sector-choice.md) 
**Portability peer (fully re-derived):** Finance (GLBA / PCI DSS / SOX) 
**Additional sketched sectors:** Public sector, Education technology 

> **All records, identifiers, tenants, and organisations in this package are synthetic
> or clearly fictitious.** Synthetic identifiers are prefixed `SYN-` and fictitious
> tenants are named `Northwind Health`, `Meridian Clinics`, etc. No real regulated data
> appears anywhere in this repository. See
> [`data-handling/synthetic-records.md`](data-handling/synthetic-records.md).

---

## The one distinction this package is organised around

Every document below labels its controls with one of two tags:

| Tag | Meaning |
|-----|---------|
| **[AGNOSTIC]** | Intrinsic to responsible agentic design. Present in *every* sector on the menu. Only its *trigger* or *parameter set* is re-bound when the regime changes. |
| **[REGIME]** | Shaped by a specific regulatory regime. Changes — sometimes disappears — when the sector changes. |

The five **[AGNOSTIC]** controls (the *spine*): auditability, human-in-the-loop above a
risk threshold, grounding-or-refuse, toggleable AI with a degraded mode, and fail-closed
default.

The five **[REGIME]** control families (the *parameters*): data residency, consent /
age-gating, retention duration, breach notification, and the access model
(minimum-necessary vs. cardholder-data isolation vs. FOIA-style disclosure vs.
vendor-data-use limits).

The tags are not decoration. The [portability analysis](portability/portability-analysis.md)
is a proof obligation: every **[AGNOSTIC]** control must come out of the finance
re-derivation as *unchanged mechanism*, and every **[REGIME]** control must come out as
tightened, relaxed, or replaced. If a control crosses the line, the tag was wrong.

---

## Package map

| Path | Deliverable | Requirement |
|------|-------------|-------------|
| [`architecture/`](architecture/) | Reference architecture, container + sequence diagrams, trust boundaries | Deliverable 1 |
| [`control-mapping/`](control-mapping/) | Obligation → control → FR traceability matrix + evidence index | Deliverable 2, NFR-1 |
| [`data-handling/`](data-handling/) | Classification, minimization, residency, retention/deletion, synthetic fixtures | Deliverable 3, FR-1 |
| [`audit/`](audit/) | Audit-log specification, hash-chain design, accountability model | FR-2, NFR-3 |
| [`hitl/`](hitl/) | Risk taxonomy, approval threshold, approval/escalation flows | Deliverable 4, FR-3 |
| [`grounding/`](grounding/) | Vetted-source definition, grounding mechanism, refuse/escalate | Deliverable 5, FR-4 |
| [`toggles/`](toggles/) | Toggle granularity, resolution semantics, degraded mode, toggle audit | Deliverable 6, FR-5 |
| [`portability/`](portability/) | Finance re-derivation + public-sector/edtech deltas + agnostic-vs-specific split | Deliverable 7, FR-6 |
| [`adrs/`](adrs/) | 10 architecture decision records | Deliverable 8 (≥6) |
| [`stretch/`](stretch/) | Consent/erasure flow, grounding red-team, tenant-isolation proof, auditor walkthrough | Stretch goals |
| [`prototype/`](prototype/) | **Runnable reference implementation** — 117 tests, both regimes, executable demos and auditor walkthrough | Beyond scope; makes the demonstrations executable |
| [`GAP-ANALYSIS.md`](GAP-ANALYSIS.md) | What the brief asks for vs. what is here, and what remains open | — |
| [`SELF-ASSESSMENT.md`](SELF-ASSESSMENT.md) | Rubric self-assessment + open compliance questions | Submission guideline 4 |
| [`GLOSSARY.md`](GLOSSARY.md) | Terms, abbreviations, requirement IDs | — |

## Suggested reading order

1. [ADR-001 — sector choice](adrs/ADR-001-sector-choice.md) and the
   [obligation inventory](control-mapping/obligation-inventory.md) — what the regime
   actually requires.
2. [Reference architecture](architecture/reference-architecture.md) and the
   [container view](architecture/container-view.md) — where the controls live.
3. [Control-mapping matrix](control-mapping/control-matrix.md) — obligation → control → FR.
4. The four control specs: [data handling](data-handling/), [audit](audit/),
   [HITL](hitl/), [grounding](grounding/), [toggles](toggles/).
5. [Portability analysis](portability/portability-analysis.md) — the neutrality proof.
6. [Auditor walkthrough](stretch/auditor-walkthrough.md) — the whole thing exercised end to end.
7. [`prototype/`](prototype/README.md) — the same controls as running code:
   `python3 demo.py`, `python3 portability_demo.py`, `python3 auditor_cli.py`,
   `python3 run_tests.py` (117 tests, no dependencies).
8. [Portability by construction](portability/portability-by-construction.md) — what
   happened when the portability claim was implemented rather than argued.

## What the system actually does (scope)

CARA is a multi-tenant agentic assistant deployed inside ambulatory-care organisations.
Three capabilities, deliberately spanning the risk range:

| Capability | What it does | Highest risk tier reached |
|-----------|--------------|--------------------------|
| `qa.record` | Answers staff questions over a specific patient's record ("what was the last A1c?") | **Tier 3** (patient-specific clinical assertion) |
| `draft.summary` | Drafts a visit summary / referral letter for clinician signature | **Tier 3** (proposes clinical content for the record) |
| `action.schedule` | Takes bounded actions: books follow-ups, requests refills for clinician approval | **Tier 3** (proposes a care action) |
| `qa.general` | Answers general, non-patient-specific policy/education questions | **Tier 1** |

The agent never writes to the clinical record autonomously; it proposes, a named human
disposes. That boundary is [ADR-003](adrs/ADR-003-hitl-threshold.md).

## Non-goals

- CARA is not a clinical decision support system under FDA device rules; it does not
  produce diagnoses or dosing recommendations. (Open question OQ-3 in
  [SELF-ASSESSMENT.md](SELF-ASSESSMENT.md).)
- CARA does not train or fine-tune on tenant data. See
  [ADR-009](adrs/ADR-009-no-training-on-tenant-data.md).
- This package specifies architecture and controls, not vendor selection. Components are
  named by role (`Flag Service`, `Grounding Verifier`) rather than product.
