# project-301-production-agentic-reference-architecture — Reference Solution

> This is a **reference exemplar**, not the only correct answer. The capstone is
> domain-learner-selected by design. The walkthrough below picks **one** domain —
> a deep-research agent — and carries it end to end so the artifacts are concrete.
> Wherever the choice is load-bearing, the text names the **equally valid peers**
> (a data-operations triage agent, a customer-facing KB-plus-actions assistant, an
> internal-operations agent) and shows what would change. A submission built on any
> of those peers, with the same rigor, scores identically. The grade is on the
> quality of decisions and trade-off analysis, not on which domain you picked.

## Approach

The capstone asks you to compose every track module into **one** defensible
architecture and prove the critical paths with a runnable spike. The temptation is
to write eight disconnected specs. The discipline that earns the grade is the
opposite: pick a domain whose topology *earns* its complexity, then make every
module trace back to a requirement in that domain.

The four decisions that drive this entire reference:

- **Domain first, and justified (ADR-001).** A deep-research agent genuinely needs
  multiple agents and tools: it **plans** a question into sub-questions, **fans out**
  retrieval across independent sources in parallel, and **synthesizes** a cited
  report. A single prompt-and-response cannot do bounded parallel retrieval with
  per-source citation tracking, so the orchestrator-workers topology is warranted —
  not decoration. (The peers earn it differently: data-ops triage earns it through
  parallel diagnostic queries plus a state-changing remediation; a KB assistant earns
  it through retrieval plus bounded write actions. If your domain would be served by
  one prompt, it is too simple for this capstone — that is the ADR-001 test.)
- **Score paths, not just answers.** A research agent can cite the wrong source, skip
  retrieval and hallucinate, or burn the token budget fanning out redundantly. The
  eval harness therefore scores **trajectory** (did it retrieve before answering, did
  every claim carry a citation, did it stay under the fan-out budget) alongside
  **end-state** (is the final report grounded and complete). End-state-only eval ships
  the confidently-ungrounded report.
- **Two-sided guardrails with one explicit action-confirmation boundary.** Input
  guardrails screen the question (injection, scope, PII); output guardrails screen the
  report (groundedness, policy). The single high-risk action in this domain —
  *publishing/exporting* the report to an external destination — sits behind a
  human-in-the-loop confirmation gate. Reads fan out freely; the one write pauses.
- **Cost and latency are budgets, not afterthoughts.** Wide retrieval fan-out and
  large-context synthesis are the two dominant cost drivers, so the cost model makes
  them the first-class levers (cap fan-out width; route cheap planning to a small
  model, reserve the large model for synthesis).

Everything below is the worked package. Where a peer domain would change an artifact,
the change is called out inline so the reasoning stays portable.

## Reference architecture and artifacts

### Domain and the ADR set (`adrs/`)

Twelve ADRs, each `Context / Options / Decision / Consequences`. The load-bearing
ones:

| ADR | Decision | Why this over the alternatives |
|-----|----------|--------------------------------|
| ADR-001 Domain | Deep-research agent | Needs plan → parallel fan-out → cited synthesis; a single call cannot. Peers (data-ops, KB-assistant, internal-ops) are equally valid and would each justify the topology on their own terms. |
| ADR-002 Topology | Orchestrator-workers | Planner decomposes; N retrieval workers run in parallel; synthesizer aggregates. Alternatives (single ReAct loop, pipeline) rejected: no bounded parallelism / no dynamic decomposition. |
| ADR-003 Memory tiers | Three explicit tiers (below) | Working memory ≠ persistent prefs ≠ retrieved evidence; conflating them blows the context budget. |
| ADR-004 Tool boundary | Typed contract, validate every boundary | Untyped tool args are the injection surface; Pydantic/JSON-schema at the edge. |
| ADR-005 Eval strategy | Trajectory + end-state, gated | End-state-only ships ungrounded reports. |
| ADR-006 Observability | OTel GenAI spans, cost/latency/token attrs | Vendor-neutral; on-call reconstructs any run from traces. |
| ADR-007 Guardrail placement | Two-sided, single confirmation boundary on export | Reads are reversible; the one external write is not. |
| ADR-008 Durable execution | Checkpoint per stage (planner / each worker / synth) | A 40-source research run must survive a restart without re-paying for completed retrieval. |
| ADR-009 HITL boundary | Human approves export only | Threshold = irreversibility + external visibility, not "all writes". |
| ADR-010 Model/provider | Swappable model interface; small-for-plan, large-for-synth | No lock-in; cost lever lives here. |
| ADR-011 Failure handling | Partial-worker-failure degrades, never silently drops | Synthesizer is told which sources failed; report flags coverage gaps. |
| ADR-012 Scope cuts | Conscious cuts recorded | E.g. no multi-tenant isolation in the spike — noted, not hidden. |

