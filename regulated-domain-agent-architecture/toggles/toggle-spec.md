# Toggleable AI — FR-5 [AGNOSTIC]

Leadership requirement: turn AI off — per tenant, per feature, or globally — **without
taking the rest of the product down**.

## 1. Scopes

| Scope | Who can flip | Typical cause | Propagation SLO |
|---|---|---|---|
| **Global** | Vendor Incident Commander (DC-8) | Model incident, provider outage, regulatory event | ≤ 10 s |
| **Tenant** | Tenant Administrator, or Vendor on tenant request | Procurement policy, tenant incident, contract lapse | ≤ 30 s |
| **Feature** (`qa.record`, `draft.summary`, `action.schedule`, `qa.general`) | Tenant Administrator (their tenant) / Vendor (global) | Feature-specific quality issue | ≤ 30 s |
| **Subject** (`ai_processing_restricted` on a record) | Tenant Privacy Officer | Patient restriction request (O-P6) | Immediate (checked on read) |

Subject scope is included because a per-patient opt-out is operationally the same
mechanism, and a design that can turn AI off for a *tenant* but not for a *person* fails
the restriction obligation.

## 2. Resolution semantics

```
effective_ai_enabled(tenant, feature, subject) =
      global_kill_switch == OFF
  AND global_flag(feature)   == ON
  AND tenant_flag(tenant)    == ON
  AND feature_flag(tenant, feature) == ON
  AND subject_restriction(subject) != RESTRICTED
```

**Conjunctive.** Any scope can turn AI off; **no scope can turn it back on** over another
scope's objection. There is no override, no "vendor forces on", no per-user exception. A
kill switch with an override is not a kill switch.

Evaluation happens **server-side in the Policy Engine on the request path**. Not in the
client, not as a UI hide. Hiding the button leaves the endpoint live.

## 3. Fail-closed evaluation

| Flag service state | Cache age | Decision |
|---|---|---|
| Reachable | — | Use fresh value |
| Unreachable | ≤ `max_stale` (60 s) | Use cached value, emit `flags.stale` |
| Unreachable | > `max_stale` | **AI OFF**, emit `flags.unavailable {decision:AI_OFF}` (FC-1) |
| Reachable, flag not found | — | **AI OFF** — unknown flag is off, not "default on" |
| Malformed / schema-invalid response | — | **AI OFF** |
| Cold start, no cache | — | **AI OFF** until first successful fetch |

The bounded stale window is a deliberate trade: a 60-second cache prevents the flag
service from becoming a hard availability dependency for every request, while capping the
window in which a kill switch is disobeyed at one minute. Zero staleness would be
*safer per request* and *less reliable overall* — an unavailable flag service would take
the whole product to degraded mode instantly rather than riding out a brief blip. 60 s
is short enough that an incident-driven global kill is effective within the human
timescale of an incident.

**A kill switch flip bypasses the cache**: the flag service pushes an invalidation to all
edges, and the global kill switch is additionally evaluated against a separate,
minimal-dependency channel so that killing AI never depends on the health of the full
flag service.

## 4. Flag record and change audit (FR-5 + FR-2)

```json
{
  "flag_id": "feature:draft.summary",
  "scope": {"level": "tenant", "tenant": "SYN-TEN-northwind"},
  "state": "off",
  "previous_state": "on",
  "actor": {"id": "SYN-USR-9001", "role": "tenant_administrator"},
  "reason_code": "INCIDENT",
  "reason_text": "INCIDENT-1042 — reviewing summary quality",
  "effective_at": "2026-08-13T09:02:00Z",
  "expires_at": null,
  "flag_version": "fv-2291",
  "approval": {"required": false},
  "ledger_event": "SYN-EVT-0002c8"
}
```

Rules:
- **No state change without a ledger event.** The flag store and the ledger are written in
  one transaction; a write to the store that fails to log is rolled back.
- **Reason code is mandatory**, from a fixed list (`INCIDENT`, `PROCUREMENT`, `CONTRACT`,
  `QUALITY`, `REGULATORY`, `PATIENT_REQUEST`, `TEST`, `OTHER`+text).
- **Turning AI back on** at global or tenant scope after an `INCIDENT` or `REGULATORY`
  kill requires two-person approval (DC-8). Turning it *off* never requires approval —
  the safe direction is always one click.
- **Every request records the flag snapshot** it evaluated against
  (`inputs.flags_snapshot` with `flag_version`), so an auditor can prove what the state
  was at decision time rather than inferring it from change history.
- **Scheduled/expiring toggles** (`expires_at`) are supported for time-boxed incidents;
  expiry is itself an audited event with `actor: system` and the originating change as
  its cause.

## 5. What must keep working when AI is off

The whole point of the requirement: turning AI off is not turning the product off. See
[`degraded-mode.md`](degraded-mode.md). Architecturally this requires that **no
non-AI code path depends on an AI component** — verified by a startup assertion and a
CI test that boots the product with all AI components stubbed to unavailable and runs the
core journeys.

## 6. Testing the switch

| Test | Expectation |
|---|---|
| Flip global off | All tenants degraded within 10 s; product core journeys pass |
| Flip tenant off | Only that tenant degraded; the other tenant unaffected (isolation, [proof](../stretch/tenant-isolation-proof.md)) |
| Flip feature off | Only that feature degraded; sibling features still AI-assisted |
| Set subject restriction | That record never appears in a subsequent `minimization.applied` event |
| Kill flag service | AI off after `max_stale`; degraded mode; `flags.unavailable` logged |
| Delete a flag record | AI off (unknown ⇒ off), not "on by default" |
| Flip during an in-flight request | In-flight request completes or aborts per policy; **queued Tier-3 approvals are held, not auto-released** |
| Attempt flip without reason code | Rejected |
| Attempt flip with ledger unavailable | Rejected and rolled back — except the global kill switch, which is allowed to proceed with a deferred-write journal entry, because "cannot log" must not mean "cannot stop" |

That last exception is the one asymmetry in the fail-closed rules, and it is deliberate:
everywhere else, unable-to-log means don't act; for the kill switch, *not acting* is the
unsafe outcome, so it proceeds and journals.

## 7. Anti-patterns this design rejects

- **Fail-open flags.** Unreachable flag service ⇒ AI stays on. The switch is decorative.
- **Client-side toggles.** The endpoint stays live; anyone with a token bypasses it.
- **Toggle without degraded mode.** The feature 500s and the tenant's operations stop, so
  the switch is never actually used in an incident — which means it doesn't exist.
- **Override hierarchies.** "Vendor can force-enable for support" reintroduces exactly the
  processing the tenant turned off.
- **Unlogged flips.** No evidence for the auditor, and no way to explain why output
  stopped on a Tuesday.
