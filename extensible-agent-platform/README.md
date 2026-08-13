# Extensible Agent Platform (platform-neutral)

A host-plus-extension platform where agents, tools, hooks and external connectors can be
added safely over time, under strong auth and isolation, with a governance lifecycle that
keeps extensions trustworthy.

| Up-front declarations (per the brief) | |
|---|---|
| **Worked domain** | **Support-ticket triage** — a non-developer internal workflow ([ADR-001](adrs/ADR-001-worked-domain.md)). The SDLC instantiation is named throughout as an equally valid peer. |
| **Alternative platform evaluated as a peer** | **LangGraph Platform** ([ADR-002](adrs/ADR-002-alternative-platform.md)), with Claude Code, Cursor and Copilot compared on the same dimensions. A **working second host binding** ships in [`portability/bindings/`](portability/bindings/). |
| **Platform neutrality** | Structural, not rhetorical: the contract, policy, grants, gate and audit format are shared across two hosts; 155 lines were host-specific on the second binding (`make glue`). |

This is a general extensible platform. Triage is one instantiation, chosen because it
exercises all four extension types, real untrusted input, customer-visible actions and
multi-tenancy — not because the platform is a support tool.

## Quick start

No dependencies, no network, no credentials. Python 3.11+.

```bash
make test        # 63 tests mapped to the acceptance criteria
make demo        # five demos: triage, injection, containment, governance, portability
make list        # every loaded extension with its version, permissions and grant
make glue        # portable vs. host-specific line counts
```

The five-minute version — watch a prompt injection fail:

```bash
make injection
```

```
[3] every proposal at the gate
    DENY  issue_tracker:close
        default-deny: triage-agent@2.1.0 never declared issue_tracker:close in its manifest
    DENY  issue_tracker:comment
        hook veto: params.body contains a credential-shaped string
    DENY  issue_tracker:label
        tainted medium-impact action escalated to confirmation: injection heuristics fired (3)

    PASS  the injection reached the gate as intent and died there
```

## The one idea

> **A model's output is never an action. It is a proposal.**

Extensions declare what they can do; the host decides whether it happens. That single
trust boundary is simultaneously the prompt-injection defence and the excessive-agency
control, which is why there is one gate rather than a security subsystem per threat.

## What is here

```
project-303-extensible-agent-platform/
├── architecture/          host/extension model + 4 diagrams (incl. the privileged-action sequence)
├── extension-contract/    the ext/v1 contract: JSON schema + 4 worked examples
├── security/             auth · ABAC · tokens · isolation · injection defence · threat model
├── governance/           proposal→removal lifecycle · approved-grants.yaml · kill-switch
├── integrations/         5 extensions covering all 4 kinds, incl. 3 toolchain connectors
├── portability/          peer comparison · lock-in analysis · migration path · 2nd binding
├── adoption-dx/          developer journey · local testing · docs plan · templates
├── adrs/                 11 ADRs
├── SELF-ASSESSMENT.md     rubric self-assessment, incl. what is weakest
└── runtime/              the reference host, CLI, tests and demos (runnable)
```

`runtime/` is deliberately not named after any vendor: it is *one binding* of the
contract. [`portability/bindings/graph_host_binding.py`](portability/bindings/graph_host_binding.py)
is a second.

## The host does five things

| Responsibility | Module | Guarantee |
|---|---|---|
| Load / isolate / revoke | `registry.py`, `sandbox.py` | Only approved versions run, boxed, and any can be pulled instantly |
| Authorize | `gate.py`, `policy.py` | Two independent keys must turn for anything privileged |
| Credential custody | `broker.py`, `secrets.py` | Short-lived scoped tokens; **secrets never reach extension code** |
| Mediate egress | `egress.py` | One allowlisted way out; everything coming back is labelled untrusted |
| Record | `audit.py` | Hash-chained, attributable, tamper-evident |

Everything else is an extension.

## The four extension types, one contract

```
   agent / tool ──proposes──▶ [ pre-action hooks ] ──▶ [ GATE ] ──▶ connector ──▶ outside world
```

| Kind | Example here | Authority |
|---|---|---|
| **agent** | `triage-agent` | Reads via brokered calls; proposes labels and comments; **no `close` permission at all** |
| **tool** | `classify-ticket` | Zero egress, one low-impact capability |
| **hook** | `pii-redaction-hook` | Zero permissions; runs host-side with veto authority |
| **connector** | `issue-tracker`, `knowledge-base`, `cicd-status` | The only extensions that reach outside, each with allowlisted egress and delegated OAuth |

