# Gap Analysis — what the brief asks for vs. what this package contains

## 1. Required deliverables (all 8 present)

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | Reference architecture + diagrams (container + sequence) | `architecture/` — 4 docs, 9 mermaid diagrams | ✅ |
| 2 | Control-mapping matrix | `control-mapping/control-matrix.md` — 33 controls, completeness + reverse check | ✅ |
| 3 | Data-handling specification | `data-handling/` — 4 docs | ✅ |
| 4 | Risk taxonomy + HITL flows | `hitl/` — 2 docs | ✅ |
| 5 | Grounding + hallucination-containment spec | `grounding/` — 2 docs | ✅ |
| 6 | Toggleable-AI + degraded-mode spec | `toggles/` — 2 docs | ✅ |
| 7 | Portability analysis | `portability/` — 2 docs, 4 sectors | ✅ |
| 8 | ADR set (≥6) | `adrs/` — 10 ADRs | ✅ |

## 2. Stretch goals (all 5 present)

| Goal | Location | Status |
|---|---|---|
| Two secondary sectors | `portability/sector-deltas.md` — public sector + edtech, 4-way table | ✅ |
| Consent and data-subject rights | `stretch/consent-and-data-subject-rights.md` | ✅ |
| Red-team the grounding | `stretch/red-team-grounding.md` (12 attacks) + **executable** in `prototype/tests/` | ✅ |
| Tenant isolation proof | `stretch/tenant-isolation-proof.md` (10 tests) + **executable** in `prototype/tests/` | ✅ |
| Auditor walkthrough | `stretch/auditor-walkthrough.md` (9 steps) + **executable** `prototype/auditor_cli.py` | ✅ |

## 3. The gap I closed: nothing was executable

**The brief does not ask for code.** Every deliverable is a document, and the effort
breakdown (20 h across 6 phases) is entirely design work. A documents-only submission meets
the letter of the requirement.

But three acceptance criteria and four verification points are phrased as *demonstrations*:

| Source | Wording |
|---|---|
| Acceptance criteria | "The system **fails closed** when grounding, authorization, or required approval is unavailable" |
| Verification | "A high-risk output with no vetted-source citation is **refused**, and the refusal is itself audited (fail-closed **demonstrated**)" |
| Verification | "**Flipping** the AI toggle off at global, tenant, and feature scope **each leaves** the product in the defined degraded mode... an unreachable flag service **results in** AI off" |
| Verification | "The audit log **is** append-only and tamper-evident (e.g. hash-chained), **is queryable**..." |
| Stretch | "**Attempt** to elicit a confident ungrounded high-risk claim and **show** the containment holds" |
| Stretch | "**Demonstrate** that one tenant's data and toggles cannot leak into another's" |

A document can *assert* that unknown flag state means AI off. Only a program can be *run*
to check it. So the package now includes a working reference implementation of the control
plane, and the demonstrations above are executed rather than described.

## 4. What the prototype is and is not

| Real (implemented and tested) | Stubbed (deliberately) |
|---|---|
| Hash-chained append-only audit ledger with verification and anchoring | Distributed storage, WORM, external notary |
| Fail-closed flag resolution with bounded stale cache | Network flag service |
| Policy engine: RBAC, care relationship, restriction flags, allow-lists | Real IdP / OIDC |
| Minimization filter: projection, transforms, manifest emission | Real EHR schema |
| Vetted corpus with validity windows and claim-type→source-class matrix | Real clinical references (licensed) |
| Grounding verifier: claim decomposition, retrieval, entailment scoring, **4 deterministic vetoes** | **The LLM itself** — replaced by a scriptable stub |
| Risk classifier: 4 axes, max-rule, round-up | — |
| HITL queue with rosters, SLA expiry, expire-closed | Approval UI |
| Degraded mode per capability | Product UI |
| Auditor saved queries | Query engine at scale |

**The model is stubbed on purpose.** The claim this architecture makes is *"the controls
hold regardless of what the model emits"* — so the prototype lets a test **inject arbitrary
model output, including deliberately fabricated clinical claims**, and asserts the controls
still contain it. A real LLM would make the demo prettier and the proof weaker, because
you could never be sure the containment held or the model just happened to behave.

## 5. Follow-up items — all closed

| Item | Status |
|---|---|
| Deterministic veto set expanded 4 → 9 | ✅ |
| Output-conformance verifier (OQ-7) | ✅ built; empty for healthcare, 2 rules for finance |
| Full obligation inventory for a second sector | ✅ 33 finance obligations |
| Misleading-by-omission instrumented (OQ-4) | ✅ advisory, with its limit asserted |
| Cache-key CI audit | ✅ |
| Prototype extended to the finance re-derivation | ✅ 6 sector leaks found |

## 6. Remaining honest gaps

| Gap | Why it stays open |
|---|---|
| Misleading-by-omission **in the general case** | Instrumented for named expectations only; the general problem is unsolved, and under UDAAP it matters more than under HIPAA |
| A third bound regime (public sector, edtech) | Sketched as documents. Binding regime #2 exposed six leaks, so these are hypotheses |
| Independent model validation (F-M2) | An organisational function; no architecture supplies it |
| Real cryptographic anchoring to an external notary | Simulated in-process |
| Entailment scorer quality | Token overlap; the control logic around it is what is demonstrated |
| Performance/scale characteristics | Out of scope for a reference architecture |
