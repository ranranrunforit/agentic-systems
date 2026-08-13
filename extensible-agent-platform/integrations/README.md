# Toolchain integrations (FR-5)

Five extensions covering all four kinds. **Every one goes through the `ext/v1` contract**
— there is no privileged built-in integration path, and no handler here calls its target
API outside `ctx.http`.

| Directory | Kind | Capabilities | Category | Runtime |
|---|---|---|---|---|
| [`issue-tracker/`](issue-tracker/) | connector | `issue_tracker.read/label/comment/close` | **Issue tracker** | local-subprocess |
| [`knowledge-base/`](knowledge-base/) | connector | `knowledge_base.read/search` | **Knowledge base** | **remote-rpc** |
| [`cicd-status/`](cicd-status/) | connector | `cicd.read` | **CI/CD** | local-subprocess |
| [`triage-agent/`](triage-agent/) | agent | `triage.ticket` | orchestration | local-subprocess |
| [`classify-ticket/`](classify-ticket/) | tool | `ticket.classify` | computation | local-subprocess |
| [`pii-redaction-hook/`](pii-redaction-hook/) | hook | `hook.pii_redaction` | cross-cutting rule | local-inproc |

Three of the four required integration categories are covered (issue tracker, knowledge
base, CI/CD). Version control is the fourth category and the natural next connector for
an SDLC instantiation — the contract does not change.

## Proof that they flow through the contract

```bash
python3 -m runtime.cli.ext list          # versions, permissions, grants, runtimes
make triage                              # a full flow across all three connectors
python3 -m unittest runtime.tests.test_platform.TestIntegrations -v
```

`TestIntegrations.test_full_triage_flow_touches_all_three_integrations` asserts that one
agent run produces egress to all three destinations, each through a gated, tokenised,
audited call.

Evidence a reviewer can check quickly:

- no handler imports an HTTP client — the sandbox blocks it, so egress is only
  `ctx.http`, which is authorized per call;
- no handler contains a credential, and none can obtain one;
- every capability is declared in a manifest and routed by the host, so nothing addresses
  anything else directly;
- removing a permission from a manifest breaks that capability and nothing else.

## How the pieces compose

```
  operator
     │
     ▼
  triage-agent (agent)
     ├─ ctx.call issue_tracker.read    ──▶ issue-tracker (connector)  ──▶ issues.example.internal
     ├─ ctx.call ticket.classify       ──▶ classify-ticket (tool)
     ├─ ctx.call knowledge_base.search ──▶ knowledge-base (connector, remote worker) ──▶ kb.example.internal
     ├─ ctx.call cicd.read             ──▶ cicd-status (connector)    ──▶ ci.example.internal
     └─ ctx.propose label / comment    ──▶ [pii-redaction-hook] ──▶ [GATE] ──▶ issue-tracker
```

Reads are brokered inline; writes are proposed and gated. That split is the platform's
central pattern, and it is why an injection in the KB article cannot become an action.

## Simulated backends

[`../runtime/backends/`](../runtime/backends/) stands in for real SaaS and behaves like it
on the axes that matter: bearer-token validation, per-route OAuth scope checks, `403
insufficient_scope`, read-only enforcement. Swapping them for real HTTP clients touches
only those files — no manifest, no policy rule, no test outside the backend fixtures.

Deliberate fixtures: `T-1042` (clean, with PII), `T-1043` (carries an injection, high
priority), `T-1044` (tenant `globex`, read-only by policy), `KB-207` (**poisoned wiki
page**), `support-platform` pipeline (failing, so triage has something real to find).

## Adding a fourth integration

No host change. Scaffold, declare, get a grant, publish:

```bash
python3 -m runtime.cli.ext scaffold vcs --kind connector --owner team-delivery-platform
# declare capabilities: vcs.read_pr, vcs.comment
# declare permissions with tenant scope; add the egress destination and delegated_auth
python3 -m runtime.cli.ext validate integrations/vcs
python3 -m runtime.cli.ext test integrations/vcs --input '{"action":"read_pr","params":{"id":"42"}}'
```

Then a policy rule for the new resource and a grant entry — both data, both reviewed.
See [`../adoption-dx/developer-journey.md`](../adoption-dx/developer-journey.md).
