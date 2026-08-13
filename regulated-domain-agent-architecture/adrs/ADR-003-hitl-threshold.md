# ADR-003 — HITL threshold on irreversibility and harm-to-person

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Clinical Safety Officer

## Context

FR-3 requires a risk taxonomy and a stated threshold above which human review is mandatory,
with the threshold justified. Lower-risk output may flow automatically with logging.

## Decision

Three tiers scored on four axes (specificity, consequence class, irreversibility, autonomy)
using a **max-rule**. **Mandatory HITL at Tier 3**, defined as: asserts a clinical fact
about a specific patient, proposes or takes a care action, or is effectively irreversible.
Ambiguity **rounds up**. No eligible approver within SLA ⇒ **expire closed**.

## Rationale

1. **Irreversibility is where review has value.** Human review after the point of no return
   is documentation, not control. Placing the gate exactly at that point is the only
   placement that buys anything.
2. **Harm-to-person is the second axis** because reversibility alone is insufficient: a
   wrong clinical assertion can be retracted and still have changed a decision in the
   interval. Anything a clinician might act on immediately is treated as irreversible in
   practice.
3. **Not model accuracy.** A threshold indexed to measured accuracy moves with every model
   change and makes the control's strength a function of the component it constrains.
4. **Not volume or cost.** If the Tier-3 queue is too large, the remedy is fewer Tier-3
   capabilities or a better review UI — never reclassifying care-affecting output downward.
5. **Max-rule, not sum.** Summing lets a high-harm output be averaged down by low scores on
   other axes, which inverts the intent.
6. **Round up on ambiguity** because unknown risk is not low risk.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Confidence-based routing (review only low-confidence output) | Reviews exactly the cases the model already flagged, and misses confident errors — the dangerous class. |
| Sampling only (review N%) | Leaves (100−N)% of irreversible clinical output unreviewed. Sampling is a *quality* instrument, kept at Tier 2, not a *safety* gate. |
| Review everything | Destroys the product's value, and reliably produces rubber-stamping — a control that degrades under its own load is worse than a narrow one that holds. |
| Post-hoc review after release | The output has already reached a clinician. |
| Monetary/quantitative threshold | No natural monetary axis in care; introduced deliberately in the finance re-derivation instead. |

## Consequences

- Throughput on Tier-3 capabilities is capped by human review capacity. Accepted.
- Tier 3 must be kept narrow and precisely defined, or the queue collapses the control.
- Duty rosters and delegation become load-bearing ([ADR-007](ADR-007-accountability-model.md)):
  an empty roster means expire-closed, so coverage is a safety property.
- Anti-rubber-stamp instrumentation is required, since a mandatory gate that is
  reflexively approved is worse than no gate — it manufactures a false record of review.
