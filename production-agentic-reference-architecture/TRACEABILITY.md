# Requirements traceability

Every functional and non-functional requirement, mapped to the ADR that decided it, the
diagram element that shows it, the file that implements it, and the thing that verifies it.
This table is the answer to "is anything bolted on rather than wired in" — a row with an
empty *verified by* column is a claim without evidence.

## Functional requirements

| Req | Requirement | Decided in | Shown in | Implemented in | Verified by |
|---|---|---|---|---|---|
| **FR-1** | Orchestration topology: decomposition, worker specialisation, aggregation, partial-failure path | ADR-002, ADR-011 | `container-view.mmd` (CORE), both sequences | `orchestrator.py::Orchestrator.run`, `_worker` | trace shows `orchestrator.plan` → `orchestrator.fanout` → N `worker.retrieval.*` → `orchestrator.synthesize`; eval C10 (partial failure) |
| **FR-2** | Three memory tiers with write/read/eviction policies + context-budget strategy | ADR-003 | `container-view.mmd` (MEM) | `memory.py`: `WorkingMemory`, `LongTermMemory`, `RetrievedMemory`, `ContextAssembler` | `context.*` span attributes (`evidence_tokens_used`, `evidence_token_cap`, `context_utilisation`, `evidence_items_dropped`) |
| **FR-3** | ≥4 typed tools, ≥1 read and ≥1 write, validation at every boundary | ADR-004, ADR-016 | `container-view.mmd` (TOOLS) | `contracts.py`, `tools.py`: `search`, `fetch`, `summarize` (read), `export_report` (write); `retrieval.py` supplies fixture **or real HTTP** transport | `python3 run.py tools`; `tool.input_rejected` events; eval C6; `TestHttpTransportLive` runs the agent over real HTTP |
| **FR-4** | Eval harness scoring end-state **and** trajectory, gated against a fixed set | ADR-005 | `container-view.mmd` (GOV/GATE) | `eval/harness.py`, `eval/dataset.v1.json` + `.sha256` | `python3 eval/harness.py` → GATE PASS/FAIL; `eval/mutation_test.py` proves it catches 4/4 regressions; `eval/control_tests.py` 22/22 control assertions |
| **FR-5** | End-to-end distributed tracing; spans carry token, latency, cost | ADR-006 | `container-view.mmd` (OBS) | `tracing.py`; every orchestrator/worker/tool/model/guardrail/gate call site | `python3 run.py trace <run_id>`; `trace.jsonl` spans carry `gen_ai.usage.*_tokens`, `gen_ai.request.model`, `cost_usd`, `latency_ms` |
| **FR-6** | Two-sided guardrails (input: injection/scope/PII; output: groundedness/policy/authorisation) + action-confirmation boundary | ADR-007, ADR-009, ADR-016 | `container-view.mmd` (TB1/TB2/TB3) | `guardrails.py`: `screen_input`, `screen_retrieved`, `screen_output`; **`groundedness.py`** as a fourth screen; boundary in `tools.ExportReportTool` + `orchestrator.approve` | eval C6/C8/C9; mutations M1, M4, **M5**; `control_tests.py` C5/C6/C7/C8; `TestGroundedness` |
| **FR-7** | Durable execution surviving restart + HITL checkpoint | ADR-008, ADR-009 | `sequence-failure-hitl.mmd` (C and D) | `checkpoint.py`, `orchestrator.approve/reject`; worker checkpoints carry **source text** so a resumed run can still verify its claims | `--crash-after-workers 1` then `resume` → `stage.resumed`, zero re-fetches; `test_resumed_run_can_still_verify_its_claims` |
| **FR-8** | Governance: ownership, change management for prompts/tools/models, audit logging, rollback | ADR-015 | `container-view.mmd` (GOV) | `governance/GOVERNANCE.md`, `eval-gate.yml`, `change-record-template.md`; `agent/audit.py` (hash-chained) + `agent/identity.py`; `LongTermMemory.audit` | `run.py audit <run_id>` verifies the chain; `verify.py` asserts tampering and truncation are detected; `run.py principals list` is the scope-review artifact |

## Non-functional requirements

| Req | Requirement | Decided in | Where | Verified by |
|---|---|---|---|---|
| **NFR-1** | Latency budget p50/p95 with per-stage breakdown | ADR-013 | `cost-model/REPORT.md` §per-stage, §verdict | model derives p50 9,584 ms / p95 23,546 ms at width 3 against an 11,000/26,000 ms budget; per-stage %p95 column |
| **NFR-2** | Per-task cost target, monthly envelope, dominant drivers, ≥2 reduction levers | ADR-010, ADR-013, ADR-016 | `cost-model/` | **$0.1119/task, 14,303 tasks/month (1.19× headroom)** at the adopted operating point; drivers: synthesis (77%), summarisation (17%); **three** levers — L1 (−33%), L2 (−57%, measured −59.3%), L3 (−16%/−32%); live guard calibrated from observed spend (`CostCalibrator`) |
| **NFR-3** | Defined behaviour under model timeout, tool failure, partial worker failure; **no silent failures** | ADR-011 | `orchestrator.py`, status enum | failure table in ADR-011; every failure emits an ERROR span + typed `error_kind` + event; eval C10 requires the coverage gap to appear in the report |
| **NFR-4** | Threat model covering injection, tool misuse, exfiltration, excessive agency, with mitigations mapped | ADR-004, ADR-007, ADR-009, ADR-013 | `threat-model/` | 4 required threats + full STRIDE sweep, each mapped to a named control in `threat-mitigation-matrix.json` with the implementing file and its test; 5-break attack-chain walkthrough, each break asserted in `control_tests.py` |
| **NFR-5** | An on-call engineer can answer "what is this run doing and why" from traces and logs alone | ADR-006 | `tracing.py::render_tree`, governance §5 runbook | the runbook's questions each resolve to one command (`run.py trace`, `run.py audit`, `run.py principals list`, `run.py serve`) |

