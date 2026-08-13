# ADR-004 — Residency by per-tenant region pinning

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Vendor Product Security + Tenant Privacy Officer

## Context

HIPAA imposes no geographic residency requirement. Tenant BAAs, state law, and procurement
terms routinely do. FR-1 requires residency/region constraints to be designed in.

## Decision

Each tenant is bound to a **contracted region**. Record store, object store, vetted corpus
and its index, **inference and embedding endpoints**, audit ledger shard, and the approval
console data plane are all pinned to it. Only two things cross the region boundary:
configuration inbound, and **audit chain root hashes** outbound. Multi-region tenants are
modelled as separate tenant instances.

## Rationale

- **Model endpoints are the boundary people forget.** Pinning storage while calling a
  globally-routed inference endpoint means the data does leave — as a prompt. The prompt is
  a disclosure to a subcontractor, in whatever region it is served from.
- **Enforcement must be layered, not contractual alone.** Egress allow-lists (deny on
  region mismatch), region-bound KMS key policies (a cross-region copy is inert
  ciphertext), and deploy-time guardrails. Any single layer can be misconfigured.
- **Hash-only egress makes external notarisation compatible with residency.** A daily root
  hash carries no content and no references, so third-party timestamping does not breach
  the pin.
- **Residency is [REGIME], and parameterising it is the point.** Because it is
  configuration rather than structure, the finance re-derivation can relax it and the
  public-sector delta can tighten it to an ATO boundary without touching the architecture.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Single global deployment with contractual assurances | Assurance is not enforcement; a misrouted request is a disclosure. |
| Region-pinned storage, globally-routed inference | The prompt is the disclosure. This is the most common version of the mistake. |
| Global audit ledger for a single ordered chain | Ledger entries contain record references; centralising them moves regulated identifiers across the boundary. Per-shard chains with independent anchors give the same tamper evidence. |
| Client-side encryption with tenant-held keys throughout | Attractive, but the model boundary needs plaintext to do anything useful; it would move the problem rather than solve it, while breaking retrieval. |

## Consequences

- No single global model pool; capacity and cost efficiency are worse. Accepted.
- Per-region operational overhead (deploys, capacity, on-call, model availability).
- New regions require a model endpoint in-region — a real constraint on where the product
  can be sold, and one that should be checked before signing, not after.
- Cross-tenant/cross-region aggregate analytics are limited to metrics with a k-anonymity
  floor.
