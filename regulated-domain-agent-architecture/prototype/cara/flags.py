"""Toggleable AI: conjunctive scopes, fail-closed resolution.

Maps to: toggles/toggle-spec.md, ADR-005.

The property under test: unknown, missing, malformed, or (past the bounded stale
window) unreachable flag state means AI OFF. A kill switch that stays on when its
control plane is down is theatre.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

MAX_STALE_SECONDS = 60.0

VALID_REASON_CODES = {
    "INCIDENT", "PROCUREMENT", "CONTRACT", "QUALITY",
    "REGULATORY", "SUBJECT_REQUEST", "TEST", "OTHER",
}


@dataclass
class FlagResolution:
    enabled: bool
    cause: str
    snapshot: dict[str, Any]


class FlagServiceUnavailable(RuntimeError):
    pass


class FlagService:
    """Holds flag state. Tests flip `reachable` to simulate an outage."""

    def __init__(self, ledger, clock=time.time) -> None:
        self._global_kill = False
        self._global: dict[str, bool] = {}       # feature -> on
        self._tenant: dict[str, bool] = {}       # tenant -> on
        self._feature: dict[tuple[str, str], bool] = {}  # (tenant, feature) -> on
        self._subject_restricted: set[str] = set()
        self.reachable = True
        self.version = "fv-1000"
        self._ledger = ledger
        self._clock = clock

    # -- writes -----------------------------------------------------------------

    def set(self, state: bool, *, scope: str, tenant: str | None = None,
            feature: str | None = None, subject: str | None = None,
            actor: str = "SYN-USR-9001", role: str = "tenant_administrator",
            reason_code: str = "TEST", reason_text: str = "") -> None:
        """Every state change writes a ledger event in the same transaction.

        A reason code is mandatory (toggle-spec §4). Turning AI OFF never requires
        approval; the safe direction is always one click.
        """
        if reason_code not in VALID_REASON_CODES:
            raise ValueError(f"invalid reason_code {reason_code!r}")

        old = self.resolve_raw(scope, tenant, feature, subject)
        if scope == "global_kill":
            self._global_kill = not state
        elif scope == "global":
            self._global[feature] = state
        elif scope == "tenant":
            self._tenant[tenant] = state
        elif scope == "feature":
            self._feature[(tenant, feature)] = state
        elif scope == "subject":
            if state:
                self._subject_restricted.discard(subject)
            else:
                self._subject_restricted.add(subject)
        else:
            raise ValueError(f"unknown scope {scope!r}")

        self.version = f"fv-{int(self._clock() * 1000) % 100000}"
        # Transactional: a flag write that cannot be logged is rolled back. The one
        # exception is the global kill switch (toggle-spec §6) -- "cannot log" must
        # not mean "cannot stop".
        try:
            self._ledger.append(
                "toggle.changed",
                scope=scope, scope_tenant=tenant, scope_feature=feature,
                subject_ref=subject, previous_state="on" if old else "off",
                state="on" if state else "off", actor_id=actor, actor_role=role,
                reason_code=reason_code, reason_text=reason_text,
                flag_version=self.version,
            )
        except Exception:
            if scope != "global_kill":
                self._rollback(scope, tenant, feature, subject, old)
                raise

    def _rollback(self, scope, tenant, feature, subject, old) -> None:
        if scope == "global":
            self._global[feature] = old
        elif scope == "tenant":
            self._tenant[tenant] = old
        elif scope == "feature":
            self._feature[(tenant, feature)] = old
        elif scope == "subject":
            (self._subject_restricted.discard if old else self._subject_restricted.add)(subject)

    def resolve_raw(self, scope, tenant, feature, subject) -> bool:
        if scope == "global_kill":
            return not self._global_kill
        if scope == "global":
            return self._global.get(feature, False)
        if scope == "tenant":
            return self._tenant.get(tenant, False)
        if scope == "feature":
            return self._feature.get((tenant, feature), False)
        if scope == "subject":
            return subject not in self._subject_restricted
        return False

    def delete_flag(self, tenant: str, feature: str) -> None:
        """Used to test 'unknown flag => off', not 'default on'."""
        self._feature.pop((tenant, feature), None)

    # -- reads ------------------------------------------------------------------

    def fetch(self, tenant: str, feature: str, subject: str | None) -> dict[str, Any]:
        if not self.reachable:
            raise FlagServiceUnavailable("flag service unreachable")
        return {
            "global_kill": "off" if self._global_kill else "on",
            "global": self._global.get(feature),        # None => unknown => off
            "tenant": self._tenant.get(tenant),
            "feature": self._feature.get((tenant, feature)),
            "subject_restricted": subject in self._subject_restricted if subject else False,
            "flag_version": self.version,
        }


class FlagCache:
    """Bounded stale cache. toggles/toggle-spec.md §3.

    The trade, stated in ADR-005: zero staleness makes the flag service a hard
    availability dependency of every request; unbounded staleness makes the kill
    switch advisory. 60 s caps disobedience below human incident timescales.
    """

    def __init__(self, service: FlagService, max_stale: float = MAX_STALE_SECONDS,
                 clock=time.time) -> None:
        self.service = service
        self.max_stale = max_stale
        self._clock = clock
        self._cache: dict[tuple, tuple[float, dict]] = {}

    def resolve(self, tenant: str, feature: str, subject: str | None = None) -> FlagResolution:
        key = (tenant, feature, subject)
        now = self._clock()
        try:
            snap = self.service.fetch(tenant, feature, subject)
            self._cache[key] = (now, snap)
            cause = "FRESH"
        except FlagServiceUnavailable:
            cached = self._cache.get(key)
            if cached and (now - cached[0]) <= self.max_stale:
                snap = dict(cached[1])
                cause = "STALE_CACHE"
            else:
                # FC-1: unreachable past max_stale => AI OFF.
                return FlagResolution(False, "FAIL_CLOSED_FLAGS_UNAVAILABLE",
                                      {"decision": "AI_OFF"})

        # Conjunctive: any scope can disable; none can re-enable over another.
        if snap["global_kill"] != "on":
            return FlagResolution(False, "GLOBAL_KILL_SWITCH", snap)
        if snap["subject_restricted"]:
            return FlagResolution(False, "SUBJECT_RESTRICTION", snap)
        for scope in ("global", "tenant", "feature"):
            value = snap.get(scope)
            if value is None:
                # Unknown flag is OFF, not "default on".
                return FlagResolution(False, f"UNKNOWN_FLAG_{scope.upper()}", snap)
            if value is not True:
                return FlagResolution(False, f"{scope.upper()}_TOGGLE_OFF", snap)
        return FlagResolution(True, cause, snap)
