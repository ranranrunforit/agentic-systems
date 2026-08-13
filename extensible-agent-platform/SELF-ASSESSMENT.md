# Self-assessment against the rubric

Written to be useful to a reviewer rather than flattering. Each dimension states the
evidence, then what a stricter reviewer would mark down. Open security questions are in
[ADR-010](adrs/ADR-010-open-security-questions.md); this document is about the
deliverable, not the design's residual risk.

Reproduce every claim below with `make test`, `make demo`, `make glue`, `make yaml-check`.

## Extensibility and contract design — 25%

**Evidence.** One `ext/v1` schema covers all four kinds; `TestContract` loads agent, tool,
hook and connector through the same parser and asserts the eight invariants. No host code
is specific to any extension. Extensions never address each other — they name capabilities
and the host routes — which is what makes the kill-switch total rather than best-effort.
Adding an integration is a manifest plus a thin handler, demonstrated by the fact that the
same five manifests run unchanged on a second host binding.

**Where it is weak.** The schema carries the union of fields across kinds, so a reader sees
`events` and `delegated_auth` on a schema most extensions barely use. `io` is descriptive
and not enforced at runtime — a real gap, cheap to fix, not done. And capability naming
(`issue_tracker.label` vs `ticket.label`) has no owner or catalogue; with twenty extensions
that becomes a deprecation cycle waiting to happen.

**Self-rating: strong.** The claim "adding an extension is principled, not bespoke" is
demonstrated rather than asserted.

## Security and sandboxing — 25%

**Evidence.** Default-deny at three independent points (grant, policy, gate). The two-key
rule is tested in both directions: R-902 keeps `cicd:rerun` unreachable although the
credential and route exist, and R-031 permits agents to close tickets while no agent can,
because none declares it. Tokens bind to extension ref, tenant, resource, action set,
intent hash and credential generation, with 15–30s TTLs; a test inspects the connector's
own return value and logs to assert no credential material is present. `make containment`
runs a rogue extension through nine escapes and all nine fail.

**Where it is weak — and this is the honest headline.** The reference sandbox's in-process
import and `open()` guards are **not a boundary**. A determined attacker with arbitrary
Python defeats them (`builtins` surgery, C extensions). `security/isolation.md` says this
twice and names the production mechanisms (seccomp + netns, gVisor/Firecracker, WASM), but
a reviewer reading `make containment` as proof of production-grade isolation would be
reading it wrong. Capability attestation is specified and unimplemented, which is the
blocker on third-party publishers. There is no rate limiting: an authorized extension can
act at machine speed within its grant.

**Self-rating: strong on model, honest-but-partial on implementation.** The interfaces are
faithful; the enforcement is defence in depth.

## Injection and untrusted-output defense — 15%

**Evidence.** One trust boundary, stated as a design rule: model output is proposed intent,
never an action. The agent is *deliberately gullible* — `_follow_instructions_like_a_model_would`
obeys planted instructions on every run — so the containment claim never rests on prompt
hygiene. `make injection` produces four independent refusals (undeclared permission, policy
R-900, hook veto, confirmation escalation), any one of which suffices. Taint is tracked
host-side, so an extension cannot launder provenance. R-900 has no confirmation path, so a
tired operator cannot click through the worst class.

**Where it is weak.** Taint is call-level, so it over-blocks; the resulting confirmation
fatigue is the most likely way this control degrades in production, and the mitigation
(narrower scopes) is process rather than code. Low-impact actions still run on tainted
input — an attacker can influence which article is read or which label is applied. The
heuristics layer is trivially evadable and is scoped to being an escalation trigger, which
the docs say plainly.

**Self-rating: strong.** The defence does not depend on recognising the attack, which is
the property that makes it durable.

## Governance lifecycle — 10%

**Evidence.** Approvals are data the loader enforces, not a wiki page. The permission-diff
fixture is realistic (a benign classifier quietly adding `issue_tracker:close`), and the
refusal, the surfaced diff, the continued service of the previous version, and the
successful load after re-approval are all tested. The kill-switch satisfies four properties
— immediate, total, credential-invalidating, irreversible without governance — each with a
test. Authority is deliberately asymmetric: one person stops, two start.

**Where it is weak.** Editing YAML is not a reviewer experience that scales; at volume this
wants a UI writing the same file. Grant version globs need care — a broad `1.*` grant
shadowing a narrow re-approval was a real bug found and fixed in `registry.grant_for`.
Grant expiry creates recurring toil by design, and nothing in the repo automates the
"which permissions did you actually use" question beyond an audit query.