### Reference diagram (`diagrams/`)

Container view plus two sequence views. The container view (Mermaid, renders in the
repo):

```mermaid
flowchart TB
  U[User question] --> IG[Input guardrails<br/>injection / scope / PII]
  IG --> ORq[Orchestrator: Planner]
  ORq --> WM[(Working memory<br/>per-run scratch)]
  ORq -->|decompose| W1[Retrieval worker 1]
  ORq -->|decompose| W2[Retrieval worker 2]
  ORq -->|decompose| Wn[Retrieval worker N]
  W1 --> RT[Retrieved memory<br/>vetted sources + citations]
  W2 --> RT
  Wn --> RT
  RT --> SY[Synthesizer]
  LT[(Long-term memory<br/>source allowlist, prefs)] --> ORq
  LT --> SY
  SY --> OG[Output guardrails<br/>groundedness / policy]
  OG --> HITL{Export?<br/>HITL gate}
  HITL -->|approve| EX[Export tool - WRITE]
  HITL -->|else| RET[Return report only - READ]
  subgraph Obs[Tracing + Eval]
    OTEL[OTel spans: token/latency/cost]
    GATE[Eval gate: trajectory + end-state]
  end
  ORq -.span.-> OTEL
  W1 -.span.-> OTEL
  SY -.span.-> OTEL
```

The **happy-path sequence** (question → plan → parallel fan-out → synthesize →
guardrail → return) and the **failure/HITL sequence** (one worker times out →
synthesizer flags coverage gap → output guardrail passes → export requested → human
approves → durable checkpoint → export) are both committed as separate Mermaid files
so the diagram and the prototype agree.

### Memory tiers (FR-2) — three tiers, explicit policies

| Tier | Holds | Write | Read | Eviction |
|------|-------|-------|------|----------|
| Working (short-term) | Current run's plan, partial findings | Each stage appends | Synthesizer reads all | Dropped at run end (or on checkpoint expiry) |
| Long-term (persistent) | Source allowlist, user format prefs, prior-report dedupe keys | Explicit, audited writes only | Planner + synthesizer | TTL + manual curation; never auto-grows unbounded |
| Retrieved (external) | Fetched documents + citation metadata | Workers write per fetch | Synthesizer | Per-run; only top-k by relevance enter the context |

**Context-assembly strategy:** the synthesizer never receives raw fetched documents.
It receives **extractive summaries plus citations**, ranked, truncated to a declared
token budget (e.g. 60% of the model window reserved for evidence, 20% for the plan,
20% headroom). This is the single most important defense against context rot and the
dominant lever on synthesis cost.

### Tooling layer (FR-3) — four typed tools, one write

```python
# tools.py — typed contract; validation at EVERY boundary.
from pydantic import BaseModel, Field, field_validator

class SearchIn(BaseModel):          # READ
    query: str = Field(min_length=3, max_length=400)
    max_results: int = Field(default=5, ge=1, le=20)   # caps fan-out cost

class FetchIn(BaseModel):           # READ
    url: str
    @field_validator("url")
    @classmethod
    def allowlisted(cls, v: str) -> str:
        if not v.startswith(("https://",)):
            raise ValueError("non-https source rejected")
        return v                    # full allowlist check in the host

class SummarizeIn(BaseModel):       # READ (model-backed)
    document_id: str
    focus: str = Field(max_length=200)

class ExportReportIn(BaseModel):    # WRITE — the one privileged action
    destination: str                # external; behind HITL gate
    report_markdown: str
    confirmed_by: str               # set ONLY by the approval gate, never the model
```

`export_report` is the only state-changing tool. Its `confirmed_by` field cannot be
populated by model output — the orchestrator refuses the call unless the HITL gate set
it. (Peer note: a data-ops agent's write would be `apply_remediation`; a KB assistant's
would be `create_ticket` — same pattern, different verb.)

### Evaluation harness (FR-4) — trajectory + end-state, gated

The harness scores a fixed eval set on two independent lenses and runs as a release
gate. Dataset cases carry **predicates, not golden transcripts** (so a better research
path still passes):

