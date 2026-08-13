# Third-party extensions (marketplace governance)

Today every extension is first-party or second-party (another internal team). This
document specifies what must be true before a third party can publish, and is honest
that the platform is **not there yet**.

## The three things that change with third parties

1. **No code review relationship.** We may see the code; we cannot vouch for the
   development process behind it, and the next version may differ.
2. **No employment relationship.** Deterrence is contractual, not organisational.
3. **Scale.** Ten first-party extensions can be reviewed thoroughly; a thousand cannot.

## Blocking prerequisite: capability attestation

**Not implemented.** The gap: `extension.yaml` is trusted because the repository is
trusted. For third parties the manifest and the code must be cryptographically bound
to what the reviewer approved:

1. the publisher signs the bundle (manifest + code) with a key registered at onboarding;
2. the registry records `(bundle digest, signature, publisher, approved permission set)`
   at approval;
3. the loader verifies signature **and** digest before registering any capability, so a
   post-approval manifest edit fails closed;
4. revocation is a transparency-log entry the loader consults.

Design in [`../security/isolation.md`](../security/isolation.md); tracked in
[ADR-003](../adrs/ADR-003-isolation-mechanism.md) and ADR-010.

## Additional controls required

| Control | Why | Status |
|---|---|---|
| Signed bundles + digest pinning | The manifest is the security contract | specified |
| Stronger isolation per invocation (gVisor/Firecracker or WASM) | In-process guards are inadequate against a hostile publisher | specified |
| Publisher identity and onboarding (legal + technical) | Attribution and takedown | not started |
| Permission ceiling by tier | An unvetted publisher must not be able to *request* high-impact actions at all | policy work |
| Mandatory staging tenancy | New extensions run against synthetic data before any real tenant | not started |
| Per-extension rate limits and egress budgets | An authorized extension can still act at machine speed | not started (ADR-010) |
| Automated re-vetting on every version | Manual review does not scale | not started |
| Tenant-level allowlisting | Each tenant decides which third-party extensions may touch their data | not started |

## Proposed tiers

| Tier | Who | Max impact | Isolation | Review |
|---|---|---|---|---|
| **T0 first-party** | Platform team | high (with justification) | subprocess | full review |
| **T1 internal** | Another internal team | high (board approval) | subprocess | full review |
| **T2 verified partner** | Contracted third party | medium | microVM or WASM | full review + signing + staging |
| **T3 open publisher** | Anyone | low, read-only, no egress beyond their own domain | WASM | automated checks + signing + tenant opt-in |

The tier caps what a manifest may *request*. A T3 publisher asking for
`issue_tracker:close` is rejected by the loader, not by a reviewer's judgement — the
policy and the tier are both data.

## Revocation at marketplace scale

Two new mechanisms beyond the existing kill-switch:

- **Publisher-level revocation.** Pull a key and every extension from that publisher
  fails to load on next verification, across every host.
- **Version-level blocklist.** A specific digest is refused while the publisher's other
  versions keep working — the usual case when one release is bad.

Existing per-extension `host.kill` remains the immediate tool; these two are for the
"we cannot reach every host in the next five minutes" problem.

## What we would tell a prospective publisher

- Your extension gets no network beyond the destinations you declare and we approve.
- You never receive a credential, ours or the customer's.
- You cannot execute a customer-visible action; you can propose one.
- Every call you make is logged and attributable to your version.
- We can turn you off in one call, and we will, before we investigate.
