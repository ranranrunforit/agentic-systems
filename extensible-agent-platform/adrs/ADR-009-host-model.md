# ADR-009 — Host/extension model: one contract for four extension types

**Status:** Accepted · **Date:** 2026-05-04 · **Deciders:** platform architecture

## Context

The platform must be open to extension and closed to abuse, across four different kinds
of thing: agents that orchestrate, tools that compute, hooks that enforce cross-cutting
rules, and connectors that reach external systems. The obvious design gives each kind its
own registration API, because they *feel* different.

## Decision

**One contract, four kinds.** A single `ext/v1` schema covers all of them: declared
capabilities, requested permissions, typed I/O, lifecycle hooks. `kind` selects which
optional blocks are meaningful; it never changes the shape.

**The host owns authority; extensions own behaviour.** The host does exactly five things
— load/isolate/revoke, authorize, credential custody, mediate egress, record — and refuses
anything else. Everything domain-specific is an extension.

**One trust boundary:** everything a model or extension emits is proposed intent; only the
host executes.

Where the kinds differ is a *consequence* of their declarations, not a special case:
an extension with no permissions and no egress gets the fast in-process runtime; one that
reaches outside must declare `output_class: untrusted`; one subscribing to `pre_action`
gets consulted before the gate.

## Alternatives considered

**Separate contracts per extension type.** Rejected. Four contracts means four review
processes, four permission models and four places to fix an isolation bug. It also makes
the interesting question — "what authority does this thing have?" — answerable four
different ways.

**A plugin API (register callbacks in code).** Rejected: authority would be expressed in
code rather than data, so it could not be reviewed, diffed on upgrade, or enforced by a
loader.

**Agents as a special privileged type.** Explicitly rejected, and the inversion is the
point: the agent is the **least** trusted extension in the system, because it is the one
reading attacker-controlled text. Giving it a privileged path would have put the
authority exactly where the injection lands.

**No hooks; put cross-cutting rules in the host.** Rejected: PII redaction policy changes
faster than host releases, and a hook gets the governance lifecycle. See
[ADR-011](ADR-011-hook-veto-placement.md).

**MCP as the contract itself.** Rejected as *the* contract: MCP is a good connector
protocol and a poor description of a hook or an agent's permission set. Connectors are
MCP-style and could speak MCP on the wire; the governance contract stays ours.

## Consequences

**Good.** One loader, one gate, one audit vocabulary, one review checklist. Adding an
extension is principled: fill in the schema. The five shipped extensions cover all four
kinds with no host code specific to any of them, and the second host binding reuses the
whole orchestration layer.

**Good.** Because the model is uniform, the *composition* risks became visible — a
read-only connector plus a gullible agent plus one write permission is an exfiltration
path. That is a design conversation we would not have had with four separate contracts.

**Bad.** The schema carries fields most extensions do not use (`events` for non-hooks,
`delegated_auth` for non-connectors). Mitigated by `ext scaffold` emitting only the
relevant blocks per kind, but a reader of the schema sees the union.

**Bad.** "Everything is an extension" means the host is on the path for every call, so it
is both the latency floor and the blast radius if it has a bug. Accepted: a small
trusted core with a narrow interface is easier to review than four privileged paths.
