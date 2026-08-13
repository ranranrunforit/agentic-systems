# ADR-007 — Short-lived, intent-bound tokens; credentials never reach extension code

**Status:** Accepted · **Date:** 2026-05-22 · **Deciders:** security, platform

## Context

Extensions need to call upstream systems that require credentials. The requirement is
that secrets never reach extension code in plaintext beyond the minimum scope, and that
the token lifecycle covers issuance, scoping, rotation and revocation with least
privilege.

## Decision

**One token per authorized action**, minted *after* the gate allows, bound to six things:
extension ref including version, tenant, resource, action set, intent hash, and
credential generation. TTL 15–30 seconds.

**Credential injection happens in the egress proxy.** Extension code calls
`ctx.http(method, url, resource=, action=)`; the host mints the handle, the proxy redeems
it, resolves the plaintext credential from the secret store, and attaches it. The
extension holds neither the credential nor a usable handle.

**Downscoping at mint time:** `(resource, action)` maps to the minimum upstream OAuth
scopes, and the broker refuses to mint a token whose upstream scopes exceed what the
stored credential holds.

**Rotation** replaces the stored credential and bumps a generation, invalidating
outstanding handles — with no extension change, because no extension ever held the value.

**Revocation** is immediate, host-wide, and checked at mint, redeem and gate liveness.

## Alternatives considered

**Pass an access token to the extension.** The conventional approach, rejected: it puts a
reusable credential in the least-trusted component, and it makes rotation a coordination
problem across N codebases.

**Long-lived per-extension service accounts.** Rejected: ambient authority by another
name, and it destroys per-action attribution.

**One token per session rather than per action.** Rejected: the intent binding is what
prevents a `read` token being replayed as a `close`. Sessions are exactly the wrong
granularity for an agent that proposes many different actions from one invocation.

**Token caching for performance.** Rejected: minting is cheap; caching trades the intent
binding for microseconds.

**Refresh inside extensions.** Rejected: refresh logic in N codebases. A token that
expires mid-flight fails and the host retries.

## Consequences

**Good.** "Secrets never reach extension code" is true by construction rather than by
policy, and it is asserted by a test that inspects the connector's own return value and
logs. Rotation is a single operation with no coordination. A stolen handle is useless:
wrong extension, wrong action, wrong intent, or expired.

**Bad.** Every upstream call round-trips through the host, so the host is on the latency
path and is a single point of failure for all egress. That is the price of the property
and we take it deliberately.

**Bad.** The `(resource, action) → upstream scope` map lives in the broker, so adding a
resource means touching host code. It belongs in configuration eventually; keeping it in
code today means it is reviewed with the same rigour as the gate.

**Bad.** Migrating to a hosted platform tempts a team to use the platform's secret
injection, which hands the value to the node and regresses this ADR's central property.
Called out explicitly in the migration path.
