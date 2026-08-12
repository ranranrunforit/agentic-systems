# ADR-014 — A deterministic offline model backend is the default

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

The eval gate is a release control: it must fail when a control breaks and pass otherwise,
on every prompt/tool/model change, cheaply. A non-deterministic backend makes a gate flaky,
and a flaky gate gets bypassed — which is the same as not having one. Separately, a reviewer
needs to run the spike; requiring an API key, network egress and a spend budget to evaluate
an architecture package is a poor trade.

## Options considered

1. **Real provider only.**
2. **Mocked tool and model responses** — return canned strings.
3. **A deterministic model *implementation*** that performs the real shape of each task
   over real (fixture) evidence, with a real-provider adapter behind the same interface.
4. **Record/replay** of real provider responses (VCR-style cassettes).

## Decision

**Option 3.** `DeterministicModel` implements each task for real over the retrieved
evidence: `plan` decomposes on the question's own connectives and facets; `summarize` is
genuinely extractive (it scores and selects sentences from the fetched text); `synthesize`
builds the report from assembled evidence only, attaches a citation to every claim, and —
critically — **declares a coverage gap instead of inventing an answer** when a sub-question
has no supporting evidence. `AnthropicModel` sits behind the identical interface for
`--model-backend anthropic`.

The distinction from option 2 is the whole point and worth being precise about. A mock
returns a fixed answer regardless of input, so the assertions it satisfies are about the
mock. This backend's outputs are **functions of the actual retrieved evidence**, so the
things the eval asserts are real properties of the pipeline: remove retrieval and the
citations disappear; poison a source and the sanitisation shows up in the summary; take a
source offline and a coverage gap appears. The mutation test proves this empirically —
breaking a control changes the outcome, which could not happen with canned responses.

What this backend does **not** exercise, stated plainly rather than left for a reviewer to
discover: real-provider reasoning quality, real prompt sensitivity, real token volumes, real
latency distributions, and real-world source diversity. Those are exactly the things the
`--model-backend anthropic` path and the cost model's production parameters cover, and the
cost model's `--calibrate` mode prints measured spike numbers next to modelled production
numbers so the gap is visible rather than implied.

Rejections: **(1)** flaky, costly and unrunnable by a reviewer. **(2)** produces an eval
that tests nothing — the credibility failure this whole ADR exists to avoid. **(4)** is a
good option, genuinely: real responses, deterministic replay. Rejected because cassettes go
stale silently and a prompt change invalidates them wholesale, so the gate would either
break or quietly stop testing the current prompts. Reasonable to revisit once prompts
stabilise.

## Consequences

**Positive**
- The gate is deterministic, so a failure means a real regression and thresholds mean
  something.
- A reviewer runs the whole package — spike, eval, mutation test, cost model — with
  `python3` and no installs, no key, no egress.
- Cost and latency attributes are still produced (from a shared rate card), so the
  observability and cost paths are exercised end to end.

**Negative / accepted costs**
- Absolute cost and latency figures from the spike are not production figures, and it would
  be dishonest to present them as such; the cost model's production parameters are the
  numbers the architecture is budgeted against.
- Quality-vs-cost comparisons in `--compare-routing` show the cost axis moving and the
  quality axis flat, because a deterministic model cannot degrade. The harness reports this
  caveat in its own output.
- Two backends to keep interface-compatible; a drift bug would show up only on the
  real-provider path.
