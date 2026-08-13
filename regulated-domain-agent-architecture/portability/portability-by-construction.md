# Portability, Proved by Construction

> **Executable.** `cd prototype && python3 portability_demo.py` runs both regimes side
> by side; `python3 run_tests.py` runs the 30-test proof in
> [`tests/test_portability.py`](../prototype/tests/test_portability.py).

The [portability analysis](portability-analysis.md) *argues* that the spine is
sector-independent. This document reports what happened when that argument was
**implemented and tested** instead.

## The experiment

1. Extract every sector-bound fact into one parameter object,
   [`Regime`](../prototype/cara/regime.py).
2. Bind it twice: `HEALTHCARE` and `FINANCE`
   ([`regimes.py`](../prototype/cara/regimes.py)).
3. Run the finance regime through the **same** ledger, flag service, policy engine,
   minimization filter, grounding verifier, risk classifier, approval queue, degraded
   service, and pipeline.
4. Assert, structurally, that no spine module contains a sector word in executable code.

The falsification condition was set in advance: **if the spine had to change to
accommodate finance, the split was wrong.**

## Result

The spine did not change. What changed was that the exercise **found six places where
the spine only looked sector-neutral**, all of which had passed 61 healthcare tests
without complaint.

| # | Leak | Why the healthcare tests never caught it |
|---|------|------------------------------------------|
| L1 | `record_spans()` hardcoded `problem_list / medications / labs / allergies` | Correct in healthcare, so no test failed. In finance, a customer's balance produced **no S1 span** and every account-specific claim was refused — a total failure that only appeared with a second regime |
| L2 | The refusal message named "the patient's record, tenant clinical protocols" | A bank customer would have been told their disclosure request was checked against clinical protocols |
| L3 | `DEGRADED_BEHAVIOUR` / `NOTICE` tables keyed on healthcare capability names | Degraded mode would have fallen back to `route_to_human` for every finance capability, quietly removing the FR-5 guarantee |
| L4 | `classify(patient_in_context=...)`, reason code `PATIENT_RESTRICTION`, rule `R3-PATIENT-ASSERTION` | Pure naming — but naming that made the spine unusable as spine |
| L5 | `_subject_ref()` guessed the subject key by trying `("patient", "customer", "student", "case")` | A sector inventory living inside the record store. Replaced with a configured path |
| L6 | The stopword list in the entailment scorer contained `"patient"` | The subtlest one: it made every claim *about a patient* marginally easier to ground. A sector assumption hiding in a stopword list, invisible to every functional test |

**L6 is the one worth dwelling on.** It was not a crash, a wrong answer, or a failing
assertion. It was a silent, systematic thumb on the scale in exactly one sector, sitting
in a helper function nobody would think to review for regulatory content. No amount of
argument would have found it. Building the second regime found it in an afternoon.

## What the tests assert

| Class | Proves |
|---|---|
| `TestSpineIsSectorNeutral` | No spine module contains a healthcare **or** finance word in executable logic (docstrings and comments exempt, via AST). Both regimes use the identical classes |
| `TestFR1DataHandling` | Taxonomy replaced (D4 added), access model replaced, **minimization mechanism byte-identical**, residency two-directional, retention tightened |
| `TestFR2Auditability` | Same ledger, same schema, same chain verification; roles re-bound, not removed |
| `TestFR3HITL` | Four axes and max-rule identical; trigger replaced; **SoD removes an option healthcare allowed**; monetary axis exists in finance and is inert in healthcare |
| `TestFR4Grounding` | Pipeline unchanged; **compatibility matrix is `==` across regimes**; only labels differ; refusals speak the regime's vocabulary |
| `TestNewRegimeSpecificControls` | Healthcare has zero conformance rules and that is correct; finance disclosure completeness blocks release; **grounding passes while conformance refuses** |
| `TestOmissionInstrumentation` | Omission is flagged, not blocked — and the detector's limit is asserted so it cannot be forgotten |
| `TestPortabilityTableRows` | Every row of the §7 classification table, plus the tally, plus both failure conditions (not all-unchanged, not all-replaced) |

## The strongest single result

```python
self.assertEqual(HEALTHCARE.compatibility, FINANCE.compatibility)
self.assertNotEqual(HEALTHCARE.source_class_labels, FINANCE.source_class_labels)
```

"Replaced source set, unchanged mechanism" is a claim that sounds accommodating until you
check it. The claim-type → source-class matrix is **equal** between the two regimes; only
the human-readable labels on the source classes differ. A patient-specific fact needs the
patient's record; an account-specific fact needs the account's record; the *rule* is one
rule.

## What the construction could not make free

Three things ported as mechanisms but still required new work:

1. **A new control.** Finance needs disclosure completeness — a positive check that
   mandated elements are present. The slot is now in the spine
   ([`conformance.py`](../prototype/cara/conformance.py)) and is **empty for
   healthcare**, which is the honest state rather than an oversight.
2. **A removed option.** Segregation of duties forbids the self-approval healthcare
   permits. The healthcare reasoning was sound *and* inapplicable. Same component,
   opposite configuration.
3. **Nine obligation families with no healthcare counterpart**, per the
   [finance obligation inventory](finance-obligation-inventory.md) — PCI scope
   semantics, operating-effectiveness evidence, independent model validation, and the
   consumer-facing content duties.

## Revised conclusion

The document version concluded: *the spine did not change; the parameters did.* The
constructed version is more precise, and less flattering:

> The spine did not change **once it was made genuinely sector-neutral**, which it was
> not when the analysis was written. Six sector assumptions were embedded in code that
> passed every test in the primary sector, including one that biased grounding in that
> sector's favour. Portability is not a property a single-sector implementation has and
> then demonstrates; it is a property the second implementation *creates*, by forcing
> the first one's assumptions into the open.

That is a better claim than the original, and it is only available because the code was
written. It also suggests the right generalisation for the two sketched sectors: the
public-sector and edtech deltas in [sector-deltas](sector-deltas.md) should be treated as
**hypotheses**, not conclusions, until someone binds a third `Regime` and finds the next
six leaks.
