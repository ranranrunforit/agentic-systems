# Accountability Model — FR-2 [AGNOSTIC]

Requirement: *which human or role owns each automated decision is explicit.*

The failure this prevents: a decision that "the system made", which in practice means no
one made it and no one can answer for it. Every automated decision class below has a named
owning role, recorded in the audit event as `accountable_role` — **including decisions no
human touched**. Auto-flow is not unowned; it is owned in advance by whoever set the
policy that let it flow.

## Decision classes and owners

| # | Automated decision class | Example | Owning role | How ownership is exercised |
|---|---|---|---|---|
| DC-1 | Release of a Tier-3 clinical assertion | Referral letter draft | **Supervising clinician** (the requesting clinician, or their designated covering clinician) | Per-instance approval in the console |
| DC-2 | Proposal of a care action | Refill request, follow-up interval | **Prescribing / ordering clinician** | Per-instance approval |
| DC-3 | Release of a Tier-2 record summary | "Here's your last visit summary" | **Tenant Clinical Informatics Lead** | Owns the policy; reviews sampled output weekly |
| DC-4 | Release of Tier-1 general content | No-show policy answer | **Tenant Operations Manager** | Owns the source corpus and the policy |
| DC-5 | Refusal of a high-risk claim | Grounding failure | **Clinical Safety Officer (vendor)** | Owns refusal thresholds; reviews refusal trends |
| DC-6 | Access allow/deny | Care-relationship check fails | **Tenant Privacy Officer** | Owns the RBAC and relationship rules |
| DC-7 | Field allow-list content | What crosses the model boundary | **Tenant Privacy Officer** + **Vendor Product Security** (joint sign-off) | Versioned config change with two approvals |
| DC-8 | Toggle change | Turning `draft.summary` off | **Tenant Administrator** (tenant/feature scope); **Vendor Incident Commander** (global scope) | Audited flip with reason code |
| DC-9 | Vetted-corpus admission | Adding a clinical protocol | **Tenant Clinical Informatics Lead** | Signed corpus manifest |
| DC-10 | Model/version change | Upgrading the inference model | **Vendor Clinical Safety Officer** + **Tenant notification** | Change record + re-run of the grounding eval suite |
| DC-11 | Deletion / legal hold | Purge on retention expiry | **Tenant Privacy Officer** (Records Manager where the tenant has one) | Audited, cannot be initiated by the agent |
| DC-12 | Escalation routing | Sending a case to human review | **Clinical Safety Officer** | Owns routing rules |

## The rule that makes this real

> No automated decision class may exist without an entry in this table. Introducing a new
> capability requires adding a row and naming a role before launch; the deployment
> pipeline blocks a capability whose `accountable_role` is unset.

## RACI for the load-bearing flows

| Flow | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|
| Approving a Tier-3 output | Reviewing clinician | Supervising clinician | Clinical informatics | Privacy officer (via review pack) |
| Setting the HITL threshold | Vendor architect | Vendor Clinical Safety Officer | Tenant clinical leadership | Compliance reviewer |
| Changing a field allow-list | Vendor product security | Tenant Privacy Officer | Clinical informatics | Auditor (via config history) |
| Flipping the global kill switch | Vendor SRE on-call | Vendor Incident Commander | Legal, Clinical Safety Officer | All tenants (status + notification) |
| Responding to a suspected breach | Vendor security | Vendor Security Officer | Tenant Privacy Officer | Regulator, per tenant's determination |

## Delegation and coverage

Clinical ownership must survive shift changes, or Tier-3 queues stall and pressure builds
to lower the threshold — the wrong failure mode. So:

- Each owning role resolves to a **duty roster**, not an individual. The console routes to
  the on-duty holder.
- Delegation is explicit, time-bounded, and audited (`delegation.granted` with grantor,
  grantee, scope, window).
- If the roster is empty for a scope, requests in that scope **expire closed** (FC-4). The
  system does not fall back to "release it anyway" — that would convert an
  accountability gap into a clinical risk.

## Accountability for the vendor's own automated decisions

Refusal thresholds, risk rules, and model changes are decisions *we* make that affect
every tenant. They are owned by the vendor-side **Clinical Safety Officer** and are
recorded as versioned, audited configuration with the same event schema. A tenant auditor
can ask "who decided the entailment threshold was 0.85 on the day of my incident, and
what was it?" and get an answer with a name attached
([ADR-002](../adrs/ADR-002-grounding-strategy.md)).

## What this looks like in the ledger

```json
{"action":"output.released","risk_tier":2,
 "actor":{"type":"system","id":"svc-risk-classifier"},
 "accountable_role":"tenant_clinical_informatics_lead",
 "accountable_party":"SYN-ROLE-CIL@SYN-TEN-northwind",
 "why":{"reason_code":"TIER2_AUTOFLOW","policy_version":"v7"}}
```

The actor is a service; the accountable party is a role held by a person. Both are
recorded. That pairing is the whole model in one line.
