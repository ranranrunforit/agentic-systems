# CARA Reference Implementation

A working implementation of the control plane described in this package. **Python 3.10+,
standard library only, no dependencies, no network access.**

```bash
cd prototype
python3 demo.py              # the five sequence views, run as live traffic
python3 portability_demo.py  # healthcare and finance side by side, same spine
python3 auditor_cli.py       # the 9-step auditor walkthrough, PASS/FAIL per check
python3 run_tests.py         # the full suite (117 tests)
```

## Why this exists

The brief asks for documents, not code. But several acceptance and verification points
are phrased as *demonstrations* — "fails closed", "fail-closed demonstrated", "an
unreachable flag service results in AI off", "show the containment holds", "demonstrate
that one tenant's data cannot leak". A document can *assert* those. Only a program can be
*run* to check them.

## What is real and what is stubbed

| Implemented and tested | Stubbed |
|---|---|
| Hash-chained append-only ledger, verification, anchoring, deferred-write journal | Distributed storage, WORM, real notary |
| Fail-closed flag resolution, conjunctive scopes, bounded stale cache | Network flag service |
| Policy engine: RBAC, care relationship, restriction flags, allow-lists | Real IdP / OIDC |
| Minimization filter: projection, transforms, manifest | Real EHR schema |
| Vetted corpus, validity windows, claim-type→source-class matrix | Licensed clinical references |
| Grounding: decomposition, retrieval, entailment, **4 deterministic vetoes** | **The LLM** — a scriptable stub |
| Risk classifier: 4 axes, max-rule, round-up | — |
| HITL queue: rosters, eligibility, SLA expiry, held items | Approval UI |
| Degraded mode per capability | Product UI |
| Auditor saved queries | Query engine at scale |

### The model is stubbed on purpose

The architecture's claim is *"the controls hold regardless of what the model emits."* So
tests inject **rogue generators that fabricate freely** — invented lab values, absence
claims the record cannot support, laundered self-citations — and assert the controls still
contain them. A real LLM would make the demo prettier and the proof weaker: you could never
tell whether the containment held or the model simply behaved.

## Module map

| Module | Spec it implements |
|---|---|
| `cara/models.py` | Data classes, risk tiers, claim types, **compatibility matrix** |
| `cara/audit.py` | `audit/audit-log-spec.md`, ADR-006 |
| `cara/flags.py` | `toggles/toggle-spec.md`, ADR-005 |
| `cara/policy.py` | `architecture/reference-architecture.md` §3.2, capability + tool registry, ADR-008 |
| `cara/minimization.py` | `data-handling/minimization-and-residency.md`, C-02 |
| `cara/grounding_corpus.py` | `grounding/vetted-sources.md` |
| `cara/grounding.py` | `grounding/hallucination-containment.md`, ADR-002 |
| `cara/risk.py` | `hitl/risk-taxonomy.md`, `hitl/approval-flows.md`, ADR-003/007 |
| `cara/degraded.py` | `toggles/degraded-mode.md` |
| `cara/pipeline.py` | `architecture/sequence-views.md` |
| `cara/fixtures.py` | `data-handling/synthetic-records.md` |
| `cara/regime.py` + `cara/regimes.py` | `portability/portability-analysis.md` — the seam, and the two profiles |
| `cara/conformance.py` | OQ-7 output conformance + OQ-4 omission instrumentation |
| `cara/fixtures_finance.py` | `portability/finance-obligation-inventory.md` |

## Test map

| Suite | Proves | Tests |
|---|---|---|
| `tests/test_failclosed.py` | FC-1…FC-10, no path to release for Tier 3 | 15 |
| `tests/test_grounding_redteam.py` | The 12 red-team attacks | 17 |
| `tests/test_isolation.py` | I-1…I-7, T-1…T-10, restriction flags | 11 |
| `tests/test_toggles_and_audit.py` | All toggle scopes, chain integrity, who/what/when/why | 18 |
| `tests/test_portability.py` | **The spine is sector-neutral**; every row of the portability table | 30 |
| `tests/test_ci_guards.py` | Cache-key safety, all 9 vetoes intact, fail-closed defaults, regime completeness | 26 |

### The five assertions worth reading first

```python
# 1. Tier-3 output cannot reach a human without a human approving it.
self.assertEqual(env.ledger.tier3_without_approval(), [])

# 2. An empty allergy list does not support "no known allergies".
#    The entailment scorer rates this ABOVE tau_soft. The polarity veto refuses it.
self.assertEqual(out.reason_code, "ABSENCE_REQUIRES_POSITIVE_SPAN")

# 3. Unknown flag state means OFF, not "default on".
self.assertEqual(res.cause, "UNKNOWN_FLAG_FEATURE")

# 4. Injected instructions cannot exfiltrate fields that were never projected.
self.assertIn("patient.ssn", manifest["fields_excluded_by_class"])

# 5. Deleting a record leaves the chain verifiable and the decision reconstructable.
self.assertTrue(env.ledger.verify()["chain_ok"])
self.assertIsNone(env.records.get(NORTHWIND, ADA))
```

## Six sector leaks the finance port caught

Full detail in [portability-by-construction](../portability/portability-by-construction.md).
All six passed 61 healthcare tests without complaint. The subtlest — a stopword list in
the entailment scorer containing `"patient"` — silently made every claim about a patient
easier to ground. No functional test could have seen it.

## Two bugs this exercise actually caught

Worth recording, because they are the argument for writing the code at all:

1. **Shared mutable fixtures.** `build_env()` originally handed every environment the same
   record dicts, so one test's mutation leaked into another's. Exactly the class of
   accidental cross-instance bleed the isolation tests exist to catch — in the harness
   itself. Fixed with a deep copy.
2. **An over-strong isolation assertion.** The first version of T-2 asserted that a
   Meridian retrieval returns *nothing* for a diabetes query. Wrong: Meridian may match its
   own corpus, and should. The property that matters is narrower — *no Northwind document
   ever appears in a Meridian retrieval*. The test was wrong, not the code, and writing it
   down forced the distinction.

## Honest limits

- The entailment scorer is token overlap, not a verifier model. The **control logic around
  it** is what the prototype demonstrates; threshold calibration is not.
- No persistence, no concurrency, no crypto beyond SHA-256/HMAC. Anchoring is in-process.
- Misleading-by-omission (OQ-4) is **instrumented, not solved**: `OmissionDetector`
  flags absent facts from a NAMED list. An omission nobody thought to name is still
  invisible, and `test_the_detector_only_sees_NAMED_expectations` asserts that limit so
  it cannot quietly be forgotten.
- The public-sector and edtech deltas remain documents. Given what binding the second
  regime exposed, they should be read as hypotheses until a third `Regime` is bound.
