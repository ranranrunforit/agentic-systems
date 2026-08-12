# ADR-006 — OpenTelemetry-shaped tracing with cost attributes

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

The operability requirement is specific: an on-call engineer must be able to answer
"what is this run doing and why" from traces and logs alone, with no dedicated SRE team
and no reproduction. For an agent this means the trace must show which sub-questions were
planned, which sources each worker touched, which one stalled or failed, what each model
call cost, and where the guardrails fired. Cost also has to be observable per run, or the
cost model is a spreadsheet nobody can check against reality.

## Options considered

1. **Structured logs only.**
2. **Vendor APM / LLM-observability SaaS** with a proprietary SDK.
3. **OpenTelemetry with GenAI semantic conventions**, exported to any OTLP collector.
4. **Custom in-house span format.**

## Decision

**Option 3**, with a local JSONL exporter as the default in the spike.

- **Span per unit of work**: orchestrator (trace root), each worker, each tool call, each
  model call, each guardrail, the HITL gate. Parent links are passed **explicitly**
  rather than via context-locals, because workers run in a thread pool and implicit
  context propagation across threads is exactly where agent traces lose their shape.
- **Standard attributes**: `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, `gen_ai.operation.name`.
- **Derived attributes**: `cost_usd` (from token counts and the local rate card — cost is
  not a standard OTel attribute) and `latency_ms` on every span.
- **Domain attributes**: `subquestion`, `tool.url`, `tool.cache_hit`,
  `guardrail.reasons`, `context.evidence_items_dropped`, `run.fanout_width`.
- **Events, not just attributes**, for things that happened once:
  `guardrail.blocked`, `worker.degraded`, `stage.resumed`, `hitl.pause`, `hitl.approved`,
  `budget.fanout_capped`, `audit.appended`.
- **Cost is not double-counted**: the root span carries `run.cost_usd` as a rollup and
  `cost_usd: 0` as its own contribution, so summing `cost_usd` across spans gives the
  true total.

The exporter is swappable and the attribute names do not change with it: JSONL by default
(offline, zero infrastructure, and directly readable by the eval harness), mirrored to a
real OTLP endpoint when `opentelemetry-sdk` is installed and `OTEL_EXPORTER_OTLP_ENDPOINT`
is set. `run.py trace <run_id>` renders the tree for on-call use.

Rejections: **(1)** cannot express the parent/child structure that makes an agent run
legible, and correlating a fan-out from flat logs is manual work under incident pressure.
**(2)** violates the no-lock-in constraint at the observability layer, which is the worst
place to be locked in, since it is the layer every incident depends on. **(4)** is
strictly worse than a standard that already has conventions, collectors and dashboards.

**The trace is also the eval and replay substrate.** The harness scores trajectory
predicates directly from `trace.jsonl`, and a failed run can be reconstructed from it.
One artifact serves observability, evaluation, and replay debugging — that reuse is a
significant part of why the trace design is worth this much attention.

## Consequences

**Positive**
- "Which source stalled?" is one glance at the child spans of the fan-out.
- Per-run cost is measured, not estimated, and feeds the cost model's calibration mode.
- Vendor-neutral: changing collector changes one env var.

**Negative / accepted costs**
- Explicit parent passing is more verbose than a context-manager-only API and can be got
  wrong; the tree-render output makes a broken link obvious.
- Cost attributes depend on a hard-coded rate card that must be updated when prices
  change; the rate card lives in one module shared with the cost model to prevent drift.
- Traces contain the question and evidence summaries, so they are subject to the same
  retention and PII policy as any user data (see `governance/`).
