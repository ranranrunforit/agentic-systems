# ADR-002 — Orchestrator-workers topology

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

The domain (ADR-001) requires decomposing a question, retrieving from several
independent sources, and synthesising one cited report. The topology must deliver
bounded parallelism, per-source observability, and a defined aggregation behaviour when
some retrieval fails — on a fixed cost envelope and a p95 latency budget, operated by a
small team.

## Options considered

1. **Single-agent ReAct loop** — one model interleaving thought and tool call.
2. **Fixed pipeline** — plan → retrieve → synthesise as hard-coded sequential stages
   with no dynamic decomposition.
3. **Orchestrator-workers** — a planner decomposes; N specialised retrieval workers run
   concurrently; a synthesizer aggregates.
4. **Peer-to-peer multi-agent / debate** — several general agents negotiate a result.
5. **Hierarchical orchestrators** — orchestrators spawning sub-orchestrators.

## Decision

**Option 3, orchestrator-workers**, with three specialisations: planner (decompose),
retrieval worker (search → fetch → screen → summarise for exactly one sub-question),
synthesizer (aggregate into a cited report).

Rejections, with the specific defect in each:

- **ReAct (1)** is sequential by construction, so wall-clock grows linearly with the
  number of sources consulted, while the fan-out design grows with the slowest source.
  It also has no natural checkpoint boundary — a durable resume would have to replay the
  whole trajectory — and errors compound because no independent worker contradicts a bad
  early observation. It remains the right choice when sub-tasks are genuinely dependent;
  here they are not.
- **Fixed pipeline (2)** cannot vary decomposition with the question. A one-part
  question and a four-part comparison would fetch the same fixed set, so it either
  overspends on simple questions or under-covers complex ones.
- **Peer-to-peer / debate (4)** multiplies model calls for a quality gain this domain
  does not need (the hard part is retrieval coverage and provenance, not reasoning
  disagreement) and makes cost non-deterministic — fatal against a fixed envelope.
- **Hierarchical (5)** is the same topology recursed. Unbounded depth makes the cost
  ceiling unenforceable and the trace tree unreadable on-call. Deliberately deferred:
  if sub-question decomposition ever needs its own decomposition, this is the first
  extension point.

Design commitments that make the topology operable:
- **Bounded width.** Fan-out is capped (default 3, hard cap 8 — ADR-013). The cap is
  enforced in the orchestrator, not requested of the model.
- **Workers are stateless and idempotent** over their sub-question, so a retry or a
  post-restart re-run is safe.
- **Aggregation is failure-aware** — the synthesizer receives the list of failed
  sub-questions and must declare coverage gaps (ADR-011).
- **Workers cannot call the write tool.** Only the orchestrator, and only via the HITL
  gate, reaches `export_report`. Privilege does not fan out with the work.

## Consequences

**Positive**
- Wall-clock is bounded by the slowest worker, not the sum (validated in the trace: the
  fan-out span is ~1× a single worker, not N×).
- One span per worker makes "which sub-question stalled" answerable directly from the
  trace — the operability requirement.
- Checkpoint boundaries fall out naturally: plan, each worker, synthesis (ADR-008).

**Negative / accepted costs**
- Coordination overhead and more moving parts than a ReAct loop; two extra model roles
  to version and evaluate.
- Cost scales linearly with fan-out width while latency scales sub-linearly, so width is
  a budget decision that must be governed rather than tuned casually (ADR-013).
- Decomposition quality becomes a distinct failure mode (a bad plan produces
  well-executed retrieval of the wrong things), which is why the eval scores planning as
  part of the trajectory lens (ADR-005).

**Peer-domain note**: a data-ops triage agent keeps this topology exactly, with workers
running diagnostic queries instead of retrievals; the aggregation step becomes
correlation rather than citation-tracking.
