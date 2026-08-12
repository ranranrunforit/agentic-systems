# Production Agentic Reference Architecture — deep-research agent

**Capstone: End-to-End Agentic Reference Architecture** ·
`project-301-production-agentic-reference-architecture`

An architecture package for a production-grade agentic system: a **deep-research agent**
that decomposes a question, fans out retrieval in parallel, and synthesises a cited report,
with one privileged action (publishing the report) behind a human-approval boundary.

The domain is learner-selected and justified in
[ADR-001](adrs/ADR-001-domain-choice.md). Peer domains — a data-operations triage agent, a
customer-facing KB assistant with bounded actions, an internal-operations agent — are equally
valid and would earn the same topology on their own terms; where an artifact here would
change for a peer, the change is noted inline.

---

## Run it first

Everything is stdlib Python — no `pip install`, no API key, no network egress.

```bash
python3 verify.py                       # 13 stages: tests, gate, durability, auth, audit, groundedness, HTTP, cost
cd prototype && python3 run.py demo     # the four critical paths, narrated
cd prototype && python3 run.py serve    # the HITL review UI on localhost:8765
```

`verify.py` is the fastest way to check that every claim below is reproducible:

```
 ✓ modules compile                          0.1s
 ✓ unit + integration tests                 6.3s     119 tests
 ✓ boundary control assertions              0.1s     22 assertions
 ✓ release gate (end-state + trajectory)    6.4s     end-state 100%, trajectory 100% of 37
 ✓ gate integrity (mutation test)           0.2s     5/5 broken controls caught
 ✓ durable crash + resume                   0.8s     resumed without re-fetching
 ✓ audit chain tamper detection             0.0s     modification + truncation detected
 ✓ review server auth + CSRF                0.3s     refuses unauthenticated + tokenless POSTs
 ✓ semantic groundedness (R3)               0.0s     fabrication, misattribution, drift caught
 ✓ real HTTP retrieval + SSRF defences      0.6s     robots, size caps, metadata endpoint refused
 ✓ MFA + login throttling                   0.5s     TOTP enforced, lockout applies to correct pw
 ✓ cost + latency model                     0.1s     derives width 3 + evidence cap 2
 ✓ scripted demo                            3.4s     6/6 assertions visible
```

## Then read

Start with [MANIFEST.md](MANIFEST.md) if you are grading this — it maps all seven
deliverables and every acceptance criterion to the file that satisfies it.

| If you have | Read |
|---|---|
| **10 minutes** | [TRACEABILITY.md](TRACEABILITY.md) — every requirement mapped to design, code and test |
| **30 minutes** | ADRs [001](adrs/ADR-001-domain-choice.md) → [002](adrs/ADR-002-topology.md) → [013](adrs/ADR-013-fanout-width-and-budget-enforcement.md) → [005](adrs/ADR-005-eval-strategy.md) → [015](adrs/ADR-015-authenticated-approval-and-review-ui.md) → [016](adrs/ADR-016-closing-the-four-residual-risks.md) → [012](adrs/ADR-012-scope-cuts.md) |
| **an afternoon** | the [threat model](threat-model/THREAT-MODEL.md), then read `prototype/agent/` top to bottom |

---

## The package

**7,367 lines of Python across 21 modules**, plus the architecture artifacts.

```
prototype/
├── run.py                 CLI: run · resume · approve · reject · principals · audit · serve · trace · tools · demo
├── server.py              HITL review UI — authenticated, shows coverage gaps + guardrail events
└── agent/
    ├── orchestrator.py    orchestrator-workers loop, budget guard, durable resume, HITL gate
    ├── tools.py           4 typed tools (3 read, 1 gated write)
    ├── contracts.py       input contracts; MODEL_FORBIDDEN field stripping
    ├── guardrails.py      3 screens: input · retrieved-content · output
    ├── memory.py          3 memory tiers + the 60/20/20 context assembler
    ├── models.py          swappable model interface, tiered router, offline deterministic backend
    ├── tracing.py         OTel-shaped spans with token/latency/cost attributes
    ├── checkpoint.py      SQLite durable execution
    ├── identity.py        PBKDF2 credentials, scoped sessions  (closes R1)
    ├── audit.py           hash-chained tamper-evident audit log  (closes R2)
    └── corpus/            fixture sources, one carrying a live injection payload

tests/test_agent.py        119 unit + integration tests
eval/                      harness (release gate) · mutation_test · control_tests · dataset + lockfile
cost-model/                params · model · generated report · notebook walkthrough
verify.py                  one command, ten stages, exit 0 or nothing shipped

adrs/                      16 ADRs — context / options / decision / consequences
diagrams/                  container view + happy-path and failure/HITL sequences
threat-model/              STRIDE-for-agents + machine-readable mitigation matrix
governance/                ownership, change management, audit, rollback, CI config
TRACEABILITY.md            FR/NFR → ADR → diagram → code → test
SELF-ASSESSMENT.md         scored against the rubric, with what is weakest
```

