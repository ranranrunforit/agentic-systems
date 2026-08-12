# Cost and latency model — notebook walkthrough

The deliverable allows a spreadsheet or a notebook. `cost_model.py` is the model; this file
is the same thing as copy-pasteable cells, for a reviewer who wants to poke at the numbers
interactively. Generated output lives in [`REPORT.md`](REPORT.md); parameters in
[`params.json`](params.json).

Run any cell from the repository root.

---

### Cell 1 — load parameters and compute the baseline

```python
import sys; sys.path.insert(0, "cost-model")
from cost_model import load_params, model_task, envelope

p = load_params()
base = model_task(p)
print(f"per-task cost  ${base['cost_usd']:.4f}")
print(f"p50 / p95      {base['p50_ms']:.0f} / {base['p95_ms']:.0f} ms")
print(f"tokens         in {base['input_tokens']:,} / out {base['output_tokens']:,}")
```

### Cell 2 — where the money goes

```python
for s in sorted(base["stages"], key=lambda s: -s.cost_usd):
    print(f"{s.name:26} {s.tier or '-':6} {s.calls:5.2f} calls  "
          f"${s.cost_usd:.4f}  {s.cost_usd/base['cost_usd']:5.1%}")
```

Synthesis is ~77% and summarisation ~17%. Both are functions of how many evidence tokens
exist, which is why the context-assembly rule in ADR-003 (extractive summaries only, 60% of
the window) is a cost control and not merely a quality one.

### Cell 3 — where the time goes, and why parallel is not free

```python
for s in base["stages"]:
    mode = "parallel" if s.parallel else "serial  "
    print(f"{s.name:26} {mode}  p50 {s.p50_ms:6.0f}  p95 {s.p95_ms:6.0f}  "
          f"{s.p95_ms/base['p95_ms']:5.1%} of p95")
```

Worker stages contribute their **maximum**, not their sum. But the p95 of a fan-out is worse
than the p95 of one worker: with N concurrent workers the chance that *at least one* lands in
its own tail is `1-(1-p)^N`. The model widens the parallel stages' p95 with width for exactly
this reason, which is what makes width a latency decision as well as a cost one.

### Cell 4 — sensitivity to fan-out width

```python
for w in (1, 2, 3, 4, 6, 8):
    m = model_task(p, fanout=w)
    e = envelope(p, m["cost_usd"])
    print(f"width {w}: ${m['cost_usd']:.4f}  p95 {m['p95_ms']:6.0f} ms  "
          f"{e['tasks_affordable']:>6,} tasks/mo  headroom {e['headroom_ratio']}x")
```

Cost is linear in width; p95 is sub-linear but rising. This cell is what produced ADR-013:
width 4 (the assumed default) breaches both budgets, and width 3 is the widest that fits.

### Cell 5 — sensitivity to synthesis context size

```python
for t in (12_000, 18_000, 24_000, 40_000, 60_000):
    m = model_task(p, synthesis_input_tokens=t)
    print(f"{t:>7,} tok: ${m['cost_usd']:.4f}  ({m['cost_usd']/base['cost_usd']-1:+.0%})")
```

Doubling the evidence context from 24k to 60k adds ~71% to per-task cost. This is the number
that justifies never sending raw documents to the synthesizer.

### Cell 6 — the two levers

```python
lever1 = model_task(p, fanout=2, dedupe_hit_rate=0.35)   # cap fan-out + dedupe harder
lever2 = model_task(p, all_small=True)                    # route synthesis to the small model
both   = model_task(p, fanout=2, dedupe_hit_rate=0.35, all_small=True)

for name, m in [("baseline", base), ("L1 fan-out cap", lever1),
                ("L2 model routing", lever2), ("L1+L2 degraded", both)]:
    print(f"{name:18} ${m['cost_usd']:.4f}  ({m['cost_usd']/base['cost_usd']-1:+.0%})  "
          f"p95 {m['p95_ms']:6.0f} ms")
```

L1 buys −33% and also improves p95; L2 buys −57% but spends the quality budget on the
quality-critical step. Neither is free, which is why both are measured in the eval harness
(`eval/harness.py --compare-routing`) rather than pulled on cost grounds alone.

### Cell 7 — is the envelope actually met?

```python
e = envelope(p, base["cost_usd"])
print(e)
feasible = [w for w in range(1, 9)
            if model_task(p, fanout=w)["p95_ms"] <= p["latency_budget"]["p95_target_ms"]
            and envelope(p, model_task(p, fanout=w)["cost_usd"])["tasks_affordable"]
                >= p["budget"]["target_tasks_per_month"]]
print("widths satisfying BOTH constraints:", feasible)
```

This is the cell that makes the model load-bearing: it can return an answer the design did
not want. It returns `[1, 2, 3]`, so 3 is the committed default.

### Cell 8 — calibrate against real spike traces

```python
import json, glob, statistics
costs, lats = [], []
for f in glob.glob("prototype/runs/*/trace.jsonl"):
    spans = [json.loads(l) for l in open(f) if l.strip()]
    if not spans: continue
    costs.append(sum(float(s["attributes"].get("cost_usd", 0)) for s in spans))
    root = next(s for s in spans if s["parent_id"] is None)
    lats.append(root["latency_ms"])
print(f"measured median: ${statistics.median(costs):.5f}, {statistics.median(lats):.0f} ms")
print(f"modelled:        ${base['cost_usd']:.4f}, p50 {base['p50_ms']:.0f} ms")
```

Or `python3 cost-model/cost_model.py --calibrate prototype/runs/*/trace.jsonl`.

**The gap is expected and must not be read as validation.** The offline backend produces far
smaller payloads than a real provider and fetches local fixtures rather than open-web pages
(ADR-014). What the spike validates is the model's *shape*: which stages exist, how many
calls each makes, that fan-out is parallel-bound, and that synthesis dominates. The absolute
numbers the architecture is budgeted against are the production parameters in
`params.json`.

---

## Assumptions a reviewer should argue with

1. **Percentiles are added across serial stages.** This assumes correlated tails and is
   deliberately conservative; independent stages would convolve to a tighter p95. If tails
   really are independent, the width-3 verdict has more headroom than stated.
2. **The parallel p95 widening factor (`1 + 0.18·(N−1)`)** is a fitted approximation to the
   order statistic, not a derivation. It is monotone and roughly right; it is not exact.
3. **Retries are priced in expectation**, not simulated. A correlated outage (one source
   down for every run) is worse than the average this implies.
4. **Token counts per stage are estimates** from typical research payloads. Synthesis input
   scales with fan-out width in the model, which is the coupling that matters most.
5. **The rate card is illustrative** and shared with `prototype/agent/models.py` so the
   spike's cost attributes and this model cannot drift.
