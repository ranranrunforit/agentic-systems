# Identity and OAuth delegation

## Three identities, kept distinct

Conflating these is how agent platforms end up with a robot superuser.

| Identity | Who it is | Where it lives |
|---|---|---|
| **Principal** | The human (or scheduled job) on whose behalf work happens | `actor` on every intent and audit record |
| **Extension identity** | `name@version`, owned by an accountable team | Manifest `metadata`; registry |
| **Upstream identity** | What the external SaaS sees | Resolved by the egress proxy from `secret_ref` |

The platform never has a "platform admin" upstream account that all extensions
share. An extension acts either **as the delegating human** (`subject: end_user`) or
**as a narrowly-scoped service** (`subject: service`), and the manifest must say
which.

## Delegated access: authorization code + PKCE

For anything a human is behind, the connector declares:

```yaml
delegated_auth:
  provider: issue-tracker-cloud
  flow: authorization_code_pkce
  subject: end_user
  scopes: [tickets.read, tickets.write, tickets.close]
  secret_ref: secrets/issue-tracker/oauth-client
```

Flow, with the host as the confidential client:

1. The operator connects the integration once. The host runs the authorization-code
   flow with PKCE against the provider; the browser goes to the provider, not to us.
2. The provider returns an authorization code to the host's redirect endpoint. The
   host exchanges it for a refresh token **bound to that human and that tenant**, and
   stores it under `secret_ref` in the secret store.
3. At action time the host mints a short-lived scoped handle
   ([`token-lifecycle.md`](token-lifecycle.md)) and the egress proxy exchanges/attaches
   the upstream credential downscoped to the scopes this action needs.
4. The extension sees neither the refresh token, the access token, nor the
   `secret_ref` value. It sees an opaque handle it cannot even use directly — the
   proxy redeems it.

**Why the host is the client, not the extension.** If extensions ran their own OAuth
flows, every extension author would be holding refresh tokens, and revocation would
mean chasing N codebases. Centralising it makes rotation and revocation one operation.

**Why PKCE even server-side.** The redirect endpoint is the most attacked surface in
this design; PKCE removes code-interception as a class rather than relying on the
client secret alone.

## Service-to-service: client credentials

Where there is genuinely no human — the CI/CD status feed polled during triage —
`flow: client_credentials` with the narrowest upstream scope (`pipelines.read`). This
is the exception, and the reviewer's job is to ask why a human is not behind it.
`cicd-status` gets it because pipeline status is not user data and no user context
exists at poll time.

## Downscoping and the confused deputy

The upstream credential for the issue tracker holds `tickets.read`, `tickets.write`
and `tickets.close`. An action that only labels a ticket must not travel with
close authority, so `broker.mint()` maps `(resource, action)` to the minimum upstream
scope set and **refuses to mint a token whose upstream scopes exceed what the stored
credential holds**:

```
issue_tracker:read    → tickets.read
issue_tracker:label   → tickets.write
issue_tracker:close   → tickets.close
```

In production this is RFC 8693 token exchange against the provider; here it is
enforced at mint time and asserted by
`TestTokenLifecycle.test_least_privilege_beyond_upstream_scopes_is_refused`.

The confused-deputy risk in an agent platform is specifically this: an agent with
read authority persuades a connector with write authority to act for it. That is why
authorization is **chained** — the caller's grant *and* the callee's grant must both
cover the action ([`authorization.md`](authorization.md)) — and why the connector's
token is minted per call, bound to the intent hash, rather than held open.

## Human authentication

Out of scope for the platform: the operator authenticates to the surrounding
application (SSO/OIDC), which passes a verified `actor` and `tenant` to
`host.invoke`. The platform trusts that boundary and records it. If that boundary is
compromised, the audit log is what tells you what was done with it — which is why
`actor` is on every record and why the log is hash-chained.

## Open items

- **Per-user rather than per-tenant upstream tokens.** Today `secret_ref` resolves one
  credential per provider per tenant. True per-user delegation means N credentials and
  a consent ledger; specified, not implemented. See ADR-010.
- **Consent revocation propagation.** If a human revokes consent upstream, the host
  learns about it on the next 401. A webhook-driven revocation feed is the right answer.
