# Evidence Index

For each control in the [matrix](control-matrix.md): what an auditor asks for, where it
lives, and what a passing result looks like. Sample identifiers are synthetic.

| Control | Evidence artefact | Where | Passing result |
|---|---|---|---|
| C-02 Minimization | `minimization.applied` event for a chosen request | Audit Ledger, query by `correlation_id` | Manifest lists only allow-listed field paths; `prompt_hash` matches the retained hash; no direct identifiers present |
| C-02 (config) | Allow-list version history per capability | Config repo, signed commits | Every change has an approver and a reason; effective-dated |
| C-05 Accounting of disclosures | Saved ledger query `disclosures_by_subject` | Ledger query library | Returns every release/action for a record ref in the window, with actor and purpose |
| C-06 Restrictions | `policy.degraded {cause:PATIENT_RESTRICTION}` | Ledger | Restricted synthetic patient never appears in any `minimization.applied` event after the flag's effective time |
| C-08 Subprocessors | Subprocessor register + egress allow-list | Config repo | Every model endpoint in the allow-list appears in the register with region and retention terms |
| C-14 Audit controls | Chain verification report | `audit/verify` job output | `chain_ok=true` for the full window; daily roots match the notary receipts |
| C-14 (fail-closed) | Ledger-unavailable drill record | Fail-closed test matrix | Consequential action refused; refusal itself recorded once the ledger returns |
| C-19 / C-33 Retention | Retention config + deletion job report | Config repo, job logs | PHI hard-deleted at tenant clock expiry; matching audit entries still present and still verify (they hold refs only) |
| C-23 Risk taxonomy | `risk.classified` events with `rule` field | Ledger | Every Tier-3 event names the rule that fired; no Tier-3 output released without a preceding `approval.granted` |
| C-24 HITL | Approval records incl. expiries | Ledger | For every `approval.expired`, a matching "action not taken" outcome |
| C-25 Grounding | `grounding.result` / `grounding.failed` events | Ledger | Every released Tier 2/3 output has ≥ 1 citation per high-risk claim; every failure has a refusal or escalation |
| C-25 (red-team) | Red-team report | [`stretch/red-team-grounding.md`](../stretch/red-team-grounding.md) | No confident ungrounded Tier-3 assertion released across the attempt set |
| C-27 Toggles | Toggle drill record at all three scopes + flag-service outage drill | Fail-closed test matrix | Each scope produces degraded mode; outage past max-stale ⇒ AI off |
| C-28 Toggle audit | `toggle.changed` events | Ledger | Old→new, scope, actor, reason present for every change; no state change without an event |
| C-29 Accountability | Ownership register | [`audit/accountability-model.md`](../audit/accountability-model.md) | Every decision class has a named role; every Tier-3 approval carries an actor holding that role |
| C-31 Tenant isolation | Isolation test report | [`stretch/tenant-isolation-proof.md`](../stretch/tenant-isolation-proof.md) | Cross-tenant read, retrieval, and flag tests all deny and audit |
| NFR-3 Reconstructability | End-to-end walkthrough | [`stretch/auditor-walkthrough.md`](../stretch/auditor-walkthrough.md) | A single decision reconstructed from `correlation_id` in ≤ 8 queries |

## Fail-closed test matrix (the drill list)

| # | Injected failure | Expected behaviour | Audited as |
|---|---|---|---|
| FC-1 | Flag service unreachable past max-stale (60 s) | AI off, degraded mode | `flags.unavailable {decision:AI_OFF}` |
| FC-2 | Retrieval/vetted corpus unavailable | Tier 2/3 refused; Tier 1 also refused if it makes factual claims | `grounding.failed {reason:RETRIEVAL_UNAVAILABLE}` |
| FC-3 | No supporting span for a Tier-3 claim | Refuse + offer escalation | `grounding.failed {reason:NO_SUPPORTING_SPAN}` |
| FC-4 | No eligible approver within SLA | Expire closed; action not taken | `approval.expired {cause:NO_APPROVER}` |
| FC-5 | Policy Engine unreachable | Deny | `policy.unavailable {decision:DENY}` |
| FC-6 | Audit ledger write fails on a consequential event | Action aborted | `action.aborted {cause:LEDGER_WRITE_FAILED}` (written on recovery, with the pending-write journal reference) |
| FC-7 | Model endpoint outside contracted region | Egress denied | `egress.denied {cause:REGION_MISMATCH}` |
| FC-8 | Risk classifier ambiguous | Round up to the higher tier | `risk.classified {tier, rule:TIE_ROUND_UP}` |
| FC-9 | Token expired mid-plan | Tool call denied; request fails, no partial side effects | `tool.denied {cause:TOKEN_EXPIRED}` |
| FC-10 | Vetted document past `valid_until` | Excluded from retrieval; dependent prior outputs flagged | `corpus.excluded {reason:EXPIRED}` |

FC-6 deserves a note: "refuse if you cannot log" creates a chicken-and-egg problem
(you cannot log the refusal either). Resolution: the write path journals to a local
append-only buffer with its own hash chain, the action is aborted, and the buffer is
merged into the ledger on recovery with an explicit `deferred_write` marker. The chain
verifier treats an unmerged buffer older than 15 minutes as an incident.
