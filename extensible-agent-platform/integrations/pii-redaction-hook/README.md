# `pii-redaction-hook` — hook

Runs before **every** privileged action. Redacts customer PII from outbound text and
vetoes any action carrying a credential-shaped string.

| Field | Value |
|---|---|
| Kind | hook |
| Version | 2.0.1 |
| Owner | team-privacy-engineering |
| Grant | none needed — **zero permissions** |
| Runtime | local-inproc (permitted precisely because it has no permissions and no egress) |
| Events | `pre_action` |

## Where it sits

```
proposal → [ pii-redaction-hook ] → GATE → broker → sandbox → audit
```

Host-side, before the gate. Two consequences: its veto is authoritative (an extension
cannot bypass it any more than it can bypass the gate), and parameters are final before
the gate judges them — a hook that rewrote them afterwards would mean the gate authorized
something other than what ran
([ADR-011](../../adrs/ADR-011-hook-veto-placement.md)).

## What it does

| Input | Action |
|---|---|
| Email addresses in `body`/`reason`/`summary`/`comment` | → `[redacted-email]` |
| Phone numbers | → `[redacted-phone]` |
| Card-shaped digit runs | → `[redacted-card]` |
| Credential-shaped strings (`sk-`, `ghp_`, `tkn_`, `access_token =`, "credential store") | **veto the whole action** |

Every invocation is audited with `mutated` and `blocked` flags plus the hook's own notes,
so a silent redaction that changes an action's meaning is visible.

## Why this is an extension, not host code

Redaction policy changes faster than host releases, and the team that owns it
(privacy engineering) should ship on its own schedule. Being an extension also means it
gets the governance lifecycle — and that `host.kill("pii-redaction-hook", …)` works, which
is uncomfortable and correct: a hook that vetoes everything must be pullable.

## In the injection scenario

When the hijacked triage agent proposes a comment containing
`access_token = fixture-issue-tracker-access-token`, this hook blocks it **before** the
gate evaluates anything. Defence in depth that falls out of the ordering.

## Known limitation

Multiple mutating hooks have undefined interaction order (load order today). Fine with
one; a priority declaration is needed before a second mutating hook ships.
