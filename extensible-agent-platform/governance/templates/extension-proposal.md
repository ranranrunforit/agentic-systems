# Extension proposal — `<extension-name>`

> Copy this file into your proposal PR. A proposal that cannot answer §3 and §5 will be
> sent back, so start there.

| Field | Value |
|---|---|
| Extension name | `<name>` |
| Kind | agent / tool / hook / connector |
| Owning team | `<team>` (must have on-call) |
| Author | `<you>` |
| Target version | `0.1.0` |
| Review ticket | `GOV-___` |
| Prototype | link to branch; `ext validate` and `ext test` output pasted below |

## 1. What it does

One paragraph, in the language of the domain, not the architecture. Who asks for it and
what they get.

## 2. Why an extension, not a host feature

Host features apply to everyone and carry authority. Extensions are optional and
carry only what they declare. Which is this, and why?

## 3. Authority requested

One row per permission. "Needed for the feature" is not a justification — describe the
blast radius if this extension were fully compromised.

| Resource | Actions | Scope | Impact | Why this is the minimum | Blast radius if abused |
|---|---|---|---|---|---|
| | | `tenant: "${caller.tenant}"`, … | low/med/high | | |

Egress destinations requested, one row each:

| Destination | Purpose | Data sent | Data received |
|---|---|---|---|

Lower-authority alternative considered (and why it was rejected):

## 4. Interfaces

- Capabilities **provided**: `resource.action`, …
- Capabilities **required** (`ctx.call`): …
- Input / output shape: see `io` in the manifest
- Timeout and expected latency:

## 5. Untrusted input

| Field | From which system | Attacker-controllable? |
|---|---|---|

- Output trust class declared: `trusted` / `untrusted` — justify if `trusted`.
- If this extension proposes actions, which are high impact and who confirms them?

## 6. Failure behaviour

- What happens on upstream 5xx / timeout / partial data?
- What is the worst *correct-looking* wrong answer it can produce?
- How does a caller tell success from degraded?

## 7. Testing

- [ ] `ext validate` passes
- [ ] `ext test` smoke run passes against the local mock host
- [ ] Contract test for each capability
- [ ] A test that asserts an *undeclared* action is refused
- [ ] A test with adversarial input (planted instruction in a text field)

## 8. Operations

- On-call rotation:
- Dashboards / alerts:
- What should trigger a kill-switch on this extension?

## 9. Reviewer sign-off

| Review | Reviewer | Date | Outcome |
|---|---|---|---|
| Platform | | | |
| Security | | | |
| Board (high impact only) | | | |

Grant committed to `governance/approved-grants.yaml` in: `<PR link>`
