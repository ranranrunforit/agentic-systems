# Data Classification — FR-1

Four classes. The class determines encryption, whether the field may cross the model
boundary, which transforms apply, and which retention clock governs it.

## Classes

| Class | Definition | Model boundary | Retention clock |
|---|---|---|---|
| **D0 — Non-sensitive** | Tenant-configured operational content with no individual referent (policies, formulary lists, templates) | Freely, with logging | Tenant operational |
| **D1 — Quasi-identifier** | Fields that identify by combination rather than alone (DOB, ZIP, admission date, rare diagnosis in a small population) | Only after transform (§ transforms) | Record clock (O-R2) |
| **D2 — PHI, clinical** | Health facts tied to an individual: problems, medications, results, notes | Only if on the capability allow-list, minimized | Record clock (O-R2) |
| **D3 — PHI, direct identifier** | Name, MRN, SSN, contact details, account numbers, biometric/facial data, full-face images | **Never crosses the model boundary** except where the capability *is* the identifier task (none in v1) | Record clock (O-R2) |

Everything not explicitly classified defaults to **D3** — the strictest class. Unclassified
fields are unreachable to the agent until someone classifies them, which is deliberate
friction ([ADR-004](../adrs/ADR-004-residency-approach.md) rationale extends to this).

## Field catalogue (synthetic examples)

| Field path | Example value (synthetic) | Class | Crosses boundary? |
|---|---|---|---|
| `patient.name` | `Ada Fictionalis` | D3 | No |
| `patient.mrn` | `SYN-MRN-000123` | D3 | No — replaced by an ephemeral `subject_alias` |
| `patient.ssn` | `SYN-SSN-000-00-0000` | D3 | No |
| `patient.dob` | `1971-04-02` | D1 | Only as `age_band: 50-59` |
| `patient.address.zip` | `99999` | D1 | Only as `zip3: 999` |
| `patient.phone`, `patient.email` | `+1-555-0100`, `ada@example.invalid` | D3 | No |
| `encounter.date` | `2026-03-11` | D1 | As relative offset (`-14d`) unless the task needs the date |
| `problem_list[]` | `Type 2 diabetes mellitus` | D2 | Yes, if allow-listed |
| `medications[]` | `Metformin 500 mg BID` | D2 | Yes, if allow-listed |
| `labs[].value` | `A1c 7.4%` | D2 | Yes, if allow-listed |
| `notes[].text` | free text | D2 (may embed D3) | Yes, **after redaction pass**, if allow-listed |
| `insurance.member_id` | `SYN-INS-777` | D3 | No |
| `tenant.policy_docs[]` | no-show policy | D0 | Yes |
| `audit.*` | record refs, hashes | D0 by construction | N/A — never contains D1–D3 |

## Transforms catalogue

Named, versioned, and referenced by ID in the `minimization_manifest`, so an auditor can
see not just *which* fields crossed but *in what form*.

| ID | Transform | Applied to | Note |
|---|---|---|---|
| `T-AGEBAND-v1` | DOB → 10-year band; ages ≥ 90 collapse to `90+` | `patient.dob` | The 90+ collapse mirrors the Safe Harbor treatment of ages over 89 |
| `T-ZIP3-v1` | ZIP → first 3 digits; suppressed entirely for low-population ZIP3s | `patient.address.zip` | Suppression list configured per tenant |
| `T-RELDATE-v1` | Absolute date → offset from request date | `encounter.date`, `labs[].date` | Preserves clinical ordering without dates |
| `T-ALIAS-v1` | MRN → per-request random `subject_alias`, mapping held control-plane-side only | `patient.mrn` | The alias never persists; the ledger stores the real record ref, the prompt stores the alias |
| `T-REDACT-v1` | Named-entity redaction of direct identifiers in free text | `notes[].text` | **Best-effort**; see caveat below |

### Caveat on `T-REDACT-v1` — stated plainly because auditors ask

Free-text redaction is probabilistic. We do **not** claim that redacted notes are
de-identified under §164.514, and we do not treat them as D0. Redacted notes remain D2,
stay inside the region, and stay inside the zero-retention inference contract. Redaction
is defence in depth, not a declassification mechanism. Claiming otherwise is the most
common way an architecture accidentally asserts a de-identification it cannot support.

## De-identification (O-P7) [REGIME]

The only outputs labelled "de-identified" in this system are aggregate operational
metrics (counts, latencies, tier distributions) computed without individual referents.
Any future attempt to treat record-derived data as de-identified must go through Safe
Harbor's full identifier removal or expert determination, documented as an ADR. There is
no informal "we scrubbed it" path.

## Class-driven enforcement summary

```
D3  → excluded from projection; excluded from prompts; excluded from ledger payloads
D2  → allow-list gated; region-pinned; grounding required when asserted; ledger by ref
D1  → transform required before boundary; transform ID recorded in manifest
D0  → flows with logging
```

Cross-references: [minimization & residency](minimization-and-residency.md),
[retention & deletion](retention-and-deletion.md),
[synthetic records](synthetic-records.md).
