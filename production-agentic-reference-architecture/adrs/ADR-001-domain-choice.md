# ADR-001 — Domain: a deep-research agent

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect
- **Supersedes / superseded by**: —

## Context

The capstone is domain-learner-selected. The domain choice is itself the first
architectural decision, because every later decision (topology, memory tiers, where the
write boundary sits, what the eval scores) is downstream of it. The selection criterion
is not "which domain is most impressive" but **which domain makes the agentic topology
necessary rather than decorative**. If a single prompt-and-response would serve the
domain, the orchestrator-workers machinery is unjustified complexity and the whole
package collapses on architectural soundness.

The constraint set is real: a fixed monthly inference envelope, a user-visible latency
budget, a small team with no dedicated SRE function, and a governance reviewer who will
not approve launch without a threat model and an eval gate.

## Options considered

1. **Deep-research agent** — takes a research question, decomposes it into
   sub-questions, fans out retrieval across independent sources in parallel, and
   synthesises a cited report. One privileged action: publishing/exporting the report.
2. **Data-operations triage agent** — receives an alert, runs diagnostic queries in
   parallel, correlates results, and proposes (or applies) a remediation. Privileged
   action: `apply_remediation`.
3. **Customer-facing KB assistant with bounded actions** — answers from a knowledge
   base and can take a small set of write actions. Privileged action: `create_ticket` /
   `issue_refund`.
4. **Internal operations agent** (finance close, supply-chain exceptions, content
   moderation) — ingests exceptions, gathers context from several systems, proposes
   dispositions.
5. **Single-purpose summariser / Q&A bot** — one prompt, one response.

## Decision

**Option 1, the deep-research agent.**

The topology-warranted test, stated concretely: the work requires (a) *decomposition*,
because a research question has independently-answerable parts; (b) *bounded parallel
retrieval*, because the parts are independent and latency is dominated by the slowest
source rather than the sum of sources; (c) *per-source provenance*, because every claim
in the output must carry a citation traceable to the specific fetch that produced it;
and (d) *aggregation under partial failure*, because sources fail independently and the
report must declare what it could not cover. No single prompt-and-response can do (b)
and (c) together — a monolithic call has no per-source span, no way to bound
concurrency, and no place to attach provenance. That is what makes the
orchestrator-workers topology load-bearing here.

Options 2–4 are **equally valid peers** and would score identically with the same
rigour; they simply earn the topology on different terms (2 through parallel diagnostic
queries plus an irreversible remediation; 3 through retrieval plus bounded writes; 4
through multi-system context gathering). Where an artifact in this package would change
for a peer domain, the change is called out inline. Option 5 is rejected outright: it
fails the topology-warranted test by construction.

Secondary reasons for picking option 1 over its peers, stated so the choice is not
mistaken for a claim of superiority: the domain has a **naturally single high-risk
action** (external publication), which makes the action-confirmation boundary crisp
rather than a judgement call spread across many write tools; and its failure mode
(a fluent, confidently uncited report) is the exact failure that trajectory evaluation
exists to catch, so the eval deliverable has real teeth.

## Consequences

**Positive**
- The orchestrator-workers topology, the three memory tiers, and the trajectory eval
  all trace to concrete needs in this domain rather than to the module list.
- One write tool means one confirmation boundary — simple enough for a small team to
  operate and reason about, which is the operability constraint.
- Groundedness is mechanically checkable (does every claim bullet carry a citation
  marker?), so the output guardrail and the eval end-state lens can share a definition.

**Negative / accepted costs**
- Retrieval quality depends on sources the team does not control; the source allowlist
  in long-term memory becomes a curated asset with ongoing cost (ADR-003).
- Open-web fetch has the fattest latency tail in the system and it sits on the hot path
  (see the cost model: fetch and synthesis dominate p95).
- "Grounded" is not "correct". A report can cite faithfully and still mislead if the
  sources are wrong. The architecture bounds provenance, not truth; this limit is
  recorded in ADR-012 rather than papered over.

**Follow-ups**
- ADR-002 (topology), ADR-009 (HITL boundary on export), ADR-013 (fan-out width).
