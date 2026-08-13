# `<extension-name>` — `<kind>`

One sentence: what it does and for whom.

| Field | Value |
|---|---|
| Kind | agent / tool / hook / connector |
| Owner | `<team>` (on-call: `<rotation>`) |
| Version | `<x.y.z>` |
| Grant | `GOV-___`, approved by `<approver>`, expires `<date>` |

## Capabilities

**Provides**

| Capability | Input | Output |
|---|---|---|

**Requires** (called via `ctx.call`)

| Capability | Why |
|---|---|

## Authority

| Resource | Actions | Scope | Impact | Why |
|---|---|---|---|---|

Egress destinations:

| Destination | Purpose |
|---|---|

## Untrusted input

Which fields are attacker-controllable, and what the handler does about it. State the
declared `trust.output_class` and why.

## Local development

```bash
python3 -m runtime.cli.ext validate integrations/<name>
python3 -m runtime.cli.ext test integrations/<name> --input '{"action":"...","params":{}}'
```

## Failure behaviour

| Condition | Behaviour |
|---|---|

## Operations

- Dashboards / alerts:
- Expected `gate.denied` baseline:
- **Kill-switch triggers:** what should make on-call pull this extension
