# Tenant Isolation — Demonstration

**Stretch goal:** demonstrate that one tenant's data and toggles cannot leak into another's.


> **Executable:** tests T-1…T-10 below are implemented in
> [`prototype/tests/test_isolation.py`](../prototype/tests/test_isolation.py).


Tenants: `SYN-TEN-northwind` (region A) and `SYN-TEN-meridian` (region B).

## 1. Isolation claims

| # | Claim | Mechanism |
|---|---|---|
| I-1 | Tenant A's records cannot be read by tenant B | Per-tenant CMK; storage-layer tenant predicate; token carries tenant |
| I-2 | Tenant A's vetted corpus cannot ground tenant B's output | Index partitioned by tenant; filter applied **at** the index, not after |
| I-3 | Tenant A's toggles cannot affect tenant B | Flag keys are tenant-scoped; resolution is per-request |
| I-4 | Tenant A's audit entries cannot appear in tenant B's queries | Separate ledger shards; queries are tenant-bound at the API |
| I-5 | Model boundary carries no cross-tenant state | Zero retention, no training ([ADR-009](../adrs/ADR-009-no-training-on-tenant-data.md)); per-request context only |
| I-6 | A compromised token from A is useless against B | Token binds tenant + audience; B's services reject A's audience |
| I-7 | Cross-region copy is inert | KMS key policy is region- and tenant-bound; ciphertext moved to B cannot be decrypted |

## 2. Tests and expected results

| Test | Method | Expected | Ledger evidence |
|---|---|---|---|
| T-1 Direct read | B's service identity requests `SYN-MRN-000123` (an A record) | Deny at storage predicate **and** decrypt failure at KMS | `access.denied {cause:TENANT_MISMATCH}` |
| T-2 Retrieval bleed | Ask CARA as B a question whose best answer lives only in A's corpus (`SYN-VS-CLIN-002`) | Refuse — no compatible in-tenant span | `grounding.failed {reason:NO_SUPPORTING_SPAN}` — **not** an answer sourced from A |
| T-3 Semantic probe | As B, query with text lifted verbatim from A's protocol | Zero hits; index partition returns nothing | `retrieval.empty {partition:B}` |
| T-4 Toggle bleed | Turn `draft.summary` off for A | B unaffected; A degraded | `toggle.changed {scope:tenant, tenant:A}` only |
| T-5 Global vs tenant | Turn global off | Both degraded; turning A back on does **not** re-enable A (conjunctive) | `flags.resolved {global:off}` |
| T-6 Audit query | As B, query `subject_ref=SYN-MRN-000123` | Empty; shard is not addressable | `query.denied {cause:CROSS_TENANT}` |
| T-7 Token replay | Present A's valid token to B's endpoint | 401 — audience mismatch | `authn.failure {cause:AUDIENCE_MISMATCH}` |
| T-8 Ciphertext relocation | Copy A's encrypted blob into B's bucket, attempt read | Decrypt denied by key policy | `kms.denied {cause:KEY_POLICY}` |
| T-9 Alias collision | Force `subject_alias` collision across tenants | No effect: aliases are per-request and per-tenant, never a join key | — |
| T-10 Shared cache probe | Issue identical prompts as A and B; check for cached-response reuse | No reuse — cache keys include tenant | `cache.miss {tenant:B}` |

T-10 deserves emphasis. **Response caching is the most likely accidental cross-tenant
channel in a system like this**, because a cache keyed on prompt content alone looks
correct, performs beautifully, and silently serves tenant A's answer to tenant B when two
prompts coincide. The cache key is `(tenant, capability, prompt_hash, model_version,
corpus_version)` and the tenant component is not optional. A test that does not probe the
cache has not tested isolation.

## 3. Deliberately *not* isolated

Three things are shared, and each is justified:

| Shared | Why it is safe |
|---|---|
| Code and container images | No tenant data; identical for all |
| Flag *definitions* (the schema of what flags exist) | Definitions, not values; values are tenant-scoped |
| Aggregate operational metrics | k-anonymity floor of 20 on any tenant-level breakdown; no individual referent |

The third is the one to watch: a metric broken down finely enough becomes a re-identifier.
The k-floor is a control, not a convention, and it is enforced at query time.

## 4. What this does *not* prove

Isolation is demonstrated at the storage, index, flag, cache, token, and key layers. It is
**not** proven at the level of a compromised control-plane service identity with legitimate
multi-tenant scope (e.g. the retention job). Those identities exist, are minimised, are
monitored, and their actions are audited — but a full compromise of one is a real residual
risk, not an eliminated one. Saying so is more useful than a claim of total isolation that
would not survive a determined reviewer.
