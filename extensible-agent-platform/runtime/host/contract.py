"""ext/v1 — the uniform extension contract.

One shape covers all four extension types (agent, tool, hook, connector).
This module is the *only* place that knows what a manifest looks like; the
loader, gate, broker and egress proxy all consume the parsed objects below.

Contract invariants enforced here (see extension-contract/contract-reference.md):

  C1  apiVersion is ext/v1 and kind is one of agent|tool|hook|connector.
  C2  Every extension declares metadata.name / version (semver) / owner.
  C3  Capabilities are explicit: `provides` (what it exposes) and `requires`
      (capabilities of other extensions it may call).
  C4  Permissions are *requests*, default-deny until the registry holds a
      matching approved grant. A permission with no scope is rejected —
      unscoped ("global") authority cannot be requested by accident.
  C5  Every action carries an impact class (low|medium|high). High impact
      means the authorization gate demands confirmation.
  C6  Egress is allowlisted per extension. `network: deny` plus a non-empty
      allowlist is a contradiction and is rejected.
  C7  Output trust class is declared. Anything reaching outside the host
      (connectors, remote runtimes) defaults to `untrusted`.
  C8  Lifecycle hooks are named from a closed set the host can actually call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import yamlio
from .errors import ContractError

API_VERSION = "ext/v1"
KINDS = ("agent", "tool", "hook", "connector")
RUNTIMES = ("local-inproc", "local-subprocess", "local-wasm", "remote-rpc")
IMPACTS = ("low", "medium", "high")
TRUST_CLASSES = ("trusted", "untrusted")
LIFECYCLE_KEYS = (
    "on_load",
    "on_activate",
    "on_revoke",
    "pre_action",
    "post_action",
    "on_upgrade",
)
LIFECYCLE_HANDLERS = (
    "validate_schema",
    "warm_cache",
    "flush_tokens",
    "authorization_gate",
    "audit_emit",
    "permission_diff",
    "noop",
)
HOOK_EVENTS = ("pre_action", "post_action", "pre_egress", "post_egress")

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_NAME = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")

# Actions the host classifies as high impact regardless of what a manifest
# claims. A manifest may raise an action's impact, never lower it below this.
HOST_HIGH_IMPACT_ACTIONS = {
    "close",
    "delete",
    "purge",
    "merge",
    "deploy",
    "rerun",
    "refund",
    "escalate",
    "transfer",
    "notify_customer",
    "admin",
}
HOST_MEDIUM_IMPACT_ACTIONS = {"write", "label", "comment", "assign", "reopen", "tag"}


@dataclass(frozen=True)
class Permission:
    """A requested (resource, actions, scope) triple. Never ambient."""

    resource: str
    actions: tuple[str, ...]
    scope: dict[str, Any]
    impact: str = "low"
    justification: str = ""

    def key(self) -> str:
        return f"{self.resource}:{','.join(sorted(self.actions))}@{_scope_key(self.scope)}"

    def covers(self, resource: str, action: str) -> bool:
        return resource == self.resource and action in self.actions

    def effective_impact(self, action: str) -> str:
        declared = self.impact
        if action in HOST_HIGH_IMPACT_ACTIONS:
            return "high"
        if action in HOST_MEDIUM_IMPACT_ACTIONS and declared == "low":
            return "medium"
        return declared


@dataclass(frozen=True)
class Runtime:
    type: str = "local-subprocess"
    entrypoint: str = ""
    timeout_ms: int = 5000
    memory_mb: int = 256
    network: str = "deny"  # deny | broker-only
    endpoint: str = ""  # remote-rpc only


@dataclass(frozen=True)
class Extension:
    kind: str
    name: str
    version: str
    owner: str
    description: str
    runtime: Runtime
    provides: tuple[str, ...]
    requires: tuple[str, ...]
    permissions: tuple[Permission, ...]
    io: dict[str, Any]
    egress_allow: tuple[str, ...]
    output_class: str
    lifecycle: dict[str, str]
    events: tuple[str, ...]
    delegated_auth: dict[str, Any]
    source_dir: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def permission_keys(self) -> set[str]:
        return {p.key() for p in self.permissions}

    def find_permission(self, resource: str, action: str) -> Permission | None:
        for perm in self.permissions:
            if perm.covers(resource, action):
                return perm
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "owner": self.owner,
            "runtime": self.runtime.type,
            "provides": list(self.provides),
            "permissions": sorted(self.permission_keys()),
            "output_class": self.output_class,
        }


# --------------------------------------------------------------------------- #
# Parsing / validation
# --------------------------------------------------------------------------- #


def load_manifest(path: str) -> Extension:
    """Parse and validate an `extension.yaml` from disk."""
    import os

    data = yamlio.load_file(path)
    if not isinstance(data, dict):
        raise ContractError(f"{path}: manifest must be a mapping")
    return parse(data, source_dir=os.path.dirname(os.path.abspath(path)))


def parse(data: dict[str, Any], source_dir: str = "") -> Extension:
    errs: list[str] = []

    if data.get("apiVersion") != API_VERSION:  # C1
        errs.append(f"apiVersion must be {API_VERSION!r}, got {data.get('apiVersion')!r}")
    kind = data.get("kind")
    if kind not in KINDS:
        errs.append(f"kind must be one of {KINDS}, got {kind!r}")

    meta = data.get("metadata") or {}
    name, version, owner = meta.get("name"), meta.get("version"), meta.get("owner")
    if not isinstance(name, str) or not _NAME.match(name or ""):  # C2
        errs.append(f"metadata.name {name!r} must match {_NAME.pattern}")
    if not isinstance(version, str) or not _SEMVER.match(str(version)):
        errs.append(f"metadata.version {version!r} must be semver")
    if not owner:
        errs.append("metadata.owner is required (an accountable team)")

    rt_raw = data.get("runtime") or {}
    runtime = Runtime(
        type=rt_raw.get("type", "local-subprocess"),
        entrypoint=rt_raw.get("entrypoint", ""),
        timeout_ms=int(rt_raw.get("timeout_ms", 5000)),
        memory_mb=int(rt_raw.get("memory_mb", 256)),
        network=rt_raw.get("network", "deny"),
        endpoint=rt_raw.get("endpoint", ""),
    )
    if runtime.type not in RUNTIMES:
        errs.append(f"runtime.type must be one of {RUNTIMES}, got {runtime.type!r}")
    if not runtime.entrypoint:
        errs.append("runtime.entrypoint is required (the remote worker needs it too)")
    if runtime.type == "remote-rpc" and not runtime.endpoint:
        errs.append("runtime.endpoint is required for remote-rpc")
    if runtime.network not in ("deny", "broker-only"):
        errs.append("runtime.network must be 'deny' or 'broker-only'")
    if runtime.timeout_ms <= 0 or runtime.timeout_ms > 120_000:
        errs.append("runtime.timeout_ms must be in (0, 120000]")

    caps = data.get("capabilities") or {}
    provides = tuple(caps.get("provides") or ())
    requires = tuple(caps.get("requires") or ())
    if not provides:  # C3
        errs.append("capabilities.provides must declare at least one capability")

    perms: list[Permission] = []
    for i, p in enumerate(data.get("permissions") or ()):
        if not isinstance(p, dict):
            errs.append(f"permissions[{i}] must be a mapping")
            continue
        resource = p.get("resource")
        actions = tuple(p.get("actions") or ())
        scope = p.get("scope")
        impact = p.get("impact", "low")
        if not resource:
            errs.append(f"permissions[{i}].resource is required")
        if not actions:
            errs.append(f"permissions[{i}].actions must be non-empty")
        if not isinstance(scope, dict) or not scope:  # C4
            errs.append(
                f"permissions[{i}].scope must be a non-empty mapping — "
                "unscoped (global) authority cannot be requested"
            )
            scope = {}
        if impact not in IMPACTS:  # C5
            errs.append(f"permissions[{i}].impact must be one of {IMPACTS}")
        if any(a in HOST_HIGH_IMPACT_ACTIONS for a in actions) and not p.get("justification"):
            errs.append(
                f"permissions[{i}] requests a high-impact action and must carry a justification"
            )
        perms.append(
            Permission(
                resource=str(resource),
                actions=actions,
                scope=scope,
                impact=impact,
                justification=p.get("justification", ""),
            )
        )

    egress = data.get("egress") or {}
    allow = tuple(egress.get("allow") or ())
    if allow and runtime.network == "deny":  # C6
        errs.append("egress.allow is non-empty but runtime.network is 'deny'")
    if runtime.network == "broker-only" and not allow:
        errs.append("runtime.network is 'broker-only' but egress.allow is empty")

    trust = data.get("trust") or {}
    default_class = "untrusted" if (allow or runtime.type == "remote-rpc") else "trusted"
    output_class = trust.get("output_class", default_class)
    if output_class not in TRUST_CLASSES:  # C7
        errs.append(f"trust.output_class must be one of {TRUST_CLASSES}")
    if (allow or runtime.type == "remote-rpc") and output_class == "trusted":
        errs.append(
            "an extension that reaches outside the host must declare "
            "trust.output_class: untrusted"
        )

    lifecycle = {}
    for key, handler in (data.get("lifecycle") or {}).items():  # C8
        if key not in LIFECYCLE_KEYS:
            errs.append(f"lifecycle.{key} is not a recognised lifecycle key {LIFECYCLE_KEYS}")
        elif handler not in LIFECYCLE_HANDLERS:
            errs.append(f"lifecycle.{key}={handler!r} is not a host lifecycle handler")
        else:
            lifecycle[key] = handler
    if "on_load" not in lifecycle:
        errs.append("lifecycle.on_load is required (validate_schema at minimum)")

    events = tuple(data.get("events") or ())
    for ev in events:
        if ev not in HOOK_EVENTS:
            errs.append(f"events entry {ev!r} must be one of {HOOK_EVENTS}")
    if kind == "hook" and not events:
        errs.append("kind: hook must subscribe to at least one event")
    if kind != "hook" and events:
        errs.append("only kind: hook may declare events")

    io = data.get("io") or {}
    if "input" not in io or "output" not in io:
        errs.append("io.input and io.output are required")

    auth = data.get("delegated_auth") or {}
    if auth:
        for required in ("provider", "flow", "scopes", "secret_ref"):
            if required not in auth:
                errs.append(f"delegated_auth.{required} is required when delegated_auth is present")
        if auth.get("flow") not in (None, "authorization_code_pkce", "client_credentials"):
            errs.append("delegated_auth.flow must be authorization_code_pkce or client_credentials")
    if allow and not auth:
        errs.append("an extension with egress must declare delegated_auth (no ambient credentials)")

    if errs:
        raise ContractError(
            f"{data.get('kind','?')}/{meta.get('name','?')}: "
            + "; ".join(errs)
        )

    return Extension(
        kind=str(kind),
        name=str(name),
        version=str(version),
        owner=str(owner),
        description=str(meta.get("description", "")),
        runtime=runtime,
        provides=provides,
        requires=requires,
        permissions=tuple(perms),
        io=io,
        egress_allow=allow,
        output_class=output_class,
        lifecycle=lifecycle,
        events=events,
        delegated_auth=auth,
        source_dir=source_dir,
        raw=data,
    )


def _scope_key(scope: dict[str, Any]) -> str:
    return ",".join(f"{k}={scope[k]}" for k in sorted(scope))


def diff_permissions(old: Extension, new: Extension) -> dict[str, list[str]]:
    """Permission diff used by governance on upgrade (FR-4 / ADR-006)."""
    old_keys, new_keys = old.permission_keys(), new.permission_keys()
    return {
        "added": sorted(new_keys - old_keys),
        "removed": sorted(old_keys - new_keys),
        "unchanged": sorted(old_keys & new_keys),
    }


def semver_tuple(version: str) -> tuple[int, int, int]:
    core = version.split("-", 1)[0]
    major, minor, patch = (int(x) for x in core.split("."))
    return major, minor, patch
