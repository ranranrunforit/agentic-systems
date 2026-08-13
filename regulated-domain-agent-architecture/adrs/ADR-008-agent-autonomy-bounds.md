# ADR-008 — The agent proposes; it never writes to the record

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Clinical Safety Officer

## Context

Agentic systems are defined by taking bounded actions. The scenario permits "taking bounded
actions", and FR-3 permits lower-risk output to flow automatically. So where exactly is the
autonomy boundary, and what enforces it?

## Decision

The agent has **no write path to the clinical record**. It produces proposals; approved
content enters the record through the EHR's own write path, attributed to the approving
human. Tools are individually registered with declared scopes, declared side effects, and a
declared maximum risk tier; unregistered tool calls are impossible. Loop bounds: ≤ 8 tool
calls, ≤ 120 s, then escalate.

## Rationale

- **Integrity of ePHI (O-S7) is easiest to guarantee by construction.** No write path means
  no unauthorised write, and the question "could the agent have altered the record?" has a
  structural answer rather than a probabilistic one.
- **Attribution stays correct.** Content entering the record is attributed to the clinician
  who approved it, which is what the record is *for*. An "AI-authored" entry with no human
  author is a provenance problem for every downstream reader of that record, forever.
- **Bounded actions still exist** — scheduling, dispute-free operational tasks — but they
  are reversible, registered, and tier-gated. Bounded autonomy is not the same as no
  autonomy; the boundary is drawn at the record and at irreversibility.
- **Loop bounds are a containment control, not a cost control.** An unbounded planner is an
  unbounded action surface, and long autonomous chains are where small misinterpretations
  compound out of a human's ability to review them afterwards.
- **Declared side effects feed the risk classifier's floor**, so a capability cannot be
  talked below its tier by its own output.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Agent writes drafts directly into the record as "unsigned" | Unsigned content is still visible to other clinicians and still influences care; the write already happened. |
| Full autonomy above a confidence threshold | Reintroduces the rejected control (see [ADR-002](ADR-002-grounding-strategy.md)) at the action layer, where it is worse. |
| Generic tool access (arbitrary HTTP, arbitrary email) | Unbounded action surface; makes prompt injection an exfiltration path rather than a quality problem. |
| No bounded actions at all (advice only) | Gives up most of the product's value without a corresponding safety gain, since the risky part is the assertion, not the booking. |

## Consequences

- EHR integration must support a proposal-and-approval flow; tenants without one get
  export-and-paste, with a resulting attribution gap that must be documented (OQ-9).
- Every new tool is a governed addition (scope, side effects, tier, owner).
- The 8-call bound occasionally truncates legitimately complex tasks; those escalate to a
  human rather than running longer, which is the intended failure direction.
