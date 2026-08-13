# Architecture — the host/extension model

**Worked domain:** support-ticket triage (a non-developer internal workflow).
**Platform stance:** host-neutral by construction; see [`../portability/`](../portability/).

The platform is a **trusted host** plus **untrusted extensions**. The host does five
things and refuses to do anything else. Extensions do the work and hold no authority
of their own.

```
                         ┌─────────────────────── the host (trusted core) ────────────────────────┐
                         │                                                                        │
  operator / schedule ──▶│  loader ──▶ registry ──▶ gate ──▶ broker ──▶ egress proxy ──▶ audit    │──▶ issue tracker
                         │             (grants)   (ABAC +   (scoped     (allowlist +              │──▶ knowledge base
                         │                        confirm)   tokens)     credential injection)    │──▶ CI/CD
                         │                                                                        │
                         └────────────▲──────────────────────────▲────────────────────────────────┘
                                      │                          │
                              sandboxed extensions        pre-action hooks
                          (agents · tools · connectors)     (host-side veto)
```

## The five host responsibilities

| Responsibility | Module | What it guarantees |
|---|---|---|
| Load / isolate / revoke | [`registry.py`](../runtime/host/registry.py), [`sandbox.py`](../runtime/host/sandbox.py) | Only approved versions run; each runs boxed; any can be pulled instantly |
| Authorize | [`gate.py`](../runtime/host/gate.py), [`policy.py`](../runtime/host/policy.py) | Nothing privileged happens without two independent keys turning |
| Credential custody | [`broker.py`](../runtime/host/broker.py), [`secrets.py`](../runtime/host/secrets.py) | Short-lived scoped tokens; plaintext secrets never enter extension code |
| Mediate egress | [`egress.py`](../runtime/host/egress.py) | One way out, allowlisted, labelled untrusted on the way back in |
| Record | [`audit.py`](../runtime/host/audit.py) | Every decision and action attributable and tamper-evident |

Everything else — classification, retrieval, ticket manipulation, orchestration — is
an extension. That split is the platform: **the host owns authority, extensions own
behaviour.**

## Diagrams

| Diagram | Shows |
|---|---|
[`diagrams/host-overview.mmd`](diagrams/host-overview.mmd) | Components, the trust boundary, and where the four extension types sit |
[`diagrams/privileged-action-sequence.mmd`](diagrams/privileged-action-sequence.mmd) | **Required sequence diagram**: an extension invoking a privileged action through the authorization gate |
[`diagrams/load-isolate-revoke.mmd`](diagrams/load-isolate-revoke.mmd) | The extension state machine from proposal to removal |
[`diagrams/injection-containment.mmd`](diagrams/injection-containment.mmd) | The red-team path: poisoned KB article → proposal → four independent refusals |

Render with any Mermaid renderer, or read them as text — they are written to be
legible either way.

## The four extension types

All four are the same contract ([`../extension-contract/`](../extension-contract/)).
What differs is where they sit relative to the gate.

```
   agent / tool ──proposes──▶ [ pre-action hooks ] ──▶ [ GATE ] ──▶ connector ──▶ outside world
   (before the gate:            (host side:              (decides)   (after the gate:
    intent only)                 can veto)                            executes, credentialed)
```

**Agents** orchestrate and are the least trusted thing in the system: they read
attacker-controlled text, so they are what an injection tries to hijack. The triage
agent may read tickets, KB articles and CI status; it may propose labels and
comments; it has no `close` permission at all, so no amount of persuasion can close
a ticket through it.

**Tools** are deterministic capabilities — `classify-ticket` is a pure function over
text with no network. Tools exist so agents do not need permissions for work that
needs no authority.

**Hooks** are the answer to "we need a rule that applies to every extension,
forever". They subscribe to host lifecycle events and run *on the host side of the
gate*, so their veto is authoritative. `pii-redaction-hook` redacts customer PII from
outbound text and refuses any action carrying a credential-shaped string.

**Connectors** are the only extensions that touch the outside world (MCP-style
adapters). Each maps declared capabilities onto upstream calls and is the sole holder
of a `delegated_auth` block. They are thin on purpose: a connector with business
logic in it is a connector nobody can review.

