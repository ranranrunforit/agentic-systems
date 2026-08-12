# ADR-008 — Durable execution: per-stage checkpoints in SQLite

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

Two things make runs long-lived. First, a wide research run does real paid work over tens
of seconds — losing it to a deploy or a crash means re-paying for completed retrieval.
Second, the HITL export pause may last hours: a run waiting for a human approver cannot
live in process memory.

The team is small and has no dedicated SRE function, so the durability mechanism must be
operable without new infrastructure.

## Options considered

1. **No durability** — retry the whole run on failure.
2. **A durable-workflow engine** (Temporal, Restate, Azure Durable Functions).
3. **Per-stage checkpoints in an embedded database (SQLite).**
4. **Event sourcing the trace** — replay from `trace.jsonl`.

## Decision

**Option 3.** SQLite with one write transaction per completed stage, and one rule:
**every unit of paid work is committed before the next one starts.**

Checkpoint boundaries are exactly the stages that cost money or time:
`plan`, `worker:<i>` (one per retrieval worker), `synthesis`, `guardrail:output`,
`awaiting_approval`, `export`. A restart reads the committed stages and skips them —
resume is *skip completed*, not replay. Worker checkpoints are per worker precisely so
that a crash mid-fan-out re-pays only for the workers that had not finished.

**Failures are checkpointed too.** A worker that failed commits its failure, so a resume
does not retry a dead source indefinitely and the synthesizer sees a stable picture of
coverage. Checkpoint writes are idempotent (`ON CONFLICT … DO UPDATE`), so a re-run of a
stage is safe.

Two implementation choices worth recording. `synchronous=FULL`, so a `kill -9` between
stages loses at most the in-flight stage. Journal mode is **TRUNCATE by default rather
than WAL**, overridable via `AGENT_SQLITE_JOURNAL` — WAL requires a shared-memory mmap
that some network and FUSE filesystems refuse, and an unrunnable spike is worse than a
slightly slower one; use WAL on local disk.

Rejections: **(2)** is the right answer at scale and the intended migration target — but
it is a service to run, monitor and learn, which contradicts the team-size constraint for
a day-one system, and its programming model would spread through the orchestrator making
later substitution harder, not easier. The checkpoint interface here is deliberately
narrow (`put` / `get` / `stages`) so swapping in a real engine is a store implementation,
not a rewrite. **(1)** re-pays for completed retrieval and cannot express an hours-long
approval pause at all. **(4)** conflates the observability record with the state machine;
traces are append-only and lossy by design (sampling, truncation), which makes them a poor
source of truth for resumption.

**Demonstrated, not asserted.** `run.py run … --crash-after-workers 1` hard-kills the
process (`os._exit`) after the first worker commits; `run.py resume <run_id>` completes
the run, emitting `stage.resumed` events and re-fetching nothing already done. The trace
shows only the remaining worker's spans.

## Consequences

**Positive**
- A crash costs at most one stage; an approval pause costs nothing.
- Zero new infrastructure — one file on disk, inspectable with `sqlite3`.
- Checkpoints double as the audit trail of what a run actually did, alongside the trace.

**Negative / accepted costs**
- SQLite is single-writer; concurrent runs on one file will contend, and this does not
  scale horizontally. Fine at the current envelope (~12k tasks/month), and the reason the
  interface is narrow.
- No automatic retry/backoff scheduling, no timers, no cross-service orchestration — all
  things a real engine gives for free. Recorded as a scope cut (ADR-012).
- Checkpoint payloads contain evidence summaries, so they inherit the retention and PII
  policy of user data.
