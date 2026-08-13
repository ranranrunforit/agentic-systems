# Portability and lock-in

The constraint on this project is platform neutrality: Claude Code, Cursor, Copilot,
LangGraph Platform and a fully custom host are **peers**. This directory is where that
claim is either earned or exposed.

| Document | Covers |
|---|---|
| [`platform-comparison.md`](platform-comparison.md) | The five hosts as peers, on the dimensions that actually differ |
| [`lock-in-analysis.md`](lock-in-analysis.md) | Portable vs. host-specific, with line counts, and **what we lose by switching** |
| [`migration-path.md`](migration-path.md) | A concrete, ordered migration to LangGraph Platform |
| [`bindings/graph_host_binding.py`](bindings/graph_host_binding.py) | **A working second host binding** (stretch goal) |
| [`bindings/measure_glue.py`](bindings/measure_glue.py) | Measures host-specific vs. portable lines |

## The claim, and the evidence

> The contract, the policy, the grants, the gate and the audit format are portable.
> The runtime driver is host-specific and bounded.

Evidence, not assertion:

```bash
make portability     # same manifests + same policy, two hosts, identical decisions
make glue            # the measurement below
python3 -m unittest runtime.tests.test_portability -v
```

```
portable (core + extensions)       2954 lines
binding #1 (subprocess host)        450 lines   (13.2% of that host's total)
binding #2 (graph-platform host)    155 lines   ( 5.0% of that host's total)
```

Binding #2 re-implements exactly one interface —
`execute(ext, payload, token_handle, on_egress) -> SandboxResult` — plus bootstrap
wiring and one entry point in the platform's idiom. Every manifest, every policy rule,
every grant, and the whole gate/broker/audit path is shared code.

`runtime.tests.test_portability` asserts that both hosts reach **identical gate
decisions** on the same input, including the injection case, and that the kill-switch
and confirmation gate behave the same on both.

## Chosen alternative peer: LangGraph Platform

Named in [ADR-002](../adrs/ADR-002-alternative-platform.md). Chosen as the primary peer
because it is the closest genuine competitor to a custom host for *this* domain: a
non-developer internal workflow with orchestration, tool calls and human-in-the-loop
approval. Claude Code, Cursor and Copilot are compared on the same dimensions and are
not dismissed — for an SDLC instantiation of this platform, Claude Code would be the
strongest peer, and the comparison says so.

## The honest headline

Portability here is a **property of the contract, not a promise of zero cost.** What
survives a host change is everything a reviewer, an auditor or a security engineer
cares about. What does not survive is the isolation guarantee — and that is the most
security-relevant thing in the system. [`lock-in-analysis.md`](lock-in-analysis.md)
names it rather than burying it.
