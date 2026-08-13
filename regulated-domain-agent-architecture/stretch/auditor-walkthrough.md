# Auditor Walkthrough — Reconstructing a High-Risk Decision End to End

**Stretch goal.** The script an auditor follows to reconstruct one Tier-3 decision. Written


> **Executable:** run `python3 auditor_cli.py` from `prototype/` to perform this
> walkthrough against a live ledger. It prints PASS/FAIL per check (currently 16/16).

as a runbook: each step states the question, the query, the expected result, and **what a
failure means**.

**Case under audit:** on 2026-08-13, CARA released a referral letter for synthetic patient
`SYN-MRN-000123` at Northwind Health. The tenant's compliance officer wants to know: what
did the model see, what did it claim, on what evidence, who approved it, and could the
record have been altered?

**Starting point:** the released document's `correlation_id` = `SYN-COR-9f21c0`
(printed in the document footer and in the EHR entry's metadata — this matters, because an
audit trail nobody can *enter* is not usable).

---

## Step 0 — Establish that the trail itself is trustworthy

**Question:** could this trail have been edited before I arrived?

```
audit.chain_verify(shard="region-a", from="2026-08-01", to="2026-08-14")
```

**Expect:** `chain_ok: true`, `entries: 412,880`, `anchors_matched: 13/13`,
`notary_receipts_matched: 13/13`, `deferred_writes_pending: 0`.

**If it fails:** stop. A chain break or a missing anchor makes everything downstream
unreliable, and is itself a reportable incident. Note the `first_bad_seq` and escalate
before continuing.

> Doing this **first** is the point. An auditor who reconstructs a decision from a trail
> they have not verified has audited a story, not a system.

---

## Step 1 — Retrieve the decision

```
audit.reconstruct(correlation_id="SYN-COR-9f21c0")
```

**Expect:** an ordered event list, 9 events, all within `tenant=SYN-TEN-northwind`,
`shard=region-a`:

| # | Event | Key fields |
|---|---|---|
| 1 | `authn.success` | actor `SYN-USR-4471`, role `supervising_clinician` |
| 2 | `policy.allow` | `reason:CARE_REL_OK`, `policy_version:v7`, flags snapshot `fv-2291` |
| 3 | `minimization.applied` | manifest, `prompt_hash`, `allowlist_version:v7` |
| 4 | `agent.tool_calls` | 3 calls, tool ids, args hashes |
| 5 | `grounding.result` | 7 claims, 7 supported, citation refs, `τ_hard:0.85` |
| 6 | `risk.classified` | `tier:3`, `rule:R3-PATIENT-ASSERTION` |
| 7 | `approval.queued` | owning role `supervising_clinician` |
| 8 | `approval.granted` | approver `SYN-USR-4471`, `dwell_ms:184000`, `edits:2` |
| 9 | `output.released` | `content_hash`, `accountable_role` |

**If any of 3, 5, 6, or 8 is missing:** a control did not execute. That is the finding.

---

## Step 2 — What did the model see? (FR-1, minimum-necessary)

Open event 3's manifest.

**Expect:** `fields_included` = problem list, medications, labs (with `T-RELDATE-v1`),
`age_band` (from `T-AGEBAND-v1`), two notes (with `T-REDACT-v1`).
`fields_excluded_by_class` includes `patient.name`, `patient.mrn`, `patient.ssn`,
`patient.phone`, `insurance.member_id`.

**Cross-check:** every included path appears on allow-list `v7` for capability
`draft.summary`.

```
config.allowlist(capability="draft.summary", version="v7")
```

**If a field crossed that is not on the allow-list:** minimum-necessary was violated for
this request, and the scope of the problem is bounded by
`boundary_fields(capability="draft.summary", window=…)` — which tells you whether this was
one request or a systematic drift.

> This is the step that is normally impossible. In most systems the honest answer to "what
> did the model see?" is "the chart, probably". Here it is a per-request record.

---

## Step 3 — What did it claim, and on what evidence? (FR-4)

Open event 5.

**Expect:** 7 atomic claims, each with `claim_type`, `source_class`, `doc_id`, `version`,
`span_offsets`, `content_hash`, and an entailment score ≥ 0.85.

Verify two of them by hand:

- A patient-specific claim ("HbA1c 7.4% on 2026-07-30") — must cite **S1** (the record). A
  patient-specific fact grounded on a reference work rather than the record is a
  **compatibility failure**, even at a high score.
- A recommendation claim ("meets endocrinology referral criteria") — must cite **S1 + S2**:
  the record values *and* `SYN-VS-CLIN-002` v4.1.

Resolve the cited span as it stood at the time:

```
corpus.get(doc_id="SYN-VS-CLIN-002", version="4.1", span="12:874-1102")
```

