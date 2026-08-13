# ADR-004 — OAuth delegation plus ABAC, with a two-key rule

**Status:** Accepted · **Date:** 2026-05-13 · **Deciders:** security, platform

## Context

Extensions need access to sensitive systems on behalf of humans. We need an identity
model for *who the extension acts as* and an authorization model for *what it may do*.
Permissions are resource-scoped, tenant-scoped and sometimes provenance-dependent.

## Decision

**Delegation:** OAuth 2.x authorization code + PKCE, with the **host** as the
confidential client. `client_credentials` only where no human exists, and the manifest
must say which (`delegated_auth.subject`).

**Authorization:** **ABAC** over `(extension, kind, owner, resource, action, impact,
tenant, environment, origin, tainted)` plus request attributes such as `project`.
Deny-overrides, default-deny.

**The two-key rule:** an action proceeds only if the manifest declares the permission
**and** governance granted that exact permission key, **and** the org ABAC policy allows
it for these attributes. A manifest cannot self-grant; policy cannot grant what was
never declared.

**RBAC survives for humans:** who may approve a grant, confirm a high-impact action, or
pull the kill-switch is a role question, and is modelled as roles.

## Alternatives considered

**RBAC for extensions.** Rejected. The real questions are attribute questions — which
tenant, which project, which impact class, was the intent tainted. Encoding them as
roles yields a role per (extension × tenant × project × impact), which no one can
review. The failure mode is not "RBAC is wrong in theory"; it is that the role
explosion makes review theatre.

**Capability tokens only (no central policy).** Elegant, and rejected: there would be no
single place to express "tenant globex is read-only pending a DPA amendment" or "we do
not mutate CI/CD". Org-level constraints need an org-level artifact.

**Policy engine only, no manifest declarations.** Rejected: the manifest is what the
reviewer reads and what the diff on upgrade compares. Without declarations there is no
permission review, only a policy file that grows.

**OPA/Rego.** Genuinely good, and the right choice at larger scale. Rejected for the
reference to keep it dependency-free and to keep the policy readable by non-specialists
— the `description` field of every rule is user-facing text that appears in denial
messages, which matters more here than expressiveness.

**Extensions run their own OAuth flows.** Rejected: N codebases holding refresh tokens,
and revocation becomes a manhunt.

## Consequences

**Good.** Default-deny is structural. Cross-tenant reach requires a manifest naming a
literal tenant, which is exactly what a reviewer notices. The asymmetry catches real
mistakes in both directions: R-902 keeps `cicd:rerun` unreachable even though the
credential and the route exist; R-031 allows agents to close tickets and no agent can,
because none declares it.

**Bad.** Two artifacts to keep coherent (grants file and policy file) — a permission can
be approved and still denied by policy, which is confusing until you read the reason
string. Mitigation: `ext permissions` shows requested-vs-approved, and every denial names
the rule id.

**Bad.** ABAC conditions will strain if the domain grows relationship rules ("the
assignee of the ticket may…"). That is ReBAC, and it is recorded as an open question.

**Accepted limitation.** One upstream credential per provider per tenant, not per user.
True per-user delegation needs a consent ledger; specified in
`security/identity-and-oauth.md`, tracked in [ADR-010](ADR-010-open-security-questions.md).
