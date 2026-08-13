"""Risk classification and the human-in-the-loop queue.

Maps to: hitl/risk-taxonomy.md, hitl/approval-flows.md, ADR-003, ADR-007.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .models import Claim, ClaimType, RiskTier
from .policy import CAPABILITIES, TOOL_REGISTRY

#: Which claim types constitute a subject-specific assertion. Spine default; a
#: regime may narrow or widen it.
_T3_CLAIMS = {ClaimType.SUBJECT_SPECIFIC_FACT, ClaimType.SUBJECT_SPECIFIC_RECOMMENDATION}

#: Fallback owning roles when no regime is supplied. Deliberately generic: the
#: earlier version named clinical roles here, which put a sector inside the spine.
OWNING_ROLE = {RiskTier.T3: "senior_owner",
               RiskTier.T2: "domain_lead",
               RiskTier.T1: "operations_manager"}


@dataclass
class RiskResult:
    tier: RiskTier
    rule: str
    owning_role: str


def classify(*, capability: str, claims: list[Claim], tools_invoked: list[str],
             subject_in_context: bool, ambiguous: bool = False,
             regime=None, amount: float | None = None) -> RiskResult:
    """Max-rule over the four axes. Never a sum.

    Summing lets a high-harm output be averaged down by low scores on other axes,
    which inverts the intent. And the learned component (claim typing) may RAISE a
    tier, never lower one: a capability's declared floor and its side effects set a
    bound no model output can talk its way under.
    """
    caps = regime.capabilities if regime else CAPABILITIES
    tools = regime.tool_registry if regime else TOOL_REGISTRY
    roles = regime.owning_roles if regime else OWNING_ROLE
    t3_types = regime.t3_claim_types if regime else _T3_CLAIMS
    cap = caps[capability]
    candidates: list[tuple[RiskTier, str]] = [(cap.tier_floor, "CAPABILITY_FLOOR")]

    for tool in tools_invoked:
        meta = tools.get(tool)
        if meta is None:
            # An unregistered tool cannot be called at all (ADR-008); reaching here
            # means something is wrong, so it rounds up.
            candidates.append((RiskTier.T3, "UNREGISTERED_TOOL"))
            continue
        if not meta["reversible"]:
            candidates.append((RiskTier.T3, "IRREVERSIBLE_ACTION"))
        else:
            candidates.append((meta["tier"], "TOOL_SIDE_EFFECT"))

    if any(c.type in t3_types for c in claims):
        candidates.append((RiskTier.T3, "R3-SUBJECT-ASSERTION"))
    elif subject_in_context:
        candidates.append((RiskTier.T2, "R2-INDIVIDUAL-RESTATEMENT"))

    # Finance layers a QUANTITATIVE threshold on the qualitative tiers. Healthcare
    # has no natural monetary axis, so this branch is inert there -- the axis exists
    # in the spine and is simply unbound.
    if (regime and regime.dual_approval_over_amount is not None
            and amount is not None and amount >= regime.dual_approval_over_amount):
        candidates.append((RiskTier.T3, "AMOUNT_OVER_DUAL_APPROVAL_THRESHOLD"))

    if ambiguous:
        # FC-8: unknown risk is not low risk.
        candidates.append((RiskTier.T3, "TIE_ROUND_UP"))

    tier, rule = max(candidates, key=lambda x: x[0])
    return RiskResult(tier, rule, roles[tier])


@dataclass
class ApprovalItem:
    item_id: str
    correlation_id: str
    tenant: str
    subject_ref: str | None
    tier: RiskTier
    owning_role: str
    text: str
    citations: list[dict[str, Any]]
    weak_claims: list[str]
    manifest_summary: dict[str, Any]
    queued_at: float
    requested_by: str = ""
    state: str = "queued"
    held_by_toggle: bool = False


class NoEligibleApprover(RuntimeError):
    pass


class ApprovalQueue:
    """Rosters, not individuals. An accountability model that breaks at a
    resignation was never real (ADR-007).

    There is no edge from any state to `released` that bypasses a human for Tier 3.
    That ABSENCE is the control; the test asserts it at the population level.
    """

    SLA_SECONDS = 4 * 3600

    def __init__(self, ledger, clock=time.time, regime=None) -> None:
        self.ledger = ledger
        self._clock = clock
        self.regime = regime
        self.rosters: dict[tuple[str, str], list[str]] = {}  # (tenant, role) -> users
        self.items: dict[str, ApprovalItem] = {}
        self._n = 0

    def eligible(self, tenant: str, role: str) -> list[str]:
        return self.rosters.get((tenant, role), [])

    def _self_approval_allowed(self) -> bool:
        """Healthcare permits it; SOX segregation of duties forbids it.

        Same component, opposite configuration. This is the sharpest single example
        in the package of a parameter that looks agnostic until the regime changes:
        the healthcare design's reasoning ("the clinician who asked for the referral
        is the right person to approve it") is sound AND inapplicable under SOX.
        """
        return self.regime.self_approval_allowed if self.regime else True

    def queue(self, **kw: Any) -> ApprovalItem:
        self._n += 1
        item = ApprovalItem(item_id=f"ITEM-{self._n:04d}", queued_at=self._clock(), **kw)
        self.items[item.item_id] = item
        self.ledger.append("approval.queued", correlation_id=item.correlation_id,
                           tenant=item.tenant, subject_ref=item.subject_ref,
                           tier=int(item.tier), owning_role=item.owning_role,
                           item_id=item.item_id)
        return item

    def approve(self, item_id: str, approver: str, *, edits: int = 0,
                dwell_ms: int = 0) -> ApprovalItem:
        item = self.items[item_id]
        if not self._self_approval_allowed() and approver == item.requested_by:
            self.ledger.append("approval.denied_sod", correlation_id=item.correlation_id,
                               actor_id=approver, cause="SEGREGATION_OF_DUTIES")
            raise PermissionError(
                f"{approver} initiated this item; segregation of duties forbids "
                "the initiator from approving it")
        if approver not in self.eligible(item.tenant, item.owning_role):
            self.ledger.append("approval.denied_ineligible", correlation_id=item.correlation_id,
                               actor_id=approver, required_role=item.owning_role)
            raise PermissionError(f"{approver} does not hold {item.owning_role}")
        item.state = "approved"
        self.ledger.append("approval.granted", correlation_id=item.correlation_id,
                           tenant=item.tenant, subject_ref=item.subject_ref,
                           actor_id=approver, actor_role=item.owning_role,
                           tier=int(item.tier), edits=edits, dwell_ms=dwell_ms,
                           item_id=item_id)
        return item

    def reject(self, item_id: str, approver: str, reason_code: str) -> ApprovalItem:
        item = self.items[item_id]
        item.state = "rejected"
        self.ledger.append("approval.rejected", correlation_id=item.correlation_id,
                           actor_id=approver, reason_code=reason_code, item_id=item_id)
        return item

    def expire_due(self) -> list[ApprovalItem]:
        """Expiry is not deferral-to-default. The default is NO OUTPUT."""
        now = self._clock()
        expired = []
        for item in self.items.values():
            if item.state == "queued" and (now - item.queued_at) > self.SLA_SECONDS:
                item.state = "expired"
                self.ledger.append("approval.expired", correlation_id=item.correlation_id,
                                   tenant=item.tenant, item_id=item.item_id,
                                   cause="NO_APPROVER", action_taken=False)
                expired.append(item)
        return expired

    def hold_for_toggle(self, tenant: str) -> list[ApprovalItem]:
        """AI turned off mid-queue: items are HELD, not auto-released, not dropped.

        A human approving text a human can read is not an AI feature
        (toggles/degraded-mode.md §4).
        """
        held = []
        for item in self.items.values():
            if item.state == "queued" and item.tenant == tenant:
                item.held_by_toggle = True
                self.ledger.append("queue.held", correlation_id=item.correlation_id,
                                   item_id=item.item_id, cause="TENANT_TOGGLE_OFF")
                held.append(item)
        return held
