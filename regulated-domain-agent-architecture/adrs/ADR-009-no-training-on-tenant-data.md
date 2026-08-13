# ADR-009 — Zero retention and no training at the model boundary

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Vendor Product Security

## Context

The inference provider is a **subcontractor business associate** (O-P8). Whatever crosses
the model boundary is a disclosure to that subcontractor, and the terms governing it are
part of the architecture, not merely of procurement.

## Decision

Inference and embedding providers are contracted for: **zero retention** of prompts and
outputs, **no training or fine-tuning** on tenant data, **region-pinned serving**, and
flow-down of BAA obligations. The provider list is versioned, audited configuration
enforced by an **egress endpoint allow-list**. Embeddings derived from records are stored
**in-tenant, in-region**, classified **D2**, and deleted with the record.

## Rationale

- **Zero retention makes the deletion story coherent.** If the provider retains prompts,
  "hard delete" is false the moment the record was ever used in a prompt, and no amount of
  in-house deletion machinery fixes it.
- **No training prevents cross-tenant leakage through weights** — a leakage path that no
  network control, key policy, or index partition can address, and that cannot be undone
  once it has happened.
- **Embeddings are not de-identified derived data.** An embedding of a clinical note is a
  lossy but partially invertible representation of PHI; classifying it D0 because it "looks
  like numbers" is a common and serious error. Classifying it D2 makes its residency and
  deletion follow the record automatically.
- **Enforced by allow-list, not by trust.** The contractual term is necessary; the egress
  control is what makes it observable.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Provider retention for abuse monitoring | Reasonable in consumer contexts; incompatible with a BAA-governed deletion obligation here. Where a provider requires it, they are not eligible. |
| Fine-tuning per tenant for quality | Creates a weights-shaped copy of tenant data with no deletion story, and would need its own residency, retention, and access model. The grounding pipeline is the better lever for quality. |
| Treating embeddings as non-sensitive | Wrong on the facts (inversion attacks), and it silently breaks residency and deletion. |
| Self-hosting the model to avoid the question | Legitimate, and compatible with this design; rejected as a *requirement* because it constrains tenants unnecessarily. Contracted terms plus egress enforcement achieve the same properties. |

## Consequences

- Narrows the eligible provider set and makes model choice a compliance decision.
- No product-improvement learning from tenant data; quality improvements must come from
  the corpus, retrieval, prompts, and evaluation on synthetic data.
- Embedding storage and its deletion pipeline are per-tenant and per-region, with the
  attendant cost.
- Provider changes are governed (DC-10) and trigger a re-run of the grounding eval suite.