## Constraints

| Constraint | How it is met | Evidence |
|---|---|---|
| **Budget** — fixed monthly envelope, defended | $2,000/month with a 20% reserve; per-task ceiling $0.30 enforced live | `cost-model/params.json`; `budget_guard` / `budget.aborted` span events |
| **Latency** — user-facing budget; prototype stays within it for the common case | p50/p95 budget declared; the derived width-3 operating point fits both | `cost-model/REPORT.md` §verdict |
| **Team size** — operable by a small team, simplicity over cleverness | no framework, no infrastructure: plain Python + OTel conventions + one SQLite file; runs on stock `python3` | `RUNNING.md` — one command, zero installs |
| **No vendor lock-in** — swappable model and tool interfaces; hard dependencies justified | `ModelClient` protocol with two implementations; OTLP-compatible attribute names; narrow `CheckpointStore` interface | ADR-010 (no provider lock-in, and the agent-framework dependency explicitly declined); ADR-008 (workflow engine as migration target) |

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| Domain learner-selected, justified, topology warranted | ✅ | ADR-001 with the topology-warranted test applied explicitly; peer domains named as equals |
| ≥10 ADRs with context/options/decision/consequences | ✅ | 16 ADRs; consequences split positive / accepted-cost |
| Diagram covers all 8 FRs + ≥2 sequence views | ✅ | `container-view.mmd` annotates FR-1…FR-8; `sequence-happy-path.mmd` + `sequence-failure-hitl.mmd` |
| 3 memory tiers with explicit policies + context budget | ✅ | ADR-003 policy table; 60/20/20 split in `ContextAssembler` |
| ≥4 typed tools incl. a write, validated everywhere | ✅ | 4 tools, `export_report` is the write; `Tool.invoke` parses before any side effect |
| Eval scores end-state **and** trajectory, runs as a gate | ✅ | 2 lenses, 5 trajectory predicates, thresholds 100%/95%/zero-tolerance |
| Spans carry token, latency, cost end to end | ✅ | `run.py trace` output; JSONL attributes |
| Two-sided guardrails + clear action-confirmation boundary | ✅ | 3 screens + a token bound to run id and report hash |
| Durable execution survives restart; ≥1 HITL checkpoint | ✅ | `--crash-after-workers` + `resume`; export approval gate |
| Cost model: per-task cost, p50/p95, top drivers, ≥2 levers | ✅ | plus a **verdict** section that rejected the assumed fan-out width |
| Threat model maps each agentic threat to a concrete mitigation | ✅ | matrix JSON with implementing file per control; mutation M1 tests the key one |
| Governance covers ownership, change mgmt, audit, rollback | ✅ | `GOVERNANCE.md` §1–4, plus a runbook and known gaps |
| Prototype demonstrates the loop, ≥2 tools, tracing, a guardrail, a HITL checkpoint | ✅ | `run.py demo` covers all four paths in one command; `verify.py` asserts 13 stages including durable resume, auth, audit tampering, groundedness and real HTTP retrieval |
| *(beyond the criteria)* Authenticated approval, review UI, tamper-evident audit | ✅ | ADR-015; closes threat-model R1/R2 and ADR-012 cuts 6/7 |
| *(beyond the criteria)* Test suite | ✅ | 119 unit + integration tests (`tests/test_agent.py`), **five** of them regressions for bugs found by running the code |
| *(beyond the criteria)* Semantic groundedness, real HTTP retrieval, MFA/CSRF/TLS, calibrated budget | ✅ | ADR-016; closes R3, R6, R9, cuts 1/4/10 |

## Stretch goals

| Goal | Status | Where |
|---|---|---|
| Multi-model routing with a cost/quality delta in the harness | ✅ | `ModelRouter`; `harness.py --compare-routing` → −59.3%. Quality axis is flat by construction with the deterministic backend, and the harness says so |
| Adversarial eval set proving the guardrails hold | ✅ | C6, C7, C8, C9 + the compromised-model export probe |
| Replay debugging from traces | ◐ | traces are sufficient and the backend is deterministic, so replay is exact; no dedicated replay command |
| Budget enforcement (abort or downgrade over budget) | ✅ | pre-flight cap + downgrade, post-fan-out abort |
| Chaos drill (tool outage during a durable run, clean recovery) | ✅ | `--fail-url` + `--crash-after-workers` + `resume`, combined in `sequence-failure-hitl.mmd` |
