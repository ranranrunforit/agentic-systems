# Audit Log Specification — FR-2 [AGNOSTIC]

Requirement restated: *every consequential agent action and model decision is logged with
who/what/when/why and the inputs that produced it, in a tamper-evident, queryable audit
trail.*

## 1. What counts as consequential

| Consequential (synchronous ledger write, action blocks on it) | Non-consequential (asynchronous, buffered) |
|---|---|
| Output released to a human | Cache hits, retries |
| Action executed via a tool | Health checks |
| Approval granted / rejected / expired | Debug traces |
| Refusal or escalation | Latency metrics |
| Access allow / deny | UI navigation |
| Data crossing the model boundary | Token refresh |
| Toggle change and toggle-driven degradation | |
| Deletion, legal hold, restriction flag change | |

The rule: **if it changed what a human saw, what a system did, or what data crossed a
boundary, it is consequential.** Consequential events fail closed — no ledger write, no
action (FC-6).

## 2. Event schema

```json
{
  "seq": 184023,
  "event_id": "SYN-EVT-0001a4",
  "prev_hash": "sha256:9c2e…",
  "hash": "sha256:1f77…",
  "ts": "2026-08-13T09:14:22.481Z",
  "shard": "region-a",
  "tenant": "SYN-TEN-northwind",
  "correlation_id": "SYN-COR-9f21c0",
  "span_id": "grounding.verify",

  "actor": {"type": "human|agent|system", "id": "SYN-USR-4471",
            "role": "supervising_clinician", "session": "SYN-SES-31", "ip_hash": "sha256:…"},
  "action": "approval.granted",
  "subject_ref": "SYN-MRN-000123",
  "capability": "draft.summary",

  "why": {"reason_code": "TIER3_CLINICAL_ASSERTION",
          "rule": "R3-PATIENT-ASSERTION",
          "policy_version": "v7",
          "narrative": "Referral letter asserts patient-specific clinical facts."},

  "inputs": {
    "prompt_hash": "sha256:4b1c…",
    "minimization_manifest_ref": "SYN-EVT-00019f",
    "retrieved_spans": [{"doc": "SYN-VS-CLIN-002", "span": "12:874-1102", "hash": "sha256:…"}],
    "model": {"id": "model-x", "version": "2026-05", "endpoint": "inference-region-a",
              "params_hash": "sha256:…", "temperature": 0.2},
    "flags_snapshot": {"global": "on", "tenant": "on", "feature": "on",
                       "flag_version": "fv-2291"}
  },

  "outcome": {"decision": "released", "content_hash": "sha256:aa03…",
              "edits": 2, "edits_hash": "sha256:…", "risk_tier": 3},

  "chain": {"algo": "sha256", "canonicalisation": "JCS (RFC 8785)"}
}
```

### Who / what / when / why — explicitly

| Question | Field |
|---|---|
| **Who** | `actor` (type, id, role, session) — and for automated decisions, `accountable_role` from the [accountability model](accountability-model.md) |
| **What** | `action`, `capability`, `subject_ref`, `outcome` |
| **When** | `ts` (UTC, RFC 3339, monotonic per shard) |
| **Why** | `why.reason_code` + `why.rule` + `why.policy_version` — a machine-checkable reason, not free text alone |
| **Inputs that produced it** | `inputs` — prompt hash, minimization manifest reference, retrieved spans (by ref + hash), model identity and parameters, flag snapshot |

That last row is the one most systems miss. Reconstructing a decision requires knowing the
*model version and the retrieved evidence at that moment*, not just the answer.

## 3. Tamper evidence

```
hash_n = SHA-256( prev_hash || JCS(canonical_event_without_hash) )
```

- **Append-only by construction.** The ledger API exposes `append`, `read`, `query`,
  `verify`. There is no update or delete verb, and the service identity's storage
  permissions do not include overwrite or delete on the ledger objects.
- **Per-shard chains.** One chain per region shard; global ordering is not required and
  would violate residency.
- **Daily anchoring.** Each shard's root hash at 00:00 UTC is written to WORM object
  storage with an object-lock retention of 6 years, and submitted to an **external
  notary** (a third-party timestamping service). Only the hash leaves the region.
- **Independent verifier.** A verifier job re-computes the chain from cold storage on a
  separate service identity that has read-only access, and publishes `chain_ok`,
  `first_bad_seq`, and the anchor comparison.
- **What tamper evidence does and does not give.** It proves that entries have not been
  altered or removed *after* anchoring, and bounds any undetected window to the anchoring
  interval. It does not prove an event was written in the first place — that is what
  synchronous, fail-closed writes on consequential events are for. Both are needed; either
  alone is a gap.

## 4. No sensitive content in the ledger

Enforced at write time by a schema validator: fields carrying free text are rejected
unless declared `redacted:false` and classified D0. Payload references only:
`subject_ref`, `content_hash`, `citation_refs`, `prompt_hash`, manifest by reference.

This is what makes the audit retention clock (≥ 6 years) compatible with the record
deletion clock — see [retention & deletion](../data-handling/retention-and-deletion.md).

## 5. Queryability

Indexed on `tenant`, `correlation_id`, `subject_ref`, `actor.id`, `action`, `ts`,
`risk_tier`, `reason_code`. Standard saved queries (the ones an auditor actually asks for):

| Query | Purpose |
|---|---|
| `reconstruct(correlation_id)` | Full ordered event list for one decision — the [walkthrough](../stretch/auditor-walkthrough.md) |
| `disclosures_by_subject(subject_ref, window)` | Accounting of disclosures (O-P5) |
| `tier3_without_approval(window)` | **Must return empty.** The single most important control test |
| `refusals(window, reason_code)` | Grounding containment working as designed |
| `toggle_history(tenant, feature)` | Kill-switch evidence (FR-5) |
| `boundary_fields(capability, window)` | Minimization drift detection |
| `approver_load(actor, window)` | Approval-fatigue signal (T6) |
| `chain_verify(shard, window)` | Tamper evidence |

## 6. Retention & storage tiering

| Age | Tier | Properties |
|---|---|---|
| 0–90 days | Hot | Indexed, sub-second query |
| 90 days–13 months | Warm | Indexed, seconds |
| 13 months–6+ years | Cold WORM | Object-locked, restore for query within hours; anchors retained alongside |

Entries are never deleted inside the retention window. Aging is a storage-class change,
and the chain is verified after each migration.

## 7. Failure behaviour

| Failure | Behaviour |
|---|---|
| Ledger unreachable, consequential event | Action aborted; local hash-chained journal records the attempt; merged on recovery with `deferred_write` marker (FC-6) |
| Ledger unreachable, non-consequential event | Buffered, best-effort, counted |
| Chain gap detected | Security incident; affected window flagged in every query result covering it; tenant notified per BAA |
| Clock skew > 2 s | Event rejected; node quarantined (ordering integrity depends on it) |

## 8. Why this is [AGNOSTIC]

Nothing above references HIPAA. §164.312(b) is why a *healthcare* auditor asks for it, but
SOX asks for the same reconstructability for financial reporting, public-sector records
schedules ask for it for disclosure, and FERPA asks for it for access logging. What
changes across regimes is the **retention duration**, the **disclosure posture of the log
itself** (in public sector the log may be FOIA-disclosable — a genuinely different
property), and whether an attestation is layered on top. The mechanism does not change.
