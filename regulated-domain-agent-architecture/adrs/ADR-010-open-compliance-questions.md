# ADR-010 — Open compliance questions are recorded, not resolved

**Status:** Accepted (living document) · **Date:** 2026-08-13 · **Owner:** Architect

## Context

Submission guideline 4 asks that open compliance questions be recorded in ADRs. Several
questions in this design cannot be settled by an architect: they need counsel, a tenant's
own compliance function, or a regulator's view. The failure mode is resolving them
implicitly, in code, by whoever writes the feature first.

## Decision

Open questions are recorded with: the question, why it cannot be closed here, the
**interim conservative posture** the architecture takes, and who must close it. The
canonical list lives in [SELF-ASSESSMENT.md](../SELF-ASSESSMENT.md); this ADR states the
policy and the conservative-default rule.

**Rule: while a question is open, the architecture takes the more restrictive branch**, and
the restriction is enforced in code rather than documented as guidance.

## Rationale

- An unresolved question with a permissive default becomes a permanent permissive answer
  that nobody remembers choosing.
- A conservative default is reversible after advice; a permissive default may already have
  disclosed data by then. The asymmetry decides the direction.
- Enforcing the restriction in code (a tenant-level data-source allow-list, a capability
  prohibition) rather than in a policy document is what stops the default from eroding.

## The questions (summary; detail in SELF-ASSESSMENT)

| ID | Question | Interim posture |
|---|---|---|
| OQ-1 | Exact BAA boundary for the inference provider as a subcontractor BA | Strictest terms assumed: zero retention, no training, region-pinned, flow-down required |
| OQ-2 | Whether 42 CFR Part 2 data could reach the agent via an integrated source | **Blocked**: tenant-level data-source allow-list excludes Part 2 programs |
| OQ-3 | Whether any capability constitutes a regulated device function | Diagnostic/dosing output prohibited at the capability level, not merely discouraged |
| OQ-4 | Whether grounding-by-claim adequately addresses misleading-by-omission | Sampled human review + manifest visibility; treated as an unsolved residual, not a closed item |
| OQ-5 | Whether anti-rubber-stamp instrumentation is itself acceptable workforce monitoring | Aggregate signals to a named role only; no automated punitive action; tenant must consent at onboarding |
| OQ-6 | Should "explainable to the affected individual" be a spine control? | Structured `why.reason_code` captured now; no consumer-facing surface in v1 |
| OQ-7 | Should the spine include a positive output-conformance verifier? | Slot identified, empty for healthcare v1 |
| OQ-8 | Should `audience` be a fifth risk axis? | Not implemented; all v1 consumers are clinicians or the patient |
| OQ-9 | Attribution gap for tenants without proposal-and-approval EHR integration | Export-and-paste documented as a known gap; such tenants are flagged at onboarding |

## Consequences

- Some capabilities remain unavailable to some tenants until questions close.
- The list is a standing agenda item for the compliance review, with owners and dates.
- Closing a question requires an ADR amendment, so the resolution is attributable — which
  is the same accountability principle as [ADR-007](ADR-007-accountability-model.md),
  applied to the design process itself.
