# Reference Architecture — CARA (Clinical Assistance & Records Agent)

Primary sector: **healthcare / HIPAA**. Every control below carries an **[AGNOSTIC]** or
**[REGIME]** tag; see the [README](../README.md) for what the tags commit us to.

---

## 1. Design principles

| # | Principle | Consequence in the architecture |
|---|-----------|--------------------------------|
| P1 | **Controls are architectural, not procedural.** | Minimum-necessary is a filter in the request path, not a line in a policy PDF. A reviewer can point at the component that enforces it. |
| P2 | **The model is untrusted.** | Nothing the model emits is consequential until it passes grounding, risk classification, and (above threshold) a human. "The model is usually right" is not a control. |
| P3 | **Fail closed.** [AGNOSTIC] | Missing grounding, missing authorization, missing approver, unknown flag state, unreachable audit sink ⇒ refuse. Never proceed open. |
| P4 | **Sensitive data crosses the fewest boundaries possible.** | The model boundary is treated like a network egress: everything crossing it is classified, minimized, and logged. |
| P5 | **Every consequential event is reconstructable.** [AGNOSTIC] | The audit record carries the *inputs that produced the decision* (by reference + hash), not just the outcome. |
| P6 | **The spine is parameterised, not rewritten.** | Sector-specific facts (vetted source set, risk trigger, residency region, retention clock) are configuration bound at the tenant level — which is exactly what makes the portability analysis short. |

## 2. Trust zones

```
Zone 0  Untrusted        End-user browsers/devices, external networks
Zone 1  Edge             API gateway, authn/authz, tenant resolution, rate limiting
Zone 2  Control plane    Flag Service, Policy Engine, Risk Classifier, Audit Ledger
Zone 3  Regulated data   Record Store (PHI), Vetted Corpus Store, Object Store
Zone 4  Model boundary   Region-pinned inference endpoints (no persistence, no training)
Zone 5  Human review     Approval Console used by named clinical roles
```

Rules across zones:

- **Z3 → Z4 is the model boundary.** The *only* path is through the Minimization Filter
  (§3.4). Direct calls from Agent Runtime to inference bypassing the filter are blocked
  by egress policy, and the absence of such a path is an audited configuration assertion.
- **Z4 has no persistence.** Inference endpoints are contracted for zero retention, zero
  training, region-pinned. [REGIME — residency] + [AGNOSTIC — data minimization]
- **Z2 can read Z3 metadata but never Z3 payloads.** The Audit Ledger stores record
  *references* and content *hashes*, never PHI ([ADR-006](../adrs/ADR-006-audit-log-design.md)).
- **Z5 sees the full proposed output plus its citations**, because approving a clinical
  assertion without seeing its evidence is not approval.

## 3. Components

### 3.1 Edge & Identity (Zone 1)
Terminates TLS 1.3, authenticates the caller (OIDC, per-tenant IdP), resolves tenant,
and issues a **request-scoped capability token** naming: tenant, subject (staff member),
role, patient-in-context (if any), capability requested, and TTL ≤ 5 min. Least privilege
is expressed in the token; every downstream component re-checks it. [AGNOSTIC]

### 3.2 Policy Engine (Zone 2)
Answers three questions before any work happens:
1. *Is this actor permitted this capability for this tenant?* (RBAC + relationship check:
   is this clinician in a care relationship with this patient? — HIPAA minimum-necessary,
   [REGIME — access model]).
2. *Is the AI feature enabled at global/tenant/feature scope?* (delegates to Flag Service).
3. *Which data classes may cross the model boundary for this capability?* (returns the
   **field allow-list** consumed by the Minimization Filter).

Denials are audited with a reason code. Unreachable Policy Engine ⇒ deny.

### 3.3 Flag Service (Zone 2)
Resolves the effective AI-enablement state. Fail-closed with a bounded stale-cache
window. Full semantics: [`toggles/toggle-spec.md`](../toggles/toggle-spec.md). [AGNOSTIC]

### 3.4 Minimization Filter (Zone 2 → Zone 4 gate)
The load-bearing data control. Given (capability, allow-list, patient-in-context) it
assembles the prompt from **only** allow-listed fields, applies transforms
(DOB → age band, ZIP → ZIP3, free-text → redaction pass for direct identifiers), and
emits a `minimization_manifest`: the exact field paths included, transforms applied, and
a hash of the assembled prompt. The manifest goes to the Audit Ledger; the prompt goes to
inference. Fields not on the allow-list are *unreachable* — the filter operates on a
projection, so a prompt-injection attempt cannot cause un-projected data to be included.
[AGNOSTIC — minimization] with a [REGIME] parameter (the allow-list is derived from
HIPAA minimum-necessary; under PCI it would be derived from cardholder-data isolation).

### 3.5 Agent Runtime (Zone 2/3)
Plans and executes with a small, explicitly registered tool set. Each tool declares:
required capability, data classes read, data classes written, whether it is
*consequential* (side-effecting), and its maximum risk tier. Tools receive the
request-scoped token, not ambient credentials. Loop bounds: max 8 tool calls, max 2
minutes wall clock, then escalate. Agent memory is per-request; nothing persists across
requests except an explicitly-stored, tenant-scoped conversation record.

