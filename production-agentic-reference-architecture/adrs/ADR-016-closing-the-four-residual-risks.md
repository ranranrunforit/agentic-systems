# ADR-016 — Closing the four remaining weaknesses

- **Status**: Accepted
- **Date**: 2026-08-12
- **Owner**: Agentic Systems Architect
- **Closes**: R3 (structural groundedness), R6 (static cost estimates), ADR-012 cut 1
  (fixture-only retrieval), cut 4 (groundedness), cut 11 partially; hardens R9 and the
  ADR-015 residuals (no MFA, no TLS, no CSRF, no rate limiting)
- **Amends**: [ADR-003](ADR-003-memory-tiers.md), [ADR-007](ADR-007-guardrail-placement.md),
  [ADR-013](ADR-013-fanout-width-and-budget-enforcement.md),
  [ADR-015](ADR-015-authenticated-approval-and-review-ui.md)

## Context

The self-assessment named four weaknesses and ranked them. Each was recorded honestly,
but a recorded weakness is still a weakness, and three of the four were closable with
work rather than with infrastructure the project does not have.

1. **Groundedness was structural, not semantic** (R3, the highest open safety risk).
   `- The sky is green [S1]` passed, because only the *presence* of a marker was checked.
2. **Retrieval was fixture-only** (cut 1) — the transport was the one simulated part of
   an otherwise real pipeline.
3. **Authentication was password-only, over plain HTTP, without CSRF tokens or
   throttling** — ADR-015 closed the "no identity at all" hole but left thin identity.
4. **Budget headroom was 1.02×**, and the live budget guard projected against static
   constants that would drift (R6).

## Decisions

### 1. Semantic groundedness as a second output screen (`agent/groundedness.py`)

Every cited claim is now verified against **the text of the source it cites** — the
fetched document, deliberately not the summary, since checking a claim against a summary
the same model produced tests internal consistency rather than grounding.

Three signals, each catching a distinct failure: **content-word coverage** (fabrication,
misattribution), **numeric grounding** in digits *and* spelled-out form (numeric drift),
and **invented negation** (polarity inversion). A claim citing an unknown id is
unsupported, not skipped — skipping would make a dangling citation the easiest bypass.

**Lexical support, not an NLI model.** An entailment model is the better instrument and
stays the production recommendation; it was rejected here because it means a model
download, a non-deterministic gate (ADR-014), and inference cost per claim. The lexical
test is deterministic, explainable in a trace event, and errs toward flagging.

Two things this decision cost, both found by running it:

- **Spelled-out numeric drift initially passed.** "ninety" versus "twenty" is a single
  ordinary token, so coverage scored it as vocabulary variation. Fixed by grading number
  words alongside digits.
- **The first negation check was bidirectional and immediately produced a false
  positive** on a correct claim, because the source contained an incidental negation in a
  neighbouring clause ("cost is *not* a standard attribute"). Narrowed to one direction
  (negations the *claim* introduces) against the single best-matching sentence. The
  general lesson: a guardrail that cries wolf gets disabled, so a false positive is a
  design defect, not a conservative default.

Tested by mutation **M5** (a fluent claim citing a source that does not support it),
which the structural screen could not see.

### 2. Real HTTP retrieval (`agent/retrieval.py`)

Two transports behind one interface. `fixture` stays the default because the gate must be
deterministic; `http` is real: robots.txt with longest-match rules, HTML→text extraction
that strips script/style/nav/footer, manual redirect handling, streaming size caps,
content-type checks with sniffing, and conditional caching.

The security work is the substance. Fetching attacker-influenceable URLs is an SSRF
surface, so: the address check runs **after DNS resolution** (defeating rebinding) and
refuses private, loopback, link-local, reserved and multicast ranges — so
`http://169.254.169.254/` cannot be reached even if someone allowlists an IP; redirects
are followed manually and **re-validated at every hop**, because urllib's automatic
handling would follow an off-allowlist redirect invisibly; and reads are capped
**mid-stream**, since `Content-Length` is a claim rather than a fact.

Two bugs this surfaced, both real:

- **Header lookup was case-sensitive.** `dict(resp.headers)` preserves the server's
  casing, so `Content-Type` missed a server sending `Content-type` — HTML went unparsed,
  and a lowercase `location:` would have turned a redirect into a failed fetch. Fixed
  with a case-insensitive mapping, per RFC 9110.
