"""The host — the trusted core (FR-1).

Responsibilities, and nothing else:

  load / isolate / revoke  ->  registry.py + sandbox.py
  authorize                ->  gate.py + policy.py
  mint / rotate / revoke   ->  broker.py + secrets.py
  reach outside            ->  egress.py
  record                   ->  audit.py

Extensions never talk to each other, to the network, or to the secret store
directly. Every arrow goes through here, which is why "add an extension" cannot
add authority.

Entry points:

  Host.invoke(name, payload)          run an agent/tool; returns value + *proposals*
  Host.perform(resource, action, ...) execute a privileged action through the gate
  Host.run_agent(name, payload)       invoke, then gate-and-execute each proposal
  Host.kill(name, reason)             kill-switch
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..backends import ROUTES
from .audit import AuditLog
from .broker import TokenBroker, intent_hash
from .contract import Extension
from .egress import EgressProxy
from .errors import AuthorizationDenied, HostError, RegistryError
from .gate import (
    AutoDenyConfirmation,
    ConfirmationProvider,
    Gate,
    GateDecision,
    Intent,
)
from .policy import PolicyEngine
from .registry import Registry
from .sandbox import Sandbox, SandboxResult
from .secrets import SecretStore, default_store
from .taint import TaintSet, UNTRUSTED

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_POLICY = os.path.join(ROOT, "security", "policy", "abac-policy.yaml")
DEFAULT_GRANTS = os.path.join(ROOT, "governance", "approved-grants.yaml")
DEFAULT_INTEGRATIONS = os.path.join(ROOT, "integrations")

# Extension call graphs are bounded by the host, not by the extensions.
MAX_CALL_DEPTH = 3


@dataclass
class _Session:
    """Per-invocation state the host owns (never the extension)."""

    taint: TaintSet = field(default_factory=TaintSet)
    reached_out: bool = False

    def absorb(self, taint: TaintSet) -> None:
        self.taint = self.taint.merge(taint)


@dataclass
class ProposalOutcome:
    proposal: dict[str, Any]
    allowed: bool
    reasons: list[str]
    impact: str = "unknown"
    result: Any = None
    error: str = ""
    taint: TaintSet = field(default_factory=TaintSet)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": f"{self.proposal.get('resource')}:{self.proposal.get('action')}",
            "params": self.proposal.get("params"),
            "allowed": self.allowed,
            "impact": self.impact,
            "reasons": self.reasons,
            "error": self.error,
        }


@dataclass
class InvocationResult:
    extension: str
    value: Any = None
    proposals: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[ProposalOutcome] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    taint: TaintSet = field(default_factory=TaintSet)
    duration_ms: float = 0.0

    def executed(self) -> list[ProposalOutcome]:
        return [o for o in self.outcomes if o.allowed]

    def blocked(self) -> list[ProposalOutcome]:
        return [o for o in self.outcomes if not o.allowed]


class Host:
    def __init__(
        self,
        *,
        policy: PolicyEngine,
        audit: AuditLog | None = None,
        secret_store: SecretStore | None = None,
        confirmation: ConfirmationProvider | None = None,
        routes: dict[str, Any] | None = None,
        token_ttl_s: float = 30.0,
    ):
        self.audit = audit or AuditLog()
        self.secrets = secret_store or default_store()
        self.broker = TokenBroker(self.secrets, self.audit, ttl_s=token_ttl_s)
        self.registry = Registry(self.audit, self.broker)
        self.policy = policy
        self.gate = Gate(
            policy, self.audit, confirmation or AutoDenyConfirmation(), registry=self.registry
        )
        self.sandbox = Sandbox(self.audit)
        self.egress = EgressProxy(self.broker, self.audit, routes or ROUTES)

    # -- construction ------------------------------------------------------ #

    @classmethod
    def bootstrap(
        cls,
        *,
        policy_path: str = DEFAULT_POLICY,
        grants_path: str = DEFAULT_GRANTS,
        integrations_dir: str | None = DEFAULT_INTEGRATIONS,
        confirmation: ConfirmationProvider | None = None,
        audit_path: str | None = None,
    ) -> "Host":
        host = cls(
            policy=PolicyEngine.from_file(policy_path),
            audit=AuditLog(path=audit_path),
            confirmation=confirmation,
        )
        host.audit.record("host.boot", actor="host", policy_version=host.policy.version)
        if grants_path and os.path.exists(grants_path):
            host.registry.load_grants(grants_path)
        if integrations_dir:
            host.load_all(integrations_dir)
        return host

    def load_all(self, directory: str) -> list[Extension]:
        loaded = []
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isdir(path) and os.path.exists(os.path.join(path, "extension.yaml")):
                loaded.append(self.load(path))
        return loaded

    def load(self, directory: str, actor: str = "host") -> Extension:
        ext = self.registry.load_dir(directory, actor=actor)
        self._lifecycle(ext, "on_load", actor)
        self._lifecycle(ext, "on_activate", actor)
        return ext

    # -- invocation -------------------------------------------------------- #

    def invoke(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        actor: str = "operator",
        tenant: str = "acme",
        origin: str = "human",
        context: dict[str, Any] | None = None,
        confirmation_ref: str = "",
        target: str = "",
    ) -> InvocationResult:
        """Run an agent or tool. Proposals come back **unexecuted**."""
        ext = self.registry.get(name)
        problem = self.registry.liveness_problem(name)
        if problem:
            raise RegistryError(problem)

        self.audit.record(
            "host.invoke",
            actor=actor,
            extension=ext.ref,
            kind=ext.kind,
            tenant=tenant,
            origin=origin,
            payload_keys=_keys(payload),
        )
        result = self._run(
            ext,
            payload,
            actor=actor,
            tenant=tenant,
            origin=origin,
            context=context or {},
            confirmation_ref=confirmation_ref,
            target=target,
        )
        return InvocationResult(
            extension=ext.ref,
            value=result.value,
            proposals=result.proposals,
            logs=result.logs,
            taint=result.taint,
            duration_ms=result.duration_ms,
        )

    def run_agent(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        actor: str = "operator",
        tenant: str = "acme",
        execute: bool = True,
    ) -> InvocationResult:
        """Invoke an agent, then send each proposed action through the gate.

        This is the whole trust-boundary story in one method: the agent's output
        is *data* until each proposal is independently authorized.
        """
        invocation = self.invoke(name, payload, actor=actor, tenant=tenant, origin="human")
        caller = self.registry.get(name)
        for proposal in invocation.proposals:
            outcome = self.perform(
                proposal.get("resource", ""),
                proposal.get("action", ""),
                proposal.get("params") or {},
                caller=caller,
                actor=actor,
                tenant=tenant,
                origin="model",
                taint=invocation.taint,
                rationale=proposal.get("rationale", ""),
                dry_run=not execute,
            )
            outcome.proposal = proposal
            invocation.outcomes.append(outcome)
        return invocation

    def perform(
        self,
        resource: str,
        action: str,
        params: dict[str, Any],
        *,
        caller: Extension | None = None,
        actor: str = "operator",
        tenant: str = "acme",
        origin: str = "human",
        taint: TaintSet | None = None,
        rationale: str = "",
        dry_run: bool = False,
        depth: int = 0,
    ) -> ProposalOutcome:
        """Execute one privileged action through the gate and a connector.

        Two keys must turn when `caller` is set: the caller's grant *and* the
        connector's grant must both cover (resource, action). Chained
        authorization means an agent cannot borrow a connector's authority.
        """
        proposal = {"resource": resource, "action": action, "params": params, "rationale": rationale}
        taint = taint or TaintSet()
        target = str(params.get("ticket_id") or params.get("service") or params.get("id") or "")
        context = {k: v for k, v in params.items() if k in ("project", "tenant", "service")}

        # pre_action hooks may rewrite params or veto entirely
        params, veto = self._run_pre_action_hooks(
            resource, action, params, actor=actor, tenant=tenant
        )
        if veto:
            return ProposalOutcome(proposal, False, [f"hook veto: {veto}"], impact="unknown")
        proposal["params"] = params

        decisions: list[GateDecision] = []
        try:
            if caller is not None:
                decisions.append(
                    self.gate.authorize(
                        Intent(
                            extension=caller,
                            resource=resource,
                            action=action,
                            params=params,
                            tenant=tenant,
                            actor=actor,
                            origin=origin,
                            taint=taint,
                            target=target,
                            context=context,
                            rationale=rationale,
                        )
                    )
                )
            connector = self.registry.provider_of(f"{resource}.{action}")
            if connector is None:
                return ProposalOutcome(
                    proposal,
                    False,
                    [f"no loaded extension provides capability {resource}.{action}"],
                )
            callee_decision = self.gate.authorize(
                Intent(
                    extension=connector,
                    resource=resource,
                    action=action,
                    params=params,
                    tenant=tenant,
                    actor=actor,
                    origin="extension" if caller is not None else origin,
                    taint=taint,
                    target=target,
                    context=context,
                    confirmation_ref=decisions[0].confirmation_ref if decisions else "",
                    rationale=rationale,
                )
            )
            decisions.append(callee_decision)
        except AuthorizationDenied as exc:
            decision = exc.decision
            return ProposalOutcome(
                proposal,
                False,
                (decision.reasons if decision else [str(exc)]),
                impact=decision.impact if decision else "unknown",
                error=exc.reason,
            )

        impact = decisions[-1].impact
        if dry_run:
            return ProposalOutcome(
                proposal, True, decisions[-1].reasons + ["dry-run: not executed"], impact=impact
            )

        try:
            run = self._run(
                connector,
                {"action": action, "params": params},
                actor=actor,
                tenant=tenant,
                origin="extension",
                context=context,
                confirmation_ref=decisions[-1].confirmation_ref,
                target=target,
                depth=depth,
            )
        except HostError as exc:
            return ProposalOutcome(
                proposal, False, decisions[-1].reasons, impact=impact, error=str(exc)
            )
        return ProposalOutcome(
            proposal,
            True,
            decisions[-1].reasons,
            impact=impact,
            result=run.value,
            taint=run.taint,
        )

    # -- kill-switch / rotation ------------------------------------------- #

    def kill(self, name: str, *, reason: str, actor: str = "security-oncall") -> dict[str, Any]:
        try:
            ext = self.registry.get(name)
            self._lifecycle(ext, "on_revoke", actor)
        except HostError:
            pass
        return self.registry.revoke(name, reason=reason, actor=actor)

    def rotate(self, secret_ref: str, new_value: str, actor: str = "sre") -> int:
        return self.broker.rotate_upstream(secret_ref, new_value, actor=actor)

    # -- internals --------------------------------------------------------- #

    def _run(
        self,
        ext: Extension,
        payload: dict[str, Any],
        *,
        actor: str,
        tenant: str,
        origin: str,
        context: dict[str, Any],
        confirmation_ref: str,
        target: str,
        depth: int = 0,
    ) -> SandboxResult:
        if depth > MAX_CALL_DEPTH:
            raise HostError(
                f"call depth {depth} exceeds MAX_CALL_DEPTH={MAX_CALL_DEPTH}; "
                "extension call graphs are bounded by the host"
            )
        session = _Session()
        handler = self._channel_handler(
            ext,
            session=session,
            actor=actor,
            tenant=tenant,
            origin=origin,
            context=context,
            confirmation_ref=confirmation_ref,
            target=target,
            depth=depth,
        )
        result = self.sandbox.execute(
            ext,
            payload,
            token_handle=f"inv_{intent_hash({'ext': ext.ref, 'payload': _keys(payload)})[:10]}",
            on_egress=handler,
        )
        # Taint is decided by the host, not self-reported by the extension.
        result.taint = result.taint.merge(session.taint)
        if ext.output_class == UNTRUSTED and result.taint.tainted is False and session.reached_out:
            result.taint = result.taint.merge(
                TaintSet(label=UNTRUSTED, sources=[f"{ext.ref} (declared untrusted output)"])
            )
        self._lifecycle(ext, "post_action", actor)
        return result

    def _channel_handler(
        self,
        ext: Extension,
        *,
        session: "_Session",
        actor: str,
        tenant: str,
        origin: str,
        context: dict[str, Any],
        confirmation_ref: str,
        target: str,
        depth: int,
    ):
        """The extension's entire outward surface: `ctx.http` and `ctx.call`.

        Both are authorized per request against the *host-tracked* taint for this
        invocation, so an extension cannot launder provenance by lying about it.
        """

        def handle_http(msg: dict[str, Any]) -> dict[str, Any]:
            resource, action = msg.get("resource", ""), msg.get("action", "")
            params = {"url": msg.get("url", ""), "method": msg.get("method", "GET")}
            try:
                decision = self.gate.authorize(
                    Intent(
                        extension=ext,
                        resource=resource,
                        action=action,
                        params=params,
                        tenant=tenant,
                        actor=actor,
                        origin="extension",
                        taint=session.taint,
                        target=target,
                        context=context,
                        confirmation_ref=confirmation_ref,
                    )
                )
            except AuthorizationDenied as exc:
                return {"ok": False, "error": str(exc)}

            secret_ref = (ext.delegated_auth or {}).get("secret_ref", "")
            try:
                grant = self.broker.mint(
                    extension=ext.ref,
                    tenant=tenant,
                    resource=resource,
                    actions=(action,),
                    secret_ref=secret_ref,
                    intent_hash=decision.intent_hash,
                    ttl_s=min(15.0, ext.runtime.timeout_ms / 1000.0 + 5),
                    actor=actor,
                )
                response = self.egress.request(
                    extension=ext.ref,
                    allowlist=ext.egress_allow,
                    handle=grant.handle,
                    method=params["method"],
                    url=params["url"],
                    body=msg.get("body") or {},
                    resource=resource,
                    action=action,
                    intent_hash=decision.intent_hash,
                )
            except HostError as exc:
                return {"ok": False, "error": str(exc)}
            session.reached_out = True
            session.absorb(response.taint)
            return {"ok": True, **response.to_wire()}

        def handle_call(msg: dict[str, Any]) -> dict[str, Any]:
            capability = str(msg.get("capability", ""))
            resource, _, action = capability.partition(".")
            if not resource or not action:
                return {"ok": False, "error": f"malformed capability {capability!r}"}
            if capability not in ext.requires:
                return {
                    "ok": False,
                    "error": (
                        f"default-deny: {ext.ref} did not declare capabilities.requires "
                        f"entry {capability!r}"
                    ),
                }
            outcome = self.perform(
                resource,
                action,
                msg.get("params") or {},
                caller=ext,
                actor=actor,
                tenant=tenant,
                origin="model" if ext.kind == "agent" else "extension",
                taint=session.taint,
                rationale=f"ctx.call from {ext.ref}",
                depth=depth + 1,
            )
            if not outcome.allowed:
                return {"ok": False, "error": "; ".join(outcome.reasons) or outcome.error}
            session.reached_out = True
            session.absorb(
                outcome.taint.merge(
                    TaintSet(label=UNTRUSTED, sources=[f"{capability} via host broker"])
                )
            )
            return {"ok": True, "value": outcome.result, "taint": session.taint.to_dict()}

        def handler(msg: dict[str, Any]) -> dict[str, Any]:
            return handle_call(msg) if msg.get("op") == "call" else handle_http(msg)

        return handler

    def _run_pre_action_hooks(
        self, resource: str, action: str, params: dict[str, Any], *, actor: str, tenant: str
    ) -> tuple[dict[str, Any], str]:
        for hook in self.registry.hooks_for("pre_action"):
            if self.registry.liveness_problem(hook.name):
                continue
            result = self.sandbox.execute(
                hook,
                {"event": "pre_action", "resource": resource, "action": action, "params": params},
            )
            value = result.value or {}
            self.audit.record(
                "hook.pre_action",
                actor=actor,
                extension=hook.ref,
                resource=resource,
                action=action,
                mutated=bool(value.get("params")),
                blocked=bool(value.get("block")),
                notes=value.get("notes", ""),
            )
            if value.get("block"):
                return params, str(value.get("reason", "blocked by hook"))
            if isinstance(value.get("params"), dict):
                params = value["params"]
        return params, ""

    def _lifecycle(self, ext: Extension, key: str, actor: str) -> None:
        handler = ext.lifecycle.get(key)
        if not handler or handler == "noop":
            return
        if handler == "flush_tokens":
            self.broker.revoke_extension(ext.ref, reason=f"lifecycle:{key}", actor=actor)
        self.audit.record(
            "lifecycle." + key, actor=actor, extension=ext.ref, handler=handler
        )

    # -- inspection -------------------------------------------------------- #

    def describe(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy.version,
            "extensions": self.registry.inspect(),
            "secrets": self.secrets.describe(),
            "audit_records": len(self.audit.records),
            "audit_chain_valid": self.audit.verify(),
        }


def _keys(payload: dict[str, Any]) -> list[str]:
    return sorted(payload.keys())
