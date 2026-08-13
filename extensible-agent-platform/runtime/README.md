# `runtime/` — the reference host

One binding of the `ext/v1` contract. Named after nothing in particular on purpose:
[`../portability/bindings/graph_host_binding.py`](../portability/bindings/graph_host_binding.py)
is a second, and the two share everything except the runtime driver.

```
runtime/
├── host/                the trusted core
│   ├── contract.py      ext/v1 parser + the 8 contract invariants   (authoritative schema)
│   ├── registry.py      load / approve / version / revoke — the governance state machine
│   ├── gate.py          the authorization gate: six checks + confirmation ledger
│   ├── policy.py        ABAC engine: default-deny, deny-overrides
│   ├── broker.py        token lifecycle: mint / scope / rotate / revoke
│   ├── secrets.py       host-only credential store (fixture values)
│   ├── egress.py        the only way out: allowlist + credential injection + taint labels
│   ├── sandbox.py       runtime drivers: subprocess / inproc / remote-rpc
│   ├── sandbox_runner.py  child-process entrypoint: env clearing, import blocker, FS guard
│   ├── taint.py         provenance labels + injection heuristics
│   ├── audit.py         hash-chained audit log
│   ├── host.py          orchestration: invoke / perform / run_agent / kill
│   └── yamlio.py        PyYAML when present, bundled fallback parser when not
├── backends/            simulated external SaaS (issue tracker, KB, CI/CD)
├── cli/ext.py           the developer CLI
├── tests/               63 tests mapped to the acceptance criteria
└── demos/               five runnable proofs
```

## Reading order for the code

1. `contract.py` — what an extension may declare, and the invariants
2. `gate.py` — the six checks; this is where the design lives
3. `host.py` — `_channel_handler`, the extension's entire outward surface
4. `broker.py` + `egress.py` — why extension code never holds a credential
5. `sandbox_runner.py` — what the sandbox actually enforces, and what it does not

## Entry points

```python
from runtime.host import Host, ScriptedConfirmation

host = Host.bootstrap()                      # loads policy, grants, and integrations/

host.invoke("classify-ticket", {...})        # run a tool/agent; proposals come back unexecuted
host.run_agent("triage-agent", {...})        # invoke, then gate each proposal
host.perform("issue_tracker", "close", {...}) # one privileged action through the gate
host.kill("knowledge-base", reason="…", actor="security-oncall")
host.rotate("secrets/issue-tracker/oauth-client", new_value)
host.describe()                              # inspectable state + audit chain validity
```

## Notes for anyone extending the host

- **The gate is the only place authorization decisions are made.** If you find yourself
  adding an `if` that permits something, it belongs in `abac-policy.yaml` or in the six
  checks — not in a call site.
- **Taint is host-owned.** `_Session` accumulates provenance; an extension's self-report is
  advisory. Never trust a child's taint claim.
- **New runtimes implement one method.** `execute(ext, payload, token_handle, on_egress)
  -> SandboxResult`. Keeping that interface narrow is what makes the platform portable.
- **Every new audit event needs an actor.** `NFR-4` is only true if it stays true.
