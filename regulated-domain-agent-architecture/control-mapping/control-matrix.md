# Control-Mapping Matrix — HIPAA obligation → control → requirement → evidence

**How to read this:** one row per obligation from the
[inventory](obligation-inventory.md). A compliance reviewer should be able to go
left-to-right in a single pass and end at an artefact they can inspect. No obligation in
the inventory is unmapped; the completeness check is at the bottom.

Column meanings:
- **Control ID** — stable identifier used across the package (`C-xx`).
- **Class** — **[A]** agnostic spine / **[R]** regime-shaped.
- **Satisfies** — the project requirement (FR-1…FR-5, NFR-1…NFR-4).
- **Evidence** — what an auditor pulls to test it (see [evidence index](evidence-index.md)).

---

## Part A — Privacy Rule

| Obligation | Control ID | Architectural control | Class | Satisfies | Evidence |
|---|---|---|---|---|---|
| O-P1 Permitted use/disclosure | C-01 | Capability model: each capability is bound to a declared purpose; Policy Engine denies purpose-mismatched calls | [R] | FR-1, NFR-2 | Capability registry; `policy.allow/deny` events with purpose code |
| O-P2 **Minimum necessary** | C-02 | **Minimization Filter** — per-capability field allow-list + transforms enforced *before* prompt assembly; emits `minimization_manifest` | [R] parameter on an [A] mechanism | FR-1 | `minimization.applied` events; allow-list config diff history |
| O-P3 Right of access | C-03 | Agent-produced content stored with record refs and exportable via the DSR flow | [R] | FR-2, NFR-3 | DSR runbook; export sample (synthetic) |
| O-P4 Right to amend | C-04 | Amendments link to the original artefact hash; superseded output is marked, never silently rewritten | [R] | FR-2 | Amendment chain for `SYN-MRN-000123` |
| O-P5 Accounting of disclosures | C-05 | Ledger query `disclosures_by_subject(record_ref, window)` over `action.executed` + `output.released` events | [R] | FR-2, NFR-3 | Saved query + sample output |
| O-P6 Restriction requests | C-06 | Per-patient `ai_processing_restricted` flag checked by Policy Engine; restricted patients route to degraded path | [R] | FR-1, FR-5 | Flag schema; `policy.degraded {cause:PATIENT_RESTRICTION}` |
| O-P7 De-identification standard | C-07 | Only Safe-Harbor-conforming transforms may be labelled "de-identified"; ZIP3/age-band transforms documented; expert determination required for anything else | [R] | FR-1 | Transform catalogue in data-handling spec |
| O-P8 BAA + subcontractor flow-down | C-08 | Inference/embedding providers contracted with zero-retention, no-training, region-pinning; provider list is a versioned, audited config | [R] | FR-1, NFR-1 | Subprocessor register; egress endpoint allow-list |

## Part B — Security Rule

| Obligation | Control ID | Architectural control | Class | Satisfies | Evidence |
|---|---|---|---|---|---|
| O-S1 Risk analysis | C-09 | Documented agent-specific threat model incl. injection, exfiltration, cross-tenant retrieval | [A] | NFR-1 | [`architecture/trust-boundaries.md`](../architecture/trust-boundaries.md) |
| O-S2 Access management | C-10 | RBAC + **care-relationship check**; request-scoped tokens (TTL ≤ 5 min) + revocation list; tools declare scopes | [A] mechanism, [R] relationship rule | NFR-2 | Token schema; `policy.deny {reason:NO_CARE_REL}` samples |
| O-S3 Activity review | C-11 | Queryable ledger + scheduled review pack (weekly: denials, refusals, Tier-3 approvals, toggle changes) | [A] | FR-2, NFR-3 | Review pack template |
| O-S4 Incident procedures | C-12 | Kill switch at global/tenant/feature scope with audited toggle and incident reason code | [A] | FR-5 | `toggle.changed` events with `reason:INCIDENT-*` |
| O-S5 Contingency / emergency mode | C-13 | **Degraded mode**: deterministic non-AI path keeps the product functional | [A] | FR-5 | [`toggles/degraded-mode.md`](../toggles/degraded-mode.md) |
| O-S6 **Audit controls** | C-14 | Append-only, **hash-chained** ledger, daily WORM + external notary anchor, synchronous write on consequential events | [A] | FR-2 | Chain verification report |
| O-S7 Integrity of ePHI | C-15 | Agent never writes to the record autonomously; proposals carry content hashes; approved output enters via the EHR's own write path | [A] | FR-2, FR-3 | Tool registry (`writes: none`); `action.executed` records |
| O-S8 Authentication | C-16 | OIDC per-tenant IdP; unique subject IDs; capability tokens verified per hop | [A] | NFR-2 | `authn.success/failure` events |
| O-S9 Transmission/at-rest security | C-17 | TLS 1.3; AES-256 at rest with per-tenant CMK; key policy denies cross-tenant decrypt | [A] mechanism, [R] key-scope rule | FR-1 | Key policy; TLS config |
| O-S10 Unique ID / automatic logoff | C-18 | Session TTL, token TTL, idle timeout; every event carries `actor.id` | [A] | FR-2, NFR-2 | Event schema |
| O-S11 Documentation retention (6 yrs) | C-19 | Audit + control documentation retained ≥ 6 years on WORM; separate clock from record retention | [R] duration on an [A] mechanism | FR-2 | Retention policy config |