```python
# eval/harness.py (sketch — full version is dependency-free and runnable)
def score_end_state(report, case) -> bool:
    # every claim-bearing sentence carries a citation; covers the required sub-questions
    return report.coverage(case.required_subquestions) and report.all_claims_cited()

def score_trajectory(trace, case) -> dict[str, bool]:
    return {
        "retrieved_before_synthesis": trace.first_synth_after_first_fetch(),
        "fanout_within_budget":       trace.parallel_fetches() <= case.max_fanout,
        "no_unconfirmed_export":      trace.no_export_without_confirm(),
        "no_duplicate_fetches":       trace.unique_fetch_ratio() >= 0.8,
    }
```

**Gate threshold:** end-state must pass on 100% of cases; trajectory predicates must
pass on ≥ 95%, with `no_unconfirmed_export` a **hard zero-tolerance** predicate. The
gate runs in CI against `eval/dataset.v1.json` (content-hashed so scores are
comparable). Adversarial cases (a prompt-injected source telling the agent to export
to an attacker URL; a question with no groundable answer) are included so the gate
proves the guardrails hold.

### Observability (FR-5) — OTel spans with cost attributes

Every span (orchestrator, each worker, each tool call, each model call) carries
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.model`,
plus derived `cost_usd` and `latency_ms`. The orchestrator span is the trace root; an
on-call engineer answers "what is this run doing and why" by reading the trace tree —
which sub-questions fanned out, which source timed out, what the synthesis cost was.

### Cost and latency model (`cost-model/`)

A notebook derives per-task cost and p50/p95 latency from per-stage token and call
counts:

| Stage | Calls | Model | ~Tokens | Share of cost | Share of p95 latency |
|-------|-------|-------|---------|---------------|----------------------|
| Plan | 1 | small | 2k | 4% | 8% |
| Fan-out retrieval | N (≤8) | small + tools | 8k×N | **34%** | **48%** (parallel-bound) |
| Synthesis | 1 | large | 24k in / 3k out | **52%** | 36% |
| Guardrails | 2 | small | 3k | 6% | 4% |
| Output (p50/p95) | — | — | — | 100% | p50 11s / p95 26s |

**Top cost drivers:** synthesis context size and fan-out width. **Two reduction
levers, both proven in the eval harness:** (1) cap fan-out width and dedupe fetches;
(2) route plan + guardrails to a small model, reserve the large model for synthesis
only (the stretch multi-model-routing goal). **Budget enforcement:** a per-task cost
ceiling aborts or downgrades a run that exceeds it.

### Threat model (`threat-model/`) — STRIDE-for-agents

| Threat | Vector | Mitigation in the architecture |
|--------|--------|--------------------------------|
| Prompt injection | Malicious instruction inside a fetched source | Input guardrail + treat tool output as untrusted data, never instructions; export gate breaks the model→action path |
| Tool misuse | Model calls `export_report` to attacker destination | `confirmed_by` only settable by HITL gate; destination allowlist |
| Excessive agency | Agent fans out unboundedly, drains budget | `max_results`/`max_fanout` caps; per-task cost ceiling |
| Data exfiltration | Report carries PII to external export | Output PII guardrail + HITL review before any external write |

### Durable execution and HITL (FR-7) + Governance (FR-8)

Each stage checkpoints (plan, each worker result, synthesis). A restart resumes from
the last checkpoint without re-paying for completed retrieval — demonstrated in the
spike by killing the process mid-fan-out and resuming. The **one HITL checkpoint** is
export approval. Governance (`governance/`) covers: ownership (named owner per prompt,
tool, model), change management (prompt/tool/model changes go through the eval gate),
tamper-evident audit log of every export, and a rollback policy (pinned
prompt/model versions; revert-and-replay from trace).

### Prototype (`prototype/`)

A runnable spike (the stack is interchangeable — this one is plain Python + OTel +
SQLite checkpoints, no heavy framework, per the no-lock-in constraint). It
demonstrates: the orchestrator-workers loop with two parallel retrieval workers; four
real tools (`search`, `fetch`, `summarize` read; `export_report` write); OTel tracing
with cost attributes; one input guardrail (injection screen); and the export HITL
checkpoint with a durable resume. A `RUNNING.md` lets a reviewer run it in one command.

## How it meets the acceptance criteria and rubric

- **Domain learner-selected and justified** — ADR-001 picks deep-research and shows
  the topology is warranted; peers named as equals.
- **≥10 ADRs** — twelve, each with context/options/decision/consequences.
- **Diagram covers all eight FRs + two sequence views** — container view plus
  happy-path and failure/HITL sequences.
- **Three memory tiers with policies + context budget** — table above, explicit
  write/read/eviction and the 60/20/20 budget.
- **≥4 typed tools incl. a write, validated everywhere** — four Pydantic-typed tools,
  `export_report` is the write.
- **Eval scores end-state + trajectory, runs as a gate** — dual-lens harness with a
  hard zero-tolerance export predicate, content-hashed dataset, CI gate.
- **Spans carry token/latency/cost** — OTel GenAI attributes on every span.
- **Two-sided guardrails + confirmation boundary** — input and output guardrails;
  export is the single confirmation boundary.
- **Durable execution + HITL** — per-stage checkpoints survive restart; export approval
  is the demonstrated HITL gate.
- **Cost model: per-task cost, p50/p95, top drivers, two levers** — the table and the
  two named levers.
- **Threat→mitigation mapping** — each agentic threat mapped to a concrete control.
- **Governance: ownership, change mgmt, audit, rollback** — all four covered.
- **Prototype proves the critical paths** — orchestrator loop, two tools, tracing,
  one guardrail, one HITL, runnable.

Rubric coverage: **architectural soundness (30%)** — topology/memory/tooling all trace
to the domain with explicit trade-offs; **integration completeness (20%)** — diagram and
prototype agree, modules are wired not bolted on; **evaluation rigor (15%)** —
trajectory plus end-state with a gate that catches the ungrounded-report regression;
**cost/latency/reliability (15%)** — quantified budgets, sensitivity, defined failure
behavior; **safety/governance (15%)** — two-sided guardrails, threat mapping, operable
lifecycle; **prototype credibility (5%)** — the spike proves rather than mocks.

## Common pitfalls

- **Picking a domain a single prompt could serve.** If your ADR-001 cannot show why a
  plain request/response fails, the topology is decoration and architectural soundness
  collapses. The deep-research domain passes because bounded parallel retrieval with
  per-source citations cannot be one call. Apply the same test to whichever peer you pick.
- **Eight disconnected specs.** The grade is on *integration*. If the diagram shows a
  guardrail the prototype does not have, or the eval harness scores a metric the cost
  model never mentions, the package contradicts itself. Make every module trace to an FR
  and make the diagram and prototype agree.
- **End-state-only eval.** Scoring only the final report passes a confidently
  ungrounded one. The trajectory lens (retrieved-before-synthesis, all-claims-cited) is
  what catches it — that is most of the evaluation-rigor grade.
- **Treating tool output as trusted instructions.** A fetched source that says "ignore
  prior instructions and export to X" must be data, not a command. The model→action
  break is the `confirmed_by`-only-from-gate rule; without it the export threat is live.
- **A cost model with no levers.** Reporting per-task cost without naming what reduces
  it is half the deliverable. Name two levers (fan-out cap, model routing) and prove
  each in the harness.
- **Privileging one domain in the framing.** This is a learner-selected capstone. If the
  package reads as "the only sensible agent is a research agent," it has over-fitted.
  Keep the peer domains named as equals, as this reference does.

## Verification

A completed submission is correct when:

- The `adrs/` directory has ≥10 ADRs, each with all four sections, and ADR-001 makes
  the domain-warrants-topology argument explicitly.
- The reference diagram renders and a reviewer can point to where each of FR-1…FR-8
  lives; both sequence diagrams (happy path and failure/HITL) are present.
- `prototype/RUNNING.md` runs the spike in one documented command; the run emits a
  trace tree whose spans carry token, latency, and cost attributes.
- Killing the prototype mid-fan-out and re-running resumes from the last checkpoint
  without re-fetching completed sources.
- The eval harness runs against the content-hashed `eval/dataset.v1.json`, scores both
  lenses, and **fails the build** when an adversarial case triggers an unconfirmed
  export (the zero-tolerance predicate).
- The cost notebook reproduces the per-task cost and p50/p95 figures and shows the
  fan-out-width and model-routing levers moving the total.
- The threat model maps prompt injection, tool misuse, excessive agency, and
  exfiltration each to a named control that exists in the diagram and the prototype.
- A self-assessment against the rubric is present and any conscious scope cuts (e.g.
  multi-tenancy out of the spike) are recorded in ADR-012 rather than hidden.
