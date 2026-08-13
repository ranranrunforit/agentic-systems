# Authorization — ABAC, default-deny, and the two-key rule

## Why ABAC over plain RBAC

RBAC answers "what may this *role* do". The questions this platform actually has to
answer are:

- may **this extension version** do this **to this tenant's** resources?
- does the request fall inside the **scope** the reviewer approved (`project: support-*`)?
- is the intent **downstream of untrusted content**?
- what is the **impact class**, and does that change the answer?
- what **origin** produced it — a human, a model, another extension, a schedule?

Those are attributes of the request, not properties of a role. Encoding them as roles
produces a role per (extension × tenant × project × impact) combination, which nobody
can review. ABAC keeps them as what they are. See
[ADR-004](../adrs/ADR-004-auth-model.md) — RBAC survives in one place, as the
*human*-facing layer: who may approve a grant, confirm a high-impact action, or pull
the kill-switch.

## The two keys

```
        manifest declares                    org policy allows
        + governance grants                  for these attributes
   ┌──────────────────────────┐        ┌──────────────────────────┐
   │  extension.yaml          │        │  security/policy/        │
   │  approved-grants.yaml    │        │  abac-policy.yaml        │
   └───────────┬──────────────┘        └────────────┬─────────────┘
               │            KEY 1        KEY 2      │
               └──────────────┬─────────────────────┘
                              ▼
                    action may proceed
```

Neither key alone is sufficient, and that asymmetry is deliberate:

- **A manifest cannot self-grant.** `cicd-status` could declare `cicd:rerun`
  tomorrow; policy rule R-902 keeps it unreachable platform-wide until a separate
  review lands. (`TestAuthorization.test_manifest_grant_alone_is_not_enough`)
- **Policy cannot grant what was never declared.** Rule R-031 explicitly allows
  `issue_tracker:close` for agents — and no agent can close a ticket, because no
  agent manifest declares it. The rule exists to make that asymmetry visible to an
  auditor rather than accidental.
  (`TestAuthorization.test_undeclared_action_is_denied_by_default`)

## The six checks the gate runs

In order, in [`../runtime/host/gate.py`](../runtime/host/gate.py). Any failure denies
and audits.

| # | Check | Failure looks like |
|---|---|---|
| 1 | **Liveness** — loaded, approved, not revoked, credentials live | `knowledge-base is revoked (INC-42)` |
| 2 | **Declaration** — manifest permission exists *and* a governance grant covers it | `default-deny: triage-agent@2.1.0 never declared issue_tracker:close` |
| 3 | **Scope** — tenant and every other scope attribute match | `out of scope: project='internal-secret' not in scope 'support-*'` |
| 4 | **Policy** — ABAC evaluation, deny-overrides, default-deny | `policy R-901: tenant globex is read-only` |
| 5 | **Provenance** — taint plus impact ([`injection-defenses.md`](injection-defenses.md)) | `policy R-900: untrusted content may never drive a high-impact action` |
| 6 | **Confirmation** — high impact needs a confirmation bound to this intent | `close is high-impact and was not confirmed (auto-deny)` |

Note check 3's failure mode: a request that does not **carry** a scope attribute is
denied, not waved through. You cannot pass a scope check by omitting the field.

## Policy evaluation semantics

```yaml
version: "2026-08-01"
default: deny            # ← the whole file could be deleted and nothing would work
rules:
  - id: R-900
    effect: deny         # deny-overrides: evaluated first, wins over any allow
    match: { action: [close, delete, deploy, refund, ...] }
    conditions: { when_taint: untrusted }
```

- **Deny-overrides.** Any matching `deny` ends evaluation. A careless `allow` added
  later cannot re-open something a deny rule closed.
- **First matching allow** otherwise; no rule at all means the default, which is deny.
- **Obligations** ride along with an allow: `confirm: true` forces the confirmation
  gate even where impact alone would not, and `reason_required: true` demands a
  recorded rationale.

Available attributes: `extension`, `kind`, `owner`, `resource`, `action`, `impact`,
`tenant`, `environment`, `origin`, `tainted`, plus request attributes such as
`project`. Conditions: `when_taint`, `when_origin`, `when_impact`, `tenants`,
`environments`, `max_taint`, `require_tenant_match`.

## Reading the shipped rules

| Rule | Effect | What it is really for |
|---|---|---|
| R-900 | deny | Tainted content may never drive a high-impact action. The injection backstop, with **no confirmation path** — a tired human cannot click through it. |
| R-901 | deny | Tenant `globex` is read-only pending a DPA amendment. A commercial/legal constraint expressed as policy rather than as tribal knowledge. |
| R-902 | deny | The platform does not mutate CI/CD, even though the upstream route and the credential exist. |
| R-903 | deny | Scheduled (unattended) runs never touch production. |
| R-010 | allow | Reads across the three data sources for onboarded tenants. |
| R-011 | allow | Tool invocation (`ticket.classify`). |
| R-020 | allow | Label and comment on `support-*` projects for tenant `acme`. |
| R-030 | allow | Closure, only via the `issue-tracker` connector, only untainted, only human/extension origin, with `confirm` and `reason_required`. |
| R-031 | allow | The deliberate no-op described above. |

## Impact classes

The host maintains a floor: `close`, `delete`, `purge`, `merge`, `deploy`, `rerun`,
`refund`, `escalate`, `transfer`, `notify_customer`, `admin` are **high** no matter
what a manifest claims; `write`, `label`, `comment`, `assign`, `reopen`, `tag` are at
least **medium**. A manifest may raise an action's impact, never lower it. High impact
implies a confirmation gate and a mandatory `justification` in the manifest.

Customer-visible is the dividing line, not technical difficulty: `notify_customer` is
high impact because you cannot un-send it.

## Multi-tenancy

Every permission scope carries `tenant: "${caller.tenant}"`, resolved from the
request. A grant is therefore never cross-tenant, and the token minted for an action
is bound to the tenant as well as the resource and action. Cross-tenant reach requires
a manifest that names a literal tenant, which is exactly the thing a reviewer will
notice.

## What is not here

- **No allow-list of individual users per extension.** That belongs in the calling
  application's authorization, not the platform's.
- **No policy hot-reload.** Policy changes ship as code review + restart, which is
  slower and much easier to audit. Hot-reload with signed policy bundles is future work.
- **No relationship-based access control (ReBAC).** If the domain grows
  "the assignee of the ticket may…" style rules, ABAC conditions will strain; ReBAC
  is the next step. Recorded in ADR-010.
