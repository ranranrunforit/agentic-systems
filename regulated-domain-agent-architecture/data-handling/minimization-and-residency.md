# Minimization at the Model Boundary & Residency — FR-1

## Part 1 — Minimization [AGNOSTIC mechanism, REGIME parameter]

### The claim

HIPAA's minimum-necessary standard (O-P2) is usually implemented as policy: *staff should
only look at what they need*. For an agentic system that is not good enough, because the
"looker" is a model whose behaviour is not constrained by a training module. So
minimum-necessary here is a **projection performed before prompt assembly**, and the
projection is evidence.

### Per-capability allow-lists

The Policy Engine returns a versioned allow-list keyed by `(capability, role, context)`.

| Capability | Allow-listed field paths | Rationale |
|---|---|---|
| `qa.general` | *(none — no patient in context)* | Non-specific content needs no PHI |
| `qa.record` | `problem_list[]`, `medications[]`, `labs[].{name,value,unit,date→T-RELDATE}`, `allergies[]`, `age_band` | The narrowest set that supports record Q&A |
| `draft.summary` | above + `notes[].text→T-REDACT`, `encounter.reason`, `vitals[]` | Drafting needs narrative context |
| `action.schedule` | `problem_list[]`, `medications[]` (name only), `next_due[]`, `age_band` | Scheduling needs indications, not the full chart |

Rules:
- The allow-list is **maximal, not typical**: within a capability, the runtime requests a
  *subset* per task, and the manifest records what was actually included.
- Allow-list changes are versioned, reviewed, and effective-dated; the manifest records
  the allow-list version so a past decision can be re-evaluated against the rules in force
  at the time.
- A field never on any allow-list (all D3) cannot be added at runtime by any prompt,
  tool, or user instruction.

### The `minimization_manifest`

```json
{
  "correlation_id": "SYN-COR-9f21c0",
  "tenant": "SYN-TEN-northwind",
  "capability": "draft.summary",
  "allowlist_version": "v7",
  "subject_ref": "SYN-MRN-000123",
  "subject_alias": "subj_7d41",
  "fields_included": [
    {"path": "problem_list[]", "count": 4, "transform": null},
    {"path": "medications[]", "count": 6, "transform": null},
    {"path": "labs[]", "count": 9, "transform": "T-RELDATE-v1"},
    {"path": "patient.dob", "transform": "T-AGEBAND-v1", "emitted_as": "age_band"},
    {"path": "notes[].text", "count": 2, "transform": "T-REDACT-v1",
     "redactions": {"PERSON": 3, "PHONE": 1}}
  ],
  "fields_excluded_by_class": ["patient.name", "patient.mrn", "patient.ssn",
                               "patient.phone", "insurance.member_id"],
  "prompt_hash": "sha256:4b1c…",
  "boundary": {"endpoint": "inference-region-a", "region": "region-a",
               "retention": "zero", "training": "prohibited"}
}
```

The manifest is written to the ledger, not the prompt. It contains **field paths and
counts, never values**, and the `subject_ref` is a record reference — so the manifest is
itself D0 and can be retained on the longer audit clock.

### What the manifest buys

1. **Minimum-necessary becomes testable.** An auditor samples requests and checks that no
   field outside the task's need appears.
2. **Breach scoping becomes arithmetic** (O-B2). If an inference endpoint were
   compromised on a given day, the exposed field set per affected request is already
   recorded — no forensic re-reading of PHI required to answer "what was exposed".
3. **Drift is detectable.** An alert fires when a capability emits a field path outside
   its historical distribution.

### Anti-pattern this replaces

Sending the whole chart and instructing the model to "only use what's relevant". That is
a disclosure of the whole chart to a subprocessor, dressed as an instruction. Under the
minimum-necessary standard, the disclosure already happened when the prompt was sent.

---

## Part 2 — Residency [REGIME]

### Rule

For each tenant, a **contracted region** is configured. All of the following are pinned to
it: the record store, the object store, the vetted corpus and its retrieval index, the
inference and embedding endpoints, the audit ledger shard, and the approval console's
data plane.

### What may leave the region

| Leaves? | Item | Why it is safe |
|---|---|---|
| ✅ in | Tenant configuration, allow-lists, flag definitions, code | Contains no individual data |
| ✅ out | **Audit chain root hashes** (one per day per shard) | A hash of hashes; no content, no references |
| ✅ out | Aggregate operational metrics (counts, latencies, tier distribution) | No individual referent; k-anonymity floor of 20 on any tenant-level breakdown |
| ❌ | Records, prompts, model outputs, citations, manifests, ledger entries | Region-pinned, full stop |

### Enforcement, not aspiration

- **Egress policy** at the model boundary allow-lists endpoint hostnames per region; a
  region mismatch is denied and audited (`egress.denied {cause:REGION_MISMATCH}`, FC-7).
- **KMS key policy** binds each tenant CMK to its region; data encrypted in region A
  cannot be decrypted by a service principal in region B, so an accidental cross-region
  copy is inert.
- **Deployment guardrails** prevent a service in one region from being configured with a
  data-plane endpoint in another; the check runs at deploy time and continuously.

### Why residency is tagged [REGIME] and not [AGNOSTIC]

HIPAA itself does **not** impose a residency requirement. Residency appears here because
tenant BAAs, state law, and customer procurement terms impose it — which is exactly the
character of a regime-shaped control: its *existence* depends on the regime and the
contract, not on responsible-AI principles. In the portability analysis it comes out
**relaxed** for some finance contexts and **tightened** for public sector (ATO
boundaries). Listing residency as a universal responsible-AI control is the most common
classification error in this project; see
[`portability/portability-analysis.md`](../portability/portability-analysis.md) §5.

### Multi-region tenants

A tenant operating in two regions is modelled as two tenant instances with separate keys,
corpora, ledgers, and flags. Cross-region aggregation, if ever required, happens on
metrics only. There is no "global patient view"; assembling one would move PHI across a
boundary the tenant contracted to keep.
