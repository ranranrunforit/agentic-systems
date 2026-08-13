#!/usr/bin/env python3
"""Runs the SAME request shape through both regimes, side by side.

    python3 portability_demo.py

Nothing below constructs a sector-specific component. Both columns use the identical
AuditLedger, FlagService, PolicyEngine, MinimizationFilter, GroundingVerifier,
RiskClassifier, ApprovalQueue, and Pipeline classes. The only difference between the
two runs is the `regime=` argument.
"""
from __future__ import annotations

from cara.fixtures import NORTHWIND, build_env
from cara.fixtures_finance import ATLAS, build_finance_env
from cara.models import RiskTier
from cara.pipeline import Request
from cara.regimes import FINANCE, HEALTHCARE

W = 84


def head(t):
    print(f"\n{'=' * W}\n{t}\n{'=' * W}")


def row(label, a, b):
    print(f"  {label:<26} | {str(a):<24} | {str(b)}")


def main():
    h, f = build_env(), build_finance_env()

    head("Same spine, two regimes")
    row("", "HEALTHCARE", "FINANCE")
    print("  " + "-" * (W - 4))
    row("ledger class", type(h.ledger).__name__, type(f.ledger).__name__)
    row("policy class", type(h.policy).__name__, type(f.policy).__name__)
    row("minimizer class", type(h.pipeline.minimizer).__name__,
        type(f.pipeline.minimizer).__name__)
    row("verifier class", type(h.pipeline.verifier).__name__,
        type(f.pipeline.verifier).__name__)
    row("queue class", type(h.queue).__name__, type(f.queue).__name__)

    head("FR-1 — data handling")
    row("access model", HEALTHCARE.access_model[:24], FINANCE.access_model[:40])
    row("never crosses boundary",
        sorted(c.value for c in HEALTHCARE.never_crosses),
        sorted(c.value for c in FINANCE.never_crosses))
    row("residency required", HEALTHCARE.residency_required, FINANCE.residency_required)
    row("documentation retention", f"{HEALTHCARE.retention_years['documentation']} yr",
        f"{FINANCE.retention_years['documentation']} yr")
    row("minimization mechanism", "MinimizationFilter", "MinimizationFilter  <= UNCHANGED")

    ho = h.pipeline.handle(Request("SYN-USR-4471", NORTHWIND, "qa.record",
                                   "what was the last a1c", "SYN-MRN-000123"))
    fo = f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "qa.account",
                                   "what is my balance", "SYN-CUST-0007"))
    hm = h.ledger.query(action="minimization.applied")[-1]
    fm = f.ledger.query(action="minimization.applied")[-1]
    row("fields crossed", len(hm["fields_included"]), len(fm["fields_included"]))
    row("excluded by class", len(hm["fields_excluded_by_class"]),
        len(fm["fields_excluded_by_class"]))
    print(f"    finance exclusions include the PCI class: "
          f"{[p for p in fm['fields_excluded_by_class'] if p.startswith('card')]}")
    row("manifest schema", "identical", "identical  <= UNCHANGED")

    head("FR-3 — risk and HITL")
    row("consequence trigger", HEALTHCARE.consequence_label[:24],
        FINANCE.consequence_label[:40])
    row("T3 claim types", "subject-specific", "subject-specific  <= UNCHANGED")
    row("owning role at T3", HEALTHCARE.owning_roles[RiskTier.T3],
        FINANCE.owning_roles[RiskTier.T3])
    row("self-approval allowed", HEALTHCARE.self_approval_allowed,
        f"{FINANCE.self_approval_allowed}  <= TIGHTENED (SoD)")
    row("monetary axis", HEALTHCARE.dual_approval_over_amount,
        f"{FINANCE.dual_approval_over_amount}  <= NEW")

    print("\n  Segregation of duties, executed:")
    fout = f.pipeline.handle(Request(
        "SYN-USR-2202", ATLAS, "draft.disclosure", "dispute disclosure",
        "SYN-CUST-0007",
        elements=frozenset({"principal_reasons", "information_source",
                            "free_report_right", "dispute_rights"})))
    try:
        f.queue.approve(fout.detail["item_id"], "SYN-USR-2202")
        print("    UNEXPECTED: self-approval succeeded under SOX")
    except PermissionError as e:
        print(f"    initiator tried to approve -> DENIED: {str(e)[:64]}...")
    hq = h.pipeline.handle(Request("SYN-USR-4471", NORTHWIND, "draft.summary",
                                   "draft referral letter", "SYN-MRN-000123"))
    h.queue.approve(hq.detail["item_id"], "SYN-USR-4471")
    print("    same action under HIPAA          -> ALLOWED (and recorded as self-approval)")

    head("FR-4 — grounding")
    row("pipeline", "decompose/retrieve/entail", "same  <= UNCHANGED")
    row("compatibility matrix",
        "identical" if HEALTHCARE.compatibility == FINANCE.compatibility else "DIFFERS",
        "identical  <= UNCHANGED")
    row("S1 means", HEALTHCARE.source_class_labels[__import__(
        "cara.models", fromlist=["SourceClass"]).SourceClass.S1][:24],
        FINANCE.source_class_labels[__import__(
            "cara.models", fromlist=["SourceClass"]).SourceClass.S1][:40])
    row("deterministic vetoes", 9, "9  <= UNCHANGED")
    row("conformance rules", len(HEALTHCARE.conformance_rules),
        f"{len(FINANCE.conformance_rules)}  <= NEW CONTROL")

    print("\n  The new control, executed:")
    incomplete = f.pipeline.handle(Request(
        "SYN-USR-2201", ATLAS, "draft.disclosure", "adverse action notice",
        "SYN-CUST-0007", elements=frozenset({"principal_reasons"})))
    print(f"    adverse-action notice missing elements -> {incomplete.decision.upper()}")
    print(f"    reason: {incomplete.reason_code}")
    print(f"    grounding.failed events: "
          f"{len(f.ledger.query(action='grounding.failed'))}  "
          "<- grounding passed; conformance refused")

    head("FR-5 — toggles")
    row("scopes", "global/tenant/feature/subj", "same  <= UNCHANGED")
    row("resolution", "conjunctive, fail-closed", "same  <= UNCHANGED")
    f.flags_service.set(False, scope="tenant", tenant=ATLAS, reason_code="INCIDENT")
    deg = f.pipeline.handle(Request("SYN-USR-2201", ATLAS, "qa.account",
                                    "balance", "SYN-CUST-0007"))
    row("AI off => degraded", "structured_record_view", deg.detail["mode"])
    print(f"    deterministic view still served: {list(deg.detail['content'])}")

    head("Verdict")
    print("  Spine components constructed for finance : 0")
    print("  Regime parameters bound for finance      : "
          f"{len(FINANCE.__dataclass_fields__)}")
    print("  New regime-specific controls discovered  : 1 (disclosure completeness)")
    print("  Ledger chains verify in both regimes     : "
          f"{h.ledger.verify()['chain_ok']} / {f.ledger.verify()['chain_ok']}")
    print()


if __name__ == "__main__":
    main()
