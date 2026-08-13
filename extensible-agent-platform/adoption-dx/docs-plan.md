# Documentation plan

Documentation is part of the security model here: an author who does not understand
default-deny writes an extension that asks for everything.

## What exists, for whom, owned by whom

| Doc | Audience | Answers | Owner |
|---|---|---|---|
| [Root README](../README.md) | Everyone | What is this, how do I run it | Platform |
| [Architecture](../architecture/README.md) | Reviewers, new engineers | How the host and extensions relate | Platform |
| [Extension contract](../extension-contract/README.md) | **Extension authors** | What may I declare, and what do the invariants mean | Platform |
| [Security model](../security/) | Security, auditors | Auth, tokens, isolation, injection, threats | Security |
| [Governance](../governance/) | Authors, reviewers, board | How do I get approved, how do you turn me off | Governance |
| [Portability](../portability/) | Leadership, architects | Are we locked in, what would switching cost | Architecture |
| [Adoption/DX](.) | **Extension authors** | How do I actually ship one | DevEx |
| [ADRs](../adrs/) | Everyone, later | Why is it like this | Whoever decided |

## Layering, and the rule behind it

1. **Error messages** — the most-read documentation in the system. `ext validate` and
   every gate denial name the check, the rule and the reason.
2. **Scaffolded code comments** — the three rules live in the handler docstring the
   author is already editing.
3. **The contract reference** — one page for the 90% case, invariants explained with
   *why*.
4. **Deep docs** — security and governance, read once and referenced.
5. **ADRs** — for the question "why not the obvious thing?"

Rule: **if authors keep asking a question, the answer belongs one layer up.** Three
questions about why `import requests` fails means the error message is wrong, not the
FAQ.

## Onboarding path (~1 hour)

1. Root README, "Quick start" — run the demos and watch an injection get blocked (10 min).
2. Extension contract README (20 min).
3. `ext scaffold` a throwaway tool and make `ext test` pass (20 min).
4. Skim [`../security/injection-defenses.md`](../security/injection-defenses.md) §"The design
   decision" — the propose-vs-execute idea (10 min).

Checklist: [`templates/onboarding-checklist.md`](templates/onboarding-checklist.md).

## Maintenance

| Trigger | Update |
|---|---|
| Contract change | Contract README, JSON schema, scaffold templates, an ADR |
| New policy rule | The rule's own `description` field (it is user-facing in denials) + authorization.md table |
| New host binding | Portability comparison, lock-in, migration path |
| Incident | Threat model, and the deny rule that now encodes the lesson |
| Recurring author question | The error message first, docs second |

Every code example in these docs is either copied verbatim from a running file or is a
command the repository actually supports — `make test` and `make demo` are the check
that they still work. Examples in `extension-contract/examples/` are generated from the
live manifests so they cannot drift.

## Known gaps

- No video walkthrough; for the terminal-heavy workflow the demos serve that purpose.
- No per-capability API reference — capabilities are declared per extension, so the
  registry (`ext list`) is the reference. A generated capability catalogue is the right
  next artifact once there are more than about twenty.
- No runbook per extension; owning teams write their own, and the proposal template
  asks for the on-call rotation.
