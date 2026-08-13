"""Second host binding — a graph-platform host (stretch goal / FR-6 evidence).

This is the same `ext/v1` contract, the same `abac-policy.yaml`, the same grants
file and the same audit format driven by a *different* host: one shaped like
LangGraph Platform, where units of work are **graph nodes** invoked by a runtime
that owns process/container isolation itself, rather than sandboxed subprocesses
started by our loader.

The point of the exercise is to find out, empirically, what had to be rewritten.
The answer is one class:

  * `GraphNodeSandbox` — the runtime driver. It satisfies the same interface the
    subprocess sandbox does (`execute(ext, payload, token_handle, on_egress)
    -> SandboxResult`) and builds the node context that gives handler code
    `ctx.http`, `ctx.call`, `ctx.propose` and `ctx.log`.
  * `GraphHost` — five lines of wiring that swap the driver in, plus a
    `run_graph` entry point in the platform's idiom.

Everything else — contract parsing, the registry and governance state machine,
the ABAC engine, the gate and its confirmation ledger, the token broker, the
egress proxy, the audit chain — is imported unchanged from `runtime/host`.

Run `python3 -m portability.bindings.measure_glue` for the line counts, and
`python3 -m unittest runtime.tests.test_portability` for the proof that both
hosts reach the same decisions on the same manifests.

Honest caveats (see portability/lock-in-analysis.md):
  * isolation here is *weaker* than the subprocess binding: the node runs
    in-process, so `network: deny` is enforced by convention plus the platform's
    container boundary, not by our import blocker. On a real graph platform you
    inherit their sandbox and give up ours.
  * `runtime.type` values are host-specific vocabulary. This binding treats
    `local-subprocess`, `local-inproc` and `remote-rpc` all as "node", which is a
    real fidelity loss: an extension that *relies* on process isolation cannot
    tell that it no longer has it. Mitigation is in the migration checklist.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from runtime.host.audit import AuditLog  # noqa: E402
from runtime.host.contract import Extension  # noqa: E402
from runtime.host.errors import SandboxError  # noqa: E402
from runtime.host.gate import ConfirmationProvider  # noqa: E402
from runtime.host.host import DEFAULT_GRANTS, DEFAULT_INTEGRATIONS, DEFAULT_POLICY, Host  # noqa: E402
from runtime.host.policy import PolicyEngine  # noqa: E402
from runtime.host.sandbox import SandboxResult  # noqa: E402
from runtime.host.taint import TaintSet  # noqa: E402

# ---------------------------------------------------------------- GLUE BEGIN #


@dataclass
class _NodeCtx:
    """The node-scoped capability surface. Mirrors the sandbox `ctx` exactly."""

    channel: Callable[[dict[str, Any]], dict[str, Any]]
    proposals: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    taint: TaintSet = field(default_factory=TaintSet)

    def http(self, method: str, url: str, body=None, *, resource: str, action: str):
        reply = self.channel(
            {
                "op": "http",
                "method": method,
                "url": url,
                "body": body or {},
                "resource": resource,
                "action": action,
            }
        )
        if not reply.get("ok"):
            raise RuntimeError(f"egress denied: {reply.get('error')}")
        self._absorb(reply.get("taint"))
        return reply.get("status"), reply.get("body")

    def call(self, capability: str, params: dict):
        reply = self.channel({"op": "call", "capability": capability, "params": params})
        if not reply.get("ok"):
            raise RuntimeError(f"call denied: {reply.get('error')}")
        self._absorb(reply.get("taint"))
        return reply.get("value")

    def propose(self, resource: str, action: str, params: dict, rationale: str = ""):
        self.proposals.append(
            {"resource": resource, "action": action, "params": params, "rationale": rationale}
        )

    def log(self, message: str):
        self.logs.append(str(message)[:500])

    def _absorb(self, taint: dict | None):
        if taint and taint.get("label") == "untrusted":
            self.taint = self.taint.merge(
                TaintSet(label="untrusted", sources=taint.get("sources") or [],
                         signals=taint.get("signals") or [])
            )


class GraphNodeSandbox:
    """Runtime driver for a graph host: every extension is a node function."""

    def __init__(self, audit: AuditLog):
        self.audit = audit
        self._nodes: dict[str, Callable] = {}

    def execute(self, ext: Extension, payload: dict[str, Any], *, token_handle: str = "",
                on_egress=None) -> SandboxResult:
        node = self._nodes.get(ext.ref) or self._compile_node(ext)
        ctx = _NodeCtx(channel=on_egress or (lambda msg: {"ok": False, "error": "no channel"}))
        try:
            value = node(ctx, payload)
        except Exception as exc:  # noqa: BLE001
            raise SandboxError(f"{ext.ref} raised {type(exc).__name__}: {exc}") from exc
        self.audit.record(
            "sandbox.executed", actor="graph-runtime", extension=ext.ref,
            runtime="graph-node", worker="graph-worker", duration_ms=0.0,
            proposals=len(ctx.proposals), taint=ctx.taint.label,
        )
        return SandboxResult(value=value, proposals=ctx.proposals, taint=ctx.taint,
                             logs=ctx.logs, runtime="graph-node", worker="graph-worker")

    def _compile_node(self, ext: Extension) -> Callable:
        import importlib.util

        module_name, _, func_name = ext.runtime.entrypoint.partition(":")
        module_name = module_name[:-3] if module_name.endswith(".py") else module_name
        spec = importlib.util.spec_from_file_location(
            f"node_{ext.name}", os.path.join(ext.source_dir, f"{module_name}.py")
        )
        if spec is None or spec.loader is None:
            raise SandboxError(f"{ext.ref}: cannot compile node from {ext.runtime.entrypoint}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        node = getattr(module, func_name or "handle")
        self._nodes[ext.ref] = node
        return node


class GraphHost(Host):
    """Host binding #2. The only difference from `runtime.host.Host` is the driver."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sandbox = GraphNodeSandbox(self.audit)

    @classmethod
    def bootstrap(cls, *, policy_path: str = DEFAULT_POLICY, grants_path: str = DEFAULT_GRANTS,
                  integrations_dir: str | None = DEFAULT_INTEGRATIONS,
                  confirmation: ConfirmationProvider | None = None,
                  audit_path: str | None = None) -> "GraphHost":
        host = cls(policy=PolicyEngine.from_file(policy_path), audit=AuditLog(path=audit_path),
                   confirmation=confirmation)
        host.audit.record("host.boot", actor="graph-host", policy_version=host.policy.version,
                          binding="graph-platform")
        if grants_path and os.path.exists(grants_path):
            host.registry.load_grants(grants_path)
        if integrations_dir:
            host.load_all(integrations_dir)
        return host

    def run_graph(self, entry_node: str, state: dict[str, Any], *, actor: str = "operator",
                  tenant: str = "acme") -> dict[str, Any]:
        """The platform's idiom: run a node against a state dict, return new state."""
        result = self.run_agent(entry_node, state, actor=actor, tenant=tenant)
        return {
            **state,
            "output": result.value,
            "taint": result.taint.label,
            "executed": [o.to_dict() for o in result.executed()],
            "blocked": [o.to_dict() for o in result.blocked()],
        }


# ------------------------------------------------------------------ GLUE END #


if __name__ == "__main__":
    import json

    host = GraphHost.bootstrap()
    print(host.registry.render())
    print()
    print(json.dumps(host.run_graph("triage-agent", {"ticket_id": "T-1043"}), indent=2)[:2000])
