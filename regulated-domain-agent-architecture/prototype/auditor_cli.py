#!/usr/bin/env python3
"""The auditor walkthrough from stretch/auditor-walkthrough.md, executed.

    python3 auditor_cli.py

Nine steps, one correlation ID. Each step prints the question, the query, the result,
and a PASS/FAIL. Step 0 comes first on purpose: an auditor who reconstructs a decision
from a trail they have not verified has audited a story, not a system.
"""
from __future__ import annotations

import sys

from cara.fixtures import NORTHWIND, build_env
from cara.pipeline import Request
from cara.policy import CAPABILITIES, TOOL_REGISTRY

USER = "SYN-USR-4471"
ADA = "SYN-MRN-000123"
W = 78
results: list[tuple[str, bool]] = []


def step(n: str, question: str) -> None:
    print(f"\n{'-' * W}\nSTEP {n} — {question}\n{'-' * W}")


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"\n         {detail}" if detail else ""))


def main() -> int:
    env = build_env()

    # --- set the scene: produce one real Tier-3 decision to audit ----------------
    out = env.pipeline.handle(Request(USER, NORTHWIND, "draft.summary",
                                      "draft referral letter", ADA))
    env.queue.approve(out.detail["item_id"], USER, edits=2, dwell_ms=184000)
    env.pipeline.release_approved(out.detail["item_id"])
    # ...plus some negative-path traffic, because a system that never refuses is
    # either perfect or broken, and only one of those is likely.
    env.policy.available = False
    env.pipeline.handle(Request(USER, NORTHWIND, "qa.record", "last a1c", ADA))
    env.policy.available = True
    env.ledger.anchor("2026-08-13")
    cid = out.correlation_id

    print("=" * W)
    print("AUDITOR WALKTHROUGH — reconstructing one Tier-3 decision")
    print(f"Case: referral letter released for {ADA} at Northwind Health")
    print(f"Correlation ID (from the document footer): {cid}")
    print("=" * W)

    step("0", "Could this trail have been edited before I arrived?")
    v = env.ledger.verify()
    print(f"  audit.chain_verify() -> {v}")
    check("chain verifies and anchors match", v["chain_ok"] and v["deferred_writes_pending"] == 0)

    step("1", "Retrieve the decision")
    events = env.ledger.reconstruct(cid)
    for e in events:
        print(f"    seq {e['seq']:>3}  {e['action']}")
    required = {"authn.success", "policy.allow", "minimization.applied",
                "risk.classified", "grounding.result", "approval.queued",
                "approval.granted", "output.released"}
    actions = {e["action"] for e in events}
    check("every control left a trace", required <= actions,
          f"missing: {required - actions or 'none'}")

    step("2", "What did the model see? (FR-1, minimum-necessary)")
    m = next(e for e in events if e["action"] == "minimization.applied")
    print(f"  included : {[f['path'] for f in m['fields_included']]}")
    print(f"  excluded : {m['fields_excluded_by_class']}")
    print(f"  allowlist: {m['allowlist_version']}   prompt_hash: {m['prompt_hash'][:22]}...")
    allowed = set(CAPABILITIES["draft.summary"].allowlist)
    crossed = {f["path"] for f in m["fields_included"]}
    check("no field crossed that is off the allow-list", crossed <= allowed,
          f"unexpected: {crossed - allowed or 'none'}")
    check("no direct identifier crossed the boundary",
          not (crossed & {"patient.mrn", "patient.ssn", "patient.name"}))

    step("3", "What did it claim, and on what evidence? (FR-4)")
    g = next(e for e in events if e["action"] == "grounding.result")
    for c in g["citations"]:
        print(f"    {c['source_class']}  {c['doc']} v{c['version']} @{c['span']}")
    check("every claim carries a citation", g["supported"] == g["total"],
          f"{g['supported']}/{g['total']} supported at tau_hard={g['tau_hard']}")
    check("patient-specific claims cite S1 (the record)",
          any(c["source_class"] == "S1" for c in g["citations"]))

    step("4", "Was the human gate applied? (FR-3)")
    r = next(e for e in events if e["action"] == "risk.classified")
    a = next(e for e in events if e["action"] == "approval.granted")
    rel = next(e for e in events if e["action"] == "output.released")
    print(f"  tier={r['tier']} rule={r['rule']} owning_role={r['accountable_role']}")
    print(f"  approver={a['actor_id']} role={a['actor_role']} "
          f"dwell={a['dwell_ms']}ms edits={a['edits']}")
    check("release came after approval", rel["seq"] > a["seq"])
    check("approver held the owning role", a["actor_role"] == r["accountable_role"])
    check("dwell time is plausible for review", a["dwell_ms"] > 3000,
          "sub-3s medians would indicate rubber-stamping (T6)")
    orphans = env.ledger.tier3_without_approval()
    check("POPULATION: no Tier-3 release without approval", orphans == [],
          f"orphans: {orphans}")

    step("5", "Was AI even supposed to be on? (FR-5)")
    pol = next(e for e in events if e["action"] == "policy.allow")
    print(f"  flags at decision time: {pol['flags_snapshot']}")
    snap = pol["flags_snapshot"]
    check("flag state was recorded per request, not inferred",
          "flag_version" in snap)
    check("AI was enabled at every scope",
          snap["global_kill"] == "on" and snap["tenant"] and snap["feature"]
          and not snap["subject_restricted"])

    step("6", "Could the record have been altered by the agent? (FR-2, integrity)")
    writes = [t for t, meta in TOOL_REGISTRY.items() if meta["writes_record"]]
    agent_writes = env.ledger.query(action="record.write")
    print(f"  tools declaring writes_record=True : {writes or 'none'}")
    print(f"  record.write events by an agent    : {len(agent_writes)}")
    check("the agent has no write path to the record", not writes and not agent_writes)

    step("7", "Where did the data physically go? (FR-1, residency)")
    print(f"  boundary: {m['boundary']}")
    b = m["boundary"]
    check("region-pinned, zero-retention, no training",
          b["region"] == "region-a" and b["retention"] == "zero"
          and b["training"] == "prohibited")

    step("8", "Does the refusal behaviour actually fire? (NFR-4)")
    denials = env.ledger.query(action="policy.deny")
    print(f"  policy.deny events: {[d['reason_code'] for d in denials]}")
    check("negative paths are exercised and audited", bool(denials),
          "a system that never refuses is either perfect or broken")

    step("9", "Accounting of disclosures (O-P5 / §164.528)")
    disclosures = env.ledger.disclosures_by_subject(ADA)
    for d in disclosures:
        print(f"    {d['action']} tier={d.get('tier')} by role={d.get('accountable_role')}")
    check("disclosures are enumerable per subject", len(disclosures) >= 1)

    print("\n" + "=" * W)
    passed = sum(1 for _, ok in results if ok)
    print(f"WALKTHROUGH COMPLETE — {passed}/{len(results)} checks passed "
          f"in {len(events)} ledger events from one correlation ID")
    print("=" * W)
    for label, ok in results:
        if not ok:
            print(f"  FAILED: {label}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
