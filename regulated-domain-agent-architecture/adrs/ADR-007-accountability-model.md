# ADR-007 — A named owning role for every automated decision class

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Architect + Tenant Privacy Officer

## Context

FR-2 requires accountability to be explicit: which human or role owns each automated
decision. The failure mode is a decision that "the system made" — which means no one made
it and no one can answer for it.

## Decision

Twelve decision classes (DC-1…DC-12), each with a **named owning role**, recorded in every
audit event as `accountable_role` + `accountable_party` — **including for auto-flowed
output that no human touched**. Roles resolve to **duty rosters**, not individuals.
Delegation is explicit, time-bounded, and audited. A capability whose `accountable_role` is
unset is blocked at deploy time.

## Rationale

- **Auto-flow is not unowned.** Someone decided that this class of output may flow without
  review; that person owns it. Recording ownership on unreviewed output is what prevents
  auto-flow from becoming an accountability vacuum, and it makes the ownership visible at
  the moment it is easiest to forget.
- **Roles, not individuals**, because individuals leave, and an accountability model that
  breaks at a resignation was never real.
- **Rosters with expire-closed on empty** rather than fallback-to-release: an
  accountability gap must not be resolved by removing the control. This makes coverage a
  safety property, not a staffing convenience.
- **Vendor-side decisions are owned too.** Entailment thresholds, risk rules, and model
  upgrades affect every tenant. "Who decided τ was 0.85 on the day of my incident?" must
  have a named answer.
- **Deploy-time enforcement**, because a policy requiring an owner that is checked by
  review will drift; one checked by the pipeline cannot.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| "The system is accountable" | Not a thing that can answer a regulator, be trained, or be replaced. |
| A single accountable executive for all AI decisions | Nominally satisfies the requirement, operationally meaningless: that person cannot review or even know about individual decisions. |
| Accountability only for HITL-reviewed output | Leaves Tier 1–2 auto-flow unowned — the majority of volume. |
| Named individuals per decision | Breaks on leave, shift change, and turnover; produces stalled queues and pressure to weaken the threshold. |

## Consequences

- Tenants must staff and maintain duty rosters; onboarding must capture role assignments.
- Adding a capability is a governance action, not only an engineering one.
- Delegation adds audit surface (grantor, grantee, scope, window) that must be reviewed —
  delegation chains are a classic place for privilege to quietly accumulate.