- **https-only had no escape hatch**, so the real transport could never be exercised by a
  test. Resolved with `ALLOW_INSECURE_LOOPBACK`, off by default, settable only by the
  host and only for loopback. Untested network code is a worse risk than a
  loopback-scoped allowance.

### 3. Authentication hardening (`agent/identity.py`, `server.py`)

**TOTP** (RFC 6238, stdlib HMAC-SHA1) per principal, opt-in so a reviewer can enrol
without a migration, with one step of clock drift tolerated. **Login throttling** with
exponential backoff, because PBKDF2 raises the cost of a guess but does not bound the
number of guesses — and the lockout applies to a *correct* password too, or an attacker
who eventually guesses right is unaffected. **CSRF tokens** bound to the session and
compared in constant time, plus an independent **Origin/Referer** check. **Optional TLS**,
and the server now **refuses to bind a non-loopback address without it** rather than
serving credentials in the clear. Cookies are HttpOnly, SameSite=Strict, Secure under TLS.

Also found by driving the real server end to end: **the gate built its own
`IdentityStore`**, which has no in-memory sessions, so a valid UI login was rejected. The
identity store is now injected. The earlier demo had been hiding this by patching the
attribute afterwards — a reminder that a test which reaches into internals is not an
end-to-end test.

### 4. Budget: calibrated estimates plus a third lever

**`CostCalibrator`** replaces the static pre-flight constants with a rolling mean over the
last 20 runs' observed per-stage spend, read from trace `cost_usd`. Below three samples the
seed constants stand in and the span records `budget.estimate_source: seed_constants`, so
the trace never implies more precision than exists. The seeds turned out to over-estimate
worker cost by ~3.5× and synthesis by ~2.3×, meaning the budget guard had been capping
fan-out unnecessarily — exactly the drift R6 predicted.

**Lever L3** caps evidence *per sub-question* rather than only globally. Synthesis input is
77% of per-task cost, and a global cap spends it unevenly: one well-covered sub-question
crowds out the others while paying for near-duplicate summaries of the same point.
Measured in the spike, capping 3→1 cut synthesis input from 811 to 401 tokens.

L3 does **not** widen fan-out — p95 binds at width 4 whatever the cost — but it fixes the
actual problem, which was margin:

| configuration | cost/task | tasks/month | headroom |
|---|---|---|---|
| width 3, evidence 3/sub-q | $0.1304 | 12,269 | 1.02× |
| **width 3, evidence 2/sub-q (adopted)** | **$0.1119** | **14,303** | **1.19×** |

So `RunConfig.max_evidence_per_subquestion = 2`. It is the cheapest of the three levers in
quality terms — dropping a usually-near-duplicate third source, rather than cutting
sub-questions (L1) or degrading synthesis (L2), both of which stay in reserve.

## Consequences

**Positive**
- The highest open safety risk is closed: claims are traceable to the text they cite, and
  the mutation suite proves the screen catches what the structural one missed.
- Retrieval is real; the fixture corpus is now a *choice made for determinism*, not a
  limitation.
- Approval requires a second factor if enrolled, survives CSRF, and is throttled.
- Budget margin is 1.19× and the live guard tracks observed cost instead of a guess.
- 119 tests, 5/5 mutations caught, 22 control assertions, ten verification stages.

**Negative / accepted costs**
- **Lexical support is not entailment.** A faithful claim in different vocabulary can be
  flagged, and a claim that copies a *wrong* source passes. The gap between "traceable"
  and "true" remains open and is now the most honest statement of the limit.
- The coverage threshold (0.6) and the negation match threshold (0.5) are judgement calls;
  both are gate thresholds and therefore governed changes.
- **Search is still not real.** `HttpTransport.fetch` is; `search` raises unless a provider
  endpoint is configured, because there is no standards-based search to fall back on.
  Pretending otherwise would be the dishonest option.
- TOTP is opt-in, so an unenrolled principal is still password-only.
- The review server remains `http.server`: no account recovery, no failed-login audit
  beyond the counter, no session store across restarts.
- L3 loses genuine third sources on questions where three sources really do differ; the
  eval harness is where that trade must be watched.
- `CostCalibrator` averages across question shapes, so a run far from the recent mix is
  mis-projected. Per-shape calibration is not built.
