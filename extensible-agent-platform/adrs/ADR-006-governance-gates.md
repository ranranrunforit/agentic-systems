# ADR-006 — Governance as data: grants file, permission diffing, kill-switch

**Status:** Accepted · **Date:** 2026-05-20 · **Deciders:** governance board, platform

## Context

Extensions get access to sensitive systems. Someone must decide who gets what, that
decision must be reviewable later, and a bad extension must be stoppable in seconds.
Governance that lives in a wiki is governance the loader cannot enforce.

## Decision

1. **Approvals are data.** `governance/approved-grants.yaml` holds exact permission keys
   per extension and version range, with approver, review ticket and expiry. The loader
   refuses any permission outside the grant.
2. **Permission expansion on upgrade is refused** until re-approval, and the diff is
   surfaced in the audit log (`governance.permission_diff`). The previous version keeps
   serving.
3. **Kill-switch:** one call marks the extension revoked, drops its capabilities and hook
   subscriptions, invalidates every outstanding token, and audits who and why. Reload
   requires a cleared revocation.
4. **Asymmetric authority:** security on-call can stop an extension alone; starting one
   takes two people. Grants have their own required reviewers, so authors cannot approve
   themselves.
5. **Grants expire** — 12 months, 6 for anything high impact.

## Alternatives considered

**Approval in a ticketing system, enforcement by convention.** Rejected: the loader
cannot read Jira, so the enforcement point and the decision point diverge — which is how
unreviewed permissions end up running.

**Enforce grants in CI only.** Rejected: CI checks the repository, not the running host.
An extension loaded from an artifact store would bypass it.

**Permissions approved once, per extension, forever.** Rejected: the interesting risk is
the *upgrade*. The fixture in `runtime/tests/fixtures/classify-ticket-v1.3.0` is exactly
the realistic case — a benign tool quietly adding `issue_tracker:close`.

**Automatic revocation on anomaly.** Tempting and rejected: a false positive silently
disables a workflow, and silent disablement is its own incident. Anomaly detection pages
a human who pulls the switch.

**Deprecation as the removal mechanism.** Rejected as insufficient — "marked deprecated"
does not revoke a token. Deprecation is for planned change; the kill-switch is for
incidents, and they are different operations.

## Consequences

**Good.** Approval is a git commit: who, when, which ticket, which exact keys.
Enforcement is at load, so there is no path around it. The diff makes the *reviewer's*
job small — they read what changed, not the whole manifest. The kill-switch is testable
and tested, including that reload without clearance fails.

**Bad.** Editing YAML to approve is not a delightful reviewer experience; at scale this
wants a UI writing the same file. The version-range globs need care — a broad `1.*` grant
can shadow a narrow re-approval, which we hit for real and fixed by preferring the grant
that actually covers the request (`registry.grant_for`).

**Bad.** Expiry creates recurring toil. That is the intended cost: unused authority is
the cheapest thing to remove and the most likely to be exploited.

**Accepted limitation.** An insider with unreviewed write access to `approved-grants.yaml`
owns the platform. The defence is CODEOWNERS and review, not code. Stated in the threat
model as A7 rather than solved.
