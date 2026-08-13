# Risk Taxonomy & HITL Threshold — FR-3 [AGNOSTIC mechanism, REGIME trigger]

## 1. What the tiers are scored on

Risk is a property of the **output or action**, not of the request and not of the model's
confidence. Four axes, scored deterministically:

| Axis | Question | Values |
|---|---|---|
| **Specificity** | Does it assert something about an identified individual? | general (0) / cohort (1) / **individual (2)** |
| **Consequence class** | What is affected if it is wrong? | none (0) / convenience (1) / money-or-record (2) / **care-or-safety (3)** |
| **Irreversibility** | How hard is it to undo before harm lands? | trivially reversible (0) / reversible with effort (1) / **effectively irreversible (2)** |
| **Autonomy** | Does the system act, or propose? | informational (0) / proposes an action (1) / **executes an action (2)** |

**Tier = max-rule, not sum-rule.** A single axis at its top value sets the tier. Summing
lets a high-harm output be averaged down by low scores elsewhere, which is exactly the
wrong behaviour.

```
Tier 3  if  consequence = care-or-safety
        or  (specificity = individual AND asserts a clinical fact)
        or  irreversibility = effectively irreversible
        or  autonomy = executes an action affecting the record or a person
Tier 2  if  specificity = individual  (record content restated to its subject)
        or  autonomy = proposes a reversible action
Tier 1  otherwise (general, non-individual, informational)
```

Ambiguity **rounds up** (FC-8): if the classifier cannot determine an axis, it takes the
higher value. Unknown risk is treated as high risk.

## 2. The tiers

| Tier | Definition | Examples (synthetic) | Flow |
|---|---|---|---|
| **Tier 3 — High** | Asserts a clinical fact about a specific patient, proposes or takes a care action, or is effectively irreversible | "Ada's A1c is trending up and she meets referral criteria"; refill request for `SYN-RX-88`; drafted referral letter | **Mandatory HITL** by the named owning role. Fail closed: no approver ⇒ expire closed |
| **Tier 2 — Medium** | Restates the patient's own record to an authorised reader, or proposes a reversible, non-clinical action | "Your last visit was 14 days ago; next follow-up is due in 6 weeks"; booking a follow-up slot | Auto-flow **with grounding + citations + logging**; ≥ 10 % sampled human review; per-tenant configurable to require HITL |
| **Tier 1 — Low** | General, non-individual, informational | "What's the no-show policy?"; "How do I request records?" | Auto-flow with grounding + logging |

There is no Tier 0. Even the most trivial output is grounded and logged; the tiers govern
*who must approve*, never *whether controls apply*.

## 3. Where the threshold sits, and why

**The threshold is between Tier 2 and Tier 3, and it is drawn on irreversibility and
harm-to-person — not on volume, not on model accuracy, not on cost.**
([ADR-003](../adrs/ADR-003-hitl-threshold.md))

The reasoning, stated so a compliance reviewer can attack it:

1. **Accuracy is the wrong axis.** If the threshold moved with measured model accuracy,
   it would move with every model update, and the control would be as reliable as the
   thing it is meant to contain. A control that depends on the trustworthiness of the
   component it constrains is not a control.
2. **Irreversibility is the right axis**, because human review is *only* valuable before
   the point of no return. Review after an irreversible action is documentation, not
   control. So the gate belongs exactly where undo stops being possible.
3. **Harm-to-person is the second axis**, because reversibility is not sufficient: a
   wrong clinical assertion can be retracted and still have changed a clinical decision in
   the interval. Anything that a clinician might act on immediately is treated as
   irreversible in practice.
4. **Volume pressure is answered by narrowing Tier 3, not by lowering the bar.** If the
   queue is too big, the correct responses are to reduce the number of Tier-3 capabilities
   or improve the review UI — never to reclassify care-affecting output downward.
   Recorded as a standing governance rule; threshold changes require Clinical Safety
   Officer sign-off and an ADR amendment.

### Where we deliberately allow Tier 2 to auto-flow

Summarising a patient's own record back to an authorised reader is high-volume and
low-harm *given grounding*: the content is drawn from the record itself, each claim
carries a citation to the record span, and the reader is a clinician or the patient
themselves who can see the underlying data. The residual risk is misleading emphasis or
omission — real, but bounded, and addressed by sampled review rather than a gate.
Tenants who disagree can flip Tier 2 to mandatory HITL per feature; the disagreement is
legitimate and is therefore configuration, not argument.

## 4. Classification is deterministic, not model-judged

The classifier is a rule engine over: capability metadata (declared max tier), presence
of a patient in context, tool-call side-effect declarations, and a claim-type detector
over the candidate output (clinical assertion / record restatement / general).

The claim-type detector is the only learned component, and it is used **one-directionally**:
it may *raise* the tier, never lower it. A capability's declared maximum tier and the
presence of side effects set a floor that no model output can talk its way under.

```
tier = max(capability_declared_tier,
           side_effect_tier(tools_invoked),
           claim_type_tier(candidate_output),   # may raise only
           patient_in_context_tier)
```

## 5. Tier assignment by capability (floors)

| Capability | Floor | Can reach |
|---|---|---|
| `qa.general` | Tier 1 | Tier 3 if the answer names an individual (detector raises) |
| `qa.record` | Tier 2 | Tier 3 on clinical assertion |
| `draft.summary` | Tier 3 | Tier 3 |
| `action.schedule` | Tier 2 (booking) | Tier 3 (medication-adjacent proposals) |

## 6. What the taxonomy would look like elsewhere (forward reference)

The *axes* — specificity, consequence, irreversibility, autonomy — are sector-independent.
The *binding of consequence class* is not:

| Sector | Top consequence class |
|---|---|
| Healthcare | care-or-safety |
| Finance | moves money / affects credit or eligibility |
| Public sector | affects a right, benefit, or an official record |
| Edtech | affects a student's record, placement, or discipline |

That is the sense in which the mechanism is **unchanged** and the trigger is **redefined**
— see [portability](../portability/portability-analysis.md) §FR-3.
