# ADR-001 — Primary sector: healthcare (HIPAA)

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Architect · **Decision class:** DC-7 adjacent

## Context

The project menu offers healthcare, finance, public sector, and edtech, and states that the
menu is balanced. Exactly one primary sector must be chosen and at least one other
re-derived. The choice must be justified on its own terms without implying the others are
inferior or easier — a rationale of the form "healthcare is the hardest" would be both
wrong and against the brief.

## Decision

**Healthcare (HIPAA)** is the primary sector. **Finance (GLBA/PCI/SOX)** is the fully
re-derived portability peer; public sector and edtech are re-derived at lower depth in
[sector-deltas](../portability/sector-deltas.md).

## Rationale

Three reasons, all about *legibility of the exercise*, not about difficulty:

1. **The obligation set is publicly documented and clause-addressable.** HIPAA's Security
   Rule enumerates audit controls, integrity, and authentication as named standards, so
   every row of the control-mapping matrix can point at a specific structural citation.
   That makes the matrix checkable by a reader who does not share my assumptions — which
   is the property a traceability artefact needs most.
2. **Minimum-necessary is unusually well-suited to expose the agentic problem.** It forces
   the question "what exactly crossed the model boundary?" to have a per-request answer.
   That question is the crux of agentic data handling in every sector; HIPAA just states
   it most bluntly, which makes the resulting control (the minimization manifest) easy to
   evaluate.
3. **Harm-to-person is a clean axis for the HITL threshold**, so the threshold can be
   justified on irreversibility and harm rather than on a monetary amount. Starting from a
   quantitative trigger (finance) risks encoding "threshold = number" into the taxonomy,
   which then ports badly to sectors with no natural amount. Starting qualitative and
   *adding* the monetary axis in the finance re-derivation is the more honest direction.

## Why the other three were not chosen (and are not inferior)

| Sector | What it would have given | Why not primary here |
|---|---|---|
| Finance | Sharpest treatment of segregation of duties, quantitative thresholds, and attestation regimes | Chosen as the peer instead, where it does the same work while also testing portability |
| Public sector | The only sector where the audit log may itself be disclosable, and where retention can *prohibit* deletion — genuinely novel constraints | Its most interesting properties (FOIA disclosability, ATO) are surfaced as deltas without needing to be primary |
| Edtech | The only sector where consent is a precondition rather than a constraint — arguably the biggest structural difference on the menu | Same: the consent-gate finding is more visible *as a delta* than it would be as the baseline, because it shows up as a new step in the request path |

Each of these is a real argument *for* the sector I did not pick, which is the test of
whether the menu was treated as balanced. Notably, the edtech and public-sector deltas
produced the three most interesting findings in the whole package
([sector-deltas §4](../portability/sector-deltas.md#part-4--three-findings-the-four-way-comparison-produced)) —
so the choice of primary determined the *order of discovery*, not its depth.

## Alternatives rejected

- **Two primary sectors.** Violates the constraint and dilutes the control-mapping matrix
  into two shallow ones.
- **A generic "regulated sector" abstraction with no concrete regime.** Produces exactly
  the over-fitted-to-nothing design the portability requirement is meant to prevent: with
  no specific obligations, no control can be shown to be traceable.

## Consequences

- The control-mapping matrix is HIPAA-clause-shaped and must be re-derived, not translated,
  for other regimes.
- The vetted-source definition is clinical and needs replacing per sector (as expected).
- Scope exclusions must be explicit: 42 CFR Part 2 and FDA device rules are out of scope
  and recorded in [ADR-010](ADR-010-open-compliance-questions.md).
