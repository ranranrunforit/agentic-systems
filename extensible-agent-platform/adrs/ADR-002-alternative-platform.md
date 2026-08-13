# ADR-002 — Alternative platform evaluated as a peer: LangGraph Platform

**Status:** Accepted · **Date:** 2026-05-06 · **Deciders:** platform architecture, engineering leadership

## Context

Leadership is wary of betting the platform on one vendor's host. "We will just use X"
is not an architecture; the reasoning for X over its peers, and the lock-in cost of
that choice, is the work. Claude Code, Cursor, Copilot, LangGraph Platform and a fully
custom host must be treated as peers.

The brief requires at least one named alternative evaluated genuinely — not a straw man.

## Decision

Build against a **generic host/extension contract**, implement it first on a **custom
host**, and evaluate **LangGraph Platform** as the primary named peer. Claude Code,
Cursor and Copilot are compared on the same dimensions in
[`../portability/platform-comparison.md`](../portability/platform-comparison.md).

To keep the comparison honest, a **working second binding** ships in the repository:
`portability/bindings/graph_host_binding.py` runs the same manifests, the same ABAC
policy and the same grants on a graph-platform-shaped host, and
`runtime/tests/test_portability.py` asserts both hosts reach identical gate decisions.

## Why LangGraph Platform is the primary peer

It is the closest genuine competitor for *this* domain: orchestration over tool calls
with human-in-the-loop approval, delivered through an API rather than an IDE. Its
`interrupt`/checkpoint primitive is a **better** human-in-the-loop mechanism than our
confirmation provider (it survives restarts), and its managed runtime removes the
operational burden that is this design's biggest weakness. Choosing a peer whose
strengths are real is the point.

## Alternatives considered as peers

**Claude Code.** The strongest peer overall, and for an SDLC worked domain it wins:
native repository context, and a mature tools/hooks/subagents/MCP extension model that
is closer to this design than anything we would write in a quarter. Not chosen as the
primary peer *here* because the worked domain's users never open a terminal — a domain
fit issue, not a capability judgement. If the domain changes, so does the
recommendation, and the comparison document says so.

**Cursor.** Best-in-class inner loop for a developer in an editor; structurally wrong
for a support workflow. High lock-in because the delivery surface *is* the product.

**GitHub Copilot.** Strong organisational reach and PR-as-approval-gate, which is a
genuinely good free confirmation mechanism when the workflow's artifact is a pull
request. Ours is a ticket, so we get nothing from it.

**Custom host (chosen for the first implementation).** The only option where we define
the security contract. Default-deny declared permissions, credentials that never enter
extension code, host-tracked taint, and a kill-switch that revokes tokens are
properties *of the host*; they cannot be bolted on from outside. Cost: we build and
operate everything, which is real and is stated as the main downside.

## Consequences

**Good.** The neutrality claim is testable rather than rhetorical: two bindings, one
contract, measured glue (`make glue`: 155 lines host-specific on binding #2, 5% of that
host's total). Migration is specified concretely, and the reverse migration is cheap
because the first binding stays in the tree.

**Bad.** Maintaining two bindings costs something on every host-layer change. The
comparison table will age — vendor capabilities move faster than this document, so the
*dimensions* are the durable artifact, not the cells. And we accept the operational
burden of a custom host in exchange for control we could have partly rented.

**Explicitly accepted.** For an SDLC instantiation the recommendation flips to Claude
Code. Writing that down is the difference between neutrality and a preference wearing
a comparison table.
