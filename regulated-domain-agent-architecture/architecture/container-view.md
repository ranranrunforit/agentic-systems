# Container View

Legend: **[A]** = agnostic control, **[R]** = regime-specific control,
`═══` conceptual trust-zone boundary, dotted arrows = audit writes.

## C1 — Container diagram

```mermaid
flowchart TB
  subgraph Z0["Zone 0 — Untrusted"]
    U["Clinical staff<br/>(browser / EHR embed)"]
    P["Patient portal user"]
  end

  subgraph Z1["Zone 1 — Edge"]
    GW["API Gateway<br/>TLS 1.3, OIDC, tenant resolution<br/>issues request-scoped token [A]"]
  end

  subgraph Z2["Zone 2 — Control plane"]
    POL["Policy Engine<br/>RBAC + care-relationship check [R]<br/>field allow-list [R]"]
    FLG["Flag Service<br/>global / tenant / feature<br/>fail-closed [A]"]
    MIN["Minimization Filter [A]<br/>projection + transforms<br/>emits minimization_manifest"]
    AGT["Agent Runtime<br/>registered tools only<br/>scoped tokens [A]"]
    GRD["Grounding Verifier [A]<br/>claim decomposition + entailment"]
    RSK["Risk Classifier [A]<br/>deterministic tiering"]
    LED[("Audit Ledger [A]<br/>append-only, hash-chained<br/>record refs only, no PHI")]
    DEG["Degraded-mode Service [A]<br/>deterministic non-AI path"]
  end

  subgraph Z3["Zone 3 — Regulated data (region-pinned) [R]"]
    REC[("Record Store — PHI<br/>AES-256, tenant CMK")]
    VET[("Vetted Corpus Store<br/>licensed clinical refs + provenance")]
    OBJ[("Object Store<br/>drafts, attachments")]
  end

  subgraph Z4["Zone 4 — Model boundary (region-pinned, zero retention) [R]"]
    LLM["Inference endpoint<br/>no training on tenant data"]
    EMB["Embedding endpoint"]
  end

  subgraph Z5["Zone 5 — Human review"]
    CON["Approval Console<br/>named owning role [A]"]
  end

  U --> GW
  P --> GW
  GW --> POL
  POL <--> FLG
  POL -->|AI off| DEG
  POL -->|AI on + allow-list| MIN
  MIN -->|projected fields only| AGT
  MIN --> REC
  AGT -->|scoped reads| REC
  AGT --> VET
  AGT --> OBJ
  AGT -->|prompt| LLM
  VET --> EMB
  AGT --> GRD
  GRD --> VET
  GRD -->|ungrounded high-risk| REF["Refuse / escalate [A]"]
  GRD -->|grounded| RSK
  RSK -->|Tier 3| CON
  RSK -->|Tier 1–2| OUT["Release + provenance"]
  CON -->|approved| OUT
  CON -->|rejected / expired| REF
  DEG --> OUT

  GW -.->|authn events| LED
  POL -.->|allow/deny + reason| LED
  FLG -.->|flag read + change| LED
  MIN -.->|minimization_manifest| LED
  AGT -.->|tool calls, prompt hash| LED
  GRD -.->|claims, citations, refusals| LED
  RSK -.->|tier + rule fired| LED
  CON -.->|approver, decision, reason| LED
  DEG -.->|degraded served| LED
```

## C2 — Component view of the model boundary

The single most scrutinised edge in the design: nothing reaches Zone 4 except through the
Minimization Filter.

```mermaid
flowchart LR
  REC[("Record Store<br/>full patient record")] --> PRJ["Projection<br/>allow-listed field paths only"]
  PRJ --> TR["Transforms<br/>DOB→age band<br/>ZIP→ZIP3<br/>free-text redaction"]
  TR --> ASM["Prompt assembly<br/>+ prompt_hash"]
  ASM --> EG{"Egress policy<br/>region + endpoint allow-list"}
  EG -->|region match| LLM["Inference endpoint<br/>(contracted region)"]
  EG -->|mismatch| DENY["Deny + audit [A]"]
  ASM -.->|minimization_manifest<br/>field paths, transforms, hash| LED[("Audit Ledger")]
  EG -.->|egress decision| LED
```

Two properties this buys:

1. **Injection cannot widen scope.** The Agent Runtime operates on a projection. A prompt
   that says *"also include the patient's SSN"* cannot succeed, because the SSN was never
   materialised in the object the runtime holds.
2. **Minimum-necessary becomes evidence.** The `minimization_manifest` is a per-request,
   hash-chained record of exactly which fields crossed the boundary — the artefact a
   HIPAA reviewer asks for and almost never gets.

## C3 — Deployment / residency view [REGIME]

```mermaid
flowchart TB
  subgraph GLOBAL["Global (no regulated data)"]
    CFG["Tenant config, flag definitions,<br/>build artefacts, code"]
    NOT["External notary<br/>(chain anchors — hashes only)"]
  end

  subgraph R1["Region A — Northwind Health (synthetic tenant)"]
    A1["Edge + control plane"] --> A2[("PHI store")]
    A1 --> A3["Inference endpoint A"]
    A1 --> A4[("Audit ledger shard A")]
  end

  subgraph R2["Region B — Meridian Clinics (synthetic tenant)"]
    B1["Edge + control plane"] --> B2[("PHI store")]
    B1 --> B3["Inference endpoint B"]
    B1 --> B4[("Audit ledger shard B")]
  end

  CFG -.->|config only, no PHI| A1
  CFG -.->|config only, no PHI| B1
  A4 -.->|daily root hash| NOT
  B4 -.->|daily root hash| NOT
```

Regulated data, model endpoints, and ledger shards are all region-pinned per tenant.
Only two things leave a region: tenant configuration (in) and **chain root hashes**
(out) — a hash of a hash, containing no record content. That is what makes external
notarisation compatible with residency.

Cross-references: [`data-handling/minimization-and-residency.md`](../data-handling/minimization-and-residency.md),
[`architecture/trust-boundaries.md`](trust-boundaries.md), [ADR-004](../adrs/ADR-004-residency-approach.md).
