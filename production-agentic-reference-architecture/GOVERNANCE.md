# Governance specification

**Deliverable 6.** Horizontal governance for the deep-research agent: who owns what, how
changes ship, what is logged, and how to get back to a known-good state. Written for a
**small team with no dedicated SRE function** — every process here must be executable by
one on-call engineer at 2am, which rules out anything needing a committee.

The governing principle: **the things that change agent behaviour are prompts, tools,
models, guardrails and routing — not just code.** Traditional change management covers code
review and misses all five. This spec closes that gap.

---

## 1. Ownership

Every mutable artifact has exactly one named owner. Unowned artifacts are the mechanism by
which agent systems drift.

| Artifact | Owner role | Reviewer | Change class |
|---|---|---|---|
| Orchestration topology (`orchestrator.py`) | Agentic Architect | Eng lead | **Governed** |
| Prompts / task implementations (`models.py`) | Agentic Architect | Eng lead | **Governed** |
| Model identifiers and tier routing (`ModelRouter`, `MODEL_FOR_TIER`) | Agentic Architect | Eng lead + budget owner | **Governed** |
| Tool contracts (`contracts.py`) | Agentic Architect | Security reviewer | **Governed** |
| Tool implementations (`tools.py`) | Agentic Architect | Security reviewer | **Governed** |
| Guardrail patterns and thresholds (`guardrails.py`) | Security reviewer | Agentic Architect | **Governed** |
| **Source allowlist** (long-term memory) | Research lead | Security reviewer | **Governed — data, not code** |
| **Export destination allowlist** | Security reviewer | Eng lead | **Governed — two-person rule** |
| Eval dataset (`dataset.v1.json`) | Agentic Architect | Eng lead | **Governed — requires re-baseline** |
| Eval thresholds (`END_STATE_THRESHOLD`, `TRAJECTORY_THRESHOLD`, `ZERO_TOLERANCE`) | Eng lead | Security reviewer | **Governed — two-person rule** |
| Cost model parameters (`params.json`) | Budget owner | Agentic Architect | Governed |
| Per-task cost ceiling / monthly envelope | Budget owner | Eng lead | Governed |
| Rate card (`RATE_CARD`) | Budget owner | — | Routine (follows provider pricing) |
| Observability config, exporters | Eng lead | — | Routine |
| Corpus fixtures / retrieval transport | Agentic Architect | — | Routine |

Three of these deserve a note on why they are governed at all, since they are the ones
usually treated as configuration:

- **The source allowlist is a security control**, not a preference list. Adding a host
  expands what the agent will ingest, which expands the indirect-injection surface (T1).
- **The destination allowlist is the last line of exfiltration defence** (C8/C17) and is the
  control that holds when PII detection fails. Two-person rule.
- **Eval thresholds are the release gate itself.** Anyone who can lower a threshold can ship
  anything. Two-person rule, and threshold changes are logged in the change record with a
  stated rationale.

**On-call rotation.** One engineer, weekly. Escalation path: on-call → eng lead →
architect. On-call authority is explicitly bounded: they may roll back, revoke an approval
token, disable a source, or pull a cost lever **without** approval; they may **not** widen an
allowlist, lower an eval threshold, or bypass the gate.

---

## 2. Change management

### 2.1 Change classes

| Class | Examples | Requirements |
|---|---|---|
| **Routine** | exporter config, rate-card update, corpus fixtures, docs | code review; gate must pass |
| **Governed** | prompt, tool, model, guardrail, routing, allowlist, dataset, threshold, budget | code review + named reviewer from the table above + **gate pass** + change record |
| **Emergency** | disabling a compromised source, revoking a token, pulling a cost lever | on-call acts immediately; change record and gate run within 24h |

### 2.2 The eval gate is the release control

No governed change ships without:

```bash
python3 eval/harness.py        # exit 0 required — the gate
python3 eval/mutation_test.py  # exit 0 required — proves the gate still has teeth
python3 eval/control_tests.py  # exit 0 required — boundary-level control assertions
```

All three are CI-blocking, and the second matters as much as the first: a change that
weakens a control *and* weakens the gate would otherwise pass. See
[EVAL-PLAN.md](../eval/EVAL-PLAN.md) for thresholds.

Reference CI configuration: [`eval-gate.yml`](eval-gate.yml).

### 2.3 Model changes specifically

A provider-side model swap is indistinguishable from a prompt regression when observed from
outside the system. Therefore:

- Model identifiers are **pinned per tier**, never "latest" or an alias that floats.
- A model change is a governed change: run the gate, run `--compare-routing`, and record the
  cost delta in the change record.
- Old and new pins are both recorded so rollback is a one-line revert.

### 2.4 Dataset changes and re-baselining

The eval set is content-hashed (`dataset.v1.sha256`). The harness refuses to run against a
modified dataset. To change it:

1. state why (new failure mode observed in production, new adversarial case, coverage gap);
2. add cases — **do not edit or delete existing ones**; deletion needs the eng lead and a
   recorded reason, because deleting the case that catches your regression is the easiest
   way to pass a gate;
3. re-baseline with `python3 eval/harness.py --update-lock`;
4. record the old and new hash in the change record.

Scores are comparable only within a hash, and the hash is printed on every run.

### 2.5 Change record

One append-only entry per governed change: date, author, reviewer, class, artifacts touched,
**why**, gate result (with dataset hash), cost delta if routing/model changed, rollback plan.
Template in [`change-record-template.md`](change-record-template.md).

---

## 3. Audit logging

Three distinct logs, with different retention and different reasons for existing.

