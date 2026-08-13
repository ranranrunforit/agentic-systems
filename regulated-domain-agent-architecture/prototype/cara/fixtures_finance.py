"""CARA-F: the same system under GLBA / PCI / SOX.

Maps to: portability/portability-analysis.md §1.

Every synthetic record here is invented. NOTE what is absent: there is no PAN in this
file, not even a test PAN. Card references are TOKENS. That is not squeamishness -- it
mirrors the actual design decision (portability-analysis §2a): CARA-F engineers itself
OUT of PCI scope rather than into compliant-in-scope, so a real PAN should be
impossible to find anywhere in the system, including its fixtures.
"""
from __future__ import annotations

import copy
from typing import Any

from .audit import AuditLedger
from .fixtures import Env
from .flags import FlagCache, FlagService
from .grounding_corpus import CorpusStore, Document
from .minimization import RecordStore
from .models import Claim, ClaimType, SourceClass
from .pipeline import Pipeline, Request
from .policy import PolicyEngine
from .regimes import FINANCE
from .risk import ApprovalQueue

ATLAS = "SYN-TEN-atlasbank"
MERIDIAN_BANK = "SYN-TEN-meridianbank"

RECORDS: list[dict[str, Any]] = [
    {
        "tenant": ATLAS,
        # The spine addresses records by `patient.mrn`. Rather than fork the store
        # for finance, the customer record presents the same shape: the spine's
        # notion is "subject reference", and `patient` is a healthcare name for it.
        # A production port would rename the key; the point here is that the STORE,
        # the predicate, and the isolation logic needed no change at all.
        "patient": {"mrn": "SYN-CUST-0007", "name": "Rae Notional",
                    "dob": "1984-09-12", "ssn": "SYN-TIN-00-0000000",
                    "phone": "+1-555-0177", "email": "rae@example.invalid",
                    "address": {"zip": "99998"}},
        # Rendered WITH the currency on purpose: the unit-fidelity veto (V5) refuses a
        # claim naming USD when the span does not, and it is right to. A bare number
        # in a financial record is a latent unit error waiting to be asserted.
        "account": {"number": "SYN-ACCT-4410", "balance": "2841.55 USD"},
        "card": {"token": "SYN-PAN-TOKEN-a91f"},  # tokenised upstream. No PAN. Ever.
        "products": [{"text": "Everyday Checking", "opened": "2019-03-04"},
                     {"text": "Atlas Rewards Card", "opened": "2022-08-15"}],
        "transactions": [
            {"text": "Card purchase 84.20 USD at SYN-MERCHANT-11", "date": "2026-08-02"},
            {"text": "Direct deposit 2400.00 USD payroll", "date": "2026-08-01"},
        ],
        "credit": {"score_band": "700-749"},
        "disputes": [{"text": "Dispute SYN-DSP-31 filed for 84.20 USD",
                      "date": "2026-08-05", "status": "under investigation"}],
        "notes": [{"date": "2026-08-05",
                   "text": "Customer called about the 84.20 USD charge. Advised of "
                           "provisional credit timeline."}],
        "labs": [], "problem_list": [], "medications": [], "allergies": [],
    },
    {
        "tenant": MERIDIAN_BANK,
        "patient": {"mrn": "SYN-CUST-9001", "name": "Sam Fictitious", "dob": "1990-02-20"},
        "account": {"number": "SYN-ACCT-8800", "balance": "120.00 USD"},
        "products": [{"text": "Basic Savings", "opened": "2021-01-01"}],
        "transactions": [], "credit": {"score_band": "650-699"}, "disputes": [],
        "notes": [], "labs": [], "problem_list": [], "medications": [], "allergies": [],
    },
]

