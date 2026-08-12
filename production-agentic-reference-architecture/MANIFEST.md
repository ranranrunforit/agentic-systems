# MANIFEST — where every deliverable lives

`project-301-production-agentic-reference-architecture` · deep-research agent
(domain justified in [ADR-001](adrs/ADR-001-domain-choice.md))

**Verify the whole package with one command:** `python3 verify.py` → 13 stages, ~19s,
stdlib Python only (no `pip install`, no API key, no network).

---

## The seven required deliverables

| # | Deliverable (from the brief) | Where | Status |
|---|---|---|---|
| 1 | **ADR set (≥10)** — one per major decision, each with context / options / decision / consequences | [`adrs/`](adrs/) — 16 ADRs + [index](adrs/README.md) | ✅ 16 |
| 2 | **Reference architecture diagram** — container view + ≥2 sequence views | [`diagrams/`](diagrams/) — [container](diagrams/container-view.mmd), [happy path](diagrams/sequence-happy-path.mmd), [failure/HITL](diagrams/sequence-failure-hitl.mmd) | ✅ 3 |
| 3 | **Eval plan + harness spike** — scores end-state *and* trajectory as a gate | [`eval/EVAL-PLAN.md`](eval/EVAL-PLAN.md), [`harness.py`](eval/harness.py), [`dataset.v1.json`](eval/dataset.v1.json) + lockfile | ✅ gate PASS |
| 4 | **Cost and latency model** — per-task cost, p50/p95, sensitivity, levers | [`cost-model/`](cost-model/) — [model](cost-model/cost_model.py), [params](cost-model/params.json), [generated report](cost-model/REPORT.md), [notebook](cost-model/NOTEBOOK.md) | ✅ |
| 5 | **Threat model** — STRIDE for agents, threat → mitigation mapping | [`threat-model/`](threat-model/) — [doc](threat-model/THREAT-MODEL.md), [machine-readable matrix](threat-model/threat-mitigation-matrix.json) | ✅ 11 threats → 30 controls |
| 6 | **Governance specification** — ownership, change mgmt, audit, rollback, eval-gate-as-release-control | [`governance/`](governance/) — [spec](governance/GOVERNANCE.md), [CI config](governance/eval-gate.yml), [change record template](governance/change-record-template.md) | ✅ |
| 7 | **Orchestration prototype** — runnable spike proving the critical paths | [`prototype/`](prototype/) + [RUNNING.md](prototype/RUNNING.md) | ✅ runs |

Supporting artifacts beyond the brief: [`TRACEABILITY.md`](TRACEABILITY.md) (every FR/NFR →
ADR → diagram → code → test), [`SELF-ASSESSMENT.md`](SELF-ASSESSMENT.md) (scored against the
rubric, weakest points named), [`tests/`](tests/) (119 tests), [`verify.py`](verify.py).

---

## The program — 7,367 lines of Python across 21 modules

### Entry points

| File | Lines | What it does |
|---|---|---|
| [`verify.py`](verify.py) | 427 | one command, thirteen stages; exit 0 or nothing ships |
| [`prototype/run.py`](prototype/run.py) | 413 | CLI: `run` `resume` `approve` `reject` `principals` `audit` `serve` `list` `trace` `tools` `demo` |
| [`prototype/server.py`](prototype/server.py) | 497 | authenticated HITL review UI (localhost) |

### The agent

| File | Lines | Requirement |
|---|---|---|
| [`agent/orchestrator.py`](prototype/agent/orchestrator.py) | 844 | FR-1 orchestrator-workers loop, budget guard, durable resume, HITL gate |
| [`agent/tools.py`](prototype/agent/tools.py) | 288 | FR-3 four typed tools (3 read, 1 gated write) |
| [`agent/contracts.py`](prototype/agent/contracts.py) | 153 | FR-3 input contracts, `MODEL_FORBIDDEN` field stripping |
| [`agent/guardrails.py`](prototype/agent/guardrails.py) | 175 | FR-6 three screens: input · retrieved-content · output |
| [`agent/memory.py`](prototype/agent/memory.py) | 281 | FR-2 three memory tiers + the 60/20/20 context assembler |
| [`agent/models.py`](prototype/agent/models.py) | 333 | swappable model interface, tiered router, offline deterministic backend |
| [`agent/tracing.py`](prototype/agent/tracing.py) | 197 | FR-5 OTel-shaped spans with token/latency/cost attributes |
| [`agent/checkpoint.py`](prototype/agent/checkpoint.py) | 145 | FR-7 SQLite durable execution |
| [`agent/identity.py`](prototype/agent/identity.py) | 313 | FR-8 PBKDF2 credentials, scoped sessions, TOTP, login throttling — closes **R1** and the ADR-015 residuals |
| [`agent/audit.py`](prototype/agent/audit.py) | 142 | FR-8 hash-chained tamper-evident audit log — closes **R2** |
| [`agent/groundedness.py`](prototype/agent/groundedness.py) | 276 | FR-6 semantic groundedness: each claim verified against the source it cites — closes **R3** |
| [`agent/retrieval.py`](prototype/agent/retrieval.py) | 441 | FR-3 fixture + real HTTP transports; robots.txt, HTML extraction, size caps, SSRF defences — closes **cut 1** |
| [`agent/corpus/sources.json`](prototype/agent/corpus/sources.json) | — | 10 fixture sources, one carrying a live injection payload |