| Log | Contents | Written by | Retention | Purpose |
|---|---|---|---|---|
| **Action audit** (`audit.jsonl`) | every `export_report`: timestamp, destination, resolved location, report hash, approver, token prefix, trace id | `ExportReportTool` | **7 years** | non-repudiation of external publication |
| **Memory audit** (`LongTermMemory.audit`) | every long-term write: actor, section, key, reason | `LongTermMemory.write` | 2 years | detect allowlist drift and unattributed changes |
| **Run trace** (`trace.jsonl`) | full span tree with tokens, cost, latency, guardrail decisions, HITL events | `Tracer` | **30 days** hot, 1 year cold | incident diagnosis, eval scoring, replay |

Rules:

- **Every privileged action is logged before it is reported as complete.** The audit append
  happens inside the tool, in the same call as the side effect.
- **Every guardrail decision is logged**, including allowed-but-flagged (an
  `indirect_injection_neutralised` event on a run that otherwise succeeded is a security
  signal, not noise).
- **Traces are user data.** They contain question text and evidence summaries, so they
  inherit the access controls and deletion obligations of any user data. Deletion request →
  purge traces and checkpoints by run id; the action audit record is retained (it holds a
  report *hash*, not report content).
- Audit logs are append-only. They are **not currently tamper-evident** — residual risk R2 in
  the threat model, closable by hash-chaining records.

### Retention enforcement

Trace pruning at 30 days and `LongTermMemory.evict_expired()` (90-day TTL on dedupe keys)
are the enforcement points. Both are currently manual; automating them is the first
follow-up in this spec.

---

## 4. Rollback

Rollback is defined per artifact class, because "revert the commit" does not cover four of
the five things that change agent behaviour.

| What broke | Rollback move | Recovery target |
|---|---|---|
| Prompt / task implementation regression | revert to previous pinned version; re-run gate | < 15 min |
| Model regression (provider-side or pin change) | revert the tier pin in `MODEL_FOR_TIER` | < 5 min |
| Guardrail too strict (blocking legitimate work) | revert the pattern change; **do not disable the screen** | < 15 min |
| Guardrail too loose (something got through) | **treat as an incident**, not a rollback: add the case to the eval set first, then fix | fix within 24h |
| Cost overrun | pull lever L1 (cap fan-out) or L2 (downgrade routing) — both are config, no deploy | < 5 min |
| A source is compromised | remove from source allowlist (emergency change) | < 5 min |
| A bad export happened | revoke the token, remove the destination from the allowlist, notify from the audit record | immediate |
| A run is stuck / looping | it is checkpointed — inspect `run.py list`, `run.py trace <id>`, resume or abandon | immediate |

**Pinning is what makes rollback possible.** Prompts, model identifiers, tool contracts and
dataset hashes are all versioned, so "the previous known-good state" is a specific
identifiable thing rather than a memory.

**Revert-and-replay.** Because the trace carries the question, the plan, every fetched URL
and every guardrail decision, a failed run can be reconstructed after a rollback to confirm
the fix actually addresses it. The trace is the reproduction case; with the deterministic
backend (ADR-014) the replay is exact.

**One asymmetry worth stating**: a too-strict guardrail is a rollback, a too-loose guardrail
is an incident. The reflex to "just relax it so work can continue" is how safety controls
erode, so the order is fixed — eval case first, then fix, then ship.

---

## 5. Operating the system

The on-call runbook, kept short enough to be used.

| Question | Answer |
|---|---|
| What is this run doing and why? | `python3 run.py trace <run_id>` — span tree with cost, latency, tokens, sub-questions, guardrail events |
| Which source stalled? | child fetch spans of the fan-out span; look for `ERROR` status and `upstream_unavailable` |
| Why was this report withheld? | `guardrail.output` span → `guardrail.reasons` |
| Why did this cost so much? | sum `cost_usd` by span; synthesis dominates — check `context.evidence_tokens_used` |
| What is waiting on a human? | `python3 run.py list` → status `awaiting_approval` |
| Did anything get exported? | `audit.jsonl` — every export, with approver |
| Is the system within budget? | `python3 cost-model/cost_model.py --calibrate <traces>` |
| Did a guardrail fire without blocking? | grep the trace for `guardrail.flagged` — these are the security signals |

**Alerting** (thresholds to implement, not yet wired): `budget_exceeded` rate > 1% of runs;
any `no_unconfirmed_export` predicate failure in CI; `indirect_injection_neutralised` rate
change > 2× week-over-week; p95 latency > the declared budget for 15 minutes; any run in
`awaiting_approval` for > 48h.

---

## 6. Review cadence

| Review | Frequency | Owner | Output |
|---|---|---|---|
| Eval gate results and dataset coverage | per change | Architect | gate pass + hash in the change record |
| Cost against envelope | weekly | Budget owner | actual vs modelled; lever decision if over |
| Source allowlist | monthly | Research lead | additions/removals with reasons |
| Guardrail flag rates | monthly | Security reviewer | new adversarial eval cases from what fired |
| Threat model | quarterly, or on any new tool | Security reviewer | updated residual risk register |
| ADR set | quarterly | Architect | superseded ADRs marked, not deleted |

**ADRs are never deleted.** A reversed decision gets a new ADR marked as superseding the old
one, and the old one gets a "superseded by" header. The record of *why* something was tried
and abandoned is the most valuable part of the set.

---

## 7. Known governance gaps

Stated here rather than discovered by a reviewer:

1. **The approve command is unauthenticated** in the spike (threat-model R1). Ownership and
   audit are meaningless without identity; this is the first thing to fix before any real
   deployment.
2. **Retention enforcement is manual** — trace pruning and TTL sweeps need a scheduled job.
3. **Audit logs are not tamper-evident** (R2).
4. **No formal incident-review process** beyond "add an eval case". A post-incident write-up
   template belongs here.
5. **Single-tenant assumptions throughout** (ADR-012, cut 5): allowlists, dedupe keys and
   budget ceilings are global.
