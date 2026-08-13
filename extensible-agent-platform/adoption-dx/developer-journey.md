# The extension developer journey

Worked end to end for a real request: *"can triage tell us how angry the customer is?"*

## Stage 1 — decide it is an extension (30 min)

| Question | This case |
|---|---|
| Does it need authority? | No — it reads text it is given |
| Does it need the network? | No |
| Is it deterministic? | Yes-ish; a scoring function |
| Who calls it? | The triage agent, via `ctx.call("ticket.sentiment", …)` |

⇒ a **tool**, zero permissions, `network: deny`. The cheapest and safest kind, and the
first question the platform team asks is always "can this be a tool?"

## Stage 2 — scaffold (2 min)

```bash
python3 -m runtime.cli.ext scaffold ticket-sentiment --kind tool --owner team-cx
```

Produces `extension.yaml` (invariants pre-satisfied), `handler.py` (rules in the
docstring), `local_test.py`, and a README with the next steps. The manifest starts with
`network: deny`, `permissions: []` and a tenant-scoped example — the safe default is the
default.

## Stage 3 — implement (1–3 hours)

```python
def handle(ctx, payload):
    body = (payload.get("params") or {}).get("body", "")
    score = _score(body)
    ctx.log(f"scored {len(body)} chars")
    return {"sentiment": score, "confidence": 0.7}
```

Three rules, in the docstring the scaffold wrote:

- you get `ctx` and nothing else — no sockets, no environment, no writes;
- reach the world with `ctx.http` (authorized and credentialed by the host);
- never *do* anything privileged — `ctx.propose` and let the gate decide.

## Stage 4 — local test (minutes, repeatedly)

```bash
python3 -m runtime.cli.ext validate integrations/ticket-sentiment
python3 -m runtime.cli.ext test integrations/ticket-sentiment \
    --input '{"action":"score","params":{"body":"I have been charged twice and nobody replies"}}'
```

`ext test` validates the manifest, loads it into a throwaway host with the real grants
file, runs it in the real sandbox against simulated backends, prints any gate denials,
and verifies the audit chain. If it passes here it will behave the same in production —
same contract, same gate, same isolation.

Details: [`local-testing.md`](local-testing.md).

## Stage 5 — wire it into a caller (30 min)

The triage agent adds `ticket.sentiment` to `capabilities.requires` and one `ctx.call`.
Because the tool declares one low-impact permission (`ticket:sentiment`), the agent
needs it too — chained authorization is symmetric — and both need a grant. That is the
moment the author meets the review process, and it is deliberately early.

## Stage 6 — proposal (1–2 hours of writing)

[`../governance/templates/extension-proposal.md`](../governance/templates/extension-proposal.md).
The two sections that take real thought: §3 authority requested (with blast radius) and
§5 untrusted input. For this tool both are short — which is the argument for tools.

Attach `ext validate` and `ext test` output. Reviewers should never be the first people
to run the code.

## Stage 7 — review (≤ 5 working days)

Platform review (does it belong, does it duplicate) and security review
([checklist](../governance/templates/security-review-checklist.md)) run in parallel. For a
zero-permission tool this is usually one pass. Expect one of two outcomes on a first
extension: approved, or "narrow the scope and resubmit" — the second is the common one
and is not a failure.

## Stage 8 — approval and publish (1 day)

A grant lands in `approved-grants.yaml` with an approver, a review ticket and an expiry.
Publishing is loading; the loader re-checks everything. `ext list` now shows the
extension with its version, permissions, grant reference and approver.

## Stage 9 — operate

- The owning team is on-call for it.
- `gate.denied` spikes for your extension are yours to explain.
- Permission expansions need re-approval — plan the review time into the release.
- The grant expires; at renewal, be ready to say which permissions you actually used.

## Timeline

| Stage | Elapsed |
|---|---|
| Decide → scaffold → local test | half a day |
| Implement and wire in | 1–2 days |
| Proposal written | half a day |
| Review | ≤ 5 working days |
| Approval → published | 1 day |
| **Total** | **~1.5 weeks, mostly waiting** |

## Second extension onwards

Scaffold → implement → test → proposal in a day, because the model is now familiar and
the reviewers know the team. The measurable goal is fewer permission expansions per
extension over time; that is what "the team learned least privilege" looks like in data.
