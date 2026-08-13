# `issue-tracker` — connector

Read, label, comment on and (with human confirmation) close support tickets. Stands in for
Jira / Linear / Zendesk.

| Field | Value |
|---|---|
| Kind | connector |
| Version | 1.4.0 |
| Owner | team-support-platform |
| Grant | GOV-114, approved by sec-review-lead@platform, expires 2027-05-02 |
| Runtime | local-subprocess, `network: broker-only` |
| Egress | `issues.example.internal` |
| Output trust | untrusted (ticket bodies are attacker-controlled) |

## Capabilities

| Capability | Params | Impact |
|---|---|---|
| `issue_tracker.read` | `ticket_id` | low |
| `issue_tracker.label` | `ticket_id`, `project`, `label` | medium |
| `issue_tracker.comment` | `ticket_id`, `project`, `body` | medium |
| `issue_tracker.close` | `ticket_id`, `project`, `reason` | **high — confirmation required** |

## Authority

| Actions | Scope | Impact |
|---|---|---|
| read | `tenant: ${caller.tenant}` | low |
| comment, label | `tenant`, `project: support-*` | medium |
| close | `tenant`, `project: support-*` | high, justified in the manifest |

Upstream OAuth: authorization code + PKCE, `subject: end_user`, scopes
`tickets.read/write/close`, credential referenced as
`secrets/issue-tracker/oauth-client` and resolved **by the egress proxy** — never by this
code.

`close` is additionally constrained by policy R-030 (only this connector, only untainted,
only human/extension origin, `confirm` + `reason_required`) and refused outright by R-900
when the intent is tainted.

## Notes for reviewers

- The handler validates `ticket_id` against `^[A-Z]{1,4}-\d{1,8}$` before building a URL,
  and label values against a strict pattern — no user string reaches a URL unchecked.
- Comment bodies are truncated and pass through `pii-redaction-hook` first.
- One capability maps to exactly one upstream route. No business logic lives here by
  design ([ADR-008](../../adrs/ADR-008-integration-approach.md)).

## Local use

```bash
python3 -m runtime.cli.ext test integrations/issue-tracker \
  --input '{"action":"read","params":{"ticket_id":"T-1042"}}'
```

## Kill-switch triggers

Egress denials to unexpected destinations; a spike in `close` proposals; any
`gate.denied` pattern suggesting the connector is being driven outside `support-*`.
