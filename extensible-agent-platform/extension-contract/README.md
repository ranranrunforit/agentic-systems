# The extension contract — `ext/v1`

**One contract, four extension types.** An agent, a tool, a hook and an MCP-style
connector are all *extensions*: they declare capabilities, request permissions,
define typed I/O, and expose lifecycle hooks. That is the whole idea. If adding a
new integration means writing host code, the platform is not extensible — it is a
pile of features with an SDK on top.

- Machine-readable schema: [`schema/extension.schema.json`](schema/extension.schema.json)
- Executable schema (authoritative): [`../runtime/host/contract.py`](../runtime/host/contract.py)
- Worked examples: [`examples/`](examples/) and the five real ones in [`../integrations/`](../integrations/)

Validate any manifest with:

```bash
python3 -m runtime.cli.ext validate integrations/issue-tracker
python3 -m runtime.cli.ext permissions integrations/triage-agent   # requested vs approved
```

## The shape

```yaml
apiVersion: ext/v1
kind: tool                       # agent | tool | hook | connector

metadata:                        # who owns this, and which version is running
  name: classify-ticket
  version: 1.2.0
  owner: team-support-platform
  description: ...

runtime:                         # how it executes and how tightly it is boxed
  type: local-subprocess         # local-inproc | local-subprocess | local-wasm | remote-rpc
  entrypoint: handler.py:handle
  timeout_ms: 3000
  network: deny                  # deny | broker-only — there is no `allow`

capabilities:
  provides: [ticket.classify]    # what the host can route to this extension
  requires: []                   # what this extension may ask the host to broker

events: [pre_action]             # hooks only

permissions:                     # REQUESTS. Default-deny until governance approves.
  - resource: ticket
    actions: [classify]
    scope: { tenant: "${caller.tenant}" }
    impact: low

egress:
  allow: ["issues.example.internal"]

delegated_auth:                  # required whenever egress is non-empty
  provider: issue-tracker-cloud
  flow: authorization_code_pkce
  subject: end_user
  scopes: [tickets.read]
  secret_ref: secrets/issue-tracker/oauth-client

trust:
  output_class: untrusted        # does its output carry taint?

io:
  input:  { action: string, params: object }
  output: { label: string, confidence: number }

lifecycle:
  on_load: validate_schema
  on_revoke: flush_tokens
  pre_action: authorization_gate
  post_action: audit_emit
  on_upgrade: permission_diff
```

## What the four kinds have in common, and where they differ

| | agent | tool | hook | connector |
|---|---|---|---|---|
| Declares capabilities | yes | yes | yes | yes |
| Requests scoped permissions | yes | usually none | none | yes |
| Typed I/O | yes | yes | yes | yes |
| Lifecycle hooks | yes | yes | yes | yes |
| Loaded / isolated / revoked identically | yes | yes | yes | yes |
| Typical runtime | subprocess | subprocess | inproc | subprocess / remote-rpc |
| Egress | none — uses `ctx.call` | none | none | brokered, allowlisted |
| Runs relative to the gate | **before** it (proposes) | before it | **on the host side** (vetoes) | **after** it (executes) |
| Output trust | untrusted | trusted | trusted | untrusted |

The last two rows are the only real differences, and they are consequences of the
declarations above rather than special cases in the host: an extension with no
`permissions` and no `egress` gets the fast in-process runtime; an extension whose
output reaches the world must declare `output_class: untrusted`; an extension that
subscribes to `pre_action` gets consulted before the gate.

## Contract invariants

The host refuses to load a manifest that breaks any of these. Each is enforced in
`contract.py` and covered by `TestContract` in `runtime/tests/test_platform.py`.

| # | Invariant | Why it exists |
|---|---|---|
| C1 | `apiVersion: ext/v1`, `kind` in the closed set | Versioned contract; unknown kinds cannot be smuggled in |
| C2 | `name` / semver `version` / `owner` present | Every running line of extension code has an accountable team |
| C3 | `capabilities.provides` non-empty; `requires` explicit | Callable surface and call graph are both declared, not discovered |
| C4 | Every permission has a **non-empty scope** | Makes "global authority" unrequestable rather than merely discouraged |
| C5 | Actions carry an impact class; high impact needs a `justification` | The reviewer reads *why*, and the gate knows when to stop and ask |
| C6 | `network: deny` and a non-empty `egress.allow` is a contradiction | Removes the "I forgot to close the network" failure mode |
| C7 | Anything reaching outside must declare `output_class: untrusted`, and egress requires `delegated_auth` | Taint cannot be opted out of; no ambient credentials |
| C8 | Lifecycle handlers come from a closed set | An extension cannot name arbitrary host functions |

