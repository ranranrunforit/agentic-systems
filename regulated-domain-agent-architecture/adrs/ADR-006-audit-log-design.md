# ADR-006 — Hash-chained, append-only, reference-only audit ledger

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Vendor Security Officer

## Context

FR-2 requires a tamper-evident, queryable audit trail capturing who/what/when/why **and the
inputs that produced each decision**. Retention obligations pull in opposite directions:
audit documentation must be kept ≥ 6 years while records must be deleted on schedule.

## Decision

Append-only, per-region-shard **hash-chained** ledger (`hash_n = SHA-256(prev_hash ||
JCS(event))`), daily root anchored to object-locked WORM storage and to an external notary,
verified by an independent read-only job. **No update or delete verb exists.** Payloads
carry **references and hashes only** — never raw sensitive content. Writes are
**synchronous and blocking for consequential events**; a local hash-chained journal covers
ledger unavailability with a `deferred_write` marker.

## Rationale

- **Reference-only is what makes the two retention clocks compatible.** If the log embedded
  clinical text, deleting a record on schedule would either break the chain or leave the
  content behind — the audit trail becomes the thing that violates the obligation it exists
  to demonstrate. With references, deletion removes content while the chain still verifies
  and still proves *that* a decision happened, by whom, when.
- **Hash-chaining over "immutable storage" alone** because object-lock proves an object was
  not altered; a chain proves entries were not *removed or reordered*, which is the
  likelier form of convenient forgetting.
- **External anchoring** bounds the undetected-tamper window to the anchor interval and
  removes the "we control the storage that proves we didn't tamper" objection.
- **Inputs, not just outcomes.** Reconstructing a decision requires the model version, the
  parameters, the retrieved evidence, the flag snapshot, and the minimization manifest at
  that moment. Logging the answer alone reconstructs nothing.
- **Synchronous on consequential events**, because tamper evidence proves entries were not
  altered *after* writing but proves nothing about entries never written. Blocking is the
  only thing that closes that gap.
- **HMAC with a tenant secret for short-identifier hashes**, since a plain hash of a
  low-entropy field is brute-forceable.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Standard application logs + retention policy | Mutable, deletable, not reconstructable, no integrity proof. |
| Blockchain / distributed ledger | Solves a trust-distribution problem we do not have, while creating residency, cost, and key-management problems we do. |
| Full content in the log "for completeness" | Directly violates record retention/deletion; also worsens the blast radius of a log compromise. In public sector it would be worse still, since the log may be disclosable. |
| Asynchronous writes everywhere | Faster, but permits an unlogged consequential action — the exact gap the requirement targets. |
| Single global chain | Moves record references across residency boundaries. |

## Consequences

- 15–40 ms p50 added latency on consequential paths.
- Investigations must join ledger references to record content, and after deletion some
  content is legitimately unavailable — a *feature*, but one investigators must be briefed
  on.
- Clock discipline is a correctness requirement (skew > 2 s quarantines a node).
- The chain verifier is itself a control that must be monitored; a silent verifier failure
  is a silent loss of tamper evidence.
