# Extension governance

An extension is a piece of privileged software that a team other than the platform
team wrote. Governance is how it becomes trustworthy and how it stops being trusted.

| Document | Covers |
|---|---|
| [`lifecycle.md`](lifecycle.md) | Proposal → review → approval → publish → version → deprecate → remove |
| [`permission-review.md`](permission-review.md) | How permissions are reviewed and how expansions are re-approved |
| [`versioning-and-deprecation.md`](versioning-and-deprecation.md) | Version policy, breaking changes, deprecation windows |
| [`kill-switch.md`](kill-switch.md) | Pulling a bad extension immediately, and the incident runbook |
| [`marketplace.md`](marketplace.md) | Extending the lifecycle to third-party publishers |
| [`approved-grants.yaml`](approved-grants.yaml) | **The grants themselves — governance as data** |
| [`templates/`](templates/) | Proposal template, security review checklist, deprecation notice |

## Governance as data

The review board's decision is not a wiki page; it is
[`approved-grants.yaml`](approved-grants.yaml), which the loader enforces on every
start-up:

```yaml
- extension: issue-tracker
  versions: "1.*"
  approver: sec-review-lead@platform
  review: GOV-114
  approved_at: "2026-05-02"
  expires_at: "2027-05-02"
  permissions:
    - resource: issue_tracker
      actions: [close]
      scope: { tenant: "${caller.tenant}", project: "support-*" }
      impact: high
      justification: >-
        Closure is customer-visible and hard to reverse...
```

Consequences worth spelling out:

- **An unapproved permission cannot run.** Not "is discouraged" — the loader refuses
  (`RegistryError`, `PermissionExpansionError`).
- **Approval is reviewable in git.** Who approved what, when, against which ticket.
- **Grants expire.** An `expires_at` in the past is a re-review, not a silent renewal.
- **Approving is separate from authoring.** The grant file has its own required
  reviewers; an extension author cannot merge their own grant.

## The four gates that actually gate

| Gate | Enforced by | Bypassable by a determined author? |
|---|---|---|
| Contract validity | `contract.py` at load | No |
| Approved grant covers every requested permission | `registry.load()` | No |
| Permission expansion on upgrade | `registry.load()` + diff | No — needs a new grant entry |
| Revocation | `registry` + `broker` | No — reload requires a cleared revocation |

Everything else in this directory is process around those four.

## Verify

```bash
make governance                                  # diff → refusal → re-approval → kill → rotate → reload
python3 -m runtime.cli.ext permissions integrations/triage-agent
python3 -m unittest runtime.tests.test_platform.TestGovernance -v
```
