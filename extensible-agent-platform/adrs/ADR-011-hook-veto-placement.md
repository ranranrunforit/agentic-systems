# ADR-011 — Hooks run host-side, before the gate, with veto authority

**Status:** Accepted · **Date:** 2026-06-02 · **Deciders:** platform, privacy engineering

## Context

Some rules must apply to every privileged action regardless of which extension proposes
it: redact customer PII from outbound text; never let credential-shaped strings leave the
host. Where does that logic live?

Three candidate homes: in each extension (unenforceable), in the host (correct but
inflexible), or in a new extension type.

## Decision

A **hook** extension type. Hooks subscribe to host lifecycle events (`pre_action`,
`post_action`, `pre_egress`, `post_egress`), run **on the host side of the gate**, and may
**rewrite parameters or veto the action outright**.

Order of operations for any privileged action:

```
proposal → pre_action hooks → gate (6 checks) → broker → sandbox → audit
```

Hooks are extensions, so they get the full governance lifecycle: proposal, review,
approval, versioning, kill-switch. But because they run host-side, their veto is
authoritative — an extension cannot bypass a hook the way it cannot bypass the gate.

Hooks declare **zero permissions and zero egress**, which is what qualifies them for the
in-process runtime ([ADR-003](ADR-003-isolation-mechanism.md)). A hook that needed
authority would be a connector wearing a hook's hat.

## Alternatives considered

**Put PII redaction in the host.** Rejected: redaction policy changes faster than host
releases, and every future cross-cutting rule would mean a host change. Also, host code
does not go through the extension review process, so the rule would be *less* reviewed
than the extensions it constrains.

**Put it in each extension.** Rejected: unenforceable. The one extension that forgets is
the one that leaks.

**Run hooks after the gate, before execution.** Rejected: a hook that rewrites parameters
after authorization means the gate authorized something other than what runs. Parameters
must be final before they are judged.

**Hooks as advisory only (no veto).** Rejected: an advisory PII filter is a logging
feature. The credential guard in `pii-redaction-hook` genuinely needs to stop the action.

**Middleware ordering configurable per hook.** Rejected for now: ordering is a
correctness concern and multiple mutating hooks with configurable order is a debugging
nightmare. Today hooks run in load order, and that is a known limitation.

## Consequences

**Good.** One rule, applied everywhere, owned by the team that cares (privacy
engineering), shipped on their schedule, governed like everything else. The credential
guard demonstrably stops the injection scenario's exfiltration attempt *before* the gate
even evaluates it — defence in depth that arrived for free from the ordering.

**Good.** Because hooks are extensions, `host.kill("pii-redaction-hook", …)` works — which
is uncomfortable and correct. A broken hook that vetoes everything must be pullable, and
the audit log records that it was.

**Bad.** Hooks are on the hot path for every privileged action, so a slow hook slows the
platform. Bounded by `timeout_ms`, but a hook timeout is an action failure.

**Bad.** Multiple mutating hooks have undefined interaction ordering (load order today).
With two hooks it is fine; with ten it is a bug factory. Explicit priority declarations
are the fix when a second mutating hook appears.

**Bad.** A hook can silently weaken a payload — redacting a field an action depends on
turns "blocked" into "wrong". Mitigated by auditing `mutated=true` with the hook's own
notes on every invocation.