---

## The four decisions that drive everything else

**1. The domain has to earn the topology.** A deep-research agent needs decomposition,
*bounded parallel* retrieval, and *per-source provenance* for every claim. A single
prompt-and-response can do none of the last two: it has no per-source span, no way to bound
concurrency, and nowhere to attach provenance. That is the test ADR-001 applies — and it is
the test that disqualifies a domain a single call would serve.

**2. Score paths, not just answers.** The failure this domain produces is a fluent,
confidently *uncited* report — it passes a human skim and any end-state-only metric. So the
eval scores the **trajectory** (did retrieval precede synthesis, did every claim carry a
citation, did fan-out stay in budget, did any export escape confirmation) alongside the
**end-state**. And because a gate that has never failed is unproven,
`eval/mutation_test.py` breaks one control at a time and asserts the gate **fails**: 4/4
mutations currently caught.

**3. Two-sided guardrails, three screens, one confirmation boundary.** This agent's job is
ingesting untrusted third-party text, so **indirect** injection is the expected case, not an
edge case — which is why tool output gets its own screen between fetch and model context.
Pattern matching is a volume reducer; the control that actually holds is architectural. The
one irreversible, externally-visible action (`export_report`) requires a token minted only by
the human approval gate and bound to the report's hash. There is no string a model can emit
that constitutes authorisation.

**4. Cost and latency are budgets that can say no.** The design assumed a fan-out width of 4.
The cost model, once actually built, showed width 4 breaches both the p95 latency budget
(+100 ms) and the monthly envelope (0.86× headroom). Width **3** is the widest that fits, so
that is the committed default in `RunConfig.max_fanout` — derived, not guessed
([ADR-013](adrs/ADR-013-fanout-width-and-budget-enforcement.md)).

---

## Architecture at a glance

Full container view with FR annotations: [`diagrams/container-view.mmd`](diagrams/container-view.mmd).

```
question
   │
   ▼  [TB1] input guardrail — injection / scope / PII      (blocked ⇒ zero model spend)
   ▼      orchestrator: PLANNER          (small model)     → checkpoint: plan
   ▼      budget guard                                      → cap width / downgrade routing
   ▼      FAN-OUT, width ≤ 3            ┌─ worker 1 ─┐
   │                                    ├─ worker 2 ─┤  search → fetch → [TB2] screen → summarize
   │                                    └─ worker 3 ─┘  → checkpoint: worker:N (each)
   ▼      aggregate — failed sub-questions carried forward, never dropped
   ▼      context assembler — 60% evidence / 20% plan / 20% headroom
   │                           (extractive summaries only; raw docs never reach synthesis)
   ▼      orchestrator: SYNTHESIZER      (large model)     → checkpoint: synthesis
   ▼      output guardrail — every claim cited? PII? instruction leak?
   │
   ├──► report returned (READ path, no confirmation)
   └──► export requested ⇒ [TB3] durable pause → human approval → token bound to report hash
                          → export_report (WRITE) → audit log

  every step ──► OTel span: gen_ai.usage.*_tokens · gen_ai.request.model · cost_usd · latency_ms
```

### The three memory tiers ([ADR-003](adrs/ADR-003-memory-tiers.md))

| Tier | Write | Read | Eviction |
|---|---|---|---|
| **Working** — plan, findings, stage status | every stage appends, run-scoped | synthesizer, operator | dropped at run end |
| **Long-term** — source + destination allowlists, prefs, dedupe keys | **explicit, attributed, audited only — never from model output** | planner, assembler, allowlist checks | TTL sweep + manual curation |
| **Retrieved** — documents, extractive summaries, citations | workers, per fetch (deduped per URL) | context assembler only | per run; top-k only |

