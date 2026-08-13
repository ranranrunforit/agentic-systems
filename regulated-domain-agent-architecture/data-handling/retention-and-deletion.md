# Retention & Deletion — FR-1

## The structural problem

Two clocks point in opposite directions:

- **Records** must be deleted when their retention period expires (tenant/state clock, O-R2).
- **Audit trails** must be retained *longer* and must be tamper-evident (O-S11, ≥ 6 years
  for documentation; longer by tenant policy).

If the audit trail embeds record content, deleting the record is impossible without
breaking the chain — and the audit trail becomes the thing that violates the retention
obligation it was built to demonstrate. This is the failure mode the design is built to
avoid.

## Resolution: the ledger holds references and hashes, never content

| Ledger field | Holds | Never holds |
|---|---|---|
| `subject_ref` | `SYN-MRN-000123` (a record identifier, D0 within the tenant's own region) | Name, DOB, address |
| `content_hash` | `sha256:…` of the output that was released | The output text |
| `citation_refs` | Vetted-document IDs + span offsets | The span text |
| `minimization_manifest` | Field *paths*, counts, transform IDs | Field *values* |
| `prompt_hash` | `sha256:…` | The prompt |

Consequence: deleting a record deletes the content; the ledger keeps the *fact* that a
decision occurred, its shape, and its hashes. The chain still verifies, because hashes of
deleted content are still hashes. An auditor can still prove *that* a Tier-3 output was
approved by whom and when — they simply cannot re-read the clinical text, which is
correct, because that text was legally required to be gone.

> **Hash-of-deleted-content caveat.** A hash of a small, low-entropy field is
> re-identifiable by brute force. That is why the ledger hashes *whole artefacts*
> (prompt, output document) rather than individual field values, and why per-tenant
> hashing keys (HMAC with a tenant secret) are used for any hash over a short identifier.

## Retention schedule

| Data | Clock | Default | Configurable per tenant | On expiry |
|---|---|---|---|---|
| Clinical records in CARA's store (cached projections) | Tenant record policy (O-R2) | Mirror tenant EHR policy | Yes (required at onboarding) | Hard delete |
| Conversation transcripts (staff ↔ agent) | Operational | 90 days | Yes, 30–730 days | Hard delete |
| Draft artefacts not accepted into the record | Operational | 30 days | Yes | Hard delete |
| Approved output that entered the record | Tenant record policy | Governed by the EHR, not by us | n/a | EHR-governed |
| Prompts and model outputs at the inference provider | Contract | **Zero retention** | No — non-negotiable term | n/a |
| Vetted corpus documents | Licence term | Licence-driven | Yes | Excluded from retrieval at `valid_until`; retained as an archived version for reconstruction of past decisions |
| **Audit ledger entries** | O-S11 + tenant | **≥ 6 years**, tenant may extend | Extend only, never shorten | Ledger is append-only: entries age out to cold WORM storage, they are not deleted within the retention window |
| Operational metrics (aggregate) | Operational | 13 months | Yes | Aggregate rollup |

## Deletion mechanics

1. **Trigger** — retention expiry job, tenant-initiated purge, or an erasure request from
   the [DSR flow](../stretch/consent-and-data-subject-rights.md).
2. **Scope resolution** — the record ref resolves to: cached projections, transcripts,
   drafts, retrieval-index entries derived from the record, and any object-store blobs.
3. **Hard delete** — content removed from primary storage; index entries removed;
   backups handled by **crypto-shredding** (the record's data key is destroyed, rendering
   backup ciphertext unrecoverable) because selective deletion inside immutable backups is
   not achievable.
4. **Verification** — a post-deletion probe attempts retrieval by ref and by semantic
   query; both must return nothing. Result recorded.
5. **Audit** — `deletion.executed {subject_ref, scope, method, verified_at, actor}` is
   appended to the ledger. The deletion event is itself part of the tamper-evident chain,
   which is how a tenant proves deletion happened.

## Legal hold

A `legal_hold` flag on a record ref suspends all deletion jobs for that ref and is itself
audited (`hold.placed` / `hold.released` with actor and reason). Deletion jobs check holds
transactionally; a hold placed mid-job aborts the job for that ref. Holds cannot be placed
or released by the agent — only by a named human role.

## What "hard delete" means at the model boundary

Nothing to delete: the inference provider is contracted for zero retention and no
training ([ADR-009](../adrs/ADR-009-no-training-on-tenant-data.md)), and embeddings
derived from records are stored **in-region, in the tenant's index**, and are deleted with
the record. Treating embeddings as non-sensitive derived data is a mistake — an embedding
of a clinical note is a lossy but partially invertible representation of PHI, and it is
classified D2 accordingly.

## Retention as a [REGIME] control

Duration, ownership, and the very existence of a maximum retention period are
regime-shaped. The *mechanisms* — reference-only audit entries, crypto-shredding,
verified deletion, legal hold — are agnostic. In the finance re-derivation this row comes
out **tightened** (SOX-era record retention is typically longer and the audit trail
becomes a financial-reporting artefact); in edtech it comes out **replaced** (FERPA/COPPA
add parental-request-driven deletion with different triggers).
