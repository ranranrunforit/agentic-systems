"""The request pipeline: the architecture's happy path and all its fail-closed exits.

Maps to: architecture/reference-architecture.md §4, architecture/sequence-views.md.

    authn -> policy/RBAC -> flags -> minimization -> agent -> grounding
          -> risk -> HITL (Tier 3) -> release

Every exit from this path is a refusal, a denial, or a degraded response. There is no
exit that releases Tier-3 output without a human, and no exit that proceeds when a
control is unavailable.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

from .audit import AuditLedger, LedgerWriteError
from .conformance import ConformanceVerifier, OmissionDetector
from .degraded import DegradedService
from .flags import FlagCache
from .grounding import GroundingVerifier
from .grounding_corpus import CorpusStore
from .minimization import MinimizationFilter, RecordStore
from .models import Claim, Outcome, RiskTier
from .policy import CAPABILITIES, PolicyEngine
from .risk import ApprovalQueue, classify


@dataclass
class Request:
    actor: str
    tenant: str
    capability: str
    question: str
    subject_ref: str | None = None
    tools_invoked: tuple[str, ...] = ()
    #: Finance layers a quantitative threshold on the qualitative tiers; inert in
    #: healthcare, which has no natural monetary axis.
    amount: float | None = None
    #: Elements/facts the generator says its output contains. In a real system these
    #: come from a structured-output parse; here the generator declares them.
    elements: frozenset[str] = frozenset()
    facts: frozenset[str] = frozenset()


#: A generator stub stands in for the LLM. Tests inject rogue generators that emit
#: deliberately fabricated clinical claims -- that is the POINT: the claim this
#: architecture makes is that the controls hold regardless of what the model emits.
Generator = Callable[[Request, dict[str, Any]], tuple[str, list[Claim]]]


class Pipeline:
    def __init__(self, *, ledger: AuditLedger, policy: PolicyEngine, flags: FlagCache,
                 records: RecordStore, corpus: CorpusStore, queue: ApprovalQueue,
                 generator: Generator, region: str = "region-a",
                 clock=time.time, regime=None) -> None:
        self.ledger = ledger
        self.policy = policy
        self.flags = flags
        self.records = records
        self.corpus = corpus
        self.queue = queue
        self.generator = generator
        self.regime = regime
        self.minimizer = MinimizationFilter(region=region, regime=regime)
        self.verifier = GroundingVerifier(corpus, regime=regime)
        self.conformance = ConformanceVerifier(regime) if regime else None
        self.omission = OmissionDetector(regime) if regime else None
        self.degraded = DegradedService(ledger, records, regime=regime)
        self._clock = clock

    def handle(self, req: Request) -> Outcome:
        cid = "SYN-COR-" + secrets.token_hex(3)
        self.ledger.append("authn.success", correlation_id=cid, tenant=req.tenant,
                           actor_id=req.actor)

        # 1. Authorization. Unreachable policy engine denies (FC-5).
        decision = self.policy.authorize(
            actor=req.actor, tenant=req.tenant, capability=req.capability,
            subject_ref=req.subject_ref, correlation_id=cid)
        if not decision.allowed:
            if decision.reason_code == "SUBJECT_RESTRICTION":
                # A restriction under §164.522 routes to the deterministic path; the
                # record must never appear in a subsequent minimization event (C-06).
                self.ledger.append("policy.degraded", correlation_id=cid,
                                   tenant=req.tenant, subject_ref=req.subject_ref,
                                   cause="SUBJECT_RESTRICTION")
                return self.degraded.serve(req, cid, cause="SUBJECT_RESTRICTION")
            self.ledger.append("policy.deny", correlation_id=cid, tenant=req.tenant,
                               actor_id=req.actor, capability=req.capability,
                               reason_code=decision.reason_code)
            return Outcome("denied", cid, reason_code=decision.reason_code)

        # 2. Flags. Unknown / missing / unreachable-past-max-stale => AI off (FC-1).
        flag = self.flags.resolve(req.tenant, req.capability, req.subject_ref)
        self.ledger.append("policy.allow", correlation_id=cid, tenant=req.tenant,
                           actor_id=req.actor, capability=req.capability,
                           reason_code=decision.reason_code,
                           policy_version=decision.allowlist_version,
                           flags_snapshot=flag.snapshot)
        if not flag.enabled:
            self.ledger.append("policy.degraded", correlation_id=cid, tenant=req.tenant,
                               capability=req.capability, cause=flag.cause)
            return self.degraded.serve(req, cid, cause=flag.cause)

        # 3. Minimization. The ONLY path across the model boundary.
        record = self.records.get(req.tenant, req.subject_ref) if req.subject_ref else None
        payload: dict[str, Any] = {}
        if record is not None:
            payload, manifest = self.minimizer.project(
                record, decision.allowlist, correlation_id=cid, tenant=req.tenant,
                capability=req.capability, allowlist_version=decision.allowlist_version,
                subject_key=self.records.subject_key)
            self.ledger.append(
                "minimization.applied", correlation_id=cid, tenant=req.tenant,
                capability=req.capability, subject_ref=manifest.subject_ref,
                allowlist_version=manifest.allowlist_version,
                fields_included=manifest.fields_included,
                fields_excluded_by_class=manifest.fields_excluded_by_class,
                prompt_hash=manifest.prompt_hash, boundary=manifest.boundary)

        # 4. Generation. Model output is UNTRUSTED input from here on.
        text, claims = self.generator(req, payload)
        self.ledger.append("agent.tool_calls", correlation_id=cid, tenant=req.tenant,
                           tools=list(req.tools_invoked), n_claims=len(claims))

        # 5. Risk classification BEFORE grounding policy, since the tier decides how
        #    an unsupported claim is handled.
        risk = classify(capability=req.capability, claims=claims,
                        tools_invoked=list(req.tools_invoked),
                        subject_in_context=bool(req.subject_ref),
                        regime=self.regime, amount=req.amount)
        self.ledger.append("risk.classified", correlation_id=cid, tenant=req.tenant,
                           subject_ref=req.subject_ref, tier=int(risk.tier),
                           rule=risk.rule, accountable_role=risk.owning_role)

        # 6. Grounding. Refuse or escalate on a Tier-3 unsupported claim.
        report = self.verifier.verify(claims, tenant=req.tenant, record=record,
                                      tier=risk.tier)
        if not report.ok:
            searched_scope_codes = ["S1", "S2", "S3"]
            self.ledger.append(
                "grounding.failed", correlation_id=cid, tenant=req.tenant,
                subject_ref=req.subject_ref, tier=int(risk.tier),
                reason_code=report.reason_code,
                unsupported=[v.claim_id for v in report.unsupported],
                searched_scope=searched_scope_codes)
            searched = _searched_scope(self.regime)
            return Outcome("refused", cid, tier=risk.tier,
                           reason_code=report.reason_code,
                           text=_refusal_text(report.reason_code, searched,
                                              self.regime),
                           detail={"searched": searched})

        self.ledger.append("grounding.result", correlation_id=cid, tenant=req.tenant,
                           subject_ref=req.subject_ref,
                           supported=sum(1 for v in report.verdicts if v.supported),
                           total=len(report.verdicts), citations=report.citations,
                           tau_hard=self.verifier.tau_hard)

        # 6b. POSITIVE output duties. Grounding checked that nothing said is
        #     unsupported; these check that nothing required is missing. Blocking
        #     (conformance) and advisory (omission) respectively -- see
        #     cara/conformance.py for why that asymmetry is deliberate.
        omission = None
        if self.conformance is not None:
            conf = self.conformance.check(req.capability, set(req.elements))
            if not conf.ok:
                self.ledger.append(
                    "conformance.failed", correlation_id=cid, tenant=req.tenant,
                    capability=req.capability, rule=conf.rule_id,
                    missing=list(conf.missing), reason_code=conf.reason_code)
                return Outcome("refused", cid, tier=risk.tier,
                               reason_code=conf.reason_code,
                               text=f"Withheld: required elements missing "
                                    f"({', '.join(conf.missing)}) under {conf.rule_id}.")
            omission = self.omission.check(req.capability, set(req.facts))
            if not omission.complete:
                # Flagged, not blocked. The reviewer sees it; the release continues.
                self.ledger.append(
                    "omission.flagged", correlation_id=cid, tenant=req.tenant,
                    capability=req.capability, rule=omission.rule_id,
                    absent_facts=list(omission.absent_facts), blocking=False)

        # 7. HITL gate for Tier 3. No approver => expire closed (FC-4).
        if risk.tier is RiskTier.T3:
            if not self.queue.eligible(req.tenant, risk.owning_role):
                self.ledger.append("approval.expired", correlation_id=cid,
                                   tenant=req.tenant, cause="NO_APPROVER",
                                   action_taken=False)
                return Outcome("expired", cid, tier=risk.tier,
                               reason_code="NO_APPROVER",
                               text="Withheld: no eligible approver is available.")
            item = self.queue.queue(
                correlation_id=cid, tenant=req.tenant, subject_ref=req.subject_ref,
                tier=risk.tier, owning_role=risk.owning_role, text=text,
                requested_by=req.actor, citations=report.citations,
                weak_claims=[v.claim_id for v in report.verdicts if v.weakly_supported],
                manifest_summary={"fields": len(payload)})
            return Outcome("queued", cid, tier=risk.tier, text=text,
                           citations=report.citations,
                           detail={"item_id": item.item_id,
                                   "owning_role": risk.owning_role,
                                   "omission_flags": list(omission.absent_facts)
                                   if omission and not omission.complete else []})

        # 8. Tier 1-2 auto-flow -- with grounding, citations, and a log. "No human"
        #    is not "no control".
        return self._release(cid, req, risk, text, report.citations)

    def release_approved(self, item_id: str) -> Outcome:
        item = self.queue.items[item_id]
        if item.state != "approved":
            raise PermissionError("item not approved")
        self.ledger.append("output.released", correlation_id=item.correlation_id,
                           tenant=item.tenant, subject_ref=item.subject_ref,
                           tier=int(item.tier), content_hash="sha256:demo",
                           accountable_role=item.owning_role)
        return Outcome("released", item.correlation_id, tier=item.tier,
                       text=item.text, citations=item.citations)

    def _release(self, cid, req, risk, text, citations) -> Outcome:
        try:
            self.ledger.append("output.released", correlation_id=cid, tenant=req.tenant,
                               subject_ref=req.subject_ref, tier=int(risk.tier),
                               content_hash="sha256:demo",
                               accountable_role=risk.owning_role)
        except LedgerWriteError:
            # FC-6: if it cannot be logged, it does not happen.
            return Outcome("refused", cid, tier=risk.tier,
                           reason_code="LEDGER_WRITE_FAILED",
                           text="Withheld: the action could not be recorded.")
        return Outcome("released", cid, tier=risk.tier, text=text, citations=citations)


def _searched_scope(regime) -> list[str]:
    """The refusal names what was searched, in the REGIME'S vocabulary.

    Another leak the finance build exposed: the refusal text hardcoded "the patient's
    record, tenant clinical protocols, and licensed references", so a bank customer
    was told their disclosure request had been checked against clinical protocols.
    Harmless-looking, and exactly the kind of thing that reveals a design was only
    ever tested in one sector.
    """
    if regime is None:
        return ["the subject's record", "tenant protocols", "licensed references"]
    from .models import SourceClass
    return [regime.source_class_labels[c] for c in
            (SourceClass.S1, SourceClass.S2, SourceClass.S3)
            if c in regime.source_class_labels]


def _refusal_text(reason_code: str, searched: list[str] | None = None,
                  regime=None) -> str:
    """A refusal is a specific, useful, audited artefact -- not an error page.

    It names the search scope, explains the distinction it draws, and offers
    escalation. A refusal that does not say what was searched is indistinguishable
    from a malfunction, and users route around it.
    """
    base = {
        "ABSENCE_REQUIRES_POSITIVE_SPAN":
            "I can't answer that from the record. It contains no entry either recording "
            "or excluding this, and an empty field isn't the same as a documented "
            "absence, so I won't state either way.",
        "UNIVERSAL_NEGATIVE_UNPROVABLE":
            "I can't confirm that nothing in the record is relevant -- no source can "
            "support a claim about everything the record does not contain.",
        "NO_SUPPORTING_SPAN":
            "I can't support that from the vetted sources available.",
        "RETRIEVAL_UNAVAILABLE":
            "The vetted sources are unavailable, so I can't ground a high-risk answer.",
        "NO_COMPATIBLE_SOURCE_CLASS":
            "The only sources that could settle this aren't authoritative for this kind "
            "of claim.",
        "ENTITY_BINDING":
            "The supporting evidence I found belongs to a different record.",
    }.get(reason_code, "I can't ground that claim in a vetted source.")
    scope = ", ".join(searched or ["the vetted sources"])
    role = "the owning approver"
    if regime is not None:
        from .models import RiskTier
        role = regime.owning_roles[RiskTier.T3].replace("_", " ")
    return f"{base}\n\nSearched: {scope}.\nOptions: [Escalate to {role}]"
