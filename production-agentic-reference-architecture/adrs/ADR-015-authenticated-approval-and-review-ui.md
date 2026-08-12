# ADR-015 — Authenticated approval, a review UI, and a tamper-evident audit log

- **Status**: Accepted
- **Date**: 2026-08-11
- **Owner**: Agentic Systems Architect
- **Closes**: threat-model R1, R2; ADR-012 cuts 6, 7
- **Amends**: [ADR-009](ADR-009-hitl-boundary.md) (the gate mechanism), [ADR-012](ADR-012-scope-cuts.md)

## Context

The self-assessment named one launch-blocker: **the approve command was
unauthenticated**. `approve <run_id> --approver alice` believed the string. Three
consequences followed, and they compound rather than sit side by side:

1. **Non-repudiation was fictional.** The audit log recorded a name anyone could type.
2. **The review UI gap made it worse.** ADR-009 argued that one narrow confirmation
   boundary is what keeps reviewers attentive — but attentiveness requires seeing what
   is being approved, and a run id is not that. A reviewer approving blind is a
   rubber stamp with extra steps, which is the exact failure ADR-009 set out to avoid.
3. **The audit log was rewritable.** Even a correct approval left a record a local
   attacker could edit, so the one durable trace of the one privileged action was
   untrustworthy.

Recording these as residual risk was honest but insufficient: R1 was rated High and
would block a launch, and the three are cheapest to fix together — authentication is
worth little without a tamper-evident record of who approved what, and a review UI is
worth little without authentication.

## Options considered

1. **Leave all three as documented residual risk.**
2. **Authentication only** — take credentials on the CLI, keep the CLI-only flow.
3. **Authentication + tamper-evident audit + a localhost review UI**, all behind the
   existing gate interface.
4. **Full enterprise path** — OIDC/SSO, MFA, an audit pipeline to append-only external
   storage, a production web app.

## Decision

**Option 3.**

**Identity (`agent/identity.py`).** Approval requires an authenticated session, not an
argument. Passwords are never stored — only PBKDF2-HMAC-SHA256, per-principal salt,
240k iterations. Authentication mints a scoped, expiring session; the gate consumes a
session and never sees a secret, which is what lets the UI hold a login. **Authorisation
is separate from authentication**: being a known principal is not permission to approve,
so `approve:export` is checked independently and a view-only reviewer is expressible.
Every secret comparison is constant-time, and a wrong password and an unknown principal
return the identical error, so the endpoint does not enumerate principals.

**Audit chain (`agent/audit.py`).** Each record carries `prev_hash` and a `hash` over
its canonical (key-order-independent) contents plus the predecessor's hash. Modification,
reordering and deletion all break verification. Truncation — the one attack a bare local
chain cannot self-detect — is caught by mirroring the record count and head hash into a
separate `audit.head.json`, so an attacker must find and rewrite both consistently.
Records are fsynced before the head pointer moves, so a crash between the two is
reported as `head_pointer_stale` rather than misread as tampering.

**Review UI (`prototype/server.py`).** Stdlib `http.server`, bound to 127.0.0.1, showing
per pending run: the full report, its **declared coverage gaps**, the **guardrail events
that fired during the run**, the destination, the report hash and the cost. The
guardrail events matter most — a reviewer should read a report differently knowing a
source was interfered with. **The server holds no authority**: it calls
`Orchestrator.approve(session_token=…)`, and every control in the write path (token
binding, report-hash binding, destination allowlist) still applies unchanged.

**Audit records now name the authenticated principal id**, not a display name, so two
people called Alice remain distinguishable forever.

Rejections: **(1)** leaves a High-severity blocker open when the fix is a few hundred
lines. **(2)** fixes attribution but leaves the reviewer deciding blind, which
undermines ADR-009's own argument for the boundary. **(4)** is the correct production
end-state and is deliberately deferred: SSO, MFA and an external audit pipeline are
infrastructure this package does not have, and `verify_session` plus `AuditLog.append`
are the two seams where they attach.

## A bug this decision surfaced

Wiring authentication exposed a real defect that had been present all along: a **failed**
gate attempt called `_finish("failed", …)`, which wrote `status=failed` onto the run. So
any caller — unauthenticated, since that was the point — could permanently block a
pending export by attempting one bad approval. A denial of service on the approval path,
reachable by anyone.

Fixed with `_finish(persist_status=False)` for attempt outcomes (`unauthorised`,
`no_pending_approval`, `export_refused`): a rejected attempt is traced but never
overwrites durable run state, so the run stays `awaiting_approval` and a legitimate
retry works. Regression-tested in
`tests/test_agent.py::test_failed_gate_attempt_does_not_mutate_run_status`, and recorded
as control **C22** in the threat matrix.

Worth stating plainly: this bug existed *before* authentication was added and was not
caused by it. Adding the control is what made the failure path reachable in a test, and
that is an argument for building controls rather than documenting them.

## Consequences

**Positive**
- R1 is closed, so ownership, non-repudiation and audit mean something.
- R2 is closed for local tampering, with the residual (external storage) precisely stated.
- ADR-009's attentiveness argument is now supported by the interface rather than
  contradicted by it.
- The rejection path is authenticated too — an unauthenticated actor able to *block*
  every export would be a denial of service in the other direction.
- 74 unit and integration tests now cover these paths, and `verify.py` asserts the
  server refuses unauthenticated queue access.

**Negative / accepted costs**
- **A local credential store is not enterprise identity.** No MFA, no SSO, no password
  rotation policy. A shared credential still repudiates.
- **The UI is genuinely unsuitable beyond localhost**: no TLS, no CSRF tokens, no rate
  limiting. It binds 127.0.0.1 and says so on every page; recorded as R9 (Low, given the
  binding).
- Sessions are in-memory, so a server restart logs everyone out — acceptable, and it
  means a stolen session dies with the process.
- Bootstrap prints a generated password once and never stores it in plaintext. Seeding a
  *known* default would be worse than the string-name approval this replaces, so the
  credential must be captured at bootstrap or the store deleted and reseeded.
- More surface to maintain: two new modules, a web server, and the CLI now has
  `principals`, `audit` and `serve` subcommands.