Two of these deserve a note, because they are the ones authors push back on:

**C4 (no unscoped permissions).** `scope: {}` would be the convenient default and
would quietly grant cross-tenant reach. Requiring `tenant: "${caller.tenant}"` costs
one line and makes multi-tenant leakage a contract error instead of an incident.

**C7 (untrusted output is not optional).** An author who knows their API returns
"clean" data will want `trusted` to avoid confirmation prompts. They cannot have
it, because the API returns whatever a customer typed into a ticket. Taint is a
property of provenance, not of intent.

## Permission semantics

A permission is a `(resource, actions, scope)` triple with an impact class. Its
key — `resource:action1,action2@scope=value` — is the unit of review, diffing and
approval:

```
issue_tracker:comment,label@project=support-*,tenant=${caller.tenant}
```

Three independent things must line up before an action happens:

1. the manifest **requests** the permission (this file);
2. `governance/approved-grants.yaml` **grants** it for this version range;
3. `security/policy/abac-policy.yaml` **allows** it for these attributes.

Miss any one and the answer is deny. See [`../security/authorization.md`](../security/authorization.md).

Scope attributes resolve against the request: `${caller.tenant}` becomes the
delegating caller's tenant, and other attributes (`project`, `service`) are matched
as globs against the request parameters. A request that does not *carry* a scope
attribute is denied rather than assumed — you cannot pass a scope check by
omitting the field.

## The capability surface extension code gets

Handler signature, for all four kinds:

```python
def handle(ctx, payload):
    ...
    return {...}   # must match io.output
```

`ctx` is the entire outward surface. There is nothing else — no sockets, no
environment, no filesystem writes, no imports of `socket` / `subprocess` /
`urllib.request`.

| `ctx` method | What it does | Who authorizes it |
|---|---|---|
| `ctx.http(method, url, body, resource=, action=)` | One upstream HTTP call | Gate checks the declared permission; egress proxy checks the allowlist and injects the credential |
| `ctx.call(capability, params)` | Invoke another extension's capability through the host | Gate checks `requires`, then **both** parties' grants |
| `ctx.propose(resource, action, params, rationale)` | Record a *proposed* privileged action | Nothing executes; the host gates each proposal afterwards |
| `ctx.log(message)` | Structured log line into the audit trail | — |

`ctx.propose` is the contract's expression of the trust boundary: **the strongest
thing an agent can do to the world is describe what it would like to happen.**

## Worked examples

| Example | Kind | What it demonstrates |
|---|---|---|
| [`examples/tool.classify-ticket.yaml`](examples/tool.classify-ticket.yaml) | tool | The minimal shape: one capability, one low-impact permission, no egress |
| [`examples/connector.issue-tracker.yaml`](examples/connector.issue-tracker.yaml) | connector | Delegated OAuth, allowlisted egress, three impact tiers including a justified high-impact action |
| [`examples/agent.triage-agent.yaml`](examples/agent.triage-agent.yaml) | agent | `requires` for brokered reads, medium-impact writes, and the *absence* of `close` |
| [`examples/hook.pii-redaction.yaml`](examples/hook.pii-redaction.yaml) | hook | Event subscription, zero permissions, in-process fast path |
| [`../integrations/`](../integrations/) | all four | The same manifests, running |

## Versioning and compatibility

| Change | Version bump | Governance |
|---|---|---|
| Handler logic, no interface change | patch | none |
| New optional input field, new capability | minor | notify reviewers |
| **Any permission expansion** (new resource, new action, widened scope) | minor at least | **re-approval required; the loader refuses until then** |
| Removing a capability others `require`, breaking I/O | major | deprecation window per [`../governance/versioning-and-deprecation.md`](../governance/versioning-and-deprecation.md) |
| Rename | new extension | new proposal; the old one is deprecated and removed |

Contract-level changes (`ext/v1` → `ext/v2`) support both versions for one full
deprecation window; the loader dispatches on `apiVersion`.

## Known limitations

Recorded honestly, and tracked in [`../adrs/ADR-010-open-security-questions.md`](../adrs/ADR-010-open-security-questions.md):

- **`io` is descriptive, not enforced.** The host validates the manifest, not
  every payload against it. Runtime I/O validation is the next contract increment.
- **Taint is call-level, not field-level.** If an extension reads one untrusted
  article, everything it proposes in that invocation is tainted. Over-blocking
  rather than under-blocking, but coarse.
- **No signing yet.** `extension.yaml` is trusted because the repository is
  trusted. Capability attestation is specified in
  [`../security/isolation.md`](../security/isolation.md) and not implemented.