## The trust boundary

There is exactly one, and it is worth stating precisely:

> Everything a model or an extension emits is **proposed intent**. Only the host,
> after policy evaluation and (for high-impact actions) human confirmation,
> **executes**.

Consequences:

- `ctx.propose()` is the strongest thing extension code can do to the world.
- A planted instruction in retrieved text becomes, at best, a proposal — and
  proposals are evaluated against permissions the attacker cannot change.
- The same boundary is simultaneously the prompt-injection defence and the
  excessive-agency control. One mechanism, two problems; see
  [`../security/injection-defenses.md`](../security/injection-defenses.md).

## Load, isolate, revoke

**Load.** `registry.load_dir()` parses the manifest against `ext/v1`, looks up an
approved grant in `governance/approved-grants.yaml`, refuses any permission outside
that grant, diffs permissions against the running version, then registers the
extension's capabilities and hook subscriptions and runs `on_load` / `on_activate`.

**Isolate.** Every invocation runs through `sandbox.execute()`, which picks the
runtime the manifest declared:

| Runtime | Boundary | Used by |
|---|---|---|
| `local-subprocess` | Separate process, cleared environment, import blocker, read-only access to its own directory, no sockets | most extensions |
| `local-inproc` | Same process — permitted **only** for zero-permission, zero-egress extensions, enforced by the sandbox | hooks |
| `remote-rpc` | Off-host attested worker; materialised copy of the extension's own files only | `knowledge-base` |
| `local-wasm` | Specified in [`../security/isolation.md`](../security/isolation.md), not bundled | — |

**Revoke.** `host.kill(name, reason, actor)` marks the extension revoked, drops its
capabilities and hook subscriptions from the routing tables, tells the broker to
invalidate every outstanding token, and writes an audit record naming who pulled it
and why. It cannot be reloaded until governance clears the revocation. See
[`../governance/kill-switch.md`](../governance/kill-switch.md).

## Request path, end to end

A human asks the triage agent to handle T-1043:

1. **`host.invoke`** — liveness check on the agent, audit `host.invoke`, sandbox starts.
2. **`ctx.call("issue_tracker.read", …)`** — the agent has no network; the host
   resolves the capability, gates *both* the agent's grant and the connector's grant,
   mints a 15-second token scoped to `issue_tracker:read`, runs the connector in its
   own sandbox, and labels the response **untrusted**.
3. **taint accumulates on the host side.** The agent's self-report is advisory only;
   the host tracks provenance for the invocation so an extension cannot launder it.
4. **`ctx.call("ticket.classify", …)`** — same path, no egress, no credentials.
5. **`ctx.call("knowledge_base.search", …)`** — the connector runs on a remote worker;
   the returned article KB-207 contains a planted instruction, and the egress proxy
   records which injection heuristics fired.
6. **`ctx.propose(...)`** ×N — the agent proposes a label, a comment, and (having been
   hijacked by the planted instruction) a `close` and a credential-leaking comment.
7. **`host.run_agent` gates each proposal in turn.** Pre-action hooks run first and
   can veto; then the gate applies liveness, declaration, scope, policy, provenance
   and confirmation.
8. **Allowed proposals dispatch to the connector**, which performs one upstream call
   with an injected credential it never sees.
9. **Everything lands in the hash-chained audit log**, attributable to the actor.

Run it: `make triage` (clean ticket) and `make injection` (poisoned ticket).

## Why this shape

The design pressure is that extensions will be written by teams the platform team
does not control, and eventually by third parties. Three consequences follow:

- **Authority cannot live in extension code**, because extension code is exactly what
  we cannot review at scale. Hence declared permissions, host-held credentials, and
  a gate no extension can call past.
- **Capability routing must be indirect.** Extensions never import or address each
  other; they name a capability and the host decides who serves it. That is what makes
  the kill-switch total rather than best-effort, and what lets a connector be swapped
  without touching its callers.
- **The interesting failures are compositional**, not per-extension: a read-only
  connector plus a gullible agent plus one write permission is an exfiltration path.
  Taint tracking and the confirmation gate are aimed at that composition, not at any
  single extension's bugs.

Decisions and their alternatives are in [`../adrs/`](../adrs/).
