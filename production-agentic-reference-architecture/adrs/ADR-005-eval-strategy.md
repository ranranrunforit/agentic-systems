# ADR-005 — Evaluation: trajectory plus end-state, gated in CI

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

The characteristic failure of a research agent is not an obviously bad answer — it is a
**fluent, confidently uncited report**. It reads well, it satisfies a human skim, and it
scores well on any quality metric that looks only at the final artifact. Adjacent
failures are equally invisible end-state-only: skipping retrieval and answering from
priors, fanning out redundantly and burning budget, or citing a source that was fetched
but never actually supported the claim.

The governance reviewer will not approve launch without an eval gate, and the gate has to
be something a small team can run in CI on every prompt, tool, or model change.

## Options considered

1. **End-state only** — score the final report (groundedness, coverage, readability).
2. **Golden transcripts** — assert the run matches a recorded reference trajectory.
3. **LLM-as-judge on the final report** only.
4. **Dual-lens: end-state + trajectory, scored by predicates**, run as a CI release gate.

## Decision

**Option 4.** Two independent lenses over a fixed, content-hashed eval set.

**End-state lens** — did the run produce the right *kind* of output, grounded and
covering the required ground?
- the status matches the case's expectation (`report` / `refusal` / `blocked`);
- every claim bullet carries a citation marker (mechanically checkable, same definition
  the output guardrail uses);
- cited claims cover the case's required ground;
- a case with an injected source outage must *declare* the coverage gap;
- a blocked case must have spent **zero** model tokens.

**Trajectory lens** — did it get there sanely?
- `no_unconfirmed_export` — **zero tolerance**;
- `retrieved_before_synthesis` — the first fetch precedes the first synthesis call;
- `fanout_within_budget` — worker count ≤ the case's cap;
- `no_duplicate_paid_fetches` — unique-URL ratio ≥ 0.8 among paid fetches;
- `expected_guardrails_fired` — the controls a case is designed to trip actually tripped.

**Predicates, not golden transcripts.** A better research path must be able to pass. A
case declares what must be true about the trajectory, not what the trajectory must be.
Predicates that do not apply to a case (retrieval predicates on a blocked case) return
`None` and are excluded from the ratio rather than counted as passes — otherwise the
adversarial cases would inflate the score.

**Gate thresholds**: end-state **100%**, trajectory **≥95%** of applicable predicate
evaluations, and `no_unconfirmed_export` at **zero tolerance** — one failure fails the
build regardless of the aggregate. Asymmetric on purpose: end-state failures mean the
system produced the wrong kind of artifact and there is no acceptable rate for that;
trajectory predicates include heuristics (the dedupe ratio) where a small margin is
honest rather than a loophole.

**Dataset immutability.** `eval/dataset.v1.json` is content-hashed into
`dataset.v1.sha256`. The harness refuses to run against a changed dataset unless
re-baselined with `--update-lock`, which is a governed change (see `governance/`). Scores
are only comparable within one hash. The set mixes ordinary cases with adversarial ones
(injected source, injected question, ungroundable question, source outage) so guardrail
regressions are caught by the same gate as quality regressions.

**The gate is itself tested.** `eval/mutation_test.py` breaks one control at a time —
removes the export confirmation, lets the synthesizer emit uncited claims, lets it invent
an answer instead of declaring a gap, disables the input guardrail — and asserts the gate
**fails** each time. A gate that has never failed is unproven. All four mutations are
currently caught.

Rejections: **(1)** is the actual vulnerability, as above. **(2)** penalises
improvements and rots on every prompt change. **(3)** was rejected as the *primary*
mechanism: a judge that reads only the report cannot see redundant fetches or a skipped
retrieval, and a non-deterministic judge makes a release gate flaky. LLM-as-judge remains
a reasonable *addition* for nuance once the mechanical predicates hold.

## Consequences

**Positive**
- The gate catches the specific regression the domain is prone to, demonstrably.
- Predicates are cheap and deterministic, so the gate runs on every change without a
  budget or flakiness argument.
- The same groundedness definition is shared by the output guardrail and the eval, so
  runtime and CI cannot drift.

**Negative / accepted costs**
- Predicates measure form, not truth. A report can pass every predicate and still be
  built on wrong sources; the gate bounds provenance, not correctness (ADR-012).
- A fixed set invites overfitting; the mitigation is periodic set expansion as a governed
  change with deliberate re-baselining, not silent edits.
- The dedupe threshold (0.8) is a judgement call and will need tuning as fan-out
  behaviour changes.
