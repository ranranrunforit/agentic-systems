# Cross-Regime Portability Analysis — FR-6

**Primary sector:** healthcare (HIPAA).
**Peer sector re-derived in full here:** finance (GLBA / PCI DSS / SOX).
**Additional sectors sketched:** public sector and edtech, in [sector-deltas.md](sector-deltas.md).

## 0. What this analysis is for

The architecture claims a **spine** (controls that are true of responsible agentic design
in any regulated setting) and a **parameter layer** (controls shaped by a specific
regime). That claim is cheap to assert and easy to get wrong. This section tests it by
re-deriving every control area from scratch for a different regime and checking whether
the predicted classification holds.

The test has a failure condition, and it is worth naming before running it: **if every row
comes out "unchanged", the analysis is lazy; if every row comes out "replaced", the
original design was over-fitted.** A correct separation produces a mix, and it produces
*the specific mix predicted in advance* by the class tags in the
[control matrix](../control-mapping/control-matrix.md) (13 pure-[A], 6 [A]-with-[R]-parameter,
14 [R]).

## 1. The scenario, re-cast for finance

Same system shape, different regime: **CARA-F**, an agentic assistant inside a retail bank
(fictitious tenant `SYN-TEN-atlasbank`), operating over customer accounts. Capabilities
mapped one-to-one so the comparison is like-for-like:

| Healthcare capability | Finance analogue | Highest tier |
|---|---|---|
| `qa.record` — Q&A over a patient's record | `qa.account` — Q&A over a customer's account and transactions | Tier 3 |
| `draft.summary` — visit summary for signature | `draft.disclosure` — adverse-action notice / account letter for officer sign-off | Tier 3 |
| `action.schedule` — bounded care actions | `action.servicing` — bounded servicing actions (stop payment, dispute filing, limit change) | Tier 3 |
| `qa.general` — general policy content | `qa.general` — product terms and process content | Tier 1 |

Applicable regimes: **GLBA** (Safeguards Rule + Privacy Rule, NPI protection),
**PCI DSS** (cardholder data), **SOX** (§302/§404 internal control over financial
reporting), plus adjacent obligations — FCRA (adverse action), Reg E/Z (error
resolution and disclosures), BSA/AML, and FFIEC/OCC model-risk guidance (SR 11-7 style).

## 2. FR-1 — Data handling and residency

### 2a. Classification → **REPLACED (same mechanism, different taxonomy)**

The four-class scheme survives; its contents are entirely different, and one new
structural constraint appears that has no healthcare analogue.

| CARA (healthcare) | CARA-F (finance) | Note |
|---|---|---|
| D3 direct identifiers (name, MRN, SSN) | D3 direct identifiers (name, SSN/TIN, account number, **PAN**) | Similar |
| D2 clinical PHI | D2 **NPI** — balances, transaction history, credit data | Similar shape |
| D1 quasi-identifiers | D1 quasi-identifiers | Unchanged |
| D0 non-sensitive | D0 non-sensitive | Unchanged |
| — | **D4 — Cardholder data (CHD/SAD)** | **New class with its own regime** |

**Why D4 is not just "D3 with a different name":** PCI DSS does not merely restrict
*access* to cardholder data, it restricts the **scope of the environment that touches
it**. Any system component that stores, processes, or transmits CHD is pulled into the
Cardholder Data Environment and inherits the full DSS control set, segmentation
requirements, and assessment burden. Under HIPAA, touching more PHI means more care; under
PCI, touching CHD means a **different audit regime for the entire component**.

Architectural consequence: CARA-F does not admit CHD to the agent at all. Card references
are **tokenised upstream** (`SYN-PAN-TOKEN-a91f`); the agent's environment is engineered to
be *out of scope* for PCI rather than compliant-in-scope. That is a genuinely different
design move than minimization — it is scope avoidance.

### 2b. Access model → **REPLACED**

| Healthcare | Finance |
|---|---|
| **Minimum necessary** (§164.502(b)) with a *care-relationship* check | **Need-to-know / least privilege** under the GLBA Safeguards Rule, with a *servicing-relationship* check, **plus CHD isolation (PCI Req. 7)** and **segregation of duties (SOX)** |

The relationship predicate changes (care relationship → servicing/authorised-representative
relationship), and SOX adds a constraint HIPAA has no analogue for: **the same actor may
not both initiate and approve** a transaction affecting financial reporting. That is not a
tightening of minimum-necessary; it is a different kind of rule (duty separation rather
than data scope), so the mechanism that implements it is new: an eligibility predicate on
the approval step, not a filter on the data.

