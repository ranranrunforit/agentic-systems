# The extension lifecycle

```
 proposal ──▶ review ──▶ approval ──▶ publish ──▶ versioning ──▶ deprecation ──▶ removal
                 │           │                        │
                 │           │                        └─▶ permission diff ──▶ re-approval
                 ▼           ▼
             rejected    revoked (kill-switch, from any state)
```

State machine in code: [`../runtime/host/registry.py`](../runtime/host/registry.py).
Diagram: [`../architecture/diagrams/load-isolate-revoke.mmd`](../architecture/diagrams/load-isolate-revoke.mmd).

## 1. Proposal

The author opens a proposal using
[`templates/extension-proposal.md`](templates/extension-proposal.md). It must answer
four questions, and a proposal that cannot is sent back:

1. **What does it do, and for whom?** One paragraph, no architecture.
2. **What authority does it need, and why each item?** Per permission, with the blast
   radius if it were abused.
3. **What untrusted input does it read?** Which fields, from which systems.
4. **What happens when it is wrong?** The failure mode a reviewer should worry about.

A working prototype is expected — `ext scaffold` → `ext validate` → `ext test` runs
locally with no shared environment ([`../adoption-dx/`](../adoption-dx/)).

## 2. Review

Two reviews run in parallel; both must pass.

**Platform review** (owner: platform team)
- contract validity, capability naming, `requires` accuracy
- does it belong as an extension at all, or is it a host feature?
- does it duplicate an existing capability?
- I/O shape, timeouts, failure behaviour

**Security review** (owner: security; checklist in
[`templates/security-review-checklist.md`](templates/security-review-checklist.md))
- least privilege per permission, and the scope on each
- impact classification honesty (is `notify_customer` really "medium"?)
- untrusted-input paths and whether output is correctly declared `untrusted`
- egress allowlist: every destination justified
- what a compromise of this extension would reach

SLA: five working days; two for a patch with no permission change.

## 3. Approval

Approval is a commit to [`approved-grants.yaml`](approved-grants.yaml) naming the
approver, the review ticket, the version range and an expiry. Rules:

- the grant lists **exact permission keys**, not wildcards;
- the version range is as narrow as the change (`1.*` for a stable connector, `1.3.*`
  for a fresh expansion);
- an expiry is mandatory — 12 months for low/medium, 6 months for anything high impact;
- the author cannot approve their own grant (CODEOWNERS on this file).

## 4. Publish

Publishing is loading: the extension directory lands in `integrations/` (or the
registry's artifact store) and the host loads it on next start or via
`registry.load_dir()`. The loader re-checks the contract and the grant — publication
is not a trusted operation.

Post-publish: the extension appears in `ext list` with its version, permissions,
grant reference and approver, and every action it takes is attributable from that
moment.

## 5. Versioning

See [`versioning-and-deprecation.md`](versioning-and-deprecation.md). The short form:

| Change | Bump | Governance |
|---|---|---|
| Behaviour fix | patch | none |
| New capability or optional input | minor | notify reviewers |
| **Any permission expansion** | minor at least | **re-approval; the loader refuses until then** |
| Breaking I/O or removed capability | major | deprecation window for callers |

Downgrades are refused outright — a rollback is a new forward version, so the audit
trail never goes backwards.

## 6. Deprecation

```python
registry.deprecate("cicd-status", successor="cicd-status@1.0.0",
                   sunset="2026-12-01", actor="governance-board")
```

A deprecated extension **keeps working** — that is the point. It is flagged in
`ext list`, callers are notified, and the sunset date is recorded. Minimum windows: 90
days for a capability other extensions `require`, 30 days for a leaf extension, 0 days
for a security removal (which is a kill-switch, not a deprecation).

## 7. Removal

At sunset, with callers migrated: revoke, unload, delete the grant, keep the audit
history forever. Removal of a capability that others still `require` is blocked — the
registry knows who depends on what, so a removal that would break a caller fails
loudly at review time rather than at 3am.

## Roles

| Role | May | May not |
|---|---|---|
| Extension author | propose, implement, test locally, request review | approve their own grant, edit policy |
| Platform reviewer | approve contract/design, publish | approve high-impact permissions alone |
| Security reviewer | approve permissions and scopes, block | author the extension under review |
| Review board (2+) | approve high-impact grants, clear a revocation | bypass the loader's checks |
| Security on-call | **pull the kill-switch at any time, no approval needed** | quietly re-enable it |

Deliberate asymmetry: **stopping something requires one person; starting it requires
two.**

## Audit events

Every transition is logged: `registry.grants_loaded`, `registry.loaded`,
`governance.grant_approved`, `governance.permission_diff`, `governance.deprecated`,
`governance.kill_switch`, `governance.revocation_cleared` — each with actor, extension
version and reason.
