# ADR-010 — Open security questions

**Status:** Open · **Date:** 2026-05-28 · **Owner:** security + platform

Recorded rather than hidden. Each item has a consequence, a current mitigation and what
would resolve it. Ordered by how much they would change if we shipped third-party
extensions tomorrow.

## 1. No capability attestation (blocking for third parties)

**Gap.** `extension.yaml` is trusted because the repository is trusted. Nothing binds the
manifest a reviewer approved to the code that runs.

**Consequence.** A third-party publisher could ship a manifest that differs from the
reviewed one. Also, no host can verify permissions before loading.

**Mitigation today.** First/second-party only; code review; the loader still enforces the
grant file, so an *unapproved permission* fails even if the manifest was edited.

**Resolution.** Sign bundles (Sigstore/cosign or org PKI); record `(digest, signature,
publisher, approved permissions)` at approval; loader verifies both before registering
capabilities; revocation via transparency log. Design in `security/isolation.md`.

## 2. In-process sandbox guards are not a boundary

**Gap.** The import blocker and `open()` guard are defeatable from arbitrary Python.

**Consequence.** The reference host's containment is defence in depth, not a guarantee.

**Mitigation today.** Documented twice in `security/isolation.md`; `remote-rpc` exists for
lower-trust code.

**Resolution.** seccomp-bpf + netns + cgroups as the baseline; gVisor/Firecracker or WASM
per invocation for untrusted publishers.

## 3. Taint is call-level, not field-level

**Gap.** If an extension reads one untrusted article, everything it proposes in that
invocation is tainted.

**Consequence.** Over-blocking, which drives confirmation fatigue — the most likely way
this control degrades in practice.

**Mitigation today.** Calibrated thresholds (taint alone does not block medium actions);
the failure direction is safe.

**Resolution.** Field-level provenance through the model boundary. Hard: it needs the
model to preserve provenance across summarisation, which is an open research problem
rather than an engineering task.

## 4. No rate limiting or anomaly detection

**Gap.** An authorized extension can act at machine speed within its grant.

**Consequence.** A compromised-but-authorized connector could label or comment on every
ticket in a tenant before anyone notices.

**Mitigation today.** Everything is audited; high-impact actions need per-target
confirmation.

**Resolution.** Per-extension, per-tenant action budgets enforced at the gate, plus
alerting on deviation from baseline. This is the next security increment we would build.

## 5. `io` is descriptive, not enforced

**Gap.** The host validates the manifest, not each payload against `io`.

**Consequence.** Malformed payloads are a correctness problem and could mask a bug.

**Resolution.** Validate at the gate boundary; reject on mismatch and audit it. Cheap;
just not done.

## 6. One upstream credential per provider per tenant

**Gap.** Not per user. An extension acting "as the end user" uses a tenant-level
credential.

**Consequence.** Upstream audit logs cannot distinguish which human's request drove an
action — our audit log can, theirs cannot.

**Resolution.** Per-user token storage plus a consent ledger, with revocation propagation
from upstream webhooks.

## 7. Confirmation fatigue

**Gap.** The control depends on humans reading prompts.

**Consequence.** Approvals become reflexive, and the gate degrades into a click-through.

**Mitigation today.** R-900 removes the click-through path for the worst class (tainted
high impact) entirely; prompts show resource, action, target, impact and taint.

**Resolution.** Narrower scopes so fewer actions are high impact; batch review surfaces;
track confirmations per operator per day as a reliability metric, not a vanity one.

## 8. No policy hot-reload; two artifacts to keep coherent

**Gap.** Policy and grants are separate files; changes need a restart.

**Consequence.** A permission can be approved and still denied by policy, which confuses
authors.

**Mitigation.** `ext permissions` and rule ids in every denial message.

**Resolution.** Signed policy bundles with hot-reload, and a single `ext why` command that
explains a decision against both artifacts.

## 9. ABAC will strain on relationship rules

**Gap.** "The assignee of the ticket may comment" is not an attribute of the request.

**Resolution.** ReBAC (Zanzibar-style) for those rules, keeping ABAC for the rest. Only
worth it when the domain actually asks.

## 10. Insider with policy write access

**Gap.** Whoever can merge `approved-grants.yaml` or `abac-policy.yaml` unreviewed owns
the platform.

**Mitigation.** CODEOWNERS, required approvers, author≠approver, hash-chained audit log
shipped off-host.

**Resolution.** Not a code problem. Signed policy bundles with a separate signing key
held by the governance board would raise the bar.

## 11. No automatic kill on anomaly

**Deliberate, not an oversight.** A false positive silently disables a workflow. Alerting
pages a human who pulls the switch. Revisit only with a very low false-positive rate and
a fast reversal path.

## Review cadence

Re-read this ADR at every grant expiry review and after every incident. An item that has
been open for a year without a resolution date is either accepted risk — and should be
moved to the threat model as such — or nobody owns it.
