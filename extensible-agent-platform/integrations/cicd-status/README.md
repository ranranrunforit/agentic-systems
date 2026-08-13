# `cicd-status` — connector

Read the latest pipeline status for a service, so triage can tell "customer problem" from
"we shipped a bad release ten minutes ago". Stands in for GitHub Actions / GitLab CI /
Buildkite.

| Field | Value |
|---|---|
| Kind | connector |
| Version | 0.9.1 |
| Owner | team-delivery-platform |
| Grant | GOV-138, expires **2026-12-01** (short: pre-1.0) |
| Runtime | local-subprocess, `network: broker-only` |
| Egress | `ci.example.internal` |
| Output trust | untrusted (build logs contain arbitrary commit text) |

## Capabilities

| Capability | Params | Impact |
|---|---|---|
| `cicd.read` | `service` | low |

## Deliberately read-only, twice over

The upstream `rerun` route exists and the credential could reach it. It is **not
declared** here, and policy **R-902** denies `cicd:[rerun, write, deploy]` platform-wide.
Two independent refusals for the same thing, which is the two-key model working as
intended: even if a future version declared `rerun`, the policy would keep it unreachable
until a separate review lands
([`../../security/authorization.md`](../../security/authorization.md)).

## Why `client_credentials`

There is no human context when triage polls pipeline status, and pipeline status is not
user data. The manifest says so explicitly, and a reviewer's job is to challenge that
claim — it is the only integration here not acting as an end user.

## Local use

```bash
python3 -m runtime.cli.ext test integrations/cicd-status \
  --input '{"action":"read","params":{"service":"support-platform"}}'
```

The fixture `support-platform` pipeline is failing on purpose (`migrate-realms`, unknown
realm mapping), which is what lets the triage flow correctly connect an SSO ticket to a
bad deploy.

## Kill-switch triggers

Any `cicd` action other than `read` appearing in proposals; egress outside
`ci.example.internal`.
