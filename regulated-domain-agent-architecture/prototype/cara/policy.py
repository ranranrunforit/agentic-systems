"""Policy engine: authorization, care relationship, allow-lists, capability registry.

Maps to: architecture/reference-architecture.md §3.2, control-mapping C-01/C-02/C-10.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import RiskTier

ALLOWLIST_VERSION = "v7"


from .regime import Capability  # noqa: F401  (re-exported for callers)


def _registries():
    """Healthcare registries, imported lazily so policy.py owns no sector data."""
    from .regimes import HEALTHCARE
    return HEALTHCARE.capabilities, HEALTHCARE.tool_registry


@dataclass
class PolicyDecision:
    allowed: bool
    reason_code: str
    allowlist: list[str] = field(default_factory=list)
    allowlist_version: str = ALLOWLIST_VERSION


class PolicyEngine:
    """Spine. The regime supplies the capability set and the RELATIONSHIP NAME;
    the authorization logic below is identical in every sector."""

    def __init__(self, records, ledger, regime=None) -> None:
        self.records = records
        self.ledger = ledger
        self.regime = regime  # None => the healthcare defaults above
        #: (user, patient) pairs. HIPAA minimum-necessary is enforced as a
        #: RELATIONSHIP check, not merely a role check (C-10).
        self.care_relationships: set[tuple[str, str]] = set()
        self.roles: dict[str, str] = {}
        self.available = True  # tests flip this: unreachable policy engine => deny

    def authorize(self, *, actor: str, tenant: str, capability: str,
                  subject_ref: str | None, correlation_id: str) -> PolicyDecision:
        if not self.available:
            # FC-5: unreachable policy engine denies. Never fails open.
            return PolicyDecision(False, "POLICY_UNAVAILABLE")

        caps = self.regime.capabilities if self.regime else _registries()[0]
        cap = caps.get(capability)
        if cap is None:
            return PolicyDecision(False, "UNKNOWN_CAPABILITY")

        if cap.requires_subject and not subject_ref:
            return PolicyDecision(False, "SUBJECT_REQUIRED")

        if subject_ref:
            record = self.records.get(tenant, subject_ref)
            if record is None:
                return PolicyDecision(False, "NO_SUCH_RECORD")
            # Tenant isolation (I-1): a record belongs to exactly one tenant, and the
            # store is queried with the tenant predicate, not filtered afterwards.
            if record["tenant"] != tenant:
                return PolicyDecision(False, "TENANT_MISMATCH")
            # The relationship predicate is spine; WHICH relationship is regime.
            # (care relationship / servicing relationship / case assignment /
            # legitimate educational interest -- same check, different name.)
            if (actor, subject_ref) not in self.care_relationships:
                return PolicyDecision(False, "NO_RELATIONSHIP")
            if record.get("flags", {}).get("ai_processing_restricted"):
                return PolicyDecision(False, "SUBJECT_RESTRICTION")

        return PolicyDecision(True, "OK", allowlist=cap.allowlist)


# Backwards-compatible module-level aliases. Resolved lazily so that importing
# policy.py does not pull a sector in.
def __getattr__(name):
    if name == "CAPABILITIES":
        return _registries()[0]
    if name == "TOOL_REGISTRY":
        return _registries()[1]
    raise AttributeError(name)
