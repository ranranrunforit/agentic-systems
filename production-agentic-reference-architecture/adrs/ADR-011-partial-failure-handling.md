# ADR-011 — Partial failure degrades loudly; no silent failures

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

Fan-out means independent failure. Sources go down, fetches time out, a search returns
nothing relevant, a model call times out. The reliability requirement is explicit: defined
behaviour under model timeout, tool failure, and partial worker failure, with **no silent
failures**.

The dangerous outcome is not a failed run — it is a *successful-looking* run whose scope
quietly narrowed. If two of three sub-questions were answered and nothing says so, the
reader reasonably assumes the report covers the question they asked.

## Options considered

1. **Fail the whole run** if any worker fails.
2. **Drop failed sub-questions** and synthesise from what succeeded.
3. **Degrade explicitly** — synthesise from what succeeded, and require the output to
   declare what was not covered.
4. **Retry until success** with unbounded retries.

## Decision

**Option 3**, with defined behaviour per failure class:

| Failure | Behaviour |
|---|---|
| `fetch` upstream unavailable / timeout | worker records the error, continues with remaining sources for its sub-question |
| worker yields no evidence | worker returns `ok: false` with an error kind; **checkpointed as a failure** so a resume does not retry a dead source forever |
| worker exceeds its timeout | future is abandoned with `worker_timeout`; the orchestrator does not block on it |
| **all** workers fail | run status `failed`, `reasons: [all_workers_failed]` — synthesis is never paid for when there is no evidence |
| some workers fail | run continues; failed sub-questions are passed to the synthesizer |
| no groundable evidence for any sub-question | status `insufficient_evidence` — an explicit refusal, not an invented answer |
| tool input invalid | typed rejection with `tool.input_rejected` event; treated as a worker error, never a crash |
| model timeout | surfaces as a worker/stage error and follows the rules above |

**The synthesizer is told what failed.** `failed_subquestions` is part of the synthesis
payload, and the report must contain a per-sub-question "Coverage gap" note plus a "Known
coverage limitations" section. This is enforced in two places, deliberately: the eval's
end-state lens fails case C10 if a declared source outage is absent from the report
(mutation M3 confirms an invented answer is caught).

**Nothing fails without a trace record.** Every failure produces a span with
`status: ERROR`, a typed `error_kind`, and an event (`worker.degraded`,
`tool.failed`, `budget.aborted`). Statuses are enumerated and appear in the result JSON:
`completed`, `blocked_input`, `blocked_output`, `insufficient_evidence`,
`budget_exceeded`, `awaiting_approval`, `exported`, `rejected`, `failed`. An operator never
has to infer what happened from an empty section.

Rejections: **(1)** wastes completed paid work and makes the system brittle against
third-party availability the team does not control. **(2)** is the silent-failure
anti-pattern — the highest-severity reliability sin available in this domain. **(4)** makes
cost and latency unbounded and turns a dead source into a budget leak; retries are bounded
and priced in expectation in the cost model instead.

## Consequences

**Positive**
- Third-party outages degrade coverage rather than availability.
- Readers can tell what the report does not cover, which is what makes a partial report
  safe to use.
- Failure is durable state, so resume behaviour is deterministic.

**Negative / accepted costs**
- Reports carry coverage caveats that some readers will find noisy. Accepted: the
  alternative is misleading them.
- A degraded report still consumes synthesis cost; the all-workers-failed short-circuit
  bounds the worst case but a one-of-three-succeeded run pays full synthesis for thin
  evidence.
- "Enough coverage to be worth synthesising" is currently a binary (any evidence at all).
  A coverage-ratio threshold would be better and is not built (ADR-012).
