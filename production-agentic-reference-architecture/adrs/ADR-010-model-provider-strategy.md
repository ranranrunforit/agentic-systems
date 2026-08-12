# ADR-010 — Model and provider strategy: one interface, tiered routing

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

The constraint is explicit: no vendor lock-in by default; model and tool interfaces
should be swappable, and any hard dependency must be justified. Separately, the cost model
shows synthesis is 77% of per-task cost while planning, summarisation and guardrails are
small and frequent — so treating every step as needing the same model is the single
easiest way to overspend.

## Options considered

1. **One model for everything** (large).
2. **One model for everything** (small).
3. **Tiered routing behind one interface** — small for cheap steps, large for synthesis.
4. **Dynamic model selection** — a router model picks per call.
5. **Provider SDK used directly throughout.**

## Decision

**Option 3.** A `ModelClient` protocol — `complete(task, tier, payload) -> ModelResponse`
— with a `ModelRouter` mapping task to tier:

| Task | Tier | Why |
|---|---|---|
| `plan` | small | short input, structured output, cheap and frequent |
| `summarize` | small | runs N× per task; extractive, so it needs fidelity not brilliance |
| `guard` | small | screening, high volume |
| `synthesize` | large | long context, must hold provenance across sources; the quality-critical step |

Nothing above the model layer knows which provider it is talking to; adding a provider is
one class, not an orchestrator change. Measured effect of the routing lever:
**−59% per-task cost** in the eval harness (`--compare-routing`) and −57% in the
production model.

**`ModelRouter.downgrade()` is the live budget control.** When a run's projected cost
exceeds its per-task ceiling, the orchestrator caps fan-out and downgrades synthesis to the
small tier rather than either overspending or failing — a degraded answer with a recorded
`budget.model_downgraded` event beats a surprise invoice or a silent abort.

Rejections: **(1)** overpays roughly 2.4× for steps where a small model is sufficient.
**(2)** saves money on the step where quality matters most; the harness is where that
trade must be argued, not assumed. **(4)** adds a model call to decide a model call,
making cost less predictable to save cost — and the static mapping already captures the
signal, since task type *is* the difficulty signal here. **(5)** is the lock-in the
constraint forbids.

**Hard dependencies, declared.** There are none on a provider. The one framework-shaped
dependency deliberately *not* taken is an agent framework (LangGraph, CrewAI and peers):
they would supply orchestration, state and tracing at the price of owning the shape of all
three, and this project's deliverable *is* those shapes. Plain Python plus OTel plus
SQLite keeps every seam visible and swappable. The cost is that retries, backoff and
scheduling are hand-rolled (ADR-008, ADR-012).

**Version pinning.** Model identifiers are pinned per tier, never "latest". A model change
is a governed change that must pass the eval gate, because a provider-side model swap is
indistinguishable from a prompt regression from the outside.

## Consequences

**Positive**
- The dominant cost lever lives in one class and is provably effective in the harness.
- Provider substitution is a one-file change; the same rate card feeds cost attributes and
  the cost model, so they cannot drift.
- Budget enforcement has a graceful degradation path instead of a binary abort.

**Negative / accepted costs**
- Two tiers means two behaviours to evaluate, and a small-model regression can be subtler
  than a large-model one.
- Task→tier mapping is static; a genuinely hard planning problem gets the small model, and
  the fix (per-case escalation) is not built.
- The offline deterministic backend is the default (ADR-014), so real-provider quality is
  not exercised by default in CI.
