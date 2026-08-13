# Versioning and deprecation

## Version policy

Extensions are semver, and the platform attaches a specific meaning to each level:

| Level | Means | Governance |
|---|---|---|
| **patch** `1.2.0 → 1.2.1` | Behaviour fix; same contract, same permissions | Load freely |
| **minor** `1.2.1 → 1.3.0` | New capability, new optional input, **or any permission change** | Re-approval if permissions changed |
| **major** `1.3.0 → 2.0.0` | Breaking I/O, removed capability, changed semantics of an existing one | Deprecation window for callers |

Two rules that are enforced by the loader rather than by convention:

- **A permission expansion is never a patch.** The loader does not check the number,
  it checks the grant — so mislabelling the version does not help; the load still fails.
- **Downgrades are refused.** `registry.load()` rejects a version lower than the one
  running (`refusing downgrade from 1.2.0`). A rollback ships as a new forward version,
  so the audit trail is monotonic and "which code was running at 14:05" always has one
  answer.

## Compatibility of capabilities

A capability name (`issue_tracker.label`) is a public interface. Other extensions
declare it in `requires`, and the host routes by it.

| Change to a capability | Allowed? |
|---|---|
| Add a new capability | Yes, minor |
| Add an optional input field | Yes, minor |
| Add a required input field | No — major, with a window |
| Change output shape | No — major, with a window |
| Remove a capability | No — deprecation window; blocked while any loaded extension `requires` it |
| Rename | Not a rename: publish the new name, deprecate the old, remove after the window |

The registry knows the dependency graph (`provides` / `requires`), so a removal that
would break a caller is caught at review time, not at runtime.

## Contract versioning

`apiVersion: ext/v1` is itself versioned. When `ext/v2` lands:

1. the loader dispatches on `apiVersion` and supports both for one full window (180 days);
2. `ext migrate` rewrites v1 manifests mechanically where possible and reports what it
   cannot;
3. permissions are **re-reviewed** during migration rather than translated silently —
   a contract change is the natural moment to ask whether the authority is still needed;
4. after the window, v1 manifests fail to load.

## Deprecation

```python
registry.deprecate("cicd-status", successor="cicd-status@1.0.0",
                   sunset="2026-12-01", actor="governance-board")
```

A deprecated extension **keeps serving traffic**. It is visibly deprecated in
`ext list`, carries a successor and a sunset date, and callers are notified. Nothing
breaks on the day of deprecation, which is what makes the window credible.

| Situation | Minimum window |
|---|---|
| Capability that other extensions `require` | 90 days |
| Leaf extension with human callers only | 30 days |
| Security removal | 0 — that is a kill-switch, not a deprecation |

Notice template: [`templates/deprecation-notice.md`](templates/deprecation-notice.md).

## Removal

At sunset, with callers migrated: revoke, unload, delete the grant, keep the audit
history indefinitely. The name is not recycled — a future extension with the same name
would make historical audit records ambiguous.

## Emergency changes

Two paths exist and they are deliberately different:

| Path | Who | Effect |
|---|---|---|
| **Kill-switch** | Security on-call, alone, immediately | Stops the extension; no code change |
| **Emergency patch** | Author + one reviewer, expedited | Fixes behaviour; **cannot expand permissions** |

There is no emergency path that expands authority. If an incident genuinely requires
new authority, it requires the review board — under time pressure is exactly when that
check is most valuable.
