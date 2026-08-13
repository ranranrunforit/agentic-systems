# Deprecation notice — `<extension-name>@<version>`

| Field | Value |
|---|---|
| Extension | `<name>@<version>` |
| Deprecated on | `<YYYY-MM-DD>` |
| **Sunset (stops working)** | `<YYYY-MM-DD>` |
| Successor | `<name>@<version>` or "none — capability withdrawn" |
| Owner | `<team>` |
| Review ticket | `GOV-___` |

## Why

One paragraph. If this is a security withdrawal, say so — and note that a security
withdrawal is a kill-switch with a notice attached, not a normal deprecation.

## Who is affected

Extensions that declare the affected capabilities in `requires`:

| Caller | Capability used | Owner | Migration status |
|---|---|---|---|

Human callers / workflows:

## What changes for callers

| Before | After |
|---|---|
| `ctx.call("<old.capability>", {...})` | `ctx.call("<new.capability>", {...})` |

Behaviour differences beyond the name:

## Migration steps

1. Update `capabilities.requires` in your manifest.
2. Adjust the call payload as above.
3. `ext validate` and `ext test`.
4. If your permissions change, expect re-approval.
5. Ship before the sunset date.

## Timeline

| Date | Event |
|---|---|
| `<date>` | Notice published; deprecation recorded in the registry |
| `<date>` | Successor available |
| `<date>` | Reminder to unmigrated callers |
| `<date>` | **Sunset — revoked and unloaded** |

Until sunset the extension keeps working normally. Questions: `<channel>`.
