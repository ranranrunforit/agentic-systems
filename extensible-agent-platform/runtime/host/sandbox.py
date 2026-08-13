"""Execution isolation (FR-2: local *and* remote extension execution).

Three runtimes, one protocol:

* `local-subprocess` — the default. Separate process, cleared environment,
  import blocker, read-only access to its own directory, no network. Production
  hardening (seccomp/netns/gVisor/Firecracker) slots in here without changing
  the protocol.
* `local-inproc` — a fast path reserved for **zero-permission, zero-egress**
  first-party extensions (typically hooks). The sandbox refuses to run anything
  else in-process, so the fast path cannot be abused into ambient authority.
* `remote-rpc` — the extension runs outside the host. The host talks to it
  through the same brokered channel over an attested worker; the remote worker
  gets a materialised copy of the extension's own files and nothing else, so it
  cannot see the host filesystem or another extension's state.

Every runtime returns the same `SandboxResult`, so the gate, broker and audit
layers do not know or care where the code ran.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .audit import AuditLog
from .contract import Extension
from .errors import SandboxError
from .taint import TaintSet, UNTRUSTED

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_runner.py")

EgressHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class SandboxResult:
    value: Any
    proposals: list[dict[str, Any]] = field(default_factory=list)
    taint: TaintSet = field(default_factory=TaintSet)
    logs: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    runtime: str = ""
    worker: str = ""


class Sandbox:
    def __init__(self, audit: AuditLog):
        self.audit = audit

    def execute(
        self,
        ext: Extension,
        payload: dict[str, Any],
        *,
        token_handle: str = "",
        on_egress: EgressHandler | None = None,
    ) -> SandboxResult:
        started = time.time()
        runtime = ext.runtime.type
        if runtime == "local-inproc":
            result = self._run_inproc(ext, payload)
        elif runtime == "local-subprocess":
            result = self._run_subprocess(ext, payload, token_handle, on_egress, ext.source_dir)
        elif runtime == "local-wasm":  # pragma: no cover - documented, not shipped
            raise SandboxError(
                "local-wasm runtime is specified in security/isolation.md but not bundled "
                "in this reference host; use local-subprocess"
            )
        elif runtime == "remote-rpc":
            result = self._run_remote(ext, payload, token_handle, on_egress)
        else:
            raise SandboxError(f"unknown runtime {runtime!r}")

        result.duration_ms = round((time.time() - started) * 1000, 2)
        result.runtime = runtime
        self.audit.record(
            "sandbox.executed",
            actor="sandbox",
            extension=ext.ref,
            runtime=runtime,
            worker=result.worker,
            duration_ms=result.duration_ms,
            proposals=len(result.proposals),
            taint=result.taint.label,
        )
        return result

    # -- runtimes ---------------------------------------------------------- #

    def _run_inproc(self, ext: Extension, payload: dict[str, Any]) -> SandboxResult:
        if ext.permissions or ext.egress_allow:
            raise SandboxError(
                f"{ext.ref}: local-inproc is only permitted for zero-permission, "
                "zero-egress extensions"
            )
        import importlib.util

        module_name, _, func_name = ext.runtime.entrypoint.partition(":")
        module_name = module_name[:-3] if module_name.endswith(".py") else module_name
        spec = importlib.util.spec_from_file_location(
            f"inproc_{ext.name}", os.path.join(ext.source_dir, f"{module_name}.py")
        )
        if spec is None or spec.loader is None:
            raise SandboxError(f"{ext.ref}: cannot load {ext.runtime.entrypoint}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        func = getattr(module, func_name or "handle")

        class _InprocCtx:
            def __init__(self) -> None:
                self.proposals: list[dict[str, Any]] = []
                self.logs: list[str] = []

            def propose(self, resource, action, params, rationale=""):
                self.proposals.append(
                    {
                        "resource": resource,
                        "action": action,
                        "params": params,
                        "rationale": rationale,
                    }
                )

            def log(self, message):
                self.logs.append(str(message)[:500])

            def http(self, *a, **kw):
                raise SandboxError("local-inproc extensions have no egress")

        ctx = _InprocCtx()
        try:
            value = func(ctx, payload)
        except SandboxError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SandboxError(f"{ext.ref} raised {type(exc).__name__}: {exc}") from exc
        return SandboxResult(
            value=value, proposals=ctx.proposals, logs=ctx.logs, worker="host-inproc"
        )

    def _run_subprocess(
        self,
        ext: Extension,
        payload: dict[str, Any],
        token_handle: str,
        on_egress: EgressHandler | None,
        workdir: str,
        worker: str = "local-worker",
    ) -> SandboxResult:
        cmd = [sys.executable, "-I", RUNNER, workdir, ext.runtime.entrypoint]
        env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C"}
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=workdir,
            text=True,
            bufsize=1,
        )
        deadline = time.time() + ext.runtime.timeout_ms / 1000.0
        logs: list[str] = []
        try:
            _write(proc, {"input": payload, "token": token_handle, "extension": ext.ref})
            while True:
                line = _read_line(proc, deadline)
                msg = json.loads(line)
                op = msg.get("op")
                if op in ("http", "call"):
                    if on_egress is None:
                        _write(proc, {"ok": False, "error": f"no {op} channel configured"})
                        continue
                    _write(proc, on_egress(msg))
                elif op == "log":
                    logs.append(msg.get("message", ""))
                elif op == "result":
                    taint_raw = msg.get("taint") or {}
                    return SandboxResult(
                        value=msg.get("value"),
                        proposals=msg.get("proposals") or [],
                        taint=TaintSet(
                            label=taint_raw.get("label", "trusted"),
                            sources=taint_raw.get("sources") or [],
                            signals=taint_raw.get("signals") or [],
                        ),
                        logs=logs,
                        worker=worker,
                    )
                elif op == "error":
                    raise SandboxError(
                        f"{ext.ref} failed in sandbox: {msg.get('type')}: {msg.get('message')}"
                    )
                else:
                    raise SandboxError(f"{ext.ref}: unknown sandbox op {op!r}")
        finally:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:  # pragma: no cover
                pass
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:  # pragma: no cover
                    pass

    def _run_remote(
        self,
        ext: Extension,
        payload: dict[str, Any],
        token_handle: str,
        on_egress: EgressHandler | None,
    ) -> SandboxResult:
        """Brokered RPC to an attested remote worker.

        Simulated by materialising *only* the extension's own files into a fresh
        workspace and running the same protocol there. The remote worker shares
        no filesystem with the host or with other extensions.
        """
        workspace = tempfile.mkdtemp(prefix=f"remote-{ext.name}-")
        worker_id = f"remote-worker-{os.path.basename(workspace)[-8:]}"
        try:
            for entry in os.listdir(ext.source_dir):
                src = os.path.join(ext.source_dir, entry)
                if os.path.isfile(src) and entry.endswith((".py", ".yaml", ".md", ".json")):
                    shutil.copy2(src, os.path.join(workspace, entry))
            self.audit.record(
                "sandbox.remote_dispatch",
                actor="sandbox",
                extension=ext.ref,
                worker=worker_id,
                endpoint=ext.runtime.endpoint,
                attestation="fixture-attested",
            )
            return self._run_subprocess(
                ext, payload, token_handle, on_egress, workspace, worker=worker_id
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


def _write(proc: subprocess.Popen, obj: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def _read_line(proc: subprocess.Popen, deadline: float) -> str:
    assert proc.stdout is not None
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise SandboxError("extension exceeded runtime.timeout_ms and was killed")
        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 0.25))
        if ready:
            line = proc.stdout.readline()
            if line:
                return line
            stderr = proc.stderr.read() if proc.stderr else ""
            raise SandboxError(f"extension exited without a result: {stderr.strip()[:400]}")
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr else ""
            raise SandboxError(f"extension exited ({proc.returncode}): {stderr.strip()[:400]}")
