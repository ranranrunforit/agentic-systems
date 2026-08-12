# Architecture Decision Records

Sixteen ADRs, each with **Context / Options considered / Decision / Consequences**.
Consequences are split into positive and accepted-cost so trade-offs are visible rather
than implied.

| ADR | Decision | Why this over the alternatives |
|---|---|---|
| [001](ADR-001-domain-choice.md) | **Domain: deep-research agent** | Needs decomposition → bounded parallel retrieval → cited synthesis with per-source provenance. A single call cannot do parallel retrieval *and* provenance. Peer domains (data-ops triage, KB assistant + bounded actions, internal ops) are named as equals. |
| [002](ADR-002-topology.md) | **Orchestrator-workers** | ReAct is sequential with no checkpoint boundary; a fixed pipeline cannot vary decomposition; debate multiplies cost non-deterministically; hierarchical makes the ceiling unenforceable. |
| [003](ADR-003-memory-tiers.md) | **Three memory tiers + 60/20/20 context budget** | Working ≠ curated persistent ≠ retrieved evidence. Raw documents never reach synthesis — simultaneously the quality control and the largest cost lever. |
| [004](ADR-004-tool-boundary.md) | **Typed contracts, validated at every boundary** | Tool args are untrusted input. Unknown fields rejected; `MODEL_FORBIDDEN` fields structurally stripped from model-authored payloads. |
| [005](ADR-005-eval-strategy.md) | **Trajectory + end-state, predicate-based, gated** | End-state-only ships the confidently-uncited report. Golden transcripts penalise better paths. The gate is itself mutation-tested. |
| [006](ADR-006-observability.md) | **OTel GenAI spans + derived cost/latency** | Vendor-neutral; one artifact serves observability, eval scoring and replay. Explicit parent links because workers are threaded. |
| [007](ADR-007-guardrail-placement.md) | **Three screens, one confirmation boundary** | Indirect injection is the *expected* case in this domain, so tool output gets its own screen. Pattern matching reduces volume; architecture is the control. |
| [008](ADR-008-durable-execution.md) | **Per-stage SQLite checkpoints** | Every unit of paid work commits before the next starts. A workflow engine is the migration target, not the day-one dependency. |
| [009](ADR-009-hitl-boundary.md) | **Human approves export only** | Threshold is irreversibility ∧ external visibility, *not* "all writes". Token bound to run id + report hash. |
| [010](ADR-010-model-provider-strategy.md) | **One interface, tiered routing** | Small for plan/summarise/guard, large for synthesis: −59% cost, measured. `downgrade()` is the live budget control. No provider or framework lock-in. |
| [011](ADR-011-partial-failure-handling.md) | **Degrade loudly, never silently** | The dangerous outcome is a successful-looking run whose scope quietly narrowed. Enumerated status per failure class. |
| [012](ADR-012-scope-cuts.md) | **Twelve conscious cuts, recorded** | Cutting scope is fine; cutting it invisibly is not. Each cut names the seam that closes it. |
| [013](ADR-013-fanout-width-and-budget-enforcement.md) | **Fan-out 3 (not the assumed 4), enforced live** | The cost model showed width 4 breaches both the p95 budget and the envelope. Width 3 is derived, not guessed. |
| [014](ADR-014-deterministic-model-backend.md) | **Deterministic offline model is the default** | A flaky gate gets bypassed. This is a real implementation over real evidence, not a mock — proven by the mutation test. |
| [015](ADR-015-authenticated-approval-and-review-ui.md) | **Authenticated approval + review UI + hash-chained audit** | Closes the one launch-blocker (R1). Identity comes from a scoped session, not an argument; the reviewer sees the report, its coverage gaps and the guardrails that fired; the audit chain detects tampering. Surfaced a real DoS bug in the gate. |
| [016](ADR-016-closing-the-four-residual-risks.md) | **Semantic groundedness · real HTTP retrieval · MFA/CSRF/TLS · calibrated budget + lever L3** | Closes R3 (the highest open safety risk), cut 1, cut 10, and the ADR-015 residuals. Headroom 1.02× → 1.19×. Each closure surfaced a real bug: case-sensitive HTTP headers, a false-positive negation check, and a gate that built its own session store. |

## Reading order for a reviewer with 15 minutes

001 (why this domain) → 002 (why this topology) → 013 (why the numbers forced a change) →
005 (why the gate has teeth) → 015 and 016 (closing the risks, and the bugs that closing
them exposed) → 012 (what is still deliberately missing).
