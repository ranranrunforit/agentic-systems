"""The authorization gate — the trust boundary (FR-3).

Nothing an agent, a tool or a model *says* is an action. It is an **intent**.
Intents cross into execution only here, and only after all of the following pass:

  1. **Liveness**   — the extension is loaded, approved and not revoked.
  2. **Declaration** — the extension declared this (resource, action) permission
                       in its manifest and governance approved that exact grant.
  3. **Scope**       — the request falls inside the permission's scope (tenant,
                       project, and any other scope attributes).
  4. **Policy**      — the org ABAC policy allows it (default-deny, deny wins).
  5. **Provenance**  — if the intent is tainted by untrusted content, it may not
                       drive medium/high-impact actions without human
                       confirmation; a tainted high-impact intent is refused
                       outright by policy rule R-900.
  6. **Confirmation**— high-impact actions require a confirmation bound to this
                       intent (resource, action, target). A confirmation cannot
                       be reused for a different target or action.

Checks 2 and 4 are the "two keys": the manifest cannot self-grant, and the org
policy cannot grant something undeclared.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .audit import AuditLog
from .broker import intent_hash
from .contract import Extension
from .errors import AuthorizationDenied, ConfirmationRequired
from .policy import Decision, PolicyEngine, Request
from .taint import TaintSet

CONFIRMATION_TTL_S = 300.0


@dataclass
class Intent:
    """A *proposed* action. Never self-executing."""

    extension: Extension
    resource: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    tenant: str = "acme"
    actor: str = "unknown"
    origin: str = "model"  # model | human | extension | schedule
    taint: TaintSet = field(default_factory=TaintSet)
    target: str = ""
    confirmation_ref: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    environment: str = "prod"
    rationale: str = ""

    @property
    def hash(self) -> str:
        return intent_hash(
            {
                "extension": self.extension.ref,
                "resource": self.resource,
                "action": self.action,
                "params": _stable(self.params),
                "tenant": self.tenant,
            }
        )

    def describe(self) -> dict[str, Any]:
        return {
            "extension": self.extension.ref,
            "resource": self.resource,
            "action": self.action,
            "target": self.target or _target_of(self.params),
            "tenant": self.tenant,
            "origin": self.origin,
            "taint": self.taint.label,
        }


@dataclass
class GateDecision:
    allowed: bool
    intent: Intent
    impact: str
    reasons: list[str] = field(default_factory=list)
    policy: Decision | None = None
    confirmation_ref: str = ""
    intent_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "impact": self.impact,
            "reasons": self.reasons,
            "policy": self.policy.to_dict() if self.policy else None,
            "confirmation_ref": self.confirmation_ref,
            "intent_hash": self.intent_hash,
            **self.intent.describe(),
        }


# --------------------------------------------------------------------------- #
# Confirmation providers
# --------------------------------------------------------------------------- #


class ConfirmationProvider(Protocol):
    def confirm(self, intent: Intent, impact: str, reasons: list[str]) -> bool: ...


class AutoDenyConfirmation:
    """Default for unattended runs: high-impact actions are refused, not guessed."""

    name = "auto-deny"

    def confirm(self, intent: Intent, impact: str, reasons: list[str]) -> bool:
        return False


class AlwaysApproveConfirmation:
    """Test/demo only — never a production default."""

    name = "always-approve"

    def confirm(self, intent: Intent, impact: str, reasons: list[str]) -> bool:
        return True


class ScriptedConfirmation:
    """Answers keyed by `resource:action` (optionally `resource:action:target`)."""

    name = "scripted"

    def __init__(self, answers: dict[str, bool], default: bool = False):
        self.answers = answers
        self.default = default

    def confirm(self, intent: Intent, impact: str, reasons: list[str]) -> bool:
        target = intent.target or _target_of(intent.params)
        for key in (
            f"{intent.resource}:{intent.action}:{target}",
            f"{intent.resource}:{intent.action}",
        ):
            if key in self.answers:
                return self.answers[key]
        return self.default


class CliConfirmation:  # pragma: no cover - interactive
    """Human in the loop on a terminal."""

    name = "cli"

    def confirm(self, intent: Intent, impact: str, reasons: list[str]) -> bool:
        target = intent.target or _target_of(intent.params)
        print(
            f"\n[confirm] {intent.extension.ref} wants {intent.resource}:{intent.action} "
            f"on {target or '(no target)'} (impact={impact}, taint={intent.taint.label})"
        )
        for reason in reasons:
            print(f"          · {reason}")
        return input("          approve? [y/N] ").strip().lower() in ("y", "yes")


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #


class Gate:
    def __init__(
        self,
        policy: PolicyEngine,
        audit: AuditLog,
        confirmation: ConfirmationProvider | None = None,
        registry: Any | None = None,
    ):
        self.policy = policy
        self.audit = audit
        self.confirmation = confirmation or AutoDenyConfirmation()
        self.registry = registry
        self._confirmations: dict[str, dict[str, Any]] = {}

    # -- main entry -------------------------------------------------------- #

    def authorize(self, intent: Intent) -> GateDecision:
        ext = intent.extension
        reasons: list[str] = []

        # 1. liveness
        if self.registry is not None:
            problem = self.registry.liveness_problem(ext.name)
            if problem:
                return self._deny(intent, "low", [problem])

        # 2. declaration
        perm = ext.find_permission(intent.resource, intent.action)
        if perm is None:
            return self._deny(
                intent,
                "unknown",
                [
                    f"default-deny: {ext.ref} never declared "
                    f"{intent.resource}:{intent.action} in its manifest"
                ],
            )
        if self.registry is not None and not self.registry.grant_covers(ext, perm):
            return self._deny(
                intent,
                perm.effective_impact(intent.action),
                [f"governance: no approved grant for {perm.key()}"],
            )

        impact = perm.effective_impact(intent.action)

        # 3. scope
        scope_problem = _scope_problem(perm.scope, intent)
        if scope_problem:
            return self._deny(intent, impact, [f"out of scope: {scope_problem}"])

        # 4. policy (ABAC, default-deny, deny-overrides)
        request = Request(
            extension=ext.name,
            kind=ext.kind,
            owner=ext.owner,
            resource=intent.resource,
            action=intent.action,
            tenant=intent.tenant,
            impact=impact,
            origin=intent.origin,
            tainted=intent.taint.tainted,
            attributes={
                "tenant": intent.tenant,
                "environment": intent.environment,
                "project": str(intent.params.get("project", "")),
            },
        )
        decision = self.policy.evaluate(request)
        reasons.append(f"policy {decision.rule_id}: {decision.reason}")
        if not decision.allowed:
            return self._deny(intent, impact, reasons, policy=decision)

        # 5. provenance
        if intent.taint.tainted:
            reasons.append(
                "intent is tainted by untrusted content from "
                + ", ".join(intent.taint.sources[:3] or ["unknown source"])
            )
            if intent.taint.signals:
                reasons.append(f"injection heuristics fired: {intent.taint.signals[:3]}")

        # 6. confirmation
        needs_confirmation = impact == "high" or bool(decision.obligations.get("confirm"))
        if impact == "medium" and intent.taint.tainted and intent.taint.signals:
            # Calibration (see security/injection-defenses.md §"Why not block all
            # tainted actions"): taint alone cannot block medium actions or no RAG
            # agent could ever label a ticket. Taint *plus* a fired injection
            # heuristic escalates to a human. Taint plus high impact is refused
            # outright by policy rule R-900, with no confirmation path at all.
            needs_confirmation = True
            reasons.append(
                "tainted medium-impact action escalated to confirmation: "
                f"injection heuristics fired ({len(intent.taint.signals)})"
            )

        confirmation_ref = ""
        if needs_confirmation:
            existing = self._valid_confirmation(intent)
            if existing:
                confirmation_ref = existing
                reasons.append(f"confirmation {existing} reused (bound to this intent)")
            elif self.confirmation.confirm(intent, impact, reasons):
                confirmation_ref = self._record_confirmation(intent)
                reasons.append(f"human confirmation granted ({self.confirmation.name})")
            else:
                self.audit.record(
                    "gate.confirmation_denied",
                    actor=intent.actor,
                    extension=ext.ref,
                    impact=impact,
                    provider=self.confirmation.name,
                    **_audit_fields(intent),
                )
                raise ConfirmationRequired(
                    f"{ext.ref}: {intent.resource}:{intent.action} is {impact}-impact and was "
                    f"not confirmed ({self.confirmation.name})",
                    decision=GateDecision(
                        False, intent, impact, reasons, decision, "", intent.hash
                    ),
                )

        gd = GateDecision(True, intent, impact, reasons, decision, confirmation_ref, intent.hash)
        self.audit.record(
            "gate.allowed",
            actor=intent.actor,
            extension=ext.ref,
            impact=impact,
            rule=decision.rule_id,
            confirmation=confirmation_ref or "-",
            intent_hash=intent.hash,
            **_audit_fields(intent),
        )
        return gd

    def check(self, intent: Intent) -> GateDecision:
        """Non-raising variant: returns a decision instead of raising."""
        try:
            return self.authorize(intent)
        except AuthorizationDenied as exc:
            return exc.decision or GateDecision(False, intent, "unknown", [str(exc)])

    # -- helpers ----------------------------------------------------------- #

    def _deny(
        self, intent: Intent, impact: str, reasons: list[str], policy: Decision | None = None
    ) -> GateDecision:
        gd = GateDecision(False, intent, impact, reasons, policy, "", intent.hash)
        self.audit.record(
            "gate.denied",
            actor=intent.actor,
            extension=intent.extension.ref,
            impact=impact,
            reasons=reasons,
            intent_hash=intent.hash,
            **_audit_fields(intent),
        )
        raise AuthorizationDenied("; ".join(reasons), decision=gd)

    def _confirmation_key(self, intent: Intent) -> str:
        """Confirmations are bound to (tenant, resource, action, target).

        Deliberately *not* to the extension: a human confirming "close T-1042"
        is confirming that effect, and the connector that carries it out inherits
        the confirmation. Changing the action or the target invalidates it, so a
        confirmation can never be swapped onto a different effect.
        """
        target = intent.target or _target_of(intent.params)
        return f"{intent.tenant}|{intent.resource}|{intent.action}|{target}"

    def _record_confirmation(self, intent: Intent) -> str:
        ref = "cnf_" + intent.hash[:12]
        self._confirmations[ref] = {
            "key": self._confirmation_key(intent),
            "granted_at": time.time(),
            "actor": intent.actor,
        }
        self.audit.record(
            "gate.confirmed",
            actor=intent.actor,
            extension=intent.extension.ref,
            confirmation_ref=ref,
            provider=self.confirmation.name,
            **_audit_fields(intent),
        )
        return ref

    def _valid_confirmation(self, intent: Intent) -> str:
        key = self._confirmation_key(intent)
        now = time.time()
        for ref, rec in list(self._confirmations.items()):
            if now - rec["granted_at"] > CONFIRMATION_TTL_S:
                self._confirmations.pop(ref, None)
                continue
            if rec["key"] == key and (not intent.confirmation_ref or intent.confirmation_ref == ref):
                return ref
        return ""


# --------------------------------------------------------------------------- #


def _scope_problem(scope: dict[str, Any], intent: Intent) -> str | None:
    for key, pattern in scope.items():
        resolved = _resolve(pattern, intent)
        if key == "tenant":
            if not fnmatch.fnmatch(intent.tenant, str(resolved)):
                return f"tenant {intent.tenant!r} not in scope {resolved!r}"
            continue
        value = intent.params.get(key, intent.context.get(key))
        if value is None:
            # A scope attribute the request does not carry cannot be verified.
            return f"request does not carry scope attribute {key!r}"
        if not fnmatch.fnmatch(str(value), str(resolved)):
            return f"{key}={value!r} not in scope {resolved!r}"
    return None


def _resolve(pattern: Any, intent: Intent) -> Any:
    if isinstance(pattern, str) and pattern.startswith("${") and pattern.endswith("}"):
        expr = pattern[2:-1]
        if expr == "caller.tenant":
            return intent.tenant
        if expr == "caller.actor":
            return intent.actor
        return "*"
    return pattern


def _audit_fields(intent: Intent) -> dict[str, Any]:
    """Intent fields for the audit record, minus the ones the caller supplies."""
    fields = intent.describe()
    fields.pop("extension", None)
    return fields


def _target_of(params: dict[str, Any]) -> str:
    for key in ("ticket_id", "article_id", "service", "target", "id"):
        if key in params:
            return str(params[key])
    return ""


def _stable(params: dict[str, Any]) -> dict[str, Any]:
    return {k: params[k] for k in sorted(params) if not k.startswith("_")}
