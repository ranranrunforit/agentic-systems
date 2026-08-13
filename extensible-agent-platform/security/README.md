# Security model

Five documents, one thesis: **an extension holds no authority of its own.**

| Document | Covers | Requirement |
|---|---|---|
| [`identity-and-oauth.md`](identity-and-oauth.md) | Identity, OAuth delegation, who an extension acts as | FR-2 |
| [`authorization.md`](authorization.md) | ABAC, the two-key rule, default-deny, scope | FR-2 |
| [`token-lifecycle.md`](token-lifecycle.md) | Issue → scope → rotate → revoke, least privilege | FR-2 |
| [`isolation.md`](isolation.md) | Local and remote execution isolation, containment evidence | FR-2, NFR-2 |
| [`injection-defenses.md`](injection-defenses.md) | Trust boundary, taint, the action-confirmation gate | FR-3 |
| [`threat-model.md`](threat-model.md) | Adversaries, assets, attack paths, what is *not* mitigated | — |
| [`policy/abac-policy.yaml`](policy/abac-policy.yaml) | The org policy itself, as data | FR-2 |

## The four invariants everything else serves

1. **Default-deny everywhere.** No approved grant, no authority. No policy rule, no
   action. No declared scope, no reach. The word `deny` is the policy default and the
   registry default and the gate default.
2. **No ambient authority.** Extensions get no environment variables, no long-lived
   credentials, no shared filesystem, no sockets. Every capability is a declared,
   granted, per-call thing.
3. **Model output is not an action.** Intent and execution are separated by the gate.
   This is one mechanism doing double duty: prompt-injection defence and
   excessive-agency control.
4. **Everything is attributable.** Every decision and action carries actor, extension
   version, tenant, intent hash and reasons into a hash-chained log.

## Verify the claims

```bash
make test          # 63 tests; TestAuthorization / TestTokenLifecycle / TestIsolation / TestInjection
make containment   # a rogue extension attempts nine escapes; all nine fail
make injection     # a planted instruction reaches the gate and dies there
```
