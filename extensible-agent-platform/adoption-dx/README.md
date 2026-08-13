# Adoption and developer experience

The platform's success condition is not "the host works". It is: **a team we do not
manage ships a safe extension without asking us how.**

| Document | Covers |
|---|---|
| [`developer-journey.md`](developer-journey.md) | Idea → local test → proposal → published, with timings |
| [`local-testing.md`](local-testing.md) | The mock host, the `ext` CLI, what to test |
| [`docs-plan.md`](docs-plan.md) | What documentation exists, for whom, and who owns it |
| [`templates/`](templates/) | Onboarding checklist and the extension README template |

## The ten-minute promise

```bash
python3 -m runtime.cli.ext scaffold ticket-sentiment --kind tool --owner team-cx
python3 -m runtime.cli.ext validate integrations/ticket-sentiment
python3 -m runtime.cli.ext test integrations/ticket-sentiment --input '{"action":"score","params":{"body":"furious"}}'
```

No shared environment, no credentials, no network, no platform-team ticket. Scaffold
writes a manifest with the invariants already satisfied, a handler with the rules in the
docstring, a local test file, and a README with the next five steps.

## Design principles for the DX

1. **The contract is the documentation.** `ext validate` explains the failure and names
   the invariant, so authors learn the model from error messages rather than a wiki.
2. **Local first, always.** Everything up to the proposal runs offline against simulated
   backends. An author who needs staging credentials to start will not start.
3. **The safe path is the easy path.** Scaffolding produces `tenant: "${caller.tenant}"`
   scopes and `network: deny` by default. Widening authority takes effort *and* prose,
   which is exactly the right cost curve.
4. **Refusals are teaching.** Every denial names the check, the rule id and the reason —
   `default-deny: triage-agent@2.1.0 never declared issue_tracker:close` is a lesson, not
   a stack trace.
5. **Governance is visible from the CLI.** `ext permissions` shows requested vs.
   approved before a reviewer ever sees the PR, so review is about judgement rather than
   diffing YAML.

## What a new team has to learn

Ordered by when they hit it. Total: about an hour of reading.

| Concept | Where | Why they cannot skip it |
|---|---|---|
| The manifest shape | [`../extension-contract/README.md`](../extension-contract/README.md) | It is the whole interface |
| `ctx` and nothing else | scaffolded handler docstring | Explains why `import requests` fails |
| Declared permissions are requests | [`../security/authorization.md`](../security/authorization.md) | Explains why their first run is denied |
| Propose vs. execute | [`../architecture/README.md`](../architecture/README.md) | The one idea that changes how they design |
| Impact classes and confirmation | [`../security/injection-defenses.md`](../security/injection-defenses.md) | Explains the confirmation prompt |
| The proposal template | [`../governance/templates/extension-proposal.md`](../governance/templates/extension-proposal.md) | It is the review interface |

## Measuring whether this works

| Metric | Target | Why this one |
|---|---|---|
| Scaffold → passing local test | < 30 min | The activation barrier |
| Proposal → approved | < 5 working days | Where enthusiasm dies |
| Permission expansions per approved extension | trending down | Are authors learning least privilege? |
| Denials at the gate in the first week after publish | trending down per team | Did they understand the model, or are they guessing? |
| Platform-team hours per extension shipped | < 4 | Whether this scales past ten extensions |
| Confirmations per operator per day | < 10 | Confirmation fatigue is the real long-term risk |

The fourth and sixth are the interesting ones: the first three measure friction, those
two measure whether the design is *understood* and *livable*.
