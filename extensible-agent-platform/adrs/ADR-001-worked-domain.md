# ADR-001 — Worked domain: support-ticket triage

**Status:** Accepted · **Date:** 2026-05-04 · **Deciders:** platform architecture

## Context

The platform is general: a host/extension model for agents, tools, hooks and
connectors. But a general platform designed without a concrete workload is a diagram.
We need one worked domain to force the design to be real — and the brief explicitly
allows either an SDLC workflow or a non-developer internal workflow.

The risk to avoid is framing the platform as one company's internal AI-for-SDLC
product. If the worked domain is code review, the platform's vocabulary drifts toward
repositories and pull requests, developer-tool hosts start looking like the obvious
answer, and neutrality is lost by accident rather than by argument.

## Decision

**Support-ticket triage**, a non-developer internal workflow, as the worked domain.

Instantiation: a triage **agent**, a `classify-ticket` **tool**, a `pii-redaction-hook`
**hook**, and **connectors** to an issue tracker, a knowledge base and a CI/CD status
feed. Tenants `acme` and `globex`; projects `support-billing` and `support-platform`.

The equally valid SDLC instantiation is named throughout: a review agent, a `lint_diff`
tool, a pre-merge hook, and VCS/issue/CI connectors — same contract, same gate, same
governance.

## Alternatives considered

**SDLC (code review, dependency triage, release notes).** Rejected as the *worked*
domain, not as a use case. It would have been easier — the toolchain integrations are
better documented and the author population is the same people building the platform.
That ease is the problem: it makes developer-tool hosts feel inevitable, and it hides
the multi-tenant and customer-visible-action problems that make the security model
interesting.

**Sales-ops research.** Attractive because it is read-heavy and low-risk. Rejected for
the same reason: with almost no privileged writes, the authorization gate and the
confirmation flow would never be exercised.

**Internal knowledge Q&A.** Rejected as too thin — one connector, no write actions, no
interesting governance.

**Two domains at once.** Rejected: the deliverable would double and the contract would
be tuned to neither.

## Why this domain exercises the design hardest

| Design property | What triage forces |
|---|---|
| All four extension types | An agent orchestrates, a tool classifies, a hook redacts, three connectors reach out — none is contrived |
| Untrusted input | Ticket bodies and wiki pages are *written by the adversary*. Injection is the normal case, not a test fixture |
| High-impact actions | Closing a ticket is customer-visible and hard to reverse — a real reason for a confirmation gate |
| Multi-tenancy | Support data is per-customer; every scope must carry a tenant |
| PII | Real redaction requirements, which is what makes the hook type earn its place |
| Mixed authority | Read-mostly agent, write-capable connector, zero-authority tool: the composition problem in miniature |
| Non-developer users | The delivery surface is not an IDE, which rules a whole class of hosts *in or out on merit* |

## Consequences

**Good.** Neutrality is structural: a support agent cannot live in a terminal, so
Claude Code and Cursor are assessed on domain fit rather than dismissed or assumed. The
injection scenario is realistic rather than academic — a poisoned wiki page is exactly
how this happens. Customer-visible actions justify the impact classification the whole
gate depends on.

**Bad.** Reviewers who work on developer tooling have to translate. Integrations are
simulated rather than hitting real Jira/Confluence APIs, so credential-handling
subtleties of specific vendors are out of scope. And the SDLC comparison in
[ADR-002](ADR-002-alternative-platform.md) is slightly weaker for it: we argue about
Claude Code's fit for a domain we did not instantiate.

**Mitigation.** Every document states the SDLC peer instantiation explicitly, and
`portability/platform-comparison.md` says outright that for an SDLC domain the
recommendation would flip to Claude Code.
