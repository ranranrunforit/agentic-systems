# The kill-switch

## What "kill" means here

Marking an extension deprecated is not a kill-switch. A kill-switch has to satisfy
four properties, and this one is tested against all four:

| Property | Implementation | Test |
|---|---|---|
| **Immediate** | One call, no restart, no deploy | `test_kill_switch_revokes_tokens_and_unloads_host_wide` |
| **Total** | Registry state + capability index + hook subscriptions + tokens | same |
| **Credential-invalidating** | Broker drops every outstanding handle and refuses new mints | same |
| **Irreversible without governance** | Reload refused until a board member clears it | `test_killed_extension_cannot_be_reloaded_without_clearance` |

## Using it

```bash
python3 -m runtime.cli.ext kill knowledge-base --reason "INC-42: poisoned article KB-207"
```

```python
host.kill("knowledge-base", reason="INC-42: poisoned article KB-207",
          actor="security-oncall")
# → {"extension": "knowledge-base@1.1.2", "tokens_revoked": 3, "state": "revoked"}
```

What happens, in order:

1. `on_revoke` lifecycle handler runs (`flush_tokens`).
2. Registry marks the extension `revoked` with the reason.
3. Its capabilities are removed from the routing index — `knowledge_base.search` now
   resolves to nothing, so callers get a clean "no provider" denial rather than a
   partial result.
4. Its hook subscriptions are dropped.
5. The broker invalidates every outstanding token handle and refuses future mints for
   that extension ref; in-flight redeems fail.
6. `governance.kill_switch` is written to the audit log with actor, reason and the
   number of tokens revoked.

Authority: **security on-call can pull it alone, with no approval.** Restarting it
takes two people. Stopping should always be cheaper than starting.

## Blast radius and graceful degradation

Killing a connector does not corrupt the callers that depend on it. Because extensions
address *capabilities* rather than each other, a revoked provider produces a
gate-level denial with a reason:

```
call denied: no loaded extension provides capability knowledge_base.search
```

The triage agent's KB-grounding step fails, its other steps continue, and the audit log
records exactly what degraded. That is the payoff for indirection through the host: no
extension holds a direct reference to another, so revocation is total rather than
best-effort.

Killing the **agent** stops the whole flow, which is usually the right response to an
injection incident: the connectors stay available for human-driven work while the
autonomous path is closed.

## Incident runbook

```
0.  Detect         gate.denied spike · egress.denied to an unknown host ·
                   injection_signals on a new source · customer report
1.  Contain        ext kill <extension> --reason "INC-nn: <one line>"
2.  Rotate         host.rotate("secrets/<provider>/oauth-client", <new>)
                   — mandatory if the extension had egress; assume anything it
                     touched is compromised
3.  Assess         audit query: what did it do, for which tenants, since when?
                     · egress.call        destinations and volumes
                     · gate.allowed       privileged actions it completed
                     · host.invoke        who invoked it
4.  Notify         affected tenants if customer data or customer-visible actions
                   are implicated; data-protection owner decides
5.  Fix            new version, permission review re-run from scratch
                   (the old grant is void, not amended)
6.  Restore        registry.clear_revocation(name, actor=<board>, review="GOV-nnn")
                   then load the new version
7.  Learn          if the platform allowed something it should not have, the fix is a
                   policy rule or a contract invariant — not a note in a wiki
```

Step 7 is the one that matters. Each of the shipped deny rules (R-900 through R-903)
should be readable as "this once got through, or would have".

## Detecting what needs killing

| Signal | Query | Likely cause |
|---|---|---|
| Denial spike for one extension | `audit.find("gate.denied", extension=…)` | Broken release, or probing |
| Off-allowlist egress attempt | `audit.find("egress.denied")` | Exfiltration attempt |
| New injection signals on a source | `egress.call` records with `injection_signals` | Freshly poisoned content |
| Permission diff outside a review window | `audit.find("governance.permission_diff")` | Unreviewed change reaching a host |
| Confirmation denials climbing | `gate.confirmation_denied` | An agent going off the rails, or confirmation fatigue |

## Limits

- **Actions already completed are not undone.** The kill-switch stops future actions;
  reversal is a domain operation (reopen the ticket, retract the comment) and is the
  incident owner's job. This is why `close` is high impact and why irreversibility is
  the criterion for that class.
- **A killed extension's *effects* persist in upstream systems.** Rotation limits
  future use of anything it captured; it does not recall data.
- **No automatic kill.** Auto-revocation on anomaly is tempting and dangerous — a
  false positive silently disables a workflow. Today a human pulls it; anomaly
  detection pages that human. Recorded in ADR-010.
