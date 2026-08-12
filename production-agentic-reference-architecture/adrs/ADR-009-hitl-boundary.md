# ADR-009 — Human-in-the-loop boundary: export only

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

Human review is the most expensive control in the system — not in compute, but in the
scarcest resource available, which is a person's attention. Placing it wrongly is
doubly damaging: too broad and reviewers rubber-stamp, which destroys the control while
keeping its cost; too narrow and an irreversible action escapes oversight.

## Options considered

1. **Approve every run** before returning any report.
2. **Approve every write** (the reflexive "all writes need HITL" rule).
3. **Approve only irreversible, externally-visible actions** — here, `export_report`.
4. **No HITL; rely on output guardrails.**
5. **Risk-scored approval** — a model decides when to ask a human.

## Decision

**Option 3.** The threshold is **irreversibility ∧ external visibility**, not the
read/write distinction.

Applying the test to this system's actions: `search`, `fetch`, `summarize` are reversible
and internal — no gate. Writing to working or retrieved memory is run-scoped and
discarded — no gate. `export_report` publishes to an external destination where the
artifact can be read, forwarded and acted on by people outside the system, and it cannot
be unpublished — **gate**.

Note that this rule is not the same as option 2 and would not collapse into it in a peer
domain either: a data-ops agent writing a scratch row to its own scoping table is a write
that needs no human, while the same agent's `apply_remediation` is irreversible and
externally visible and does. The rule is about consequence, not about verbs.

**Mechanism.** On export request the run commits `awaiting_approval` (destination, report
hash, report body) and stops. Approval mints a **single-use token bound to the run id and
the report hash**. The write tool then requires all three of: a token present (the
contract layer strips `confirmed_by` from any model-authored payload — ADR-004), the token
matching the one the gate issued for this run, and the report hash still matching what was
approved. Plus the destination allowlist from long-term memory.

Two consequences of the hash binding are worth stating. Approval is of a **specific
artifact**, not of a run — a report modified after approval fails the check, so an
approve-then-mutate path does not exist. And the token being gate-minted is what breaks
the model→action path: there is no string a model can emit that constitutes authorisation.

Rejections: **(1)** makes the agent useless for its main read-only use and trains
reviewers to click through. **(2)** over-triggers on inconsequential writes and produces
exactly that rubber-stamping. **(4)** leaves a detector as the only thing between an
injected instruction and an external publication — and detectors are probabilistic; the
mutation test M1 shows the gate is what catches it. **(5)** puts the model in charge of
deciding when the model needs supervising, which is circular.

## Consequences

**Positive**
- Exactly one confirmation point — reviewable, testable (mutation M1), and cheap enough
  that reviewers stay attentive.
- Reads fan out freely, so the common case has no human latency.
- Every approval is attributable: approver, report hash, timestamp, trace id, in an
  append-only audit log.

**Negative / accepted costs**
- Export throughput is bounded by human availability; batch publication would need a
  different design (per-destination standing approval with post-hoc audit, deliberately
  not built).
- The approval interface in the spike is a CLI command; a real deployment needs a review
  UI showing the report and the coverage gaps (ADR-012).
- A reviewer approving without reading is still possible. The control is a boundary, not a
  guarantee of judgement — which is precisely why it is one boundary and not fifty.