**Self-rating: strong.**

## Portability and lock-in — 15%

**Evidence.** Not a design document: `portability/bindings/graph_host_binding.py` is a
working second host, and `test_portability` asserts both hosts reach identical gate
decisions on the same manifests, including the injection case, the confirmation gate and
the kill-switch. `make glue` measures the split — 155 host-specific lines on binding #2,
5.0% of that host's total. The lock-in analysis names what switching **costs**: per-invocation
isolation weakens, `runtime.type` becomes advisory, and the platform's convenient secret
injection would regress the "credentials never reach extension code" property unless the
egress proxy is deliberately preserved.

**Where it is weak.** Binding #2 is a graph-shaped host in the same process, not a
deployment against real LangGraph Platform — it proves the contract's portability, not the
vendor's behaviour. It also currently *accepts and downgrades* manifests whose declared
runtime it cannot honour (reporting `runtime=graph-node`) where a production binding should
fail closed; the migration path says so. The comparison table will age faster than the
dimensions it is built from.

**Self-rating: strong**, with the caveat that "portable" is demonstrated at contract level
and argued at vendor level.

## Adoption and DX — 10%

**Evidence.** `ext scaffold` → `validate` → `test` runs offline with no credentials and no
shared environment; scaffolding emits the safe defaults (`network: deny`, tenant-scoped,
zero permissions) so widening authority costs effort *and* prose. `ext test` uses the real
grants file, the real sandbox and the real gate — there is no relaxed test mode, so a local
pass means the same behaviour in production. Every denial names the check, the rule id and
the reason, which is the most-read documentation in the system.

**Where it is weak.** No `ext why` command to explain a decision against both the grant file
and the policy file, which is the single thing most likely to confuse a new author (a
permission can be approved and still denied by policy). No generated capability catalogue.
The DX metrics in `adoption-dx/README.md` are proposed, not measured — nobody has actually
run a new team through this.

**Self-rating: good, not strong.** The scaffolding and feedback loop are real; the
"a new team could realistically ship" claim is argued rather than observed.

## Acceptance criteria

| Criterion | Status |
|---|---|
| Four types under one contract with load/isolate/revoke | met — `TestContract` |
| OAuth delegation + RBAC/ABAC, default-deny | met — ABAC for extensions, RBAC for humans ([ADR-004](adrs/ADR-004-auth-model.md)) |
| Token lifecycle: issue, scope, rotate, revoke, least privilege | met — `TestTokenLifecycle` |
| Isolation for local **and** remote execution | met in model and code; production hardening specified, not shipped |
| Trust boundary + action-confirmation gate | met — `TestInjection`, `make injection` |
| Governance proposal→removal incl. kill-switch | met — `TestGovernance`, `make governance` |
| ≥3 integrations through the contract | met — issue tracker, knowledge base, CI/CD (VCS is the uncovered fourth category) |
| ≥1 named alternative as a peer + portability/lock-in + migration path | met, with a working second binding |
| Adoption/DX prototype→published | met |
| Platform-neutral; worked domain stated up front | met — [ADR-001](adrs/ADR-001-worked-domain.md), [ADR-002](adrs/ADR-002-alternative-platform.md); the recommendation explicitly flips to Claude Code for an SDLC domain |
| ≥8 ADRs | met — 11 |

## Stretch goals

| Goal | Status |
|---|---|
| Second host binding, with glue measured | **done** — 155 lines, 5.0% |
| Injection red-team | **done** — poisoned KB-207, four independent refusals |
| Permission diffing with re-approval | **done** — fixture, refusal, diff, re-approval |
| Marketplace governance | **done as a model** — [`governance/marketplace.md`](governance/marketplace.md), with tiers and revocation |
| Capability attestation | **not implemented** — designed in [`security/isolation.md`](security/isolation.md); the blocking prerequisite for third parties |

## What I would build next, in order

1. **Runtime `io` validation at the gate boundary.** Cheapest real gap; closes a whole class
   of correctness bugs.
2. **`ext why <extension> <resource>:<action>`** — explain a decision against the manifest,
   the grant and the policy in one output. Biggest DX win per hour.
3. **Per-extension, per-tenant action budgets at the gate.** The most valuable *security*
   increment: it addresses the "authorized but compromised, acting at machine speed" case
   that nothing currently bounds.
4. **Capability attestation.** Unblocks third-party publishers; pointless before (3).
5. **A VCS connector**, to cover the fourth integration category and to test whether the
   contract holds up for an SDLC instantiation without changes.
