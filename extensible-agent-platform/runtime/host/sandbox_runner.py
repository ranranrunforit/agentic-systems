"""Child process entrypoint for the local sandbox.

Executed as: python3 -I sandbox_runner.py <ext_dir> <module:function>

The runner is host code, not extension code. Before it imports anything from the
extension it:

  * clears the environment (no ambient credentials, no shared config);
  * installs an import blocker for network / process / FFI modules, so the only
    way out of the sandbox is the brokered `ctx.http` channel;
  * restricts `open()` to read-only access inside the extension's own directory,
    so one extension cannot read another's files;
  * denies `eval`-style dynamic loading of blocked modules via `__import__`.

These in-process restrictions are **defence in depth for a reference host**. The
production boundary is an OS/VM sandbox (gVisor, Firecracker, seccomp+netns) or
a WASM runtime — see security/isolation.md and ADR-003. The protocol below is
identical in both cases, which is what makes the runtime swappable.

Wire protocol (newline-delimited JSON on stdin/stdout):

  host -> child : {"input": {...}, "token": "tkn_...", "extension": "name@1.0.0"}
  child -> host : {"op": "http", "method": "GET", "url": "...", "body": {...},
                   "resource": "issue_tracker", "action": "read"}
  host -> child : {"ok": true, "status": 200, "body": {...}, "taint": {...}}
  child -> host : {"op": "call", "capability": "knowledge_base.search", "params": {...}}
  host -> child : {"ok": true, "value": {...}, "taint": {...}}
  child -> host : {"op": "log", "message": "..."}
  child -> host : {"op": "result", "value": {...}, "proposals": [...]}
  child -> host : {"op": "error", "message": "...", "type": "..."}
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import sys
import traceback

BLOCKED_MODULES = {
    "socket",
    "ssl",
    "http.client",
    "http.server",
    "urllib.request",
    "urllib.error",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "telnetlib",
    "subprocess",
    "multiprocessing",
    "ctypes",
    "cffi",
    "pty",
    "fcntl",
    "mmap",
    "resource",
    "webbrowser",
    "pickle",
    "shutil",
}


# Narrow carve-outs: pure string/parsing helpers with no I/O surface. The blocked
# set is granular for the same reason — extension authors need `urllib.parse.quote`
# far more often than they need `urllib.request.urlopen`, and a DX papercut here
# is how you end up with people asking for a wider sandbox.
ALLOWED_SUBMODULES = {"urllib", "urllib.parse", "http", "http.cookies"}


class _ImportBlocker:
    """A meta-path finder that refuses blocked modules."""

    def find_module(self, fullname, path=None):  # legacy API, harmless
        return self.find_spec(fullname, path)

    def find_spec(self, fullname, path=None, target=None):
        if fullname in ALLOWED_SUBMODULES:
            return None
        root = fullname.split(".")[0]
        if fullname in BLOCKED_MODULES or root in BLOCKED_MODULES:
            raise ImportError(
                f"sandbox: import of {fullname!r} is blocked; use ctx.http() for egress"
            )
        return None


def _install_fs_guard(ext_dir: str):
    real_open = builtins.open
    ext_dir = os.path.realpath(ext_dir)

    def guarded_open(file, mode="r", *args, **kwargs):
        path = os.path.realpath(str(file))
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise PermissionError("sandbox: filesystem writes are denied")
        if not path.startswith(ext_dir + os.sep) and path != ext_dir:
            raise PermissionError(
                f"sandbox: read of {path!r} denied; extensions may only read their own directory"
            )
        return real_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open


class Ctx:
    """The only capability surface extension code gets."""

    def __init__(self, extension: str, token: str):
        self.extension = extension
        self._token = token  # opaque handle, not a credential
        self.proposals: list[dict] = []
        self.tainted = False
        self.taint_sources: list[str] = []
        self.taint_signals: list[str] = []

    # -- brokered egress --------------------------------------------------- #

    def http(self, method: str, url: str, body=None, *, resource: str, action: str):
        _send({
            "op": "http",
            "method": method,
            "url": url,
            "body": body or {},
            "resource": resource,
            "action": action,
        })
        reply = _recv()
        if not reply.get("ok"):
            raise RuntimeError(f"egress denied: {reply.get('error')}")
        taint = reply.get("taint") or {}
        if taint.get("label") == "untrusted":
            self.tainted = True
            for source in taint.get("sources", []):
                if source not in self.taint_sources:
                    self.taint_sources.append(source)
            for signal in taint.get("signals", []):
                if signal not in self.taint_signals:
                    self.taint_signals.append(signal)
        return reply.get("status"), reply.get("body")

    # -- host-brokered calls to other extensions --------------------------- #

    def call(self, capability: str, params: dict):
        """Invoke another extension's declared capability *through the host*.

        Extensions never import or address each other. The host resolves the
        capability, applies both parties' grants at the gate, and returns the
        result. Anything that comes back is treated as untrusted data.
        """
        _send({"op": "call", "capability": capability, "params": params})
        reply = _recv()
        if not reply.get("ok"):
            raise RuntimeError(f"call denied: {reply.get('error')}")
        taint = reply.get("taint") or {}
        if taint.get("label") == "untrusted":
            self.tainted = True
            for source in taint.get("sources", []):
                if source not in self.taint_sources:
                    self.taint_sources.append(source)
            for signal in taint.get("signals", []):
                if signal not in self.taint_signals:
                    self.taint_signals.append(signal)
        return reply.get("value")

    # -- proposing privileged actions -------------------------------------- #

    def propose(self, resource: str, action: str, params: dict, rationale: str = ""):
        """Ask the host to consider a privileged action. NEVER executes here.

        This is the trust boundary in code: extension/model output can only
        *propose*. Execution happens on the host side of the gate.
        """
        self.proposals.append(
            {
                "resource": resource,
                "action": action,
                "params": params,
                "rationale": rationale,
            }
        )

    def log(self, message: str):
        _send({"op": "log", "message": str(message)[:500]})


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _recv() -> dict:
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("sandbox: host closed the channel")
    return json.loads(line)


def main() -> int:
    ext_dir, entrypoint = sys.argv[1], sys.argv[2]
    module_name, _, func_name = entrypoint.partition(":")
    module_name = module_name[:-3] if module_name.endswith(".py") else module_name

    os.environ.clear()  # no ambient authority
    sys.meta_path.insert(0, _ImportBlocker())
    sys.path[:] = [p for p in sys.path if p and "site-packages" not in p]
    sys.path.insert(0, ext_dir)

    bootstrap = _recv()
    ctx = Ctx(bootstrap.get("extension", "?"), bootstrap.get("token", ""))

    try:
        spec = importlib.util.spec_from_file_location(
            f"ext_{module_name}", os.path.join(ext_dir, f"{module_name}.py")
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load entrypoint {entrypoint!r} from {ext_dir}")
        module = importlib.util.module_from_spec(spec)
        _install_fs_guard(ext_dir)
        spec.loader.exec_module(module)
        func = getattr(module, func_name or "handle")
        value = func(ctx, bootstrap.get("input") or {})
    except BaseException as exc:  # noqa: BLE001 - report everything to the host
        _send(
            {
                "op": "error",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=4),
            }
        )
        return 1

    _send(
        {
            "op": "result",
            "value": value,
            "proposals": ctx.proposals,
            "taint": {
                "label": "untrusted" if ctx.tainted else "trusted",
                "sources": ctx.taint_sources,
                "signals": ctx.taint_signals,
            },
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