DOCS = [
    Document("SYN-VS-FIN-TERMS-001", ATLAS, "Everyday Checking product terms",
             SourceClass.S2, "3.0", "2027-06-30", "current",
             [{"text": "Overdraft fee is 34.00 USD per item, maximum three per day.",
               "offsets": "4:0-58"},
              {"text": "Provisional credit is issued within 10 business days of a dispute.",
               "offsets": "5:0-66"}]),
    Document("SYN-VS-FIN-REG-002", ATLAS, "Reg E error resolution summary",
             SourceClass.S5, "2026.1", "2027-12-31", "current",
             [{"text": "The institution must investigate a dispute within 45 days and "
                       "may issue provisional credit.", "offsets": "1:0-92"}]),
    Document("SYN-VS-FIN-PROC-003", ATLAS, "Dispute handling procedure",
             SourceClass.S4, "2.1", "2027-03-31", "current",
             [{"text": "Disputes over 500.00 USD are escalated to the servicing officer.",
               "offsets": "2:0-62"}]),
    Document("SYN-VS-MERB-001", MERIDIAN_BANK, "Meridian Bank savings terms",
             SourceClass.S2, "1.0", "2027-01-31", "current",
             [{"text": "Meridian Bank overdraft fee is 20.00 USD per item.",
               "offsets": "1:0-48"}]),
]


def finance_generator(req: Request, payload: dict[str, Any]):
    q = req.question.lower()

    if "balance" in q:
        return ("Your Everyday Checking balance is 2841.55 USD.",
                [Claim("C1", "balance 2841.55 USD", ClaimType.SUBJECT_SPECIFIC_FACT,
                       req.subject_ref)])

    if "dispute" in q or "adverse" in q or "disclosure" in q:
        return ("Provisional credit is issued within 10 business days of a dispute.",
                [Claim("C1", "Provisional credit issued within 10 business days dispute",
                       ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION, req.subject_ref)])

    if "overdraft" in q or "fee" in q:
        return ("The overdraft fee is 34.00 USD per item, maximum three per day.",
                [Claim("C1", "Overdraft fee 34.00 USD per item maximum three per day",
                       ClaimType.ORGANISATIONAL_PROCESS)])

    return ("I don't have enough to answer that.", [])


def build_finance_env() -> Env:
    """Note what this function does NOT do: it does not construct a single
    finance-specific spine component.

    AuditLedger, FlagService, FlagCache, PolicyEngine, RecordStore, CorpusStore,
    ApprovalQueue, Pipeline -- all the same classes as healthcare, differing only in
    the `regime=FINANCE` argument. That is the portability claim, executed.
    """
    ledger = AuditLedger(shard="region-a")
    svc = FlagService(ledger)
    for feature in ("qa.general", "qa.account", "draft.disclosure", "action.servicing"):
        svc.set(True, scope="global", feature=feature, reason_code="TEST")
        for tenant in (ATLAS, MERIDIAN_BANK):
            svc.set(True, scope="feature", tenant=tenant, feature=feature,
                    reason_code="TEST")
    for tenant in (ATLAS, MERIDIAN_BANK):
        svc.set(True, scope="tenant", tenant=tenant, reason_code="TEST")

    records = RecordStore(copy.deepcopy(RECORDS), subject_key="patient.mrn")
    policy = PolicyEngine(records, ledger, regime=FINANCE)
    policy.care_relationships = {          # here: the SERVICING relationship
        ("SYN-USR-2201", "SYN-CUST-0007"),  # front-line agent
        ("SYN-USR-2202", "SYN-CUST-0007"),  # servicing officer
        ("SYN-USR-8801", "SYN-CUST-9001"),
    }
    policy.roles = {"SYN-USR-2201": "front_line_agent",
                    "SYN-USR-2202": "servicing_officer",
                    "SYN-USR-8801": "servicing_officer"}

    queue = ApprovalQueue(ledger, regime=FINANCE)
    queue.rosters = {
        (ATLAS, "servicing_officer"): ["SYN-USR-2202"],
        (ATLAS, "operations_lead"): ["SYN-USR-2203"],
        (ATLAS, "product_operations_manager"): ["SYN-USR-2204"],
        (MERIDIAN_BANK, "servicing_officer"): ["SYN-USR-8801"],
    }

    corpus = CorpusStore(copy.deepcopy(DOCS))
    flags = FlagCache(svc)
    pipeline = Pipeline(ledger=ledger, policy=policy, flags=flags, records=records,
                        corpus=corpus, queue=queue, generator=finance_generator,
                        regime=FINANCE)
    return Env(ledger, svc, flags, policy, records, corpus, queue, pipeline)
