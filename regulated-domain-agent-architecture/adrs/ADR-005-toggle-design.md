# ADR-005 — Conjunctive, fail-closed toggle resolution

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Vendor Incident Commander / Tenant Administrator (DC-8)

## Context

Leadership requires the ability to turn AI off per tenant, per feature, or globally without
taking the product down. FR-5 adds a defined degraded mode and an audit record of the
toggle.

## Decision

Four scopes — **global, tenant, feature, subject** — resolved **conjunctively**: any scope
can disable, **no scope can re-enable** over another. Evaluation is server-side on the
request path. Unknown, missing, malformed, or (past a 60 s bounded stale window)
unreachable flag state ⇒ **AI off**. Flag change and ledger write are transactional; a
reason code is mandatory; re-enabling after an `INCIDENT` or `REGULATORY` kill requires
two-person approval, while disabling never requires approval.

## Rationale

- **Conjunctive with no override** is what makes it a kill switch. A "vendor can force
  enable for support" path reintroduces exactly the processing the tenant prohibited, at
  the worst possible moment.
- **Fail-closed on unknown state.** If an unreachable flag service leaves AI on, the switch
  works only when nothing is wrong — i.e. never when it matters.
- **The 60-second bounded stale window** is a deliberate trade. Zero staleness makes the
  flag service a hard availability dependency of every request, so a brief blip becomes a
  full product degradation; unbounded staleness makes the kill switch advisory. 60 s caps
  disobedience at well under human incident timescales while absorbing transient failures.
  The global kill switch additionally rides a separate minimal-dependency channel and
  bypasses caches, so stopping never depends on the health of the full flag service.
- **Subject scope exists** because a per-patient restriction (§164.522) is operationally
  the same mechanism; a design that can disable per tenant but not per person fails that
  obligation. It also turned out to be the closest existing analogue to edtech's consent
  gate — unplanned portability.
- **Asymmetric approval** because the safe direction should always be one click and the
  unsafe direction should require a second person.
- **Transactional flag+ledger write**, with one deliberate exception: the global kill switch
  proceeds and journals if the ledger is unavailable, because "cannot log" must not mean
  "cannot stop".

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Client-side feature hiding | Endpoint stays live; anyone with a token bypasses it. |
| Config-file toggles requiring redeploy | Minutes-to-hours propagation during an incident; not a switch. |
| Fail-open with alerting | An alert is not a control; the processing happens anyway. |
| Global-only kill switch | Forces an all-tenant outage to respond to one tenant's incident, so it never gets used. |
| Degrading to a smaller model when "off" | The tenant said off, not cheaper. |

## Consequences

- Every AI-dependent code path needs a specified, tested degraded counterpart
  ([degraded-mode](../toggles/degraded-mode.md)), enforced by a CI journey suite.
- Flag reads are on the hot path; caching and the stale window are load-bearing and must
  be monitored.
- Re-enable friction (two-person) is real operational cost during incident recovery.
  Accepted.
