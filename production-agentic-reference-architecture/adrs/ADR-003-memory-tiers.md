# ADR-003 — Three memory tiers and the context-assembly budget

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

A research run holds three kinds of state that are routinely conflated: the current
run's plan and partial findings, slow-changing curated configuration (which sources are
trustworthy, how the user wants reports formatted), and the fetched evidence itself.
Conflating them has two concrete failure modes: the model context fills with raw fetched
documents and quality degrades (context rot), and model-authored text ends up written
into persistent state, which turns a prompt injection into a durable compromise.

Synthesis is also the dominant cost driver (77% of per-task cost at the modelled
baseline), and its cost is a direct function of how many evidence tokens enter the
context. Memory design and cost control are therefore the same decision.

## Options considered

1. **One flat context** — append everything to a growing message list.
2. **Two tiers** — session state plus a vector store for everything else.
3. **Three explicit tiers** — working (short-term), long-term (persistent), retrieved
   (external), each with its own write/read/eviction policy.
4. **Full agent-memory framework** — adopt a third-party memory product.

## Decision

**Option 3.** Three tiers as separate classes with explicit policies:

| Tier | Holds | Write policy | Read policy | Eviction |
|---|---|---|---|---|
| **Working** (`WorkingMemory`) | current run's plan, partial findings, stage status, guardrail events | every stage appends; run-scoped only | synthesizer + operator + trace | dropped at run end; durable copy is the checkpoint record, TTL-bounded |
| **Long-term** (`LongTermMemory`) | source allowlist, export-destination allowlist, format preferences, prior-report dedupe keys | **explicit, attributed, audited calls only — never from model output**; sections are enumerated and non-model-writable | planner, context assembler, `fetch` allowlist check, `export_report` destination check | TTL sweep on dedupe keys (90 d); allowlists are manually curated, never auto-grown |
| **Retrieved** (`RetrievedMemory`) | fetched documents, extractive summaries, citation metadata; doubles as the per-run fetch dedupe cache | workers, per fetch; one stable citation id per URL | context assembler only | per run; only top-k by relevance enter the synthesis context |

> **Amended by [ADR-016](ADR-016-closing-the-four-residual-risks.md)**: the assembler now
> also caps evidence *per sub-question* (default 2), which is cost lever L3. A purely global
> token cap let one well-covered sub-question crowd out the others while paying for
> near-duplicate summaries; the per-sub-question cap buys breadth per token and raised budget
> headroom from 1.02× to 1.19×.

**Context-assembly strategy (the load-bearing part).** The synthesizer never receives a
raw fetched document. It receives ranked **extractive summaries plus citations**,
truncated to a declared budget: **60% of the window for evidence, 20% for question and
plan, 20% headroom** for output, guardrail re-reads and retry margin. The assembler
reports `context_utilisation` and `evidence_items_dropped` as span attributes, so
truncation is visible in the trace rather than silent.

Rejections: **(1)** blows the window and makes cost unbounded in the number of sources.
**(2)** hides the critical distinction — a vector store holding both curated allowlists
and model-derived text has no defensible write policy. **(4)** was rejected for
vendor-lock-in and because the policies above are the actual deliverable; a framework
would supply mechanism while leaving the policy decisions unmade, and the policies are
what a reviewer needs to approve.

## Consequences

**Positive**
- Cost is controlled at its dominant driver: extractive summarisation before synthesis
  is simultaneously the quality control and the largest cost lever.
- The injection blast radius is bounded. Model output cannot reach long-term memory, so
  a poisoned source cannot add itself to the allowlist or change the export destination.
- Truncation is observable, so "the report missed a source" is diagnosable from the trace
  rather than a mystery.

**Negative / accepted costs**
- Extractive-only summarisation loses cross-document synthesis that an abstractive pass
  might catch; the trade is deliberate, because extractive spans stay checkable against
  the source and abstractive ones do not.
- Three tiers is more code and more concepts than one context list.
- The allowlist is a curated asset with ongoing human cost; coverage is bounded by it.
- Working memory is dropped at run end, so post-hoc analysis relies on the trace and
  checkpoints. Accepted: the trace is the durable record (ADR-006).
