# ADR-013 — Fan-out width of 3, enforced live

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

Fan-out width is the parameter that ties the topology to both budgets. The design started
from an assumed width of 4. When the cost/latency model was actually built and run, that
assumption did not survive contact with the numbers — which is the outcome a cost model
exists to produce.

At width 4 the modelled task costs **$0.1557**, giving **10,274 tasks/month** against a
12,000 target (0.86× headroom — a shortfall), with modelled **p95 26,100 ms** against a
26,000 ms budget (100 ms over). Both constraints breached, marginally, in the same
direction.

## Options considered

1. **Keep width 4** and raise the monthly envelope.
2. **Keep width 4** and relax the p95 budget.
3. **Reduce the default width to 3.**
4. **Keep width 4** and permanently route synthesis to the small model (lever L2).
5. **Make width fully dynamic** per question, with no default.

## Decision

**Option 3: default width 3, hard cap 8.** Width 3 is the widest fan-out satisfying both
constraints: **$0.1304/task, p50 9,584 ms, p95 23,546 ms, 12,269 tasks/month (1.02×
headroom)**. The model computes this rather than asserting it (`cost-model/REPORT.md`,
"Verdict"), and `RunConfig.max_fanout = 3` in the prototype so the artifacts agree.

Two asymmetries drive the reasoning. **Cost scales linearly in width; latency scales
sub-linearly** — so width is primarily a cost decision. But **the p95 order statistic grows
with width** (the chance that at least one of N workers lands in its own tail rises with N),
so "parallel is free" is false at the tail: widening buys coverage at both meters.

Rejections: **(1)** and **(2)** are legitimate but they are *someone else's* decisions —
raising the envelope or relaxing a user-facing latency budget is an escalation, not
something an architect absorbs silently; recording them here is what makes the escalation
possible. **(4)** spends the quality budget on the step where quality matters most, and
holds no reserve lever for when traffic grows. **(5)** makes cost unpredictable against a
fixed envelope; dynamic widening exists, but as an explicitly-flagged exception charged
against the reserve, not as the default.

**Enforcement is live, not documentary.** Before fan-out the orchestrator projects
`spent + width × worker_estimate + synthesis_estimate` against the per-task ceiling. Over
ceiling it caps width and calls `ModelRouter.downgrade()`, emitting
`budget.fanout_capped` and `budget.model_downgraded`. After fan-out and before the
expensive synthesis call it re-checks actual spend and aborts with `budget_exceeded` if the
ceiling is already breached — synthesis is never entered on a doomed budget. The ceiling
($0.30) is deliberately ~2.3× the modelled task so ordinary variance does not trip it;
tripping means something is genuinely wrong.

> **Amended by [ADR-016](ADR-016-closing-the-four-residual-risks.md)** on both of the
> "accepted costs" below. Headroom is no longer 1.02×: lever L3 (evidence capped at 2 per
> sub-question) brings it to **1.19×** at the same width 3, and that is now the default. And
> the pre-flight estimates are no longer static constants — `CostCalibrator` derives them from
> a rolling window of observed spend, which revealed the seeds were over-estimating worker cost
> by ~3.5× and synthesis by ~2.3×, i.e. the guard had been capping fan-out unnecessarily.

## Consequences

**Positive**
- Both budgets are met with a derived, defensible number rather than a guessed one.
- The ceiling cannot be exceeded silently; degradation is visible in the trace.
- Deep runs remain possible as a governed exception with a named cost source.

**Negative / accepted costs**
- ~~Headroom is thin (1.02×)~~ → **1.19× after ADR-016's lever L3.** Still not generous:
  weekly cost review (governance §6) remains load-bearing rather than routine.
- Width 3 caps decomposition, so a genuinely five-part question is under-covered — it will
  produce declared coverage gaps (ADR-011) rather than silent narrowing, which is the
  right failure but is still a real limitation.
- ~~Cost estimates are static constants~~ → **calibrated in ADR-016.** Residual: the rolling
  mean averages across question shapes, so a run far from the recent mix is mis-projected.
