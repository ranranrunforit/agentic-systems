# Architecture decision records

Eleven ADRs. The two the brief asks for up front are ADR-001 (worked domain) and
ADR-002 (alternative platform).

| ADR | Decision | Status |
|---|---|---|
| [001](ADR-001-worked-domain.md) | Worked domain: support-ticket triage (non-developer) | Accepted |
| [002](ADR-002-alternative-platform.md) | Alternative peer platform: LangGraph Platform | Accepted |
| [003](ADR-003-isolation-mechanism.md) | Isolation: subprocess now, WASM/microVM path, remote via brokered RPC | Accepted |
| [004](ADR-004-auth-model.md) | Auth: OAuth delegation + ABAC (not RBAC) with a two-key rule | Accepted |
| [005](ADR-005-injection-defense-placement.md) | Injection defence sits at the host gate, after intent, before execution | Accepted |
| [006](ADR-006-governance-gates.md) | Governance as data: grants file, permission diffing, kill-switch | Accepted |
| [007](ADR-007-token-lifecycle.md) | Short-lived, intent-bound, host-held tokens; no credentials in extensions | Accepted |
| [008](ADR-008-integration-approach.md) | All integrations are extensions; capability routing through the host | Accepted |
| [009](ADR-009-host-model.md) | Host/extension model with one contract for four extension types | Accepted |
| [010](ADR-010-open-security-questions.md) | Open security questions, recorded rather than hidden | Open |
| [011](ADR-011-hook-veto-placement.md) | Hooks run host-side, before the gate, with veto authority | Accepted |

Format: context → decision → alternatives considered (with why not) → consequences,
including the ones we dislike.
