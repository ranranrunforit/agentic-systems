"""ABAC policy engine (FR-2 / ADR-004).

Two keys must turn for an action to proceed:

  Key 1 — the *manifest grant*: the extension declared the (resource, action)
          permission and the registry holds an approved grant for that exact
          permission set (checked in registry.py / host.py).
  Key 2 — the *org policy*: a rule in `security/policy/abac-policy.yaml`
          allows this (subject, resource, action) under the request's
          attributes.

Both keys are default-deny. A manifest cannot grant itself authority the org
policy withholds, and org policy cannot hand an extension authority it never
declared. Explicit `deny` rules always win over `allow`.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import yamlio

ALLOW, DENY = "allow", "deny"


@dataclass(frozen=True)
class Rule:
    id: str
    effect: str
    match: dict[str, Any]
    conditions: dict[str, Any] = field(default_factory=dict)
    obligations: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def matches(self, req: "Request") -> bool:
        m = self.match
        if not _glob_any(m.get("extension", "*"), req.extension):
            return False
        if not _glob_any(m.get("kind", "*"), req.kind):
            return False
        if not _glob_any(m.get("owner", "*"), req.owner):
            return False
        if not _glob_any(m.get("resource", "*"), req.resource):
            return False
        if not _glob_any(m.get("action", "*"), req.action):
            return False
        for key, expected in (m.get("attributes") or {}).items():
            if not _glob_any(expected, str(req.attributes.get(key, ""))):
                return False
        return self._conditions_hold(req)

    def _conditions_hold(self, req: "Request") -> bool:
        cond = self.conditions
        if "when_taint" in cond:
            want = cond["when_taint"]
            if want == "untrusted" and not req.tainted:
                return False
            if want == "trusted" and req.tainted:
                return False
        if "when_origin" in cond and req.origin not in _as_list(cond["when_origin"]):
            return False
        if "when_impact" in cond and req.impact not in _as_list(cond["when_impact"]):
            return False
        if "tenants" in cond and req.tenant not in _as_list(cond["tenants"]):
            return False
        if cond.get("require_tenant_match") and req.attributes.get("tenant") != req.tenant:
            return False
        if "max_taint" in cond and cond["max_taint"] == "trusted" and req.tainted:
            return False
        if "environments" in cond and req.attributes.get("environment") not in _as_list(
            cond["environments"]
        ):
            return False
        return True


@dataclass
class Request:
    """The attribute bundle the engine decides on."""

    extension: str
    kind: str
    owner: str
    resource: str
    action: str
    tenant: str
    impact: str = "low"
    origin: str = "model"  # model | human | extension | schedule
    tainted: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    effect: str
    rule_id: str
    reason: str
    obligations: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.effect == ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect": self.effect,
            "rule": self.rule_id,
            "reason": self.reason,
            "obligations": self.obligations,
        }


class PolicyEngine:
    def __init__(self, rules: Iterable[Rule], default: str = DENY, version: str = "0"):
        self.rules = list(rules)
        self.default = default
        self.version = version

    # -- construction ------------------------------------------------------ #

    @classmethod
    def from_file(cls, path: str) -> "PolicyEngine":
        data = yamlio.load_file(path) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyEngine":
        rules = [
            Rule(
                id=str(r.get("id", f"R-{i:03d}")),
                effect=r.get("effect", DENY),
                match=r.get("match") or {},
                conditions=r.get("conditions") or {},
                obligations=r.get("obligations") or {},
                description=r.get("description", ""),
            )
            for i, r in enumerate(data.get("rules") or [])
        ]
        return cls(rules, default=data.get("default", DENY), version=str(data.get("version", "0")))

    # -- evaluation -------------------------------------------------------- #

    def evaluate(self, req: Request) -> Decision:
        matched_allow: Decision | None = None
        for rule in self.rules:
            if not rule.matches(req):
                continue
            if rule.effect == DENY:  # deny-overrides
                return Decision(DENY, rule.id, rule.description or "explicit deny", rule.obligations)
            if matched_allow is None:
                matched_allow = Decision(
                    ALLOW, rule.id, rule.description or "explicit allow", rule.obligations
                )
        if matched_allow:
            return matched_allow
        return Decision(
            self.default,
            "default",
            f"no rule matched; policy default is {self.default} (default-deny)",
        )

    def explain(self, req: Request) -> list[str]:
        out = []
        for rule in self.rules:
            out.append(f"{rule.id:<8} {rule.effect:<5} {'MATCH' if rule.matches(req) else '-'}")
        return out


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


def _glob_any(patterns: Any, value: str) -> bool:
    for pattern in _as_list(patterns):
        if fnmatch.fnmatch(value, str(pattern)):
            return True
    return False
