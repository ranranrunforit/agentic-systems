# Migration path — custom host → LangGraph Platform

Concrete and ordered. The exercise has been done in miniature: see
[`bindings/graph_host_binding.py`](bindings/graph_host_binding.py), which is a working
second binding, and `runtime.tests.test_portability`, which proves both hosts reach the
same decisions.

Estimate for a real migration: **3–4 engineer-weeks**, dominated by step 3 (isolation)
and step 7 (verification), not by code volume.

## Phase 0 — decide, and write down what you are giving up

Before any code: re-read [`lock-in-analysis.md`](lock-in-analysis.md) §"What we lose"
and get explicit sign-off that per-invocation isolation weakens and that the egress
proxy must be preserved rather than replaced by platform secret injection. A migration
that skips this step silently regresses the platform's central NFR.

Deliverable: an ADR recording the decision and the accepted regressions.

## Phase 1 — inventory (½ day)

```bash
make glue    # what is portable vs. host-specific, with line counts
```

Moves unchanged: every `extension.yaml`, `abac-policy.yaml`, `approved-grants.yaml`,
`contract.py`, `policy.py`, `gate.py`, `broker.py`, `registry.py`, `audit.py`,
`taint.py`, `egress.py`, `secrets.py`, `host.py`, and all handler code.

Must be rewritten: the runtime driver (`sandbox.py`, `sandbox_runner.py`) — 450 lines.

## Phase 2 — implement the runtime driver (3–5 days)

One interface:

```python
class GraphNodeRuntime:
    def execute(self, ext, payload, *, token_handle="", on_egress=None) -> SandboxResult:
        ...
```

Requirements, in priority order:

1. Build a node context exposing exactly `ctx.http`, `ctx.call`, `ctx.propose`,
   `ctx.log` — no more, no less. Extra affordances are how ambient authority returns.
2. Route `http` and `call` back through `on_egress` (the host's channel handler), so the
   gate, broker and taint tracking remain the host's.
3. Return `SandboxResult(value, proposals, taint, logs, runtime, worker)`.
4. **Refuse manifests whose declared `runtime.type` you cannot honour.** Binding #2
   currently accepts and downgrades them; a production migration should fail closed,
   and the manifest should gain an explicit `runtime.type: graph-node` rather than
   pretending `local-subprocess` was satisfied.

Reference: `GraphNodeSandbox` in the binding, ~110 lines.

## Phase 3 — re-establish isolation (5–8 days, the hard part)

The platform will not give per-invocation process isolation for free. Options, best
first:

| Approach | Isolation | Cost |
|---|---|---|
| One deployment per extension; nodes call each other over the network | Strong — process and network boundary per extension | Highest; N deployments to operate |
| Compile extensions to WASM and run them inside the node | Strong, host-independent — and it makes the *next* migration cheap | High up-front, best long-term |
| Group extensions by trust tier into deployments | Partial — cross-tier containment only | Medium |
| Single deployment, all nodes in-process | None between extensions | Lowest; acceptable only for first-party |

Whatever you choose, re-run `make containment` against it and record which of the nine
escapes still fail. Any that now succeed goes in the ADR from Phase 0.

## Phase 4 — credentials and egress (2–3 days)

**Keep the egress proxy.** The temptation is to use the platform's secret injection,
which hands the credential to the node — that is the regression named in the lock-in
analysis. Concretely:

- deploy the egress proxy as a sidecar or an internal service;
- network policy: nodes may reach the proxy and nothing else outbound;
- the broker stays as-is (it is portable); handles still bind to extension, action and
  intent hash;
- the platform's secret store replaces our `SecretStore` implementation behind the same
  interface — one adapter, not a redesign.

## Phase 5 — human-in-the-loop (1–2 days, and an upgrade)

Replace `ConfirmationProvider` with the platform's `interrupt`/checkpoint mechanism.
This is the one place migration makes the system *better*: an interrupt survives a
process restart, where our in-memory confirmation ledger does not.

Non-negotiable: the confirmation must stay bound to `(tenant, resource, action, target)`
so it cannot be replayed onto a different effect. Port
`TestInjection.test_confirmation_cannot_be_reused_for_another_target` first and make it
pass before wiring anything else.

## Phase 6 — audit (1 day)

Platform traces are for debugging, not for security audit. Keep the hash-chained audit
log and ship it to the same sink as before. Traces are additive.

## Phase 7 — verify (3–4 days)

The migration is done when this passes on the new host:

```bash
python3 -m unittest runtime.tests.test_platform runtime.tests.test_portability -v
make containment       # record every escape that now succeeds
make injection         # must still contain: ticket open, no comment, nothing closed
make governance        # diff refusal, re-approval, kill-switch, rotation
```

Plus a shadow-run period: both hosts on the same traffic, comparing gate decisions,
until they agree for a week.

## Phase 8 — cut over (2 days)

Extension-by-extension, lowest authority first: tools, then read-only connectors, then
agents, then the write-capable connector. Keep the old host loadable for one full
deprecation window. Roll back by pointing traffic back — the manifests and grants are
identical on both sides, which is the point of the whole design.

## Reverse migration

Coming *back* is cheaper: the runtime driver already exists in the repository, and no
manifest, policy rule or grant changed while you were away. That asymmetry is the
practical value of keeping a second binding alive in the tree rather than as a
design document.
