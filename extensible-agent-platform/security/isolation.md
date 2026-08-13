# Execution isolation — local and remote

Implemented in [`../runtime/host/sandbox.py`](../runtime/host/sandbox.py) and
[`../runtime/host/sandbox_runner.py`](../runtime/host/sandbox_runner.py). Evidence:
`make containment` and `TestIsolation`.

## The requirement, restated

A misbehaving extension must not be able to (a) read another extension's secrets or
data, (b) exceed its declared permissions, or (c) compromise the host. Note what is
*not* required: that extensions be well-behaved. The design assumes at least one
extension is hostile at any time.

## Four runtimes, one interface

Every runtime implements `execute(ext, payload, token_handle, on_egress) -> SandboxResult`.
Because the interface is narrow, the runtime is the *only* thing a second host has to
replace ([`../portability/`](../portability/)).

| Runtime | Boundary | When it is allowed | Used by |
|---|---|---|---|
| `local-subprocess` | Separate process; cleared environment; import blocker; read-only access to its own directory; no sockets; wall-clock timeout | Default | agents, tools, most connectors |
| `local-inproc` | Same process — **only** for zero-permission, zero-egress extensions, refused otherwise by the sandbox itself | Hooks on the hot path | `pii-redaction-hook` |
| `remote-rpc` | Off-host attested worker; a materialised copy of the extension's own files and nothing else; same brokered channel | Third-party or heavy extensions | `knowledge-base` |
| `local-wasm` | WASM module, capability-based imports, no ambient syscalls | Specified below; not bundled | — |

The `local-inproc` restriction is the interesting one: a fast path that cannot be
abused into ambient authority, because the sandbox checks the manifest before running
it (`TestIsolation.test_inproc_runtime_refuses_privileged_extensions`).

## Local subprocess: what is actually enforced

Before extension code is imported, the runner:

1. **clears the environment** — `os.environ.clear()`. No inherited credentials, no
   config leakage, nothing to harvest.
2. **installs an import blocker** — `socket`, `ssl`, `http.client`, `urllib.request`,
   `requests`, `httpx`, `subprocess`, `multiprocessing`, `ctypes`, `mmap`, `pickle`,
   `shutil` and friends raise `ImportError`. Narrow carve-outs (`urllib.parse`) are
   explicit, because a DX papercut here is how you end up granting a wider sandbox.
3. **guards the filesystem** — `open()` is wrapped: writes are denied outright, reads
   are confined to the extension's own directory. Another extension's manifest,
   handler or state is unreachable.
4. **strips `site-packages` from `sys.path`** — an extension gets the standard library
   and its own files.
5. **enforces a timeout** — `runtime.timeout_ms`; the process is killed on expiry.

Communication is a line-oriented JSON protocol on stdin/stdout. There is no other
channel, which is what makes `ctx` the complete capability surface.

### Containment evidence

`make containment` loads a red-team fixture that tries nine escapes:

| Attempt | Result |
|---|---|
| `import socket` | `ImportError: sandbox: import of 'socket' is blocked` |
| `import subprocess` | blocked |
| read `runtime/host/secrets.py` | `PermissionError` — outside its own directory |
| read another extension's manifest | `PermissionError` |
| write `/tmp/rogue-was-here` | `PermissionError` — writes denied |
| harvest `*TOKEN*` / `*SECRET*` from the environment | `none: environment was cleared` |
| `ctx.call("issue_tracker.close", …)` | denied: capability not in `requires`, and no grant |
| `ctx.http` to an allowlisted host without a permission | denied at the gate |
| `ctx.http` to `attacker.example` | denied by the egress proxy allowlist |

## Honest limits of the reference sandbox

**In-process guards are defence in depth, not the boundary.** A determined attacker
with arbitrary Python can defeat an import hook — `builtins`, `sys.modules` surgery,
C extensions. The production boundary is the operating system:

| Layer | Production mechanism |
|---|---|
| Process | seccomp-bpf syscall filter, `no_new_privs`, non-root uid, read-only rootfs |
| Network | Dedicated netns with no default route; the egress proxy is the only reachable socket |
| Filesystem | Per-invocation `tmpfs` overlay; the extension bundle mounted read-only |
| Resources | cgroups v2 memory/CPU/pids limits; wall-clock kill |
| Stronger | gVisor or Firecracker microVM per invocation (third-party extensions) |
| Alternative | WASM (wasmtime) with capability-based imports — the strongest option for untrusted code, at the cost of a narrower language/library story |

The reference host models the *interface* to these mechanisms faithfully and
implements what is portable in pure Python. Migrating to gVisor changes
`sandbox.py`; it changes no manifest, no policy rule and no test outside
`TestIsolation`.

## Remote execution isolation

`remote-rpc` extensions run on a worker pool the host reaches over a brokered channel.
Properties the host enforces (see `_run_remote`):

- **No shared filesystem.** Only the extension's own files are materialised into a
  fresh workspace, which is destroyed afterwards.
- **No shared state between extensions.** One workspace and one worker identity per
  invocation; the audit log records the worker id and an attestation claim.
- **Same brokered egress.** The remote worker cannot reach upstream systems directly;
  `ctx.http` still round-trips to the host proxy, so allowlists, credential injection
  and taint labelling apply identically.
- **Output is untrusted by contract.** C7 forces `output_class: untrusted` for
  `remote-rpc`, so nothing the worker returns is treated as instructions.

Production hardening for the remote path: mTLS between host and worker pool, workload
identity (SPIFFE) rather than a shared secret, hardware-attested workers for
third-party code, and per-tenant worker pools where data residency demands it.

## Capability attestation (specified, not implemented)

The gap: `extension.yaml` is trusted because the repository is trusted. For a
third-party marketplace that is insufficient. The specified design:

1. Publisher signs the extension bundle (manifest + code) with a key registered
   during onboarding — Sigstore/cosign keyless, or an org PKI.
2. The registry stores `(bundle digest, signature, publisher, approved permission set)`
   at approval time.
3. The loader verifies the signature **and** that the manifest digest matches the one
   the reviewer approved before registering any capability. Content and permissions are
   both attested; editing the manifest post-approval invalidates the signature.
4. Revocation is a transparency-log entry the loader checks, so a pulled publisher key
   fails closed.

Tracked in [ADR-003](../adrs/ADR-003-isolation-mechanism.md) and ADR-010.

## Failure modes and what happens

| Failure | Host behaviour |
|---|---|
| Extension crashes | `SandboxError`, audited, caller gets a clean error; no partial privileged action |
| Extension hangs | Killed at `timeout_ms`; tokens expire on their own |
| Extension floods egress | Each call is gated and audited independently; rate limits belong here (not implemented — ADR-010) |
| Extension returns garbage | Caller sees it as data; nothing privileged followed from it |
| Sandbox itself fails to start | Fails closed: no execution, no token minted |