Note this also **invalidates one healthcare design choice**: in CARA, self-approval by the
requesting clinician is permitted ([approval flows §5](../hitl/approval-flows.md#5-eligibility-rules)).
In CARA-F, for reporting-relevant actions, it is prohibited. Same component, opposite
configuration — a good illustration of a parameter that looks agnostic until you change
regimes.

### 2c. Minimization mechanism → **UNCHANGED**

The Minimization Filter, allow-lists, transforms catalogue, and `minimization_manifest`
port with **zero structural change** — only the allow-list contents differ. The manifest
remains the artefact that answers "what was exposed" for breach scoping under state
breach-notification laws and the FTC Safeguards Rule notification duty, exactly as it does
for §164.402.

### 2d. Residency → **RELAXED in some contexts, TIGHTENED in others**

Genuinely two-directional, which is why "residency is a universal control" is the wrong
call:

- **Relaxed:** neither GLBA nor PCI imposes a general geographic residency requirement. A
  US-only retail bank may run CARA-F in a multi-region deployment with no residency pin at
  all.
- **Tightened:** where the tenant operates cross-border, banking secrecy laws, national
  supervisory expectations, and outsourcing/cloud-concentration rules (e.g. EU DORA-style
  regimes) impose location and exit-plan requirements considerably stiffer than a HIPAA
  BAA. PCI adds scope-driven segmentation that behaves like residency at the network level.

The *mechanism* (region-pinned stores, endpoints, ledger shards; egress allow-lists;
region-bound keys) is unchanged and simply configured differently — which is the whole
argument for parameterising residency rather than hard-coding it.

### 2e. Retention → **TIGHTENED and RE-OWNED**

| Healthcare | Finance |
|---|---|
| Documentation 6 years (§164.316); record retention set by **state law/tenant** | SOX-driven retention of records supporting financial statements (commonly **7 years**, audit workpaper rules longer); BSA/AML records typically **5 years**; Reg E/Z dispute records with their own clocks |

More clocks, generally longer, and — the structural change — **the audit trail itself
becomes a retained business record**, because it evidences internal control over financial
reporting. In healthcare the ledger is a compliance artefact *about* the system; under SOX
it is partly *part of the record*. This raises the bar on the ledger's own integrity
guarantees but does not change its design.

**Classification for FR-1 overall: REPLACED (taxonomy + access model), TIGHTENED
(retention), TWO-DIRECTIONAL (residency), UNCHANGED (minimization mechanism).**

## 3. FR-2 — Auditability and accountability → **UNCHANGED mechanism, TIGHTENED obligations**

| Element | Change |
|---|---|
| Hash-chained, append-only, externally anchored ledger | **Unchanged** |
| Who/what/when/why + inputs schema | **Unchanged** |
| References-and-hashes-only payload rule | **Unchanged** — and *more* valuable, because financial-record retention is longer still |
| Synchronous write on consequential events | **Unchanged** |
| Named owning role per decision class | **Unchanged mechanism**, roles re-bound (supervising clinician → **lending/servicing officer**; Clinical Safety Officer → **Model Risk Management**) |
| **New:** management assertion on ICFR | **Added** — SOX §302/§404 mean the log must support a management attestation and external-auditor testing, with control-effectiveness evidence assembled per period |
| **New:** model risk governance | **Added** — SR 11-7-style expectations require model inventory, independent validation, and documented performance monitoring. Our model-version and threshold records already exist; the *governance wrapper* is new |
| **New:** FCRA adverse-action explainability | **Added** — where output contributes to a credit decision, the *reason* must be expressible to the consumer, not just to the auditor |

That last row is the sharpest finding of the whole analysis. In healthcare, the audit
trail's audience is a regulator, an auditor, and the tenant. Under FCRA the trail acquires
a **consumer-facing** audience: the affected individual has a right to the principal
reasons for an adverse decision. That is a genuinely new *output* requirement derived from
the same log — an argument for having captured `why.reason_code` as structured data rather
than free text, which was originally motivated by machine-checkability, not by FCRA.

**Classification: UNCHANGED core, TIGHTENED/EXTENDED by attestation, model-risk, and
explainability duties.**

## 4. FR-3 — HITL and risk taxonomy → **UNCHANGED mechanism, REDEFINED trigger**

The four axes port verbatim: specificity, consequence class, irreversibility, autonomy.
The max-rule ports. Round-up-on-ambiguity ports. Expire-closed ports.

Only the **consequence class binding** changes:

| Axis value | Healthcare | Finance |
|---|---|---|
| Top consequence class | care-or-safety | **moves money, or affects credit / eligibility / account access** |
| Tier 3 examples | Clinical assertion about a patient; refill proposal | Payment initiation; adverse-action notice; account restriction; anything feeding a credit decision |
| Tier 2 examples | Record summary to its subject | Balance/transaction summary to the account holder; reversible servicing action |
| Tier 1 examples | General education content | Product terms, branch hours |

Two finance-specific *additions* to the eligibility predicate, both from SOX/AML rather
than from the risk model itself:

1. **Segregation of duties** — initiator ≠ approver for reporting-relevant transactions
   (§2b). This *removes* an option the healthcare design allowed.
2. **Dual approval above monetary thresholds** — finance layers a *quantitative* threshold
   (amount) on top of the qualitative tiers. Healthcare has no natural monetary axis; the
   nearest analogue would be a cohort-size threshold for population-level output.

Note what did **not** change: the threshold still sits on irreversibility and harm, not on
model accuracy or volume. A wire transfer is Tier 3 for exactly the reason a refill
proposal is — review after the point of no return is documentation, not control.

**Classification: UNCHANGED mechanism, REPLACED trigger definition, TIGHTENED eligibility
(SoD + dual approval).**

## 5. FR-4 — Grounding and hallucination containment → **UNCHANGED mechanism, REPLACED source set**

| Element | Change |
|---|---|
| Claim decomposition, typing, retrieval, entailment, thresholds | **Unchanged** |
| `τ_hard` / `τ_soft` with veto-only deterministic checks | **Unchanged** — and numeric fidelity becomes *more* load-bearing (a wrong balance or APR is a compliance event, not just an error) |
| Prohibition on self-grounding, open web, other tenants | **Unchanged** |
| Refuse-or-escalate on Tier-3 ungrounded claims | **Unchanged** |
| Source classes | **Replaced** (see below) |
| **New:** required-disclosure completeness | **Added** — Reg Z/E and FCRA mandate that certain output *contains* prescribed language. Grounding checks that claims are supported; it does not check that mandated content is present |

| Source class | Healthcare | Finance |
|---|---|---|
| S1 subject record | Patient record | Customer's account/transaction system of record |
| S2 tenant policy | Clinical protocols | Product terms, fee schedules, servicing procedures |
| S3 licensed reference | Clinical references | Regulatory text, rate tables, published indices |
| S4 operational policy | Scheduling/records policy | Complaint-handling, dispute procedures |
| S5 statutory text | Health regulation | Reg E/Z/FCRA text |

The disclosure-completeness row is the second interesting finding: it is a control the
healthcare design **did not need and does not have**. Finance requires a *positive
completeness check* (a template-conformance verifier asserting mandated elements are
present) alongside the *negative* grounding check (no unsupported claims). This is a
**new control**, not a re-parameterisation — honest evidence that the spine is not
everything, and that porting is real work rather than a config change.

**Classification: UNCHANGED mechanism, REPLACED source set, plus one NEW regime-specific
control (disclosure completeness).**

## 6. FR-5 — Toggleable AI and degraded mode → **UNCHANGED**

Global/tenant/feature/subject scopes, conjunctive resolution, no overrides, fail-closed
with a bounded stale window, mandatory reason codes, two-person re-enable, transactional
flag+ledger write, held (not auto-released) approval queues, tested non-degradation
journeys — **all of it ports without modification.**

Only the degraded-path *content* differs, and only because the product differs: templated
letters instead of templated visit summaries, deterministic account views instead of
deterministic record views.

One nuance worth recording: under SOX, the *availability* of the degraded path is itself
part of the control environment, because a business process that silently stops working
when a model is disabled is a control deficiency. In healthcare the equivalent duty exists
(O-S5 contingency operation) but is less sharply tested. So: unchanged control, slightly
sharper audit scrutiny.

**Classification: UNCHANGED.**

## 7. Summary table

| Control area | Healthcare → Finance | Class |
|---|---|---|
| FR-1 data classification | PHI taxonomy → NPI + **new CHD class with scope semantics** | **Replaced** |
| FR-1 access model | Minimum-necessary + care relationship → need-to-know + servicing relationship + CHD isolation + **SoD** | **Replaced** |
| FR-1 minimization mechanism | Filter, allow-lists, manifest | **Unchanged** |
| FR-1 residency | No HIPAA mandate → no GLBA/PCI mandate, but cross-border/outsourcing rules bite; PCI segmentation acts network-side | **Relaxed *and* tightened (context-dependent)** |
| FR-1 retention | State/tenant record clocks → SOX ~7 yr, BSA 5 yr, dispute clocks; ledger becomes a business record | **Tightened** |
| FR-2 audit mechanism | Hash-chained append-only ledger | **Unchanged** |
| FR-2 obligations on the log | + ICFR attestation, + model-risk governance, + FCRA consumer explainability | **Tightened / extended** |
| FR-2 accountability roles | Clinician roles → officer + Model Risk Management roles | **Unchanged mechanism, re-bound roles** |
| FR-3 risk axes & max-rule | Specificity / consequence / irreversibility / autonomy | **Unchanged** |
| FR-3 trigger definition | "affects care" → "moves money / affects credit" | **Replaced** |
| FR-3 approver eligibility | Self-approval allowed → **prohibited** (SoD) + dual approval over amount | **Tightened** |
| FR-4 grounding pipeline | Decompose → retrieve → entail → refuse | **Unchanged** |
| FR-4 source classes | Clinical → financial/regulatory | **Replaced** |
| FR-4 disclosure completeness | *(absent)* → mandated-content verifier | **New (regime-specific)** |
| FR-5 toggles & degraded mode | Scopes, fail-closed, audit, held queues | **Unchanged** |
| NFR-4 fail-closed | Every path | **Unchanged** |

**Tally:** 7 unchanged · 4 replaced · 3 tightened · 1 two-directional · 1 new.

Compare to the prediction in the [control matrix](../control-mapping/control-matrix.md#class-tally-input-to-the-portability-analysis):
every pure-[A] control came out unchanged, every [R] control moved, and no [A] mechanism
was replaced. The prediction held **with one correction**: the analysis surfaced a control
the healthcare design does not have at all (disclosure completeness), which is a reminder
that the spine is necessary, not sufficient — porting adds regime-specific controls rather
than merely re-parameterising existing ones.

## 8. The explicit split

### Regime-agnostic responsible-AI controls
True in all four menu sectors; only triggers and source sets are re-bound.

1. **Auditability** — tamper-evident, append-only, reference-only, who/what/when/why **plus the inputs that produced the decision**.
2. **Accountability** — a named owning role for every automated decision class, including auto-flowed ones.
3. **HITL above a risk threshold** — with the threshold drawn on irreversibility and harm, and the four scoring axes.
4. **Grounding-or-refuse** — vetted-source citation for high-risk factual claims; refuse or escalate when grounding fails; never self-ground.
5. **Toggleable AI with a safe degraded mode** — global/tenant/feature scopes, conjunctive, fail-closed, audited.
6. **Fail-closed everywhere** — missing grounding, authorization, approver, flag state, or ledger ⇒ refuse.
7. **Minimization at the model boundary as a mechanism** — the *filter and manifest*, independent of which fields the regime protects.
8. **Tenant isolation.**
9. **No training on tenant data / zero retention at the model boundary.**

### Regime-specific controls
Change — sometimes appear, sometimes vanish — with the regime.

1. **Data taxonomy** — what counts as sensitive (PHI / NPI + CHD / records + FOIA-exempt categories / education records).
2. **Access model** — minimum-necessary vs. need-to-know + CHD isolation + SoD vs. FOIA-driven disclosure vs. vendor-data-use limits.
3. **Residency** — whether it exists at all, and how tight.
4. **Consent and age-gating** — absent in this healthcare design, central in edtech.
5. **Retention duration and ownership** — and whether the audit trail is itself a retained business record.
6. **Breach/incident notification** — audience and clock.
7. **Regime-specific output duties** — disclosure completeness (finance), accessibility (public sector), explainability to the individual (FCRA).
8. **Attestation and validation regimes** — SOX ICFR, model-risk validation, ATO.

### The one-sentence version

> The spine did not change; the parameters did — and porting also *added* a control the
> original regime never asked for, which is the difference between an architecture that is
> portable and one that merely claims to be.

## 9. Would the analysis look different starting from another sector?

Deliberately checked, because the menu is balanced and a design that only looks principled
from the healthcare end would be over-fitted in a subtler way.

Starting from **finance** and porting to healthcare, the same spine appears and the
movement reverses: SoD relaxes, disclosure-completeness drops away, retention shortens,
and minimum-necessary replaces need-to-know. Starting from **public sector**, the spine
appears again and the striking delta is that the audit log becomes potentially
*disclosable* rather than merely inspectable — a property no other sector on the menu
imposes. Starting from **edtech**, consent moves from absent to prerequisite, gating
processing before it begins rather than constraining it afterwards.

Four starting points, one spine, four different parameter sets. That is the claim, and
[sector-deltas.md](sector-deltas.md) works the remaining two.
