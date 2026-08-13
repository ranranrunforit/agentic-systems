# Threat model

Scope: the extensible agent platform — host, extensions, brokered egress, governance.
Out of scope: the identity provider, the upstream SaaS products' own security, and the
surrounding application's authentication (the platform trusts a verified `actor` and
`tenant` at the boundary and records them).

## Assets

| Asset | Why an attacker wants it |
|---|---|
| Upstream credentials (`secrets/*`) | Direct access to every ticket, article and pipeline in the tenant |
| Customer data in tickets and articles | PII; commercially sensitive |
| The ability to act on tickets | Fraud (closing complaints, refunds), sabotage, social engineering of customers |
| Cross-tenant reach | One compromise, many victims |
| The approved-grants file | Approving your own permissions is the cleanest privilege escalation there is |
| The audit log | Erasing the record after the fact |

## Adversaries

| # | Adversary | Capability assumed |
|---|---|---|
| A1 | **External content author** | Can write text the platform will read: ticket bodies, forwarded emails, wiki pages, commit messages |
| A2 | **Careless internal extension author** | Ships an extension with over-broad permissions, a hard-coded secret, or a naive prompt |
| A3 | **Malicious internal extension author** | Deliberately writes an extension that exfiltrates or escalates |
| A4 | **Third-party publisher** (future) | Same as A3, plus no employment relationship and no code review by us |
| A5 | **Compromised connector** | Attacker controls a connector's code, which legitimately holds authority for its resource |
| A6 | **Compromised operator account** | Can invoke agents and approve confirmations as a human |
| A7 | **Insider with repository write access** | Can propose changes to policy, grants, and host code |

## Attack paths and controls

### A1 — planted instructions in content (the headline threat)

| Step | Control |
|---|---|
| Attacker edits a wiki page the agent retrieves | None — this is expected and cannot be prevented |
| Content reaches the model as instructions | Fenced and labelled untrusted; heuristics recorded |
| Agent proposes a privileged action | Trust boundary: proposals are not actions |
| Action requires authority the agent lacks | Default-deny declaration check |
| Action is high impact | Policy R-900 — tainted high impact is refused, no confirmation path |
| Action leaks credentials or PII | Pre-action hook veto; extension holds no credentials |
| Action targets an attacker-controlled destination | Egress allowlist |

Residual: low-impact influence (which article is read, which label is applied).
Evidence: `make injection`.

### A2 — careless author

| Path | Control |
|---|---|
| Requests `scope: {}` to "keep it simple" | Contract invariant C4 rejects unscoped permissions at load |
| Requests `close` "just in case" | Requires a written justification; permission review; high-impact actions draw scrutiny |
| Hard-codes a credential | There is nothing to hard-code — the credential lives in the host; a literal in code reaches no allowlisted destination without a grant |
| Ships a naive prompt that follows retrieved instructions | Assumed by design; contained by the gate |
| Expands permissions in a patch release | Loader refuses; permission diff requires re-approval |

### A3 / A4 — malicious extension author

| Path | Control |
|---|---|
| Exfiltrate to an attacker host | Egress allowlist; destinations are reviewed and non-`https` is refused |
| Read another extension's files or secrets | Filesystem guard; per-invocation workspace; no shared state |
| Harvest credentials from the environment | Environment cleared; credentials never in the extension's address space |
| Spawn a process or open a socket | Import blocker; production: seccomp + netns |
| Call a capability it did not declare | `requires` check, then the callee's own grant |
| Replay a token for a stronger action | Token bound to extension ref, action set, intent hash, generation, 15–30s TTL |
| Sit quietly and act later | Kill-switch revokes host-wide in one call; every action is logged |

Gap for A4: **no signing yet.** A third-party marketplace needs capability
attestation (specified in [`isolation.md`](isolation.md)) before this adversary is in
scope. Recorded in ADR-010 and [`../governance/marketplace.md`](../governance/marketplace.md).

### A5 — compromised connector (the worst realistic case)

A connector legitimately holds authority for its resource, so containment is about
blast radius rather than prevention:

- authority is bounded by its own manifest scope (`tenant`, `project: support-*`) and by
  the org policy — a compromised `cicd-status` still cannot mutate CI (R-902);
- credentials are still host-held; the connector can *use* authority for the duration
  of a gated call, but cannot exfiltrate a reusable secret;
- egress remains allowlisted, so stolen data has nowhere to go;
- every call is logged with destination and intent, so detection is realistic;
- one `host.kill` ends it, and rotation invalidates everything it touched.

Connectors are therefore deliberately thin, reviewed hardest, and the only extension
type carrying `delegated_auth`.

### A6 — compromised operator account

| Path | Control |
|---|---|
| Confirm high-impact actions | Confirmation is bound to `resource:action:target`; each is logged with the actor |
| Drive an agent to act cross-tenant | Scope binds every permission to the caller's tenant |
| Mass-close tickets | R-030 requires per-target confirmation and a recorded reason; rate limiting is future work (ADR-010) |
| Approve a permission expansion | Separation of duties: approvals are code review on `approved-grants.yaml` by a named approver, not an in-app action |

### A7 — insider with repository access

The platform's defence here is process, not code: `approved-grants.yaml`, the ABAC
policy and host code are all code-reviewed with required approvers (CODEOWNERS), the
audit log is hash-chained and shipped off-host, and the review board that approves a
grant is not the team that authors the extension. This is stated as a limit, not
solved: an insider with unreviewed write access to policy owns the platform.

## Trust boundaries

```
   attacker-controlled text ─┬─▶ connectors ─▶ [ EGRESS PROXY ] ─▶ host ─┐
                             │   (untrusted)                             │
   extension code ───────────┘                                          │
                                                                        ▼
                                              [ AUTHORIZATION GATE ] ── executes
                                                        ▲
   model / agent intent ────────────────────────────────┘  (proposals only)
```

Three crossings, each with a control: **egress proxy** (allowlist + credential
injection + taint labelling), **authorization gate** (two keys + impact + confirmation),
**loader** (contract + grant + permission diff).

## What is explicitly not mitigated

1. **Extension code signing / attestation** — specified, not implemented. Blocks the
   third-party marketplace.
2. **Rate limiting and anomaly detection** — an authorized extension can act at machine
   speed within its grant. Per-extension budgets are the next security increment.
3. **Field-level taint** — coarse call-level propagation over-blocks; it does not
   under-block, but it is imprecise.
4. **Runtime I/O schema enforcement** — `io` is descriptive; malformed payloads are a
   correctness problem, not currently a contract violation.
5. **Denial of service against the host** — timeouts and memory limits exist; there is
   no global admission control.
6. **Side channels between extensions** — timing and resource contention are
   unaddressed; irrelevant at this trust level, relevant with third-party code.
7. **The human in the confirmation loop** — confirmation fatigue is a real degradation
   path. The metric to watch is confirmations per operator per day; the mitigation is
   narrower scopes, not more prompts.

## Detection

Every one of the following is a queryable audit event:
`gate.denied`, `gate.confirmation_denied`, `egress.denied`, `token.revoked`,
`governance.permission_diff`, `governance.kill_switch`, plus `egress.call` records
carrying `injection_signals`.

Alert-worthy patterns: a spike in `gate.denied` for one extension (probing or a broken
release), any `egress.denied` with an off-allowlist destination (exfiltration attempt),
`injection_signals` on a source that never carried them before (freshly poisoned
content), and any `governance.permission_diff` outside a review window.
