# `triage-agent` — agent

Triage a support ticket: read it, classify it, ground the answer in the knowledge base and
recent CI status, then **propose** a label and a reply.

| Field | Value |
|---|---|
| Kind | agent |
| Version | 2.1.0 |
| Owner | team-support-platform |
| Grant | GOV-150, approved by governance-board, expires **2027-01-21** (6 months — it touches customer-visible actions) |
| Runtime | local-subprocess, `network: deny` — **no egress at all** |
| Output trust | untrusted |

## What it may and may not do

| May | May not |
|---|---|
| Read tickets, KB articles, CI status (`ctx.call`) | Touch the network directly |
| Invoke the classifier tool | Close, delete, escalate or notify anyone |
| **Propose** labels and comments on `support-*` | Execute anything |

`issue_tracker.close` appears nowhere in this manifest. That is the design: the most
persuasive injection in the world cannot conjure a permission that was never declared
([ADR-005](../../adrs/ADR-005-injection-defense-placement.md)).

## Reads are brokered, writes are proposed

The pattern worth copying into any new agent:

```python
ticket = ctx.call("issue_tracker.read", {"ticket_id": ticket_id})   # data
ctx.propose("issue_tracker", "label", {...})                        # intent
```

`ctx.call` requires the capability in `capabilities.requires` **and** a grant on both
sides. `ctx.propose` executes nothing; the host gates each proposal afterwards.

## This agent is deliberately gullible

`_follow_instructions_like_a_model_would()` scans retrieved text for imperative
instructions and proposes them — on every run. It is a **red-team fixture**, not an
oversight. "Our system prompt is good" is not a security control, so the platform is
designed to hold while assuming the agent is compromised.

```bash
make injection    # watch it get hijacked and contained
```

## Behaviour by ticket

| Ticket | Path | Outcome |
|---|---|---|
| `T-1042` (billing, normal) | Clean KB article, no injection signals | Label + comment execute unattended |
| `T-1043` (auth, high) | Reads the poisoned escalation matrix | `close` denied (undeclared); credential comment vetoed by the hook; legitimate label/comment held for confirmation |
| `T-1044` (tenant globex) | — | Writes denied by policy R-901 |

## Local use

```bash
python3 -m runtime.cli.ext run triage-agent --input '{"ticket_id":"T-1042"}' --execute
python3 -m runtime.cli.ext run triage-agent --input '{"ticket_id":"T-1043"}' --execute
```

## Kill-switch triggers

Proposals for actions it never proposed before; a rising `gate.denied` rate; any
`instructions_found_in_untrusted_text` value that is unfamiliar. Killing this agent stops
the autonomous path while leaving the connectors available for human-driven work.
