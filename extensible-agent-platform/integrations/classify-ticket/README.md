# `classify-ticket` — tool

Classify a support ticket into a queue label, with a confidence score and a suggested
priority. A pure function over the ticket text.

| Field | Value |
|---|---|
| Kind | tool |
| Version | 1.2.0 |
| Owner | team-support-platform |
| Grant | GOV-142, expires 2027-06-09 |
| Runtime | local-subprocess, `network: deny` |
| Output trust | trusted (derives only from its input; reaches nothing) |

## Capability

| Capability | Params | Output | Impact |
|---|---|---|---|
| `ticket.classify` | `subject`, `body` | `label`, `confidence`, `priority`, `signals` | low |

## Why a tool rather than agent logic

Because it needs no authority. Keeping classification in a zero-egress tool means the
agent does not need a permission for it, the logic is independently testable and
versionable, and a reviewer reading the agent's manifest sees a smaller surface. The first
question to ask about any new extension is "can this be a tool?"

## Deliberately boring

Keyword scoring, no model call, no network. If it were LLM-backed the important property
would be unchanged: **its output is a label, not an action.** Nothing here can close a
ticket, and the gate would refuse it if it tried.

## Governance fixture

`runtime/tests/fixtures/classify-ticket-v1.3.0` is this extension with a quiet permission
expansion — it adds `issue_tracker:[read, close]` "to verify classification against the
resolved outcome". The loader refuses it until the grant is re-approved:

```bash
make governance
```

## Local use

```bash
python3 -m runtime.cli.ext test integrations/classify-ticket \
  --input '{"action":"classify","params":{"subject":"double charge","body":"charged twice for invoice 88213"}}'
```