**Expect:** `content_hash` matches the value recorded in event 5, even though the live
document is now v4.2.

**If the hash does not match:** either the corpus was altered or the version pointer is
wrong. Both are findings; the second is worse, because it means past decisions cannot be
reconstructed at all.

---

## Step 4 — Was the gate applied? (FR-3)

Open events 6–8.

**Expect:** `tier:3`; `approval.granted` by an actor holding `supervising_clinician`; a
care relationship at the time; `dwell_ms` of 184 s with 2 edits; the release event's
timestamp **after** the approval.

**Population check — the single most important query in this walkthrough:**

```
audit.tier3_without_approval(window="2026-08-01..2026-08-14")
```

**Expect: empty.** A non-empty result means Tier-3 output reached a human without a human
approving it — the control failed, and this is a systemic finding, not a case finding.

Also worth running, because a gate that is always approved instantly is a gate in name
only:

```
audit.approver_load(actor="SYN-USR-4471", window="2026-08-01..2026-08-14")
```

**Expect:** a median dwell time that is plausible for reading a referral letter and its
citations (tens of seconds to minutes), not sub-3-second approvals.

---

## Step 5 — Was AI even supposed to be on? (FR-5)

Event 2 carries `flags_snapshot` with `flag_version: fv-2291`.

```
config.flags(version="fv-2291")
audit.toggle_history(tenant="SYN-TEN-northwind", feature="draft.summary")
```

**Expect:** global on, tenant on, feature on at `2026-08-13T09:14:22Z`; the toggle history
shows no conflicting change in the window; the subject carries no
`ai_processing_restricted` flag.

**If a toggle was off at decision time:** processing occurred that the tenant had
prohibited. Serious finding — and the reason the flag snapshot is recorded per request
rather than inferred from change history.

---

## Step 6 — Could the record have been altered by the agent? (FR-2, integrity)

```
tools.registry(capability="draft.summary")
audit.query(subject_ref="SYN-MRN-000123", action="record.write", window=…)
```

**Expect:** every registered tool declares `writes: none` to the clinical record; zero
`record.write` events attributed to an agent actor. The EHR entry is attributed to
`SYN-USR-4471`.

**If an agent-attributed write exists:** [ADR-008](../adrs/ADR-008-agent-autonomy-bounds.md)
was violated and the integrity guarantee is void.

---

## Step 7 — Where did the data physically go? (FR-1, residency)

Event 3's `boundary` block: `endpoint: inference-region-a`, `region: region-a`,
`retention: zero`, `training: prohibited`.

```
audit.query(action="egress.denied", window=…, tenant="SYN-TEN-northwind")
config.subprocessors(effective="2026-08-13")
```

**Expect:** the endpoint appears in the subprocessor register with region A and
zero-retention terms; any `egress.denied` events show the region control functioning
(their presence is *reassuring*, not alarming — it demonstrates the control is live).

---

## Step 8 — Does the refusal behaviour actually fire? (NFR-4)

Sample the same window for the negative cases, because a system that never refuses is
either perfect or broken, and only one of those is likely:

```
audit.query(action="grounding.failed", window=…, limit=20)
audit.query(action="approval.expired", window=…)
```

**Expect:** refusals present with reason codes (`NO_SUPPORTING_SPAN`,
`RETRIEVAL_UNAVAILABLE`); every `approval.expired` has a matching "action not taken"
outcome and **no** corresponding `output.released`.

---

## Step 9 — Accounting of disclosures (O-P5)

```
audit.disclosures_by_subject(subject_ref="SYN-MRN-000123", window="2026-01-01..2026-08-14")
```

**Expect:** every release and action for this patient, with actor, purpose, and timestamp —
the artefact that answers a §164.528 request.

---

## Closing the walkthrough

| Question | Answered by | Result |
|---|---|---|
| Is the trail trustworthy? | Step 0 | Chain verified, anchors matched |
| What did the model see? | Step 2 | Manifest, within allow-list v7 |
| What did it claim, on what evidence? | Step 3 | 7 claims, all cited, hashes match |
| Was the human gate applied? | Step 4 | Tier 3, approved with edits; population query empty |
| Was AI permitted at that moment? | Step 5 | Flags on, no restriction |
| Could the record have been altered? | Step 6 | No write path, no write events |
| Where did the data go? | Step 7 | Region A, zero retention |
| Does it fail closed? | Step 8 | Refusals and expiries present and correct |

**Nine queries, one correlation ID.** The design target for NFR-3 was ≤ 8 queries to
reconstruct a decision; the extra one is Step 0, which is not about the decision but about
the trail. An auditor who cannot get here in a bounded number of steps will not do it at
all, and an observability property that is not exercised is not a property.
