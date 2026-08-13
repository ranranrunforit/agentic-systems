# Safe Degraded Mode — FR-5 [AGNOSTIC]

**Definition:** the deterministic, non-AI path the product runs on when AI is disabled at
any scope. It is a first-class product mode, specified and tested, not an error state.

Design rule: **the product is a records and workflow product that has an AI assist. It is
not an AI product.** Everything below follows from that.

## 1. Per-capability degraded behaviour

| Capability | AI on | AI off (degraded) | User-visible message |
|---|---|---|---|
| `qa.record` | Grounded natural-language answer with citations | **Structured record view**: deterministic filtered query results (labs, meds, problems) rendered as tables, plus keyword search over the record | "AI assist is off. Showing the record directly." |
| `draft.summary` | Drafted narrative for clinician approval | **Templated skeleton** pre-filled with deterministic record fields (visit date, problems, meds, vitals), clinician completes the narrative | "AI assist is off. Here's the standard template with your record data filled in." |
| `action.schedule` | Proposes intervals and refill requests | **Manual scheduling UI** with protocol-derived default intervals from `SYN-VS-CLIN-001` (a lookup table, not a model) | "AI assist is off. Suggested intervals come from your clinic's protocol." |
| `qa.general` | Grounded answer over policy corpus | **Keyword search + document links** into the same policy corpus | "AI assist is off. Here are matching policy documents." |

Two properties across every row:

1. **The underlying data and workflow remain fully available.** Nothing about record
   access, scheduling, or document retrieval depends on the model.
2. **The degraded path uses the same vetted corpora.** Turning off AI removes the
   *generation*, not the *sources* — so answers are less convenient, not less grounded.

## 2. What degraded mode must never do

| Never | Why |
|---|---|
| Return 500 / "service unavailable" | Then the toggle is unusable in a real incident |
| Silently fall back to a weaker model | The tenant turned AI **off**, not "down a tier" |
| Queue requests to replay when AI returns | Replaying processing the tenant prohibited, later, is a compliance violation with a delay |
| Hide the mode from users | Users must know why output changed, or they route around the product |
| Lose in-flight work | Drafts and queued approvals are preserved (§4) |

## 3. Transparency

Degraded state is surfaced three ways: a persistent banner in the affected surface, a
per-response notice, and a status field in the API (`ai_status: {enabled:false, scope:"tenant", since:"…"}`)
so embedding systems (EHR integrations) can render their own indication. The *reason code*
is shown to tenant administrators; end users see the fact, not the incident detail.

## 4. In-flight work at the moment of the flip

| In-flight item | Disposition |
|---|---|
| Request mid-generation | Aborted; user sees the degraded path; no partial AI output released |
| Draft saved but not submitted | Preserved, editable, marked "AI assist unavailable" |
| Tier-3 item queued for approval | **Held** — visible and approvable by a human, never auto-released, never silently dropped. Disposition audited |
| Bounded action approved but not executed | Executes (a human already approved it; the approval, not the model, is the authority) |

The distinction in the last two rows: the toggle stops *AI processing*, not *human
decisions that have already been made*. Cancelling a clinician's approved action because a
flag flipped would be its own kind of harm.

## 5. Audit

| Event | When |
|---|---|
| `toggle.changed` | The flip itself (see [toggle-spec](toggle-spec.md#4-flag-record-and-change-audit-fr-5--fr-2)) |
| `policy.degraded {feature, cause}` | Each request served by the degraded path — so the *volume* of degraded operation is measurable, not just the flip |
| `queue.held {item_id, cause}` | Each Tier-3 item held |
| `queue.disposition {item_id, outcome}` | How each held item ended |
| `degraded.exited {duration_s, requests_served}` | When AI is re-enabled — the incident record's summary line |

## 6. Non-degradation guarantees (tested in CI)

The product must boot and pass these journeys with every AI component stubbed unavailable:

1. Authenticate, open a patient record, read structured data.
2. Search records and policy documents by keyword.
3. Create, save, and print a visit summary from a template.
4. Book, reschedule, and cancel an appointment.
5. Submit a records request and a data-subject request.
6. Approve or reject a held Tier-3 item.
7. Read the audit trail.

If any of these fails with AI stubbed out, the dependency is a bug: an AI component has
become load-bearing for a non-AI journey, and the kill switch has quietly become a
product outage switch.

## 7. Degraded mode as a compliance control, not just resilience

This mode is what makes several obligations satisfiable at all:

- **Contingency / emergency operation (O-S5)** — the product functions without the model.
- **Patient restrictions (O-P6)** — a restricted patient's workflows still work; they just
  run deterministically.
- **Incident procedures (O-S4)** — an incident response that requires taking the product
  down is one the tenant will resist using; one that only removes the assist will actually
  be used.
- **Procurement flexibility** — `SYN-TEN-meridian` runs with `draft.summary` permanently
  off by policy. Degraded mode means that is a supported configuration, not a broken one.