## Part C — Breach notification

| Obligation | Control ID | Architectural control | Class | Satisfies | Evidence |
|---|---|---|---|---|---|
| O-B1 BA notification duty | C-20 | Detection hooks (egress anomaly, chain gap, cross-tenant assertion failure) → incident workflow with tenant-notification SLA in the BAA | [R] timing on an [A] detection mechanism | NFR-3 | Incident runbook |
| O-B2 Breach risk assessment | C-21 | **Per-request minimization manifest** answers "exactly which fields were exposed" without re-reading PHI | [R] | FR-1, FR-2 | Manifest sample; scoping query |
| O-B3 Notification content/timeliness | C-22 | Ledger query produces affected record refs; tenant resolves refs→individuals inside their region | [R] | FR-2 | Saved query + region-boundary note |

## Part D — Requirements not driven by a specific HIPAA clause (the agnostic spine)

These exist because responsible agentic design requires them, not because a regulator
names them. They are the rows that will come out **unchanged** in the portability
analysis.

| Control ID | Control | Class | Satisfies | Evidence |
|---|---|---|---|---|
| C-23 | **Risk taxonomy** (Tier 1/2/3) with deterministic classification, ties round up | [A] | FR-3 | [`hitl/risk-taxonomy.md`](../hitl/risk-taxonomy.md) |
| C-24 | **Mandatory HITL above threshold** by a *named owning role*; no eligible approver ⇒ expire closed | [A] | FR-3, NFR-4 | `approval.*` events |
| C-25 | **Grounding-or-refuse**: atomic-claim decomposition + vetted-span entailment ≥ τ; no span ⇒ refuse/escalate; refusals audited | [A] mechanism, [R] source set | FR-4, NFR-4 | [`grounding/hallucination-containment.md`](../grounding/hallucination-containment.md) |
| C-26 | **Prohibited grounding sources**: model's own prior output, open web, other tenants' data | [A] | FR-4 | Retrieval config |
| C-27 | **Toggleable AI** at global/tenant/feature with fail-closed resolution and bounded stale cache | [A] | FR-5 | [`toggles/toggle-spec.md`](../toggles/toggle-spec.md) |
| C-28 | **Toggle audit record** (who/when/scope/old→new/reason) | [A] | FR-5, FR-2 | `toggle.changed` events |
| C-29 | **Accountability model**: every automated decision class has a named owning role | [A] | FR-2 | [`audit/accountability-model.md`](../audit/accountability-model.md) |
| C-30 | **Fail-closed default** across grounding, authorization, approval, flags, ledger | [A] | NFR-4 | Fail-closed test matrix |
| C-31 | **Tenant isolation** (CMK, index partition, flag scope) | [A] | NFR-2 | [`stretch/tenant-isolation-proof.md`](../stretch/tenant-isolation-proof.md) |
| C-32 | **No training on tenant data**; zero-retention inference | [A] intent, [R] contractual form | FR-1 | [ADR-009](../adrs/ADR-009-no-training-on-tenant-data.md) |

---

## Completeness check

| Inventory section | Obligations | Mapped | Unmapped |
|---|---|---|---|
| A. Privacy Rule | O-P1…O-P8 (8) | C-01…C-08 | 0 |
| B. Security Rule | O-S1…O-S11 (11) | C-09…C-19 | 0 |
| C. Breach notification | O-B1…O-B3 (3) | C-20…C-22 | 0 |
| D. Retention | O-R1, O-R2 | C-19 (documentation), C-33 below (records) | 0 |

| Obligation | Control ID | Control | Class | Satisfies |
|---|---|---|---|---|
| O-R2 Medical-record retention (state/tenant) | C-33 | Per-tenant retention clock, hard delete on expiry, audit entries survive by holding **references only** | [R] | FR-1 |

**Reverse check (no orphan controls):** C-01…C-22 each trace to an obligation above.
C-23…C-32 are deliberately obligation-free — they are the agnostic spine, and their
justification is design principle P2/P3 rather than a regulatory clause. Making that
explicit is the point: if a reviewer asks "which of your controls would survive a change
of statute?", the answer is *exactly Part D*.

## Class tally (input to the portability analysis)

| Class | Count | Expectation in portability re-derivation |
|---|---|---|
| [A] pure | 13 | **Unchanged** |
| [A] mechanism with [R] parameter | 6 | **Unchanged mechanism, re-bound parameter** |
| [R] | 14 | **Tightened / relaxed / replaced** |

If the finance re-derivation returns any pure-[A] row as "replaced", or any [R] row as
"unchanged", the classification above was wrong and this matrix is the thing to fix.
