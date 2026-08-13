"""Extension registry — load / isolate / revoke plus the governance state machine.

The registry is the host's source of truth for *what is loaded, at what version,
with which approved permissions*. It enforces:

* **Approved grants** — an extension may only hold permissions that appear in
  `governance/approved-grants.yaml` (default-deny: no entry, no authority).
* **Permission-diff re-approval** — upgrading to a version that requests new
  permissions is refused until the grant is re-approved (FR-4 stretch goal).
* **Kill-switch** — `revoke()` marks the extension revoked, unloads it and tells
  the broker to invalidate every outstanding token, host-wide, immediately.
* **Inspectability** — `inspect()` returns permissions, versions, runtime and
  state for every loaded extension (NFR-4).

States: `proposed -> approved -> loaded -> deprecated -> revoked/removed`.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from . import yamlio
from .audit import AuditLog
from .broker import TokenBroker
from .contract import Extension, Permission, diff_permissions, load_manifest, semver_tuple
from .errors import PermissionExpansionError, RegistryError, RevokedError

LOADED, DEPRECATED, REVOKED = "loaded", "deprecated", "revoked"


@dataclass
class Grant:
    """An approved permission set for a name + version range."""

    extension: str
    versions: str  # semver glob, e.g. "1.*"
    permissions: tuple[Permission, ...]
    approver: str
    review: str
    approved_at: str = ""
    expires_at: str = ""

    def keys(self) -> set[str]:
        return {p.key() for p in self.permissions}

    def applies_to(self, ext: Extension) -> bool:
        import fnmatch

        return ext.name == self.extension and fnmatch.fnmatch(ext.version, self.versions)


@dataclass
class Entry:
    ext: Extension
    state: str = LOADED
    loaded_at: float = field(default_factory=time.time)
    revoked_reason: str = ""
    deprecation: dict[str, Any] = field(default_factory=dict)


class Registry:
    def __init__(self, audit: AuditLog, broker: TokenBroker | None = None):
        self.audit = audit
        self.broker = broker
        self._entries: dict[str, Entry] = {}
        self._grants: list[Grant] = []
        self._capabilities: dict[str, str] = {}  # capability -> extension name
        self._hooks: dict[str, list[str]] = {}  # event -> extension names

    # -- grants (governance as data) --------------------------------------- #

    def load_grants(self, path: str) -> int:
        data = yamlio.load_file(path) or {}
        for raw in data.get("grants") or []:
            perms = tuple(
                Permission(
                    resource=p["resource"],
                    actions=tuple(p.get("actions") or ()),
                    scope=p.get("scope") or {},
                    impact=p.get("impact", "low"),
                    justification=p.get("justification", ""),
                )
                for p in raw.get("permissions") or []
            )
            self._grants.append(
                Grant(
                    extension=raw["extension"],
                    versions=str(raw.get("versions", "*")),
                    permissions=perms,
                    approver=raw.get("approver", "unknown"),
                    review=raw.get("review", ""),
                    approved_at=str(raw.get("approved_at", "")),
                    expires_at=str(raw.get("expires_at", "")),
                )
            )
        self.audit.record("registry.grants_loaded", actor="host", count=len(self._grants), path=path)
        return len(self._grants)

    def grant_for(self, ext: Extension) -> Grant | None:
        """The grant that governs this exact version.

        Several grants can match a version glob (a broad `1.*` grant plus a
        narrower `1.3.*` re-approval). Prefer one that actually covers what the
        manifest requests, then the most specific glob, then the most recently
        approved — so a re-approval supersedes the grant it amends instead of
        being shadowed by it.
        """
        matches = [g for g in self._grants if g.applies_to(ext)]
        if not matches:
            return None
        requested = ext.permission_keys()
        covering = [g for g in matches if requested <= g.keys()]
        pool = covering or matches
        return max(pool, key=lambda g: (len(g.versions), self._grants.index(g)))

    def grant_covers(self, ext: Extension, perm: Permission) -> bool:
        grant = self.grant_for(ext)
        return bool(grant and perm.key() in grant.keys())

    def approve(self, grant: Grant, actor: str = "governance-board") -> None:
        """Programmatic approval (the review board's action in code form)."""
        self._grants = [
            g for g in self._grants if not (g.extension == grant.extension and g.versions == grant.versions)
        ]
        self._grants.append(grant)
        self.audit.record(
            "governance.grant_approved",
            actor=actor,
            extension=f"{grant.extension}@{grant.versions}",
            permissions=sorted(grant.keys()),
            review=grant.review,
        )

    # -- load / upgrade ---------------------------------------------------- #

    def load_dir(self, directory: str, actor: str = "host") -> Extension:
        manifest = os.path.join(directory, "extension.yaml")
        if not os.path.exists(manifest):
            raise RegistryError(f"{directory}: no extension.yaml")
        return self.load(load_manifest(manifest), actor=actor)

    def load(self, ext: Extension, actor: str = "host") -> Extension:
        existing = self._entries.get(ext.name)
        if existing and existing.state == REVOKED:
            raise RevokedError(
                f"{ext.name} is revoked ({existing.revoked_reason}); "
                "governance must clear the revocation before it can load again"
            )

        # governance: approved grant must cover every requested permission
        grant = self.grant_for(ext)
        requested = ext.permission_keys()
        if requested and grant is None:
            raise RegistryError(
                f"{ext.ref}: default-deny — no approved grant exists for this extension/version. "
                f"Requested: {sorted(requested)}"
            )
        if grant:
            excess = requested - grant.keys()
            if excess:
                raise PermissionExpansionError(
                    f"{ext.ref}: requests permissions outside its approved grant "
                    f"(review {grant.review or 'n/a'}): {sorted(excess)}. "
                    "Re-approval required before load."
                )

        # governance: permission diff on upgrade
        if existing:
            if semver_tuple(ext.version) < semver_tuple(existing.ext.version):
                raise RegistryError(
                    f"{ext.ref}: refusing downgrade from {existing.ext.version}"
                )
            diff = diff_permissions(existing.ext, ext)
            if diff["added"]:
                self.audit.record(
                    "governance.permission_diff",
                    actor=actor,
                    extension=ext.ref,
                    added=diff["added"],
                    removed=diff["removed"],
                    previous_version=existing.ext.version,
                )

        self._entries[ext.name] = Entry(ext=ext, state=LOADED)
        for capability in ext.provides:
            self._capabilities[capability] = ext.name
        for event in ext.events:
            self._hooks.setdefault(event, [])
            if ext.name not in self._hooks[event]:
                self._hooks[event].append(ext.name)

        self.audit.record(
            "registry.loaded",
            actor=actor,
            extension=ext.ref,
            kind=ext.kind,
            runtime=ext.runtime.type,
            permissions=sorted(requested),
            grant=grant.review if grant else "-",
            provides=list(ext.provides),
        )
        return ext

    def upgrade(self, directory: str, actor: str = "host") -> Extension:
        """Same as load_dir, named for intent; raises on permission expansion."""
        return self.load_dir(directory, actor=actor)

    # -- lifecycle --------------------------------------------------------- #

    def deprecate(
        self,
        name: str,
        *,
        successor: str = "",
        sunset: str = "",
        actor: str = "governance-board",
    ) -> None:
        entry = self._require(name)
        entry.state = DEPRECATED
        entry.deprecation = {"successor": successor, "sunset": sunset}
        self.audit.record(
            "governance.deprecated",
            actor=actor,
            extension=entry.ext.ref,
            successor=successor,
            sunset=sunset,
        )

    def revoke(self, name: str, *, reason: str, actor: str) -> dict[str, Any]:
        """KILL-SWITCH. Immediate, host-wide, token-invalidating."""
        entry = self._entries.get(name)
        ref = entry.ext.ref if entry else name
        killed = 0
        if self.broker is not None:
            killed = self.broker.revoke_extension(ref, reason=reason, actor=actor)
            self.broker.revoke_extension(name, reason=reason, actor=actor)
        if entry:
            entry.state = REVOKED
            entry.revoked_reason = reason
            for capability, owner in list(self._capabilities.items()):
                if owner == name:
                    self._capabilities.pop(capability)
            for event, names in self._hooks.items():
                self._hooks[event] = [n for n in names if n != name]
        self.audit.record(
            "governance.kill_switch",
            actor=actor,
            extension=ref,
            reason=reason,
            tokens_revoked=killed,
            unloaded=bool(entry),
        )
        return {"extension": ref, "tokens_revoked": killed, "state": REVOKED}

    def clear_revocation(self, name: str, *, actor: str, review: str) -> None:
        entry = self._entries.get(name)
        if entry:
            self._entries.pop(name)
        if self.broker is not None:
            self.broker.unrevoke_extension(name, actor=actor)
            if entry:
                self.broker.unrevoke_extension(entry.ext.ref, actor=actor)
        self.audit.record(
            "governance.revocation_cleared", actor=actor, extension=name, review=review
        )

    # -- lookup ------------------------------------------------------------ #

    def get(self, name: str) -> Extension:
        return self._require(name).ext

    def liveness_problem(self, name: str) -> str | None:
        entry = self._entries.get(name)
        if entry is None:
            return f"{name} is not loaded"
        if entry.state == REVOKED:
            return f"{name} is revoked ({entry.revoked_reason})"
        if self.broker is not None and self.broker.is_revoked(entry.ext.ref):
            return f"{name} has revoked credentials"
        return None

    def provider_of(self, capability: str) -> Extension | None:
        name = self._capabilities.get(capability)
        return self._entries[name].ext if name and name in self._entries else None

    def hooks_for(self, event: str) -> list[Extension]:
        return [self._entries[n].ext for n in self._hooks.get(event, []) if n in self._entries]

    def loaded(self) -> list[Extension]:
        return [e.ext for e in self._entries.values() if e.state != REVOKED]

    def inspect(self) -> list[dict[str, Any]]:
        out = []
        for entry in self._entries.values():
            grant = self.grant_for(entry.ext)
            out.append(
                {
                    **entry.ext.summary(),
                    "state": entry.state,
                    "grant_review": grant.review if grant else "-",
                    "approver": grant.approver if grant else "-",
                    "revoked_reason": entry.revoked_reason,
                    "deprecation": entry.deprecation,
                    "outstanding_tokens": len(self.broker.outstanding(entry.ext.ref))
                    if self.broker
                    else 0,
                }
            )
        return out

    def render(self) -> str:
        rows = [f"{'EXTENSION':<26} {'KIND':<10} {'STATE':<11} {'RUNTIME':<17} PERMISSIONS"]
        for row in self.inspect():
            rows.append(
                f"{row['ref']:<26} {row['kind']:<10} {row['state']:<11} "
                f"{row['runtime']:<17} {','.join(row['permissions']) or '-'}"
            )
        return "\n".join(rows)

    def _require(self, name: str) -> Entry:
        entry = self._entries.get(name)
        if entry is None:
            raise RegistryError(f"{name} is not loaded")
        if entry.state == REVOKED:
            raise RevokedError(f"{name} is revoked ({entry.revoked_reason})")
        return entry
