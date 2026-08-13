# Permission review and re-approval

## What a reviewer is actually deciding

Not "is this reasonable" but: **if this extension were fully compromised tomorrow,
what could the attacker do with exactly these permissions?** The manifest's
`justification` field exists to make the author answer that first.

## The review checklist

For each requested permission:

1. **Is the resource right?** Does the extension need `issue_tracker` at all, or does
   it need one capability another extension already provides?
2. **Is each action necessary?** `[read, label]` and `[read, label, close]` are
   different products. Actions are approved individually.
3. **Is the scope as narrow as the job?** `tenant: "${caller.tenant}"` is mandatory
   (contract invariant C4). Is `project: "support-*"` the tightest true pattern?
4. **Is the impact class honest?** The host floors it, but an author can and should
   raise it. Customer-visible ⇒ high, always.
5. **Does the justification describe the blast radius?** "Needed for triage" is not a
   justification. "Closure is customer-visible and hard to reverse; only after human
   confirmation" is.
6. **Is there a lower-authority design?** The commonest good outcome of a review is
   *propose instead of act*: the extension returns a proposal and a human or a separate
   connector performs the effect.

Worked example from this repo: the triage agent asked for read + classify + search +
CI-read + label + comment, and **not** `close`. Closure lives with the connector,
requires human confirmation, and is refused outright when tainted. That split is the
review outcome, not an accident of implementation.

## Approval

A grant entry in [`approved-grants.yaml`](approved-grants.yaml):

```yaml
- extension: triage-agent
  versions: "2.*"
  approver: governance-board
  review: GOV-150
  approved_at: "2026-07-21"
  expires_at: "2027-01-21"      # 6 months: this one touches customer-visible actions
  permissions: [ ... exact keys ... ]
```

The permission **key** is the unit of approval:

```
issue_tracker:comment,label@project=support-*,tenant=${caller.tenant}
```

Widening the action list or loosening the scope changes the key, which means the
existing grant no longer covers it, which means the loader refuses. That is the whole
enforcement mechanism, and it needs no discipline from the author.

## Permission diffing on upgrade

The fixture `runtime/tests/fixtures/classify-ticket-v1.3.0` is a realistic bad
upgrade: a tool that legitimately holds `ticket:classify` quietly adds
`issue_tracker:[read, close]` "to verify classification against the resolved outcome".

```
$ make governance
[1] classify-ticket 1.3.0 quietly asks for issue_tracker:read,close
    ADD  + issue_tracker:close,read@project=support-*,tenant=${caller.tenant}
    SAME = ticket:classify@tenant=${caller.tenant}

[2] the loader refuses the upgrade
    DENY classify-ticket@1.3.0: requests permissions outside its approved grant
         (review GOV-142): ['issue_tracker:close,read@…']. Re-approval required.
    · still running: classify-ticket@1.2.0
```

Three properties matter here:

- **the diff is surfaced, not just the refusal** — the reviewer sees exactly what was
  added (`governance.permission_diff` in the audit log);
- **the previous version keeps serving** — a rejected upgrade is not an outage;
- **re-approval is a normal grant commit**, after which the same load succeeds.

Asserted by `TestGovernance.test_permission_expansion_on_upgrade_is_refused` and
`test_upgrade_loads_after_re_approval`.

## Grant expiry and periodic re-review

Every grant carries `expires_at`: 12 months for low/medium, 6 for anything high
impact. At expiry the reviewer asks a different question from the original one:
**which of these permissions has the extension actually used?** `ext permissions`
flags approved-but-no-longer-requested keys, and the audit log answers the usage
question directly:

```bash
python3 -m runtime.cli.ext permissions integrations/triage-agent
#   warn  - issue_tracker:close@…   approved but no longer requested (candidate for revocation)
```

Unused authority is the cheapest thing to remove and the most likely to be exploited.

## Escalation

| Situation | Decision |
|---|---|
| Low/medium impact, narrow scope | One security reviewer |
| Any high-impact action | Review board (2+), 6-month expiry |
| Cross-tenant scope (a literal tenant, or `*`) | Review board + data-protection sign-off; expect rejection |
| New resource type | Platform + security; policy rules must be written first |
| Third-party publisher | See [`marketplace.md`](marketplace.md) — blocked on capability attestation |
