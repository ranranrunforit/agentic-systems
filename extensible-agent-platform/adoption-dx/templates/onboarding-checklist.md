# New extension author — onboarding checklist

## Understand (about an hour)

- [ ] Ran `make demo` and watched a planted instruction get refused
- [ ] Read [the extension contract](../../extension-contract/README.md)
- [ ] Can explain **propose vs. execute** to a colleague
- [ ] Know why `import requests` fails inside an extension
- [ ] Know what "default-deny" means for your first run (it will be denied)

## Set up (10 minutes)

- [ ] Python 3.11+ available; `make test` passes on your machine
- [ ] Scaffolded a throwaway extension and made `ext test` pass
- [ ] Read the error message from a deliberate denial (remove a permission and rerun)

## Design your extension

- [ ] Chose the **least powerful kind** that works (tool < hook < connector < agent)
- [ ] Listed every permission with a one-line justification and its blast radius
- [ ] Every scope includes `tenant: "${caller.tenant}"` and the tightest true pattern
- [ ] Identified every untrusted input field and where it comes from
- [ ] Decided which actions are high impact and who confirms them
- [ ] Considered the propose-instead-of-act alternative and can say why not

## Build

- [ ] Handler uses only `ctx`
- [ ] Identifiers validated before being interpolated into URLs
- [ ] Clean failures on upstream errors and timeouts
- [ ] `ext validate` and `ext test` pass
- [ ] `ext permissions` shows no unapproved expansion

## Test

- [ ] One test per capability
- [ ] A test that an undeclared action is refused
- [ ] An adversarial-input test
- [ ] A failure-path test
- [ ] If you propose actions: a test that proposals are returned, not executed

## Ship

- [ ] Proposal filled in, including §3 authority and §5 untrusted input
- [ ] `ext validate` / `ext test` output attached
- [ ] Platform and security reviews requested
- [ ] Grant entry drafted for `approved-grants.yaml` with an expiry
- [ ] On-call rotation and alerting named
- [ ] Wrote down what should trigger a kill-switch on your extension
