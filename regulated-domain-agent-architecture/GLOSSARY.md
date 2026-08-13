# Glossary

## Package conventions

| Symbol | Meaning |
|---|---|
| **[AGNOSTIC]** / **[A]** | Control intrinsic to responsible agentic design; present in every menu sector |
| **[REGIME]** / **[R]** | Control shaped by a specific regulatory regime |
| `C-xx` | Control ID in the [control matrix](control-mapping/control-matrix.md) |
| `O-Px` / `O-Sx` / `O-Bx` / `O-Rx` | Obligation IDs: Privacy / Security / Breach / Retention |
| `DC-x` | Decision class in the [accountability model](audit/accountability-model.md) |
| `FC-x` | Fail-closed drill case |
| `OQ-x` | Open compliance question |
| `T-x` | Threat in [trust-boundaries](architecture/trust-boundaries.md) |
| `I-x` | Isolation claim |
| `S1…S5` | Vetted-source classes |
| `D0…D3` (`D4` in finance) | Data classification levels |
| `SYN-*` | Synthetic identifier — nothing in this package is real |

## System terms

| Term | Meaning |
|---|---|
| **CARA** | Clinical Assistance & Records Agent — the healthcare system designed here |
| **CARA-F / CARA-P / CARA-E** | Its finance / public-sector / edtech counterparts in the portability analysis |
| **Model boundary** | The edge between regulated storage (Zone 3) and inference (Zone 4). Anything crossing it is a disclosure to a subprocessor |
| **Minimization Filter** | The component that projects a record down to a capability's allow-listed fields before prompt assembly |
| **`minimization_manifest`** | The per-request record of which field paths and transforms crossed the model boundary |
| **Capability** | A declared unit of agent functionality (`qa.record`, `draft.summary`, `action.schedule`, `qa.general`) with a purpose, allow-list, tool set, and risk floor |
| **Consequential event** | One that changed what a human saw, what a system did, or what data crossed a boundary. Ledger write is synchronous and blocking |
| **Vetted source** | A document/record span admitted by a named role, versioned, currently valid, and authoritative *for the claim type* |
| **Claim-type → source-class matrix** | The rule that a claim may only be grounded on a source class authoritative for that kind of claim |
| **Circularity guard** | The prohibition on grounding on model-generated intermediates, enforced structurally |
| **`τ_hard` / `τ_soft`** | Entailment thresholds (0.85 / 0.60) — versioned, owned, and recorded per decision |
| **Deterministic veto** | A non-model check (numeric, temporal, polarity, entity binding) that can fail a claim but never pass one |
| **Tier 1 / 2 / 3** | Risk tiers; Tier 3 requires mandatory human approval |
| **Max-rule** | Tier = the highest value across the four risk axes, never an average |
| **Expire closed** | No eligible approver within SLA ⇒ output withheld, action not taken |
| **Degraded mode** | The deterministic non-AI path the product runs on when AI is disabled |
| **Conjunctive resolution** | Any toggle scope can disable AI; none can re-enable over another |
| **Bounded stale window** | The 60 s during which a cached flag value may be used when the flag service is unreachable |
| **Crypto-shredding** | Deleting backup-resident data by destroying its data key |
| **Reference-only ledger** | Audit entries hold record references and content hashes, never sensitive content |

## Regulatory shorthand

| Term | Meaning |
|---|---|
| **PHI / ePHI** | Protected health information (electronic) — HIPAA |
| **Covered entity / business associate / subcontractor BA** | HIPAA role structure. CARA is a BA; the inference provider is a subcontractor BA |
| **BAA** | Business associate agreement |
| **Minimum necessary** | HIPAA's limit on how much PHI a use or disclosure may involve |
| **Safe Harbor** | The identifier-removal route to de-identification under §164.514(b) |
| **NPI** | Nonpublic personal information — GLBA |
| **CHD / SAD** | Cardholder data / sensitive authentication data — PCI DSS |
| **CDE** | Cardholder Data Environment — the PCI scope boundary |
| **ICFR** | Internal control over financial reporting — SOX §302/§404 |
| **SoD** | Segregation of duties |
| **FCRA adverse action** | The duty to give principal reasons for a credit-related adverse decision |
| **FERPA / COPPA / PPRA** | US education-record privacy / children's online privacy / pupil-rights regimes |
| **School-official exception** | The FERPA basis on which a vendor may access education records |
| **FOIA-style disclosure** | Public-records disclosure obligations in the public-sector regime |
| **ATO** | Authorization to operate — the public-sector authorisation boundary |
| **DSR** | Data-subject request (access, amendment, accounting, restriction, erasure) |
| **Records schedule** | A public-sector retention schedule with mandatory disposition — may *prohibit* deletion |
| **Model risk management** | Supervisory expectations (SR 11-7 style) for model inventory, validation, and monitoring |
