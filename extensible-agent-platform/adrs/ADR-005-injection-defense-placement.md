# ADR-005 — Injection defence sits at the host gate, after intent, before execution

**Status:** Accepted · **Date:** 2026-05-18 · **Deciders:** security, platform

## Context

Agents read attacker-controlled text: ticket bodies, wiki pages a contractor can edit,
CI logs containing commit messages. Any of it can contain instructions. The question is
not *whether* an agent will be manipulated — assume it will — but **where** the platform
stops the manipulation from becoming an action.

## Decision

The defence lives **at the host authorization gate**: after the model or extension
proposes, before anything executes. Concretely:

1. `ctx.propose()` is the strongest thing extension code can do to the world. Intent and
   execution are different operations, performed by different components.
2. The host tracks **taint** per invocation, on the host side. The extension's
   self-report is advisory, so provenance cannot be laundered.
3. At the gate: tainted + high impact is **refused outright** (policy R-900, no
   confirmation path). Tainted + medium + a fired injection heuristic escalates to human
   confirmation. Untainted high impact requires confirmation bound to
   `(tenant, resource, action, target)`.
4. Prompt fencing and regex heuristics exist as *hints and triggers*, explicitly not as
   controls.

## Alternatives considered

**Defend in the prompt (better system prompts, delimiters).** Rejected as a control. It
helps and it is bypassable; the reference agent deliberately obeys planted instructions
on every run so that no one can mistake prompt hygiene for security.

**Detect and block injections with a classifier.** Rejected as the primary mechanism:
an arms race with an adversary who can iterate. Retained as an escalation signal, which
is the role it can actually play.

**Sanitise untrusted content before the model sees it.** Rejected: you cannot strip
instruction-shaped language from a support ticket without destroying the ticket. The
customer's complaint *is* natural-language imperatives.

**Put the gate inside the agent** ("the agent checks its own permissions"). Rejected —
that is asking the compromised component to police itself.

**Confirm everything.** Rejected: confirmation fatigue makes the control worthless, and
a platform that pauses on every label gets switched off. Hence the calibration in
`security/injection-defenses.md`.

**Block every tainted action.** Rejected for the same reason: every useful RAG agent is
tainted on every run.

## Consequences

**Good.** One mechanism covers prompt injection *and* excessive agency, so there is no
separate injection subsystem to keep in sync. The defence does not depend on
recognising the attack, which is the property that makes it durable. The red-team
exercise produces four independent refusals, any one of which suffices — that redundancy
is deliberate.

**Bad.** Coarse call-level taint over-blocks: a high-priority ticket whose runbook page
happens to contain injection-shaped text pauses legitimate labelling for human
confirmation. Over-blocking is the right failure direction, but it creates confirmation
fatigue, which is the real long-term risk. Metric to watch: confirmations per operator
per day.

**Bad.** Low-impact actions still run on tainted input: an attacker can influence which
article is read or which label is applied. This is blast-radius management, not
prevention, and the docs say so.

**Residual.** A compromised *connector* is a different threat — it holds real authority.
Mitigation is thin connectors, harder review, independent kill-switch. See the threat
model.
