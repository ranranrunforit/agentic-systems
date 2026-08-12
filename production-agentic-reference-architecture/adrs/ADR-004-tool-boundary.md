# ADR-004 — Typed tool contracts, validated at every boundary

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect

## Context

Tool arguments are model-authored, which makes every tool boundary an untrusted input
boundary — structurally identical to an HTTP handler taking a request body from the
internet. The domain needs at least four tools (`search`, `fetch`, `summarize`,
`export_report`), one of which is state-changing and externally visible. Two specific
risks follow: unvalidated arguments (an SSRF-shaped `fetch`, an unbounded
`max_results` that drains the budget), and **privilege forgery** — model output
populating a field that is supposed to represent human authorisation.

## Options considered

1. **Untyped dicts** with ad-hoc checks inside each tool.
2. **Types as documentation** — declare a schema for the model's benefit, trust the
   model's output at runtime.
3. **Typed contracts enforced at the boundary** — parse-don't-validate, reject unknown
   fields, enforce ranges, and structurally strip privileged fields from model-authored
   payloads.
4. **A tool framework's built-in validation** (e.g. framework-native function calling
   with automatic coercion).

## Decision

**Option 3.** Each tool declares an input contract; `Tool.invoke` parses the payload
*before* any side effect, and a parse failure returns a typed error rather than raising
into the orchestrator loop.

Four properties are non-negotiable:

1. **Unknown fields are rejected**, not ignored. Silent pass-through of a
   model-invented key is how privileged fields get set by accident.
2. **Constraints are enforced at parse time** — `max_results ∈ [1,20]`, `query` length
   bounds, `url` must be https and well-formed. `max_results` is a *cost* control as much
   as a correctness one.
3. **Two parse entry points.** `parse()` for host-authored payloads;
   `parse_model_authored()` for anything derived from model output, which **deletes every
   field listed in `MODEL_FORBIDDEN` before validating**. `ExportReportIn.confirmed_by`
   is in that list, so a model — or an injected source speaking through a model — cannot
   supply it. This is the structural half of the model→action break; the token check in
   the tool (ADR-009) is the other half.
4. **Allowlist checks live in the host, not the contract.** The contract enforces shape
   (https, well-formed); the host checks the value against curated long-term memory.
   Shape is static, policy is curated, and mixing them would put policy in a place where
   a code change could quietly widen it.

Rejections: **(1)** scatters validation and guarantees drift between tools. **(2)** is
the actual vulnerability — types that inform the model but do not gate execution are
documentation, not a control. **(4)** was rejected as a hard dependency on the framework
whose lock-in ADR-010 avoids; frameworks also tend to *coerce* (string "20" → 20), and
coercion at a trust boundary hides malformed input instead of surfacing it.

*Implementation note*: production intent is Pydantic v2 / JSON Schema. The spike ships a
stdlib-only equivalent with identical semantics so a reviewer can run it with no
installs; recorded as a scope cut in ADR-012.

## Consequences

**Positive**
- Every tool call has one place where invalid input is refused, and the refusal is a
  trace event (`tool.input_rejected` with the offending field).
- Privilege forgery is prevented structurally rather than by detection, so it does not
  depend on a pattern matcher recognising the attack.
- Contracts are the machine-readable interface for the model, so the tool description and
  the runtime check cannot disagree.

**Negative / accepted costs**
- Strict rejection means a slightly malformed model call fails instead of being repaired;
  the orchestrator must handle tool-level errors as a normal path (it does — worker
  degradation, ADR-011).
- Hand-rolled validators in the spike duplicate what a library would give; the
  duplication is the price of zero-install reviewability.