**Prohibited by construction:** the agent cannot call an unregistered tool, cannot write
to the Record Store (only propose), and cannot ground on its own prior output
([ADR-002](../adrs/ADR-002-grounding-strategy.md)).

### 3.6 Grounding Verifier (Zone 2/3)
Decomposes candidate output into atomic claims, retrieves supporting spans from the
tenant's vetted corpora, and requires an entailment decision per claim. No support ⇒
refuse or escalate. Spec: [`grounding/hallucination-containment.md`](../grounding/hallucination-containment.md). [AGNOSTIC]

### 3.7 Risk Classifier (Zone 2)
Assigns Tier 1/2/3 to the *proposed output or action* using a deterministic rule set
(capability + specificity + irreversibility + harm class), not a model score. Ties and
unknowns round **up**. Spec: [`hitl/risk-taxonomy.md`](../hitl/risk-taxonomy.md). [AGNOSTIC mechanism, REGIME trigger]

### 3.8 Approval Console (Zone 5)
Presents the proposed output, its citations, the minimization manifest summary, and the
risk tier to the **named owning role**. Approve / edit-and-approve / reject, each with a
reason code, each written to the ledger before the output is released. If no eligible
approver is available within the SLA, the request **expires closed** and the requester is
told why. [AGNOSTIC]

### 3.9 Audit Ledger (Zone 2)
Append-only, hash-chained, queryable; anchored daily to WORM storage and to an external
notary. Writes are synchronous for consequential events: if the ledger write fails, the
action does not happen. Spec: [`audit/audit-log-spec.md`](../audit/audit-log-spec.md). [AGNOSTIC]

### 3.10 Record Store & Vetted Corpus Store (Zone 3)
Region-pinned, per-tenant encryption keys (envelope encryption, tenant CMK, key policy
denies cross-tenant use), AES-256 at rest, TLS 1.3 in transit. The Vetted Corpus Store
holds the tenant's licensed clinical reference set with per-document provenance and
review metadata ([`grounding/vetted-sources.md`](../grounding/vetted-sources.md)).

## 4. The request path in one paragraph

A request enters at the edge, is authenticated and tenant-scoped, and is checked by the
Policy Engine (permission + care relationship + flag state + field allow-list). If AI is
off, the request is served by the deterministic degraded path and never reaches the model.
If AI is on, the Minimization Filter projects the record down to the allow-listed fields
and assembles the prompt; the Agent Runtime plans and calls registered tools; candidate
output goes to the Grounding Verifier, which refuses or escalates anything high-risk it
cannot support with a vetted span; surviving output is risk-classified; Tier 3 goes to a
named human in the Approval Console and is released only on approval; Tier 1–2 flows
automatically. Every hop — including every refusal, denial, and toggle read — writes to
the hash-chained Audit Ledger.

## 5. Where each functional requirement is enforced

| FR | Enforcing component(s) | Fails closed by |
|----|------------------------|-----------------|
| FR-1 data handling/residency | Minimization Filter, region-pinned Zone 3/4, KMS key policy | No allow-list ⇒ no prompt; region mismatch ⇒ endpoint refuses |
| FR-2 auditability | Audit Ledger (synchronous on consequential events) | Ledger unavailable ⇒ action refused |
| FR-3 HITL | Risk Classifier + Approval Console | Classifier uncertain ⇒ round up; no approver ⇒ expire closed |
| FR-4 grounding | Grounding Verifier + Vetted Corpus Store | Retrieval unavailable ⇒ refuse Tier 2/3 |
| FR-5 toggles | Flag Service + Policy Engine + degraded path | Unknown/stale flag ⇒ AI off |

## 6. Non-functional requirements

- **Defensibility (NFR-1)** — [`control-mapping/control-matrix.md`](../control-mapping/control-matrix.md)
  gives obligation → control → FR → evidence in one table.
- **Least privilege (NFR-2)** — request-scoped tokens, per-tool declared scopes, per-tenant
  CMKs, no ambient credentials in the Agent Runtime, revocation via token TTL ≤ 5 min plus
  an immediate revocation list checked at each tool call.
- **Observability (NFR-3)** — the ledger plus the trace store reconstruct any decision:
  see the [auditor walkthrough](../stretch/auditor-walkthrough.md).
- **Fail-safe (NFR-4)** — enumerated in §5 and tested in
  [`stretch/red-team-grounding.md`](../stretch/red-team-grounding.md).

## 7. Deliberate limitations

- Synchronous ledger writes on consequential events cost latency (~15–40 ms p50). Accepted:
  an unlogged consequential action is worse than a slow one ([ADR-006](../adrs/ADR-006-audit-log-design.md)).
- Tier 3 HITL caps throughput at human review capacity. Accepted, and mitigated by keeping
  Tier 3 narrow rather than by lowering the bar ([ADR-003](../adrs/ADR-003-hitl-threshold.md)).
- Region pinning forecloses a single global model pool and its cost advantages
  ([ADR-004](../adrs/ADR-004-residency-approach.md)).
