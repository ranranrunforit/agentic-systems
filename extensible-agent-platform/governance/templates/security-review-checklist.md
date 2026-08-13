# Security review checklist

Reviewer: fill this in on the proposal PR. Anything unchecked is a blocker, not a nit.

## Contract

- [ ] `apiVersion: ext/v1`; `kind` matches what the extension actually is
- [ ] `metadata.owner` is a team with on-call, not an individual
- [ ] `capabilities.provides` names only what it serves; nothing speculative
- [ ] `capabilities.requires` lists every capability it calls (grep the handler for `ctx.call`)
- [ ] `runtime.type` is the tightest that works; `local-inproc` only if permissions and egress are both empty
- [ ] `timeout_ms` is realistic and bounded

## Permissions

- [ ] Every permission has a non-empty scope including `tenant`
- [ ] Scope patterns are the tightest true pattern (`support-*`, not `*`)
- [ ] Each action is individually necessary — challenge every one
- [ ] Impact classes are honest; anything customer-visible is `high`
- [ ] Every high-impact action has a justification describing blast radius
- [ ] A lower-authority design was considered (propose-instead-of-act)
- [ ] No permission exists solely for a future feature

## Credentials and egress

- [ ] `delegated_auth` present iff there is egress
- [ ] `flow: client_credentials` justified by the absence of a human, not by convenience
- [ ] Upstream `scopes` are the minimum for the declared actions
- [ ] `secret_ref` points at an existing store entry; no literal secret anywhere in the bundle
- [ ] Every `egress.allow` destination is justified; all `https`
- [ ] No wildcard destination

## Untrusted input and output

- [ ] `trust.output_class: untrusted` for anything reaching outside the host
- [ ] Untrusted fields identified; the handler treats them as data
- [ ] Identifiers validated before being interpolated into URLs or queries
- [ ] Outbound text cannot carry credentials or PII (hook coverage confirmed)
- [ ] Nothing in the handler branches on instructions found in retrieved text
      (or, if it does, it is a red-team fixture and labelled as one)

## Code

- [ ] Handler is thin; no business logic hidden in a connector
- [ ] No blocked-module imports; no `open()` outside its own directory
- [ ] No dynamic code execution
- [ ] Bounded loops and payload sizes
- [ ] Errors raise cleanly rather than returning plausible-looking wrong data

## Tests

- [ ] Contract test per capability
- [ ] A test asserting an undeclared action is refused
- [ ] An adversarial-input test
- [ ] Failure-path test (upstream error, timeout)

## Compromise assessment

Answer in prose on the PR:

1. If an attacker controlled this extension's code, what could they reach?
2. What would we see in the audit log?
3. What would we lose by killing it during business hours?

## Outcome

- [ ] Approved — grant entry drafted for `approved-grants.yaml` with expiry
- [ ] Approved with narrower scope (specify)
- [ ] Rejected (reason)
- [ ] Blocked pending platform change (specify)

Reviewer: ______________  Date: __________  Review ticket: GOV-____