### The four typed tools ([ADR-004](adrs/ADR-004-tool-boundary.md))

`search` (read) · `fetch` (read, https + allowlist) · `summarize` (read, model-backed) ·
**`export_report` (write)**. Every payload is parsed against its contract before any side
effect; unknown fields are rejected; and `confirmed_by` is *structurally stripped* from
model-authored payloads.

---

## Headline numbers

| | Value | Source |
|---|---|---|
| Per-task cost (width 3, evidence cap 2) | **$0.1119** | [cost-model/REPORT.md](cost-model/REPORT.md) |
| Latency p50 / p95 | **9,584 / 23,546 ms** (budget 11,000 / 26,000) | same |
| Monthly envelope / capacity | **$2,000** → 14,303 tasks vs 12,000 target (**1.19×**) | same |
| Dominant cost drivers | synthesis **77%**, summarisation **17%** | same |
| Lever L1 (cap fan-out + dedupe) | **−33%** cost, −21% p95 | same |
| Lever L2 (route synthesis small) | **−57%** modelled, **−59.3%** measured in the harness | [eval](eval/EVAL-PLAN.md) |
| Lever L3 (evidence cap per sub-question) | **−16%** at 2, **−32%** at 1 — the cheapest in quality terms | [cost-model/REPORT.md](cost-model/REPORT.md) |
| Eval gate | end-state 100%, trajectory 100% of 37 predicates — **PASS** | `eval/harness.py` |
| Gate integrity | **5/5** mutations caught | `eval/mutation_test.py` |
| Boundary control assertions | **22/22** hold | `eval/control_tests.py` |
| Unit + integration tests | **119** passing | `tests/test_agent.py` |
| Threats mapped to implemented controls | **11 threats → 30 controls** | [matrix](threat-model/threat-mitigation-matrix.json) |

---

## What this package deliberately does not claim

Stated up front rather than left for a reviewer to find; the full list with closing moves is
[ADR-012](adrs/ADR-012-scope-cuts.md) and the residual-risk register in the
[threat model](threat-model/THREAT-MODEL.md) §5.

- **The reports are traceable, not true.** Every claim is now verified against the text of the
  source it cites (ADR-016), but support is **lexical, not logical**: a claim faithfully copying
  a *wrong* source passes, and a correct paraphrase in unusual vocabulary can be flagged.
- **Regex-only PII detection (R5) is the highest open risk**, and **there is no rate limiting on
  research requests** (R4).
- **The spike's cost and latency numbers are not production numbers.** The default model
  backend is offline and deterministic so the gate is stable and a reviewer needs no key
  ([ADR-014](adrs/ADR-014-deterministic-model-backend.md)). Only the model's *shape* is
  validated by the spike; the production figures come from `cost-model/params.json`.
- **Identity is a local credential store, not SSO.** TOTP, throttling, CSRF and optional TLS
  are in place (ADR-016), but MFA is opt-in per principal and there is no directory integration.
- **Fetch is real; search is not.** `--retrieval http` needs a commercial search provider —
  `HttpTransport.search` raises rather than pretending (cut 13).
- **Audit records are not shipped off-host.** The hash chain detects local tampering; full
  non-repudiation needs append-only external storage.
- **Injection detection is not claimed to work.** Paraphrase defeats regexes. What is claimed
  and tested is that the *consequences* of successful injection are bounded by structural
  controls.
- **Single-tenant throughout**, and no rate limiting (R4).

---

## Verify the claims yourself

```bash
cd prototype
python3 run.py demo                                  # four critical paths
python3 run.py run "<q>" --max-fanout 3 --crash-after-workers 1
python3 run.py resume <run_id>                       # durable: no re-fetch of completed work
python3 run.py trace <run_id>                        # spans with token / latency / cost
python3 run.py run "<q>" --retrieval http --search-endpoint <url>   # real web retrieval
python3 run.py tools                                 # typed tool registry

cd ..
python3 eval/harness.py                              # the release gate
python3 eval/harness.py --compare-routing            # cost lever, measured
python3 eval/mutation_test.py                        # does the gate catch broken controls?
python3 eval/control_tests.py                        # boundary-level control assertions
python3 cost-model/cost_model.py                     # per-task cost, p50/p95, verdict
python3 cost-model/cost_model.py --calibrate prototype/runs/*/trace.jsonl
```
