# Token lifecycle — issue, scope, rotate, revoke

Implemented in [`../runtime/host/broker.py`](../runtime/host/broker.py); asserted by
`TestTokenLifecycle`.

## Design in one line

**One token per authorized action, minted after the gate says yes, scoped to that
action, valid for seconds, redeemable only by the egress proxy, revocable in one
call — and never visible to extension code.**

## Issue

`broker.mint()` runs *after* the gate allows, never before:

```python
grant = broker.mint(
    extension="issue-tracker@1.4.0",
    tenant="acme",
    resource="issue_tracker",
    actions=("label",),
    secret_ref="secrets/issue-tracker/oauth-client",
    intent_hash=decision.intent_hash,   # binds the token to this exact intent
    ttl_s=15,
)
# grant.handle == "tkn_9f3c…"  ← opaque; not a credential
```

The handle is bound to six things: extension **ref including version**, tenant,
resource, action set, intent hash, and the credential generation. Every one of those
is a replay defence:

| Attack | Why it fails |
|---|---|
| Reuse a `read` handle to `close` | `redeem()` checks the action set → `token is scoped to issue_tracker:['read']` |
| Another extension presents a stolen handle | Handle is bound to the extension ref |
| Same extension, different target ticket | Bound to the intent hash |
| Replay after rotation | Bound to the credential generation |
| Replay tomorrow | 15–30 second TTL |
| Escalate beyond the stored credential | Mint refuses upstream scopes the credential does not hold |

## Scope

Two layers of scoping, and they are checked independently:

- **Platform scope** — `(resource, actions, tenant)`, from the manifest permission.
- **Upstream scope** — the minimum OAuth scopes the action needs, mapped in the
  broker (`issue_tracker:label → tickets.write`) and enforced by the simulated
  provider, which returns `403 insufficient_scope` if the proxy sends less than the
  route needs and refuses to accept more than the credential holds.

## Extensions never hold credentials — or handles

Worth being precise, because it is stronger than the usual claim:

1. Extension code calls `ctx.http(...)` with a URL, a resource and an action.
2. The **host** authorizes, mints the handle, and passes it to the egress proxy.
3. The **proxy** redeems the handle, resolves the plaintext credential from the secret
   store, attaches it to the upstream request, and returns only the response body.

The credential is never in the extension's address space, and neither is the handle
it would need to fetch one. `TestTokenLifecycle.test_extension_code_never_receives_a_credential`
asserts the connector's own return value and logs contain no credential material.

## Rotate

```bash
host.rotate("secrets/issue-tracker/oauth-client", new_value)
```

Rotation replaces the stored credential, bumps a generation counter, and invalidates
every outstanding handle for that `secret_ref` (they now fail with
`token predates a credential rotation`). No extension changes, no redeploy, no
coordination — because no extension ever held the old value.

Policy: scheduled rotation every 90 days, immediate rotation on any suspicion, and
automatic rotation as step 2 of the kill-switch runbook.

## Revoke

Two levels:

| Operation | Effect |
|---|---|
| `broker.revoke_extension(ref)` | Every outstanding handle dies; further mints refuse; in-flight redeems fail |
| `host.kill(name, reason, actor)` | The above, plus registry revocation, capability de-registration, hook de-subscription and an audit record |

Revocation is idempotent and host-wide, and it is checked at three points (mint,
redeem, gate liveness) so an in-flight call cannot outrun it. See
[`../governance/kill-switch.md`](../governance/kill-switch.md).

## Lifecycle summary

| Phase | Trigger | TTL / effect |
|---|---|---|
| Issue | Gate allowed an action | 15–30s, single purpose |
| Redeem | Egress proxy makes the upstream call | One-shot in practice; scope + intent verified |
| Expire | TTL elapses | Silent; nothing to clean up |
| Rotate | Schedule or suspicion | Old generation dies immediately |
| Revoke | Kill-switch, incident, extension removal | All handles die immediately |

## Deliberate non-features

- **No refresh inside extensions.** An extension whose token expired mid-flight fails
  and is retried by the host. Refresh logic in extension code is refresh logic in N
  codebases.
- **No long-lived service tokens.** The one `client_credentials` integration
  (`cicd-status`) still mints per-action handles.
- **No token caching.** Minting is cheap; caching would trade the intent binding for
  microseconds.