Contract: [`extension-contract/README.md`](extension-contract/README.md).

## How the requirements are met

| Req | Where | Executable evidence |
|---|---|---|
| FR-1 extension architecture | [`architecture/`](architecture/), [`extension-contract/`](extension-contract/) | `TestContract` — all four kinds under one schema; load/isolate/revoke round trip |
| FR-2 auth and sandboxing | [`security/`](security/) | `TestAuthorization`, `TestTokenLifecycle`, `TestIsolation`; `make containment` |
| FR-3 injection defences | [`security/injection-defenses.md`](security/injection-defenses.md) | `TestInjection`; `make injection` |
| FR-4 governance lifecycle | [`governance/`](governance/) | `TestGovernance`; `make governance` |
| FR-5 toolchain integrations | [`integrations/`](integrations/) | `TestIntegrations` — one run touches all three destinations through the contract |
| FR-6 portability and lock-in | [`portability/`](portability/) | `test_portability` — identical decisions on two hosts; `make glue` |
| FR-7 adoption and DX | [`adoption-dx/`](adoption-dx/) | `ext scaffold` → `validate` → `test` in under 30 minutes |
| ≥8 ADRs | [`adrs/`](adrs/) | 11 |

Self-assessment against the rubric, including where this work is weakest:
[`SELF-ASSESSMENT.md`](SELF-ASSESSMENT.md).

Stretch goals delivered: second host binding, injection red-team, permission diffing with
re-approval, marketplace governance model. Capability attestation is **specified and not
implemented** — see [ADR-010](adrs/ADR-010-open-security-questions.md).

## Try the interesting paths

```bash
# a clean ticket: label and comment execute unattended
python3 -m runtime.cli.ext run triage-agent --input '{"ticket_id":"T-1042"}' --execute

# a poisoned ticket: everything privileged is refused or held
python3 -m runtime.cli.ext run triage-agent --input '{"ticket_id":"T-1043"}' --execute

# a rogue extension tries nine escapes; all nine fail
make containment

# pull an extension host-wide, with token revocation
python3 -m runtime.cli.ext kill knowledge-base --reason "INC-42: poisoned article"

# scaffold your own
python3 -m runtime.cli.ext scaffold ticket-sentiment --kind tool --owner team-cx
```

## What we would not claim

Honesty is part of the deliverable, so the limits are listed rather than buried:

- **The reference sandbox is not a production boundary.** In-process import and `open()`
  guards are defence in depth; production needs seccomp + netns, gVisor/Firecracker, or
  WASM. [`security/isolation.md`](security/isolation.md) says so twice.
- **No capability attestation yet**, which is the blocker on third-party publishers.
- **Taint is call-level**, so it over-blocks; the resulting confirmation fatigue is the
  most likely way this control degrades.
- **Switching hosts costs the isolation guarantee**, and that is the most
  security-relevant thing in the system — named in
  [`portability/lock-in-analysis.md`](portability/lock-in-analysis.md) rather than
  hand-waved.
- **For an SDLC worked domain the recommendation flips to Claude Code**, and the
  comparison document says so.

Full list: [ADR-010](adrs/ADR-010-open-security-questions.md) and
[`security/threat-model.md`](security/threat-model.md).

## Reading order

- **Reviewer, 20 minutes:** this file → `make demo` → [`architecture/README.md`](architecture/README.md) → [`portability/lock-in-analysis.md`](portability/lock-in-analysis.md)
- **Security reviewer:** [`security/threat-model.md`](security/threat-model.md) → [`security/injection-defenses.md`](security/injection-defenses.md) → [`security/isolation.md`](security/isolation.md) → [ADR-010](adrs/ADR-010-open-security-questions.md)
- **Extension author:** [`extension-contract/README.md`](extension-contract/README.md) → [`adoption-dx/developer-journey.md`](adoption-dx/developer-journey.md) → `ext scaffold`
- **Architect weighing hosts:** [`portability/platform-comparison.md`](portability/platform-comparison.md) → [`portability/migration-path.md`](portability/migration-path.md) → [ADR-002](adrs/ADR-002-alternative-platform.md)
