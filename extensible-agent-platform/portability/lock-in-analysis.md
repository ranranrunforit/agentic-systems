# Lock-in analysis — what is portable, what is not, what we lose

Measured, not asserted: `make glue` produces the line counts, and
`runtime.tests.test_portability` proves the behavioural claims on a second host.

## The split

### Portable — plain data or host-agnostic logic

| Artifact | Lines | Why it moves unchanged |
|---|---|---|
| `extension.yaml` manifests (5 shipped) | — | Data. No host vocabulary except `runtime.type`. |
| `security/policy/abac-policy.yaml` | ~120 | Data. Attribute names are ours. |
| `governance/approved-grants.yaml` | ~90 | Data. |
| `contract.py` — parser + invariants | 348 | Pure logic over that data |
| `policy.py` — ABAC engine | 208 | Pure logic |
| `gate.py` — the six checks, confirmation ledger | 383 | Depends only on contract + policy + audit |
| `broker.py` — token lifecycle | 234 | Depends on a secret store interface |
| `registry.py` — governance state machine | 285 | Depends on contract + broker |
| `egress.py`, `audit.py`, `taint.py`, `secrets.py`, `errors.py` | ~400 | Interfaces, not implementations |
| `host.py` — orchestration, taint session, lifecycle | 513 | **Subclassed unchanged** by binding #2 |
| Extension handler code | ~450 | Uses only `ctx`; no host imports |

Roughly **2950 lines** of portable core plus every manifest, policy rule and grant.

### Host-specific — the runtime driver, and only that

| Artifact | Binding #1 | Binding #2 |
|---|---|---|
| Runtime driver (`execute(...) -> SandboxResult`) | `sandbox.py` 245 | `GraphNodeSandbox` ~110 |
| Child-process protocol / node context | `sandbox_runner.py` 205 | folded into the driver |
| Bootstrap + platform-idiom entry point | in `host.py` (shared) | ~45 |
| **Total host-specific** | **450 (13.2%)** | **155 (5.0%)** |

The second binding was smaller than the first because the interface had already been
found. That number is the honest measure of "bounded, documented glue".

### The grey zone

Not everything is cleanly one or the other, and pretending otherwise is where
portability claims usually go wrong:

| Item | Why it is grey |
|---|---|
| `runtime.type` values | `local-subprocess` / `remote-rpc` are our vocabulary. Binding #2 collapses all three into "node" — the manifest still loads, but it now means something weaker. |
| `ctx` surface | Portable as a *shape*; every host must implement `http`, `call`, `propose`, `log` with the same semantics, and semantics are not enforced by the schema. |
| Impact floors | Ours. A different host might classify actions differently; the floors live in `contract.py`, so they travel — but a hosted platform's own approval UI may not respect them. |
| Confirmation UX | The *binding* to `resource:action:target` is portable; the surface asking the human is not. |
| Audit sink | Format portable; retention, tamper-evidence and export are infrastructure. |

## What we lose by switching to LangGraph Platform

The part that matters most, stated plainly.

### 1. Isolation — the real cost

Our strongest security property is that a compromised extension is contained by the
*runtime we chose*: separate process, cleared environment, import blocker, filesystem
guard, and a path to seccomp/gVisor/WASM. On a graph platform, isolation is the
platform's, at the granularity the platform offers — typically the deployment, not the
individual node.

Consequence: **two extensions in one graph may share a process.** `TestIsolation`'s
containment guarantees weaken from "enforced" to "trusted". For first-party extensions
that is an acceptable trade; for third-party publishers it is disqualifying, which is
why the marketplace prerequisite is isolation-first.

### 2. Fidelity of the runtime declaration

`runtime.type` becomes advisory. An extension author who wrote `local-subprocess`
because they wanted process isolation gets a node instead and **cannot tell**. Mitigation
in [`migration-path.md`](migration-path.md): the binding must reject manifests whose
declared runtime it cannot honour, rather than silently downgrading them. Binding #2
accepts them today and reports `runtime=graph-node` in the audit log — visible, but
weaker than refusing.

### 3. Enforcement points we would hand over

| Property | Ours today | On a hosted platform |
|---|---|---|
| Egress allowlist | Enforced in-process by our proxy | Enforced by network policy we configure — different failure modes, generally fine |
| Credential injection | Our proxy; extension never sees a secret | Platform secret injection typically hands the value to the node — **a real regression** |
| Token TTL and intent binding | Ours, 15–30s, per action | Retained (broker is portable), but pointless if the node also holds the raw secret |
| Kill-switch immediacy | Our registry + broker, one call | Retained for routing; killing an in-flight deployment is the platform's semantics |

Item two is the sharpest: our NFR "secrets never reach extension code in plaintext" is
a property of *our egress proxy*. Preserving it on another host means keeping the proxy
and refusing the platform's convenient secret injection — extra work that a migrating
team will be tempted to skip.

### 4. What we gain, honestly

Durable execution (checkpointing, resume, time-travel debugging), a better
human-in-the-loop primitive (`interrupt`), managed autoscaling, and the removal of an
on-call burden. For a small team those may outweigh everything above.

## Lock-in by host

| Host | What binds you | Exit cost |
|---|---|---|
| Custom (this) | Nothing external; your own build and on-call | Low technically, high in sunk cost |
| LangGraph Platform | Graph runtime idioms, deployment model, trace tooling | Medium — rewrite the driver, re-establish isolation |
| Claude Code | Tool/hook/MCP shapes, session model, terminal-first UX | Medium — the extension *shapes* differ, the intent does not |
| Cursor | IDE coupling; users must be in the IDE | High — the delivery surface is the lock-in |
| Copilot | GitHub coupling; PR-as-gate | High for non-SDLC domains |

## The rule we would give another team

> Keep authority in data (`extension.yaml`, `abac-policy.yaml`, `approved-grants.yaml`)
> and keep exactly one host-specific interface (the runtime driver). Then a host change
> is a rewrite of one class and a re-argument about isolation — not a rewrite of the
> platform.

Two things are worth 155 lines of glue: never re-litigating who may do what, and being
able to say precisely which security property you gave up.
