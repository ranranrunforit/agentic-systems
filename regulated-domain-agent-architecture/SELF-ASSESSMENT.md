# Self-Assessment

## 1. Acceptance criteria

| # | Criterion | Where | Met |
|---|---|---|---|
| 1 | Exactly one primary sector chosen from the menu and justified in an ADR | [ADR-001](adrs/ADR-001-sector-choice.md) — healthcare, with a stated argument *for* each sector not chosen | ✅ |
| 2 | Sensitive data classified, with residency, minimization, retention/deletion | [data-classification](data-handling/data-classification.md), [minimization-and-residency](data-handling/minimization-and-residency.md), [retention-and-deletion](data-handling/retention-and-deletion.md) | ✅ |
| 3 | Control-mapping matrix traces each sector obligation to a concrete control | [control-matrix](control-mapping/control-matrix.md), 33 controls, completeness check + reverse check | ✅ |
| 4 | Audit trail tamper-evident, queryable, who/what/when/why | [audit-log-spec](audit/audit-log-spec.md) — hash chain, WORM + notary anchors, `inputs` block, 8 saved queries | ✅ |
| 5 | Accountability explicit: named owning human/role per automated decision | [accountability-model](audit/accountability-model.md) — 12 decision classes, deploy-time enforcement | ✅ |
| 6 | Risk taxonomy defines high-risk output and a HITL threshold | [risk-taxonomy](hitl/risk-taxonomy.md) — 4 axes, max-rule, Tier-3 threshold justified on irreversibility and harm | ✅ |
| 7 | Hallucination containment grounds high-risk output; refuses/escalates on failure | [hallucination-containment](grounding/hallucination-containment.md), [vetted-sources](grounding/vetted-sources.md) | ✅ |
| 8 | AI toggleable global/tenant/feature + degraded mode + toggle audit | [toggle-spec](toggles/toggle-spec.md), [degraded-mode](toggles/degraded-mode.md) — 4 scopes (adds subject) | ✅ |
| 9 | Fails closed when grounding, authorization, or approval unavailable | 10-case [fail-closed matrix](control-mapping/evidence-index.md#fail-closed-test-matrix-the-drill-list) | ✅ |
| 10 | Portability re-derives all five control areas for a second sector, classified | [portability-analysis](portability/portability-analysis.md) — finance, 16 rows classified | ✅ |
| 11 | Explicit regime-agnostic vs. regime-specific split | [portability §8](portability/portability-analysis.md#8-the-explicit-split) — 9 agnostic, 8 regime-specific | ✅ |
| 12 | No sector privileged; rationale holds on its own terms | [ADR-001](adrs/ADR-001-sector-choice.md) + all four sectors re-derived ([sector-deltas](portability/sector-deltas.md)) | ✅ |
| — | Synthetic data only | [synthetic-records](data-handling/synthetic-records.md); `SYN-` prefixes; `.invalid` domains; tokenised card refs only | ✅ |

## 2. Rubric self-assessment

### Regulatory translation — 25%
The [obligation inventory](control-mapping/obligation-inventory.md) works from the regime
outward (22 obligations across Privacy, Security, Breach, Retention) rather than
retrofitting citations to a design. Each maps to a concrete component, and the matrix
carries both a completeness check and a **reverse check** identifying the 10 controls with
no regulatory driver — which is what makes the agnostic/specific split falsifiable rather
than asserted. Adjacent regimes (42 CFR Part 2, FDA CDS) are scoped out explicitly with an
enforced conservative default rather than ignored.
**Self-score: strong.** Weakness: the inventory is structured around clause groupings; a
reviewer working from a specific compliance framework crosswalk (e.g. HITRUST) would need
to map across.

### Data handling and residency — 15%
Four classes with a default-to-strictest rule, a versioned transform catalogue, and the
`minimization_manifest` as the load-bearing artefact. The design states plainly what it
does *not* claim (free-text redaction is not de-identification; embeddings are D2, not
derived-and-safe). Residency is enforced at three layers and is explicitly tagged
[REGIME] with the two-directional finance result to back the tagging.
**Self-score: strong.**

### Auditability and accountability — 15%
Hash-chained, reference-only, synchronously written on consequential events, externally
anchored, with the `inputs` block that makes reconstruction possible. The spec states the
limit of tamper evidence (it proves nothing about events never written) and closes that gap
separately. Accountability covers auto-flowed output and vendor-side decisions, resolves to
rosters, and is enforced at deploy time.
**Self-score: strong.**

### HITL and risk taxonomy — 15%
Four axes, max-rule (with the reason sum-rules were rejected), round-up on ambiguity,
learned components able to raise but never lower a tier, expire-closed with no path to
release. The threshold is argued on irreversibility and harm with the alternatives
enumerated and rejected on their merits. Anti-rubber-stamp instrumentation is included
because a mandatory gate that is reflexively approved manufactures a false record of review.
**Self-score: strong.** Weakness: approval-fatigue mitigation is governance-shaped and its
effectiveness is asserted rather than demonstrated (OQ-5).

### Hallucination containment — 15%
Claim decomposition → typing → compatibility-constrained retrieval → separate-verifier
entailment → deterministic vetoes → tier-dependent policy. The claim-type→source-class
matrix and the circularity guard are the two mechanisms that address specifically *agentic*
failure rather than generic RAG. The [red-team](stretch/red-team-grounding.md) found that
the deterministic veto, not the learned verifier, caught the most dangerous case — and that
finding is reported rather than smoothed over.
**Self-score: strong.** Honest residual: misleading-by-omission is structurally outside
claim-level grounding (OQ-4).

### Portability analysis — 15%
Finance re-derived across all five FRs with per-control classification; public sector and
edtech re-derived at lower depth; a four-way comparison table. The analysis makes a
falsifiable prediction from the control matrix's class tags, checks it, and reports the
one place the prediction was incomplete (finance requires a *new* control — disclosure
completeness — that the healthcare design does not have). Three findings are recorded as
open questions rather than quietly back-ported.
**Self-score: strong.** Weakness: the public-sector and edtech derivations are sketches
by design; a full obligation inventory for either would surface more.

## 2b. Beyond the brief: executable verification

The brief asks for documents only. Several verification points are nonetheless phrased as
demonstrations, so the package includes a dependency-free reference implementation of the
control plane ([`prototype/`](prototype/README.md)) in which those demonstrations are
executed rather than asserted:

| Claim in the docs | Executed by | Result |
|---|---|---|
| Fails closed on grounding, authz, approver, flags, ledger | `tests/test_failclosed.py` | 15 tests |
| No confident ungrounded high-risk claim can be released | `tests/test_grounding_redteam.py` | 17 tests, 12 attacks |
| One tenant's data and toggles cannot reach another | `tests/test_isolation.py` | 11 tests |
| Toggles work at every scope; chain is tamper-evident | `tests/test_toggles_and_audit.py` | 18 tests |
| An auditor can reconstruct a decision from one correlation ID | `auditor_cli.py` | 16/16 checks |
| **The spine is sector-neutral; every portability row holds** | `tests/test_portability.py` | 30 tests |
| Cache safety, all 9 vetoes intact, fail-closed defaults, regime completeness | `tests/test_ci_guards.py` | 26 tests |

**Total: 117 tests, 0 failures.** Writing it caught two defects in the harness and, when the finance regime was bound,
**six sector assumptions embedded in supposedly sector-neutral code** — including a
stopword list that silently biased grounding in healthcare's favour. All are documented in
[portability-by-construction](portability/portability-by-construction.md) rather than
quietly fixed, since a design exercise that produces no surprises probably was not
exercised.

## 3. Open compliance questions

Per [ADR-010](adrs/ADR-010-open-compliance-questions.md), each carries a conservative
interim posture enforced in code.

| ID | Question | Interim posture | Who closes it |
|---|---|---|---|
| OQ-1 | Precise BAA boundary and flow-down for the inference provider as a subcontractor BA | Strictest terms assumed (zero retention, no training, region-pinned) | Counsel + tenant Privacy Officer |
| OQ-2 | Could 42 CFR Part 2 data reach the agent through an integrated source? | Blocked by tenant-level data-source allow-list | Tenant compliance |
| OQ-3 | Does any capability constitute a regulated device function? | Diagnostic/dosing output prohibited at capability level | Regulatory counsel |
| OQ-4 | Does claim-level grounding adequately address misleading-by-omission? | Sampled review + manifest visibility; treated as unresolved | Clinical Safety Officer |
| OQ-5 | Is anti-rubber-stamp instrumentation acceptable workforce monitoring? | Aggregate-only, no automated punitive action, tenant consent at onboarding | Tenant HR/legal |
| OQ-6 | Should "explainable to the affected individual" be a spine control? (Reached independently from FCRA *and* public-sector due process) | Structured `why.reason_code` captured; no consumer-facing surface in v1 | Architecture review |
| OQ-7 | Should the spine include a positive output-conformance verifier? (Finance disclosures, public-sector accessibility, edtech age-appropriateness) | Slot identified, empty for healthcare v1 | Architecture review |
| OQ-8 | Should `audience` be a fifth risk axis? | Not implemented; all v1 consumers are clinicians or the patient | Clinical Safety Officer |
| OQ-9 | Attribution gap for tenants without proposal-and-approval EHR integration | Export-and-paste documented as a known gap; flagged at onboarding | Product + tenant |
| OQ-10 | Is a 60-second bounded stale window on flags defensible to a regulator after an incident? | 60 s with a separate minimal-dependency kill channel | Security Officer |

## 4. Follow-up work — status

All six items previously listed as "next" are now done.

| # | Item | Done | Where |
|---|------|------|-------|
| 1 | Expand the deterministic veto set | ✅ 4 → **9** vetoes (unit, comparator, quantifier, modality, negation parity added); each asserted individually so a refactor cannot silently drop one | [`grounding.py`](prototype/cara/grounding.py), `test_ci_guards.py` |
| 2 | Build the output-conformance verifier slot (OQ-7) | ✅ Blocking positive check; **empty for healthcare**, 2 rules for finance | [`conformance.py`](prototype/cara/conformance.py) |
| 3 | Full obligation inventory for a second sector | ✅ 33 finance obligations, incl. 5 families with no healthcare counterpart | [finance-obligation-inventory](portability/finance-obligation-inventory.md) |
| 4 | Instrument misleading-by-omission (OQ-4) | ✅ Advisory flags to the reviewer — and a test asserting the detector's limit, so the residual is not mistaken for a solution | `OmissionDetector` |
| 5 | Cache-key audit in CI | ✅ 5 guards on the tenant/model/corpus key components, plus the naive-key bug written down | `test_ci_guards.py` |
| 6 | **Extend the prototype to the finance re-derivation** | ✅ Both regimes on one spine; 30 tests; **6 sector leaks found** | [portability-by-construction](portability/portability-by-construction.md) |

### What the finance port changed about the conclusion

The document version of the portability analysis said *the spine did not change; the
parameters did*. That was too generous to the original design. The accurate version:

> The spine did not change **once it was made genuinely sector-neutral**, which it was
> not when the analysis was written. Portability is not a property a single-sector
> implementation has and then demonstrates; it is a property the second implementation
> creates, by forcing the first one's assumptions into the open.

### Now genuinely open

1. **A third regime.** Public-sector and edtech remain documents. Given that binding the
   second regime exposed six leaks, those deltas should be read as hypotheses.
2. **Misleading-by-omission in the general case** (OQ-4) — instrumented, unsolved. Under
   finance's UDAAP framing the stakes are higher than under HIPAA, and the design does
   not solve it in either.
3. **Independent model validation** (F-M2) — an organisational function no architecture
   supplies.
4. **The entailment scorer** is token overlap. The control logic around it is what the
   prototype demonstrates; calibration is not.