### Test and analysis layers

| File | Lines | What it proves |
|---|---|---|
| [`tests/test_agent.py`](tests/test_agent.py) | 1,186 | 119 unit + integration tests; 5 are regressions for bugs found by running the code |
| [`eval/harness.py`](eval/harness.py) | 329 | the release gate — end-state + trajectory, scored from the trace file |
| [`eval/mutation_test.py`](eval/mutation_test.py) | 198 | breaks a control, asserts the gate **fails** — 5/5 caught |
| [`eval/control_tests.py`](eval/control_tests.py) | 193 | 22 boundary-level security assertions |
| [`cost-model/cost_model.py`](cost-model/cost_model.py) | 515 | derives cost, p50/p95, sensitivity, and the feasible operating point |

---

## Acceptance criteria → evidence

| Criterion | Evidence |
|---|---|
| Domain learner-selected and justified; topology warranted | ADR-001 applies an explicit disqualifying test |
| ≥10 ADRs with context/options/decision/consequences | 16 ADRs |
| Diagram covers all 8 FRs + ≥2 sequence views | container view annotates FR-1…FR-8; 2 sequences |
| 3 memory tiers with write/read/eviction + context budget | ADR-003 policy table; `ContextAssembler` 60/20/20 |
| ≥4 typed tools incl. a write, validated at every boundary | `run.py tools`; `Tool.invoke` parses before any side effect |
| Eval scores end-state **and** trajectory, gated | `eval/harness.py` → GATE PASS |
| Spans carry token, latency, cost end to end | `run.py trace <id>` |
| Two-sided guardrails + action-confirmation boundary | 4 screens (input · retrieved · output · groundedness); token bound to run id **and** report hash, minted only by an authenticated principal |
| Durable execution survives restart; ≥1 HITL checkpoint | `--crash-after-workers 1` then `resume`; the export gate |
| Cost model: per-task cost, p50/p95, drivers, ≥2 levers | `cost-model/REPORT.md` — **3 levers**, plus a verdict that rejected the assumed fan-out width and then raised headroom 1.02× → 1.19× |
| Threat model maps each threat to a concrete mitigation | matrix JSON names the implementing file **and** its test per control |
| Governance: ownership, change mgmt, audit, rollback | `governance/GOVERNANCE.md` §1–4 + runbook + known gaps |
| Prototype runs: loop, ≥2 tools, tracing, guardrail, HITL | `run.py demo`; `verify.py` asserts 13 stages |

### Stretch goals

| Goal | Status |
|---|---|
| Multi-model routing with a cost/quality delta | ✅ `harness.py --compare-routing` → −59.3% cost |
| Adversarial eval set proving the guardrails hold | ✅ cases C6–C9 + the compromised-model export probe |
| Replay debugging from traces | ◐ traces sufficient and the backend is deterministic, so replay is exact; no dedicated command |
| *(beyond the brief)* Real HTTP retrieval with SSRF defences | ✅ ADR-016, `agent/retrieval.py` |
| *(beyond the brief)* Semantic groundedness verification | ✅ ADR-016, mutation M5 |
| *(beyond the brief)* TOTP MFA, CSRF, TLS, login throttling | ✅ ADR-016 |
| *(beyond the brief)* Self-calibrating budget projection | ✅ `CostCalibrator` |
| Budget enforcement (abort or downgrade over budget) | ✅ pre-flight cap + downgrade, post-fan-out abort |
| Chaos drill with clean recovery | ✅ `--fail-url` + `--crash-after-workers` + `resume` |

---

## Reading order

1. `python3 verify.py` — confirm the claims are reproducible
2. `cd prototype && python3 run.py demo` — watch the four critical paths
3. [`TRACEABILITY.md`](TRACEABILITY.md) — the requirement-by-requirement map
4. ADRs [001](adrs/ADR-001-domain-choice.md) → [002](adrs/ADR-002-topology.md) →
   [013](adrs/ADR-013-fanout-width-and-budget-enforcement.md) →
   [005](adrs/ADR-005-eval-strategy.md) →
   [015](adrs/ADR-015-authenticated-approval-and-review-ui.md) →
   [012](adrs/ADR-012-scope-cuts.md)
5. [`SELF-ASSESSMENT.md`](SELF-ASSESSMENT.md) — including what is weakest

## Known limitations, up front

The full list is [ADR-012](adrs/ADR-012-scope-cuts.md) (**8 open cuts, 5 closed**) and the
residual-risk register in [the threat model](threat-model/THREAT-MODEL.md) §5. Five risks were
closed since the first draft (R1, R2, R3, R6, R9). The ones that matter most now:

1. **Regex-only PII detection (R5)** — highest open risk; the destination allowlist is what
   holds when detection fails.
2. **No rate limiting on research requests (R4)** — needed before any untrusted user population.
3. **Lexical support is not logical entailment (R10)** — a claim copying a *wrong* source passes.
4. **No search provider for `--retrieval http` (cut 13)** — fetch is real, discovery is not.
5. **Headroom is 1.19×** — better than 1.02×, still not generous.

The spike's absolute cost and latency numbers are **not** production numbers; the offline
deterministic backend exists so the gate is stable and a reviewer needs no API key
([ADR-014](adrs/ADR-014-deterministic-model-backend.md)). Production figures live in
`cost-model/params.json`.
