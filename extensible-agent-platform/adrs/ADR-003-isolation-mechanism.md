# ADR-003 — Isolation: subprocess now, WASM/microVM path, remote via brokered RPC

**Status:** Accepted · **Date:** 2026-05-11 · **Deciders:** platform, security

## Context

Extensions are written by teams we do not manage and eventually by third parties. The
requirement is that a misbehaving extension cannot read another extension's secrets,
exceed its declared permissions, or compromise the host. We must support both local and
remote execution.

## Decision

Three shipped runtimes behind **one interface** —
`execute(ext, payload, token_handle, on_egress) -> SandboxResult`:

1. **`local-subprocess`** (default): separate process, cleared environment, import
   blocker for network/process/FFI modules, `open()` restricted to the extension's own
   directory and read-only, `site-packages` stripped, wall-clock timeout.
2. **`local-inproc`**: same process, permitted **only** for zero-permission, zero-egress
   extensions; the sandbox itself refuses anything else.
3. **`remote-rpc`**: off-host attested worker, a materialised copy of the extension's own
   files and nothing else, same brokered egress channel, output forced to `untrusted` by
   contract invariant C7.

`local-wasm` is specified and not bundled. The interface is deliberately narrow because
it is the only thing a second host has to reimplement ([ADR-002](ADR-002-alternative-platform.md)).

## Alternatives considered

**Trust extensions, review code.** Rejected: does not scale past first-party, and code
review does not survive the next version.

**Docker container per extension invocation.** Rejected for the reference: startup cost
per call, and Docker-in-anything is an operational tax. It remains the natural
production choice for the `remote-rpc` worker pool.

**WASM only.** The strongest isolation for untrusted code and the best answer for a
marketplace — but it narrows the language and library story enough to hurt adoption
today, and the toolchain work is significant. Deferred, not rejected; the runtime
interface is designed so it slots in without touching manifests.

**Python `RestrictedPython` / audit hooks only.** Rejected as a *boundary*: defeatable
from arbitrary Python. Kept as defence in depth, which is exactly what the import
blocker and `open()` guard are.

**gVisor / Firecracker per invocation.** The right production answer for hostile code;
too heavy for the reference host and unnecessary for first-party extensions. Named in
`security/isolation.md` as the migration target.

## Consequences

**Good.** Containment is demonstrable — `make containment` runs a rogue extension
through nine escapes and all nine fail. The interface is narrow enough that swapping to
gVisor changes one file and no manifest. `local-inproc` gives hooks a fast path that
*cannot* be abused into ambient authority, because the check is on the manifest.

**Bad, and stated in the docs.** In-process guards are not a real boundary against a
determined attacker with arbitrary Python (`builtins` surgery, C extensions). The
reference host therefore models the interface faithfully and implements what is portable;
production must add seccomp + netns at minimum. Anyone reading `make containment` as
proof of production-grade isolation has read it wrong, which is why `isolation.md` says
so twice.

**Also bad.** Blocking whole modules creates DX papercuts (`urllib.parse` needed a
carve-out). Papercuts here cause pressure to widen the sandbox, so the blocked set is
granular on purpose.

**Deferred:** capability attestation (signed bundles, digest pinning at approval). Until
it exists, the manifest is trusted because the repository is — which is the blocker on
third-party publishers. Tracked in [ADR-010](ADR-010-open-security-questions.md).
