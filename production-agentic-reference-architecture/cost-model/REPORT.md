# Cost and latency model — derived output

Baseline: fan-out 4, routing plan/summarize/guardrails=small, synthesis=large.

## Per-stage breakdown (per task)

| stage                   | tier  | calls | in tok | out tok | cost        | %cost | p50 ms    | p95 ms    | %p95 | mode     |
|-------------------------|-------|-------|--------|---------|-------------|-------|-----------|-----------|------|----------|
| guardrail.input         | small | 1.00  | 700    | 120     | $0.0010     | 1%    | 420       | 900       | 3%   | serial   |
| orchestrator.plan       | small | 1.00  | 1,400  | 600     | $0.0035     | 2%    | 900       | 2100      | 8%   | serial   |
| worker.search           | —     | 4.24  | 0      | 0       | $0.0000     | 0%    | 250       | 900       | 3%   | parallel |
| worker.fetch            | —     | 3.39  | 0      | 0       | $0.0000     | 0%    | 700       | 3200      | 12%  | parallel |
| worker.summarize        | small | 4.24  | 25,440 | 1,696   | $0.0271     | 17%   | 1300      | 3400      | 13%  | parallel |
| orchestrator.synthesize | large | 1.03  | 24,720 | 3,090   | $0.1205     | 77%   | 6500      | 14000     | 54%  | serial   |
| guardrail.output        | small | 1.00  | 3,400  | 200     | $0.0035     | 2%    | 700       | 1600      | 6%   | serial   |
| **TOTAL**               | —     | —     | 55,660 | 5,706   | **$0.1557** | 100%  | **10770** | **26100** | 100% | —        |

Latency budget: p50 11,000 ms (modelled 10,770 — within), p95 26,000 ms (modelled 26,100 — OVER).

## Dominant cost drivers

1. **orchestrator.synthesize** — $0.1205/task (77% of cost). Evidence tokens are paid on every synthesis attempt, so context size is the lever.
1. **worker.summarize** — $0.0271/task (17% of cost). Cost scales linearly with fan-out width; latency only sub-linearly.

## Sensitivity: fan-out width

| width | cost/task | Δcost | p50 ms | p95 ms | Δp95 | tasks/month |
|-------|-----------|-------|--------|--------|------|-------------|
| 2     | $0.1051   | -33%  | 8271   | 20718  | -21% | 15226       |
| 4     | $0.1557   | +0%   | 10770  | 26100  | +0%  | 10274       |
| 6     | $0.2064   | +33%  | 12903  | 30695  | +18% | 7752        |
| 8     | $0.2570   | +65%  | 14829  | 34843  | +33% | 6225        |

## Sensitivity: synthesis context size

| synth input tok | cost/task | Δcost | p95 ms | tasks/month |
|-----------------|-----------|-------|--------|-------------|
| 12,000          | $0.1186   | -24%  | 20718  | 13485       |
| 18,000          | $0.1372   | -12%  | 23546  | 11662       |
| 24,000          | $0.1557   | +0%   | 26100  | 10274       |
| 40,000          | $0.2052   | +32%  | 32118  | 7798        |
| 60,000          | $0.2670   | +71%  | 38688  | 5993        |

## Reduction levers

| lever                             | cost/task | Δcost | p95 ms | tasks/month |
|-----------------------------------|-----------|-------|--------|-------------|
| baseline                          | $0.1557   | —     | 26100  | 10274       |
| L1 cap fan-out 4→2, dedupe 20→35% | $0.1051   | -33%  | 20718  | 15226       |
| L2 route synthesis to small model | $0.0674   | -57%  | 26100  | 23755       |
| L3 cap evidence/sub-question 3→2  | $0.1310   | -16%  | 26100  | 12213       |
| L3 cap evidence/sub-question 3→1  | $0.1063   | -32%  | 26100  | 15053       |
| L1 + L2 (degraded mode)           | $0.0439   | -72%  | 20718  | 36449       |

L1 costs coverage (fewer sub-questions answered) and L2 costs synthesis quality. **L3 is the cheapest of the three in quality terms**: it drops the *third-best* source for each sub-question, which is usually a near-duplicate of the first two, so breadth is preserved while synthesis input shrinks. Measured in the spike: capping 3→1 cut synthesis input from 811 to 401 tokens on a two-part question. All three are measured in the eval harness, which is what stops a lever from being pulled on cost grounds alone.

## Monthly envelope

- Envelope **$2,000/month**, 20% reserved for eval runs, re-baselining and incident replay → **$1,600** usable.
- At $0.1557/task that funds **10,274 tasks/month** against a target of 12,000 — headroom ratio **0.86×**.
- Per-task ceiling **$0.30** (1.9× the modelled task) is enforced live: the orchestrator caps fan-out and downgrades routing before synthesis, and aborts after it (`orchestrator.budget_guard` / `budget.aborted` span events).

## Verdict — the defended operating point

**The nominal fan-out of 4 does not fit.** It lands +100 ms against the p95 budget and funds 10,274 of 12,000 target tasks (0.86× headroom). This is the model doing its job: the number that was assumed during design is not affordable, and something has to give.

The widest fan-out that satisfies **both** the p95 latency budget and the monthly envelope is **3**: $0.1304/task, p50 9,584 ms, p95 23,546 ms, 12,269 tasks/month (1.02× headroom). That is the committed default (`RunConfig.max_fanout`), with width 8 reachable only for explicitly-flagged deep runs that accept the latency and are charged against the reserve.

**Headroom, not width, is the binding problem.** At width 3 the plain configuration leaves 1.02× headroom — a rounding error, not engineering margin. A rate-card increase or a traffic bump breaches it immediately. L3 does not widen fan-out (p95 binds at width 4 whatever the cost), but it does buy margin at the committed width:

| configuration                               | cost/task | tasks/month | headroom  |
|---------------------------------------------|-----------|-------------|-----------|
| width 3, evidence 3/sub-q                   | $0.1304   | 12,269      | 1.02×     |
| width 3, evidence 2/sub-q **(recommended)** | $0.1119   | 14,303      | **1.19×** |

So the defended operating point is **width 3 with evidence capped at 2 per sub-question**. That is the cheapest of the three levers in quality terms: it drops the third-best source for each sub-question, which is usually a near-duplicate of the first two, rather than cutting sub-questions (L1) or degrading synthesis (L2). L1 and L2 stay in reserve for a genuine overrun.

Three consequences this model forces, all recorded in ADRs rather than discovered in production:

1. Synthesis context is the budget. At 4 sources it is 77% of per-task cost, which is why extractive summarisation before synthesis (ADR-003) is a cost control and not just a quality one.
2. Fan-out is not free in latency either — the p95 order statistic grows with width, so 'just add workers' buys coverage at both meters.
3. The p95 tail is dominated by open-web fetch and synthesis, so the on-call runbook's first question for a slow run is which fetch span stalled (visible directly in the trace).
