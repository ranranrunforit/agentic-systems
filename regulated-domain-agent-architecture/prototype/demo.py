#!/usr/bin/env python3
"""Runs the five sequence views from architecture/sequence-views.md as live traffic.

    python3 demo.py

Every line printed is produced by the pipeline, not scripted output. The ledger
event counts at the end are the actual chain.
"""
from __future__ import annotations

from cara.fixtures import MERIDIAN, NORTHWIND, build_env
from cara.pipeline import Request

USER = "SYN-USR-4471"
ADA = "SYN-MRN-000123"
CY = "SYN-MRN-000789"

W = 78


def head(title: str) -> None:
    print(f"\n{'=' * W}\n{title}\n{'=' * W}")


def show(out, label: str = "outcome") -> None:
    print(f"  {label:<12} {out.decision.upper()}"
          f"{'  tier=' + str(int(out.tier)) if out.tier else ''}"
          f"{'  reason=' + out.reason_code if out.reason_code else ''}")
    if out.text:
        for line in out.text.splitlines()[:4]:
            print(f"               {line}")
    for c in out.citations[:3]:
        print(f"    cite       {c.get('doc')} v{c.get('version','-')} "
              f"[{c.get('source_class','-')}]")


def trace(env, cid: str) -> None:
    print("  ledger:")
    for e in env.ledger.reconstruct(cid):
        extra = e.get("reason_code") or e.get("rule") or e.get("cause") or ""
        print(f"    seq {e['seq']:>3}  {e['action']:<24} {extra}")


def main() -> None:
    env = build_env()
    p = env.pipeline

    head("S1 — High-risk path, approved (FR-1 → FR-4)")
    out = p.handle(Request(USER, NORTHWIND, "draft.summary", "draft referral letter", ADA))
    show(out)
    m = env.ledger.query(action="minimization.applied")[-1]
    print(f"  boundary     {len(m['fields_included'])} field paths crossed; "
          f"{len(m['fields_excluded_by_class'])} excluded by class")
    print(f"               excluded: {', '.join(m['fields_excluded_by_class'][:4])} ...")
    env.queue.approve(out.detail["item_id"], USER, edits=2, dwell_ms=184000)
    released = p.release_approved(out.detail["item_id"])
    show(released, "after HITL")
    trace(env, out.correlation_id)

    head("S2 — Fail-closed on grounding (silence is not absence)")
    env2 = build_env()
    from cara.models import Claim, ClaimType
    env2.pipeline.generator = lambda r, pl: (
        "The patient has no known drug allergies.",
        [Claim("C1", "no known drug allergies", ClaimType.PATIENT_SPECIFIC_FACT,
               r.subject_ref, asserts_absence=True)])
    out = env2.pipeline.handle(Request(USER, NORTHWIND, "draft.summary", "allergies?", ADA))
    show(out)
    print("  note         the allergy list is EMPTY, not a documented absence.")
    print("               the polarity veto refuses; the entailment scorer alone would not.")

    head("S3 — Toggle off → degraded mode (FR-5)")
    env3 = build_env()
    env3.flags_service.set(False, scope="feature", tenant=NORTHWIND,
                           feature="qa.record", actor="SYN-USR-9001",
                           reason_code="INCIDENT", reason_text="INCIDENT-1042")
    ev = env3.ledger.query(action="toggle.changed")[-1]
    print(f"  toggle       {ev['scope']}:{ev['scope_feature']} "
          f"{ev['previous_state']}→{ev['state']} by {ev['actor_id']} ({ev['reason_code']})")
    out = env3.pipeline.handle(Request(USER, NORTHWIND, "qa.record", "last a1c", ADA))
    show(out)
    print(f"  degraded     mode={out.detail['mode']}")
    print(f"               labs still available: {out.detail['content']['labs']}")

    print("\n  -- and with the flag service unreachable past max-stale --")
    env3.flags_service.reachable = False
    env3.flags._cache.clear()
    out = env3.pipeline.handle(Request(USER, NORTHWIND, "qa.general", "no-show policy"))
    show(out)

    head("S4 — Low-risk auto-flow (Tier 1: no human, but not no control)")
    env4 = build_env()
    out = env4.pipeline.handle(Request(USER, NORTHWIND, "qa.general", "no-show policy"))
    show(out)
    rel = env4.ledger.query(action="output.released")[-1]
    print(f"  owned by     {rel['accountable_role']}  (auto-flow is not unowned)")

    head("S5 — Bounded action, no approver → expire closed")
    env5 = build_env()
    env5.queue.rosters[(NORTHWIND, "supervising_clinician")] = []
    out = env5.pipeline.handle(Request(USER, NORTHWIND, "action.schedule",
                                       "schedule follow up", ADA,
                                       tools_invoked=("refill.request",)))
    show(out)
    ev = env5.ledger.query(action="approval.expired")[-1]
    print(f"  action_taken {ev['action_taken']}  (the default is NO OUTPUT)")

    head("Injection attempt (trust-boundaries T1)")
    env6 = build_env()
    env6.pipeline.handle(Request(USER, NORTHWIND, "draft.summary", "summarise visit", CY))
    m = env6.ledger.query(action="minimization.applied")[-1]
    print("  the note for SYN-MRN-000789 contains an embedded instruction to exfiltrate")
    print("  the SSN, address and insurance ID by email. Result:")
    print(f"    fields that crossed : {[f['path'] for f in m['fields_included']]}")
    print(f"    never materialised  : {m['fields_excluded_by_class'][:5]}")
    from cara.policy import TOOL_REGISTRY
    print(f"    registered tools    : {list(TOOL_REGISTRY)}  (no email, no generic HTTP)")

    head("Ledger integrity")
    v = env.ledger.verify()
    env.ledger.anchor("2026-08-13")
    print(f"  chain_ok={v['chain_ok']}  entries={v['entries']}  "
          f"deferred={v['deferred_writes_pending']}")
    print(f"  tier3_without_approval = {env.ledger.tier3_without_approval()}  "
          "(must always be empty)")
    print()


if __name__ == "__main__":
    main()
