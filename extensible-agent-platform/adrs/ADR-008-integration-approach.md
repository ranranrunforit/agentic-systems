# ADR-008 — Every integration is an extension; capabilities route through the host

**Status:** Accepted · **Date:** 2026-05-25 · **Deciders:** platform

## Context

The platform needs integrations with an issue tracker, a knowledge base and a CI/CD
system. The tempting shortcut is to build them into the host: fewer moving parts, direct
API calls, no contract overhead. That shortcut is also the single biggest way to fail
this design — three bespoke features with an SDK bolted on is not an extensible platform.

## Decision

**All integrations are extensions**, expressed in `ext/v1`, loaded by the same loader,
authorized by the same gate, credentialed by the same broker, audited the same way.
There is no privileged "built-in integration" path.

**Extensions never address each other.** They name a **capability** (`resource.action`)
and the host resolves the provider from the registry's capability index. Cross-extension
calls go through `ctx.call`, which requires the capability in `capabilities.requires` and
then applies **both** parties' grants — chained authorization.

**Connectors are thin.** One capability maps to one upstream call, with identifier
validation and nothing else. Business logic belongs in agents and tools.

## Alternatives considered

**Host-native integrations with an extension SDK on the side.** Rejected: the built-in
path would inevitably get affordances (direct credential access, no gate for "internal"
calls) that extensions do not have, and every future integration would argue for
built-in status.

**Direct imports between extensions.** Rejected: it defeats the kill-switch. If the
triage agent imported the issue-tracker connector, revoking the connector would leave a
live reference. Indirection through the capability index is what makes revocation total.

**One connector per external system, with a fat interface** (`issue_tracker.execute` taking
an arbitrary operation). Rejected: it collapses the permission model. `close` and `read`
must be separately grantable, so they must be separate capabilities.

**Let connectors hold their own credentials** (env vars, config files). Rejected — see
[ADR-007](ADR-007-token-lifecycle.md).

## Consequences

**Good.** Adding an integration is filling in a manifest and a thin handler; no host
change. Swapping Jira for Linear is a new connector providing the same capabilities, and
callers do not change. Revocation is total because no one holds a direct reference. The
same three connectors run unchanged on the second host binding.

**Good, and slightly surprising:** because tools go through the same path, invoking
`ticket.classify` is gated and audited like anything else. That felt like overhead until
it made the whole capability graph inspectable from the audit log.

**Bad.** Indirection costs latency (two gate evaluations per cross-extension call) and
makes stack traces less obvious — a denial surfaces as `call denied: …` inside the
caller. Mitigated by putting the rule id and reason in the message.

**Bad.** Capability naming is now a design problem with no owner. `issue_tracker.label`
versus `ticket.label` is a real question, and a wrong early choice is a deprecation
cycle. A capability catalogue is the missing artifact once there are more than about
twenty.
