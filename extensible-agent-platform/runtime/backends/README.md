# Simulated external systems

These stand in for real SaaS products so the platform runs offline. They are reachable
**only** through the host egress proxy — extensions have no network — and they behave like
real APIs on the axes that matter for the security model:

- they validate the injected bearer credential (`401 invalid_token`);
- they check OAuth scope per route (`403 insufficient_scope`);
- the knowledge base rejects writes (`403 read_only_integration`).

| Module | Domain | Deliberate fixtures |
|---|---|---|
| `issue_tracker.py` | `issues.example.internal` | `T-1042` clean billing ticket with PII · `T-1043` carries a planted injection, high priority · `T-1044` tenant `globex` (read-only by policy R-901) |
| `knowledge_base.py` | `kb.example.internal` | `KB-101`/`KB-102` normal runbooks · **`KB-207` poisoned escalation matrix** |
| `cicd.py` | `ci.example.internal` | `support-platform` pipeline failing at `migrate-realms` on purpose |

`reset_all()` restores mutable state between tests.

**Swapping these for real HTTP clients is the only change needed to point the platform at
production SaaS.** No manifest, no policy rule, no grant and no test outside these files
changes — which is the property the whole contract exists to produce.
