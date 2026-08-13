# ADR-002 — Grounding strategy and the definition of a vetted source

**Status:** Accepted · **Date:** 2026-08-13 · **Owner:** Clinical Safety Officer (DC-5, DC-10)

## Context

FR-4 requires high-risk factual output to be grounded in vetted sources with citations, and
requires the agent to refuse or escalate when it cannot ground a claim. "Vetted source"
must be defined concretely or the control is unfalsifiable.

## Decision

1. **Vetted source** = a document or record span that is admitted by a named accountable
   role, versioned with provenance, currently valid, and **authoritative for the claim
   type** (the last clause enforced by a claim-type → source-class matrix).
2. For healthcare, the admitted classes are: the patient's own record (S1), tenant clinical
   protocols (S2), licensed clinical references (S3), tenant operational policy (S4), and
   regulatory text (S5).
3. **Prohibited as grounding:** the model's parametric knowledge, the model's own prior or
   intermediate output, the open web, other tenants' data, user assertions in the
   conversation, and expired or withdrawn documents.
4. Verification is **per atomic claim** by a verifier model *separate from the generator*,
   with **veto-only deterministic checks** on numbers, dates, negation/polarity, and entity
   binding.
5. Thresholds `τ_hard = 0.85` / `τ_soft = 0.60` are versioned configuration recorded in
   every grounding event and owned by the Clinical Safety Officer.

## Rationale

- **Claim-type compatibility, not just similarity.** A drug monograph can be highly similar
  to a claim about what *this patient* takes and be the wrong authority for it. Similarity
  answers "is this text related?"; authority answers "may this text settle the question?".
  Only the second is a control.
- **Self-grounding is the specific agentic failure mode.** In a multi-step loop the model's
  intermediate output is the most available "evidence" in context. If it is admissible, an
  unsupported claim launders itself into a supported one over two hops. Making the
  prohibition structural (intermediates are never written to a retrievable store) beats
  making it a prompt instruction.
- **Separate verifier.** A generator asked to check itself shares its errors. Independence
  is the point, not model quality.
- **Deterministic vetoes** because entailment models are unreliable exactly where the
  stakes are highest: a transposed digit in a dose or a dropped negation is a small
  semantic distance and a large clinical one.
- **Recall over precision.** A false "unsupported" costs a refusal. A false "supported"
  costs an ungrounded clinical assertion delivered to a clinician. These are not
  symmetric, so the calibration is not symmetric.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Model self-reported confidence | Confidence is not calibrated to truth and is trivially high on fluent fabrication. This is the "model is usually right" control the brief explicitly rules out. |
| Retrieval presence alone ("we did RAG") | Retrieving a document does not entail that the claim follows from it. Un-verified RAG produces citations that do not support the sentences they are attached to — arguably worse than no citation, because it looks checked. |
| Grounding only the final answer | Misses the loop: an ungrounded intermediate steers tool calls and the final answer's framing before final verification ever runs. |
| Post-hoc disclaimer ("verify independently") | Shifts the control to the reader while the output still asserts. Not a control. |
| Fine-tuning on tenant data to reduce hallucination | Does not bound the failure, conflicts with [ADR-009](ADR-009-no-training-on-tenant-data.md), and creates a data-use problem in exchange for an unmeasurable benefit. |

## Consequences

- Refusal rate becomes a first-class product metric; corpus gaps, not prompts, are the
  usual fix.
- Corpus admission is a governed workflow with a named owner (DC-9), i.e. real operational
  cost for tenants.
- Latency increases (decomposition + retrieval + entailment per claim), accepted for
  Tier 2/3.
- Threshold changes require an ADR amendment and an eval re-run — deliberate friction on a
  number that silently governs safety.
