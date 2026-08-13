# Platform comparison — five hosts as peers

Comparing a custom host against Claude Code, Cursor, Copilot and LangGraph Platform on
the dimensions this project is graded on. No host is the assumed answer; the
recommendation at the end is conditional and states the conditions.

Assessed as of the platform's design date (mid-2026). Vendor capabilities move fast;
the *dimensions* are the durable part of this analysis, so re-run the table rather than
trusting the cells.

## The dimensions that actually differ

| Dimension | Custom host (this design) | LangGraph Platform | Claude Code | Cursor | GitHub Copilot |
|---|---|---|---|---|---|
| **Extension model** | Explicit 4-type contract (agent/tool/hook/connector) under one schema | Graph nodes + tools; agents are graphs | Tools, hooks, subagents, MCP servers, slash commands | Rules, MCP servers, custom modes | Extensions, MCP servers, custom agents |
| **Who defines the extension contract** | You | The framework | The vendor | The vendor | The vendor |
| **Non-developer surface** | Whatever you build (web app, Slack, ticket queue) | API/SDK + platform UI | Terminal/IDE-first — a poor fit for support agents | IDE only | IDE and repo-centric |
| **Isolation** | Yours: subprocess/WASM/microVM per invocation | Platform-managed containers; per-node isolation is not the primitive | Process-level, permission prompts, hooks | IDE sandbox | Runner/IDE sandbox |
| **Authorization model** | ABAC you own; two-key (manifest + policy) | Framework-level; policy is application code | Permission prompts + hooks; allow/deny lists | Approval prompts | Repo/org permissions |
| **Credential custody** | Host-held, per-action minted, never in extension code | Platform secret store; nodes typically receive credentials | MCP OAuth; per-server credentials | Account/IDE-scoped | GitHub identity + app tokens |
| **Untrusted-output handling** | Host-tracked taint + gate | Application's job | Vendor mitigations + hooks | Vendor mitigations | Vendor mitigations |
| **Human-in-the-loop primitive** | Confirmation bound to `resource:action:target` | Interrupt/checkpoint (a genuine strength) | Interactive prompts | Interactive prompts | PR review as the gate |
| **Governance lifecycle** | Yours: grants-as-data, permission diffing, kill-switch | Deployment versioning; permission governance is yours to add | Config-managed; org policy controls | Team settings | Org policy, allow-lists |
| **Audit** | Hash-chained, per-action, attributable | Platform traces (LangSmith) — excellent for debugging, not designed as a security audit trail | Session logs + hook output | Limited | Repo/audit log |
| **Operational burden** | High — you run everything | Medium — managed runtime, autoscaling, checkpointing | Low | Low | Low |
| **Build cost to reach this design** | High (weeks) | Medium | Low, but the model is not yours | Low | Low |
| **Fit for support-ticket triage** | Good | Good | Poor (developer-shaped) | Poor | Poor |
| **Fit for an SDLC instantiation** | Good | Good | **Excellent** (native VCS/CI/code context) | Good (in-IDE) | Good (PR-native) |
| **Lock-in cost** | Low on contract, high on build | Medium — graph runtime and deployment idioms | Medium — host conventions, tool/hook shapes | High — IDE-coupled | High — GitHub-coupled |

## What each peer is genuinely better at

Stated without hedging, because a comparison where the incumbent wins every row is a
sales document.

**LangGraph Platform** — durable execution. Checkpointing, resumable runs, interrupts
and time-travel debugging are real engineering we would otherwise build badly. Its
`interrupt` primitive is a *better* human-in-the-loop mechanism than our confirmation
provider, and its managed runtime removes the operational burden that is this design's
biggest cost.

**Claude Code** — for an SDLC worked domain it wins outright. Native repository context,
a mature tools/hooks/subagents/MCP extension model, and permission prompting that
already exists. If the worked domain here were code review or dependency triage, the
honest recommendation would be to build on it rather than reproduce it.

**Cursor** — the tightest inner loop for a developer sitting in an editor. Unbeatable
for developer-assist; structurally wrong for a workflow whose users never open an IDE.

**Copilot** — organisational reach and PR-as-the-approval-gate. If the workflow's
natural artifact is a pull request, that gate is free and already trusted.

**Custom host** — the only option that lets *us* define the security contract. Our
requirements are default-deny declared permissions, credentials that never reach
extension code, host-tracked taint, and a kill-switch with token revocation. Those are
properties of the host; you cannot add them from the outside.

## Where a hosted platform would have been enough

Being honest about when not to build this:

- if extensions were only ever first-party, a framework plus code review gets you most
  of the value;
- if no extension needed customer-visible write access, the gate matters much less;
- if there were one tenant, most of the scope machinery is dead weight;
- if the domain were SDLC, Claude Code's existing model is closer to this design than
  anything we would write in a quarter.

The reason to build is the *combination*: multi-tenant, customer-visible actions,
extensions from teams we do not control, and a governance story an auditor will read.

## Recommendation, with its conditions

Build on the **generic host/extension contract**, implement it first against a custom
host, and keep the LangGraph binding in the repository as a live second target.

Conditions under which this is wrong:

- **The worked domain moves to SDLC** → build on Claude Code; its extension model
  already covers the ground and the domain fit is decisive.
- **Operational cost dominates** (small team, no platform on-call) → LangGraph
  Platform, and give up the isolation guarantee explicitly rather than by accident.
- **Third-party publishers arrive** → neither: the blocker is capability attestation
  plus microVM/WASM isolation, and that is work regardless of host.

Migration mechanics: [`migration-path.md`](migration-path.md). What we would lose:
[`lock-in-analysis.md`](lock-in-analysis.md).
