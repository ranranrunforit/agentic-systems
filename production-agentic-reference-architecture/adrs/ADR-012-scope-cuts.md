# ADR-012 — Conscious scope cuts

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

This is a 30-hour architecture package with a prototype sized to prove critical paths, not
a product. Cuts are therefore inevitable. The failure mode worth avoiding is not cutting
scope — it is cutting scope *invisibly*, so a reviewer mistakes a gap for a completed
feature. This ADR is the single place a reviewer can look to see what is deliberately
absent, why, and what it would take to close.

## Options considered

1. Leave gaps undocumented and hope they are read as prototype boundaries.
2. Scatter caveats through the code as TODOs.
3. Record every material cut in one ADR, with rationale, risk, and the closing move.

## Decision

**Option 3.** The cuts, in rough order of how much a reviewer should care:

| # | Cut | Why | Risk accepted | To close |
|---|---|---|---|---|
| ~~1~~ | ~~Fixture corpus instead of live web retrieval~~ — **CLOSED**, see [ADR-016](ADR-016-closing-the-four-residual-risks.md) | fixture stays the *default* for gate determinism | residual: **search** still needs a commercial provider; `HttpTransport.search` raises rather than pretending | `agent/retrieval.py` — real HTTP with robots.txt, HTML extraction, streaming size caps, redirect re-validation and SSRF defences; `--retrieval http` |
| 2 | **Stdlib validation instead of Pydantic** | zero-install reviewability | hand-rolled validators could diverge from the documented Pydantic semantics | drop in Pydantic v2 models; semantics were written to match |
| 3 | **SQLite instead of a durable-workflow engine** (ADR-008) | no infrastructure for a small team | single-writer; no timers, backoff scheduling or cross-service orchestration | implement the narrow `CheckpointStore` interface against Temporal/Restate |
| ~~4~~ | ~~Groundedness is structural, not entailment-based~~ — **CLOSED**, see [ADR-016](ADR-016-closing-the-four-residual-risks.md) | — | residual: lexical support is not logical entailment; a claim copying a *wrong* source still passes | `agent/groundedness.py` — coverage, numeric grounding (digits **and** words), invented negation; mutation M5 |
| 5 | **No multi-tenancy or per-tenant isolation** | out of scope for a single-team green-field system | long-term memory, allowlists and the checkpoint DB are global; a second tenant would share source policy and dedupe keys | tenant column on every table, tenant-scoped LTM, per-tenant budget ceilings |
| ~~6~~ | ~~HITL approval is a CLI command~~ — **CLOSED**, see [ADR-015](ADR-015-authenticated-approval-and-review-ui.md) | — | — | `prototype/server.py` now serves an authenticated review UI showing the report, its declared coverage gaps, guardrail events and cost before approval |
| ~~7~~ | ~~Audit log is not tamper-evident~~ — **CLOSED**, see [ADR-015](ADR-015-authenticated-approval-and-review-ui.md) | — | residual: shipping to append-only external storage is still the production requirement | `prototype/agent/audit.py` hash-chains every record with a mirrored head pointer; `run.py audit <run_id>` verifies |
| 8 | **Retries are simple and inline; no backoff or jitter** | keeps the loop legible | a flapping upstream is retried without pacing | wrap tool invocation in a bounded retry policy with jitter (or get it from the workflow engine, cut 3) |
| 9 | **Coverage sufficiency is binary** (ADR-011) | simple, no threshold to defend | a one-of-three-succeeded run pays full synthesis for thin evidence | coverage-ratio threshold with a configured minimum before synthesis is entered |
| ~~10~~ | ~~Pre-flight cost estimates are static constants~~ — **CLOSED**, see [ADR-016](ADR-016-closing-the-four-residual-risks.md) | — | residual: averages across question shapes, so an unusual run is mis-projected | `CostCalibrator` — rolling mean over the last 20 runs' observed spend; the seeds were over-estimating by 2–3.5× |
| 11 | **No PII detection beyond regex** | volume reduction is the goal, not completeness | novel PII formats pass the egress screen | commercial classifier or a trained NER model at the output boundary |
| 13 | **Search has no provider** (new, from closing cut 1) | fetch is real; there is no standards-based search to fall back on | `--retrieval http` cannot discover sources without `--search-endpoint` | wire a commercial search API at `HttpTransport.search` |
| 12 | **Single-language, single-region assumptions** | scope | keyword-based retrieval and screening are English-shaped | tokenizer- and locale-aware keyword extraction; localised injection patterns |

Two cuts a reviewer might expect to see here but which are **not** cuts, because they were
built: distributed tracing with cost attributes (FR-5) is real and end-to-end, and the
durable resume (FR-7) genuinely survives a `kill -9` mid-fan-out.

**Cuts 6 and 7 (threat-model R1, R2) were closed by
[ADR-015](ADR-015-authenticated-approval-and-review-ui.md); cuts 1, 4 and 10 (R3, R6) by
[ADR-016](ADR-016-closing-the-four-residual-risks.md).** They are struck through above
rather than deleted, because the record of what was cut and later reinstated is part of the
decision history — and because each closure surfaced a real bug that the documented version
never would have (see ADR-015 §"A bug this decision surfaced" and ADR-016 §Decisions).

## Consequences

**Positive**
- A reviewer can grade the package on what it claims, and the claims are bounded.
- Each cut names the interface that makes it closable, which is a design property, not
  just documentation — cuts 1, 2 and 3 are all single-seam substitutions because the seams
  were placed deliberately.

**Negative / accepted costs**
- The prototype's absolute cost and latency numbers are not production numbers (see
  ADR-014); only the shape transfers.
- Eight cuts remain open (2, 3, 5, 8, 9, 11, 12, 13); five have been closed (1, 4, 6, 7, 10).
- The most consequential open one is now **cut 11** (regex-only PII detection), since the
  destination allowlist is what holds when detection fails.
- **Cut 13 is new, created by closing cut 1**: making fetch real exposed that search was
  never real either. Recording it as a fresh cut rather than folding it into the old one keeps
  the count honest — closing a gap can reveal an adjacent one.
