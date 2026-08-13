"""Token broker (FR-2: token lifecycle — issue, scope, rotate, revoke).

The broker mints a **short-lived, single-purpose token handle** per authorized
action. Properties that matter:

* Scoped down: the handle is bound to (extension ref, tenant, resource,
  actions, intent hash). A handle minted for `issue_tracker:read` cannot be
  replayed against `issue_tracker:close`.
* Opaque: the handle is not a credential. The upstream credential is resolved
  from the secret store by the egress proxy at call time (RFC 8693-style token
  exchange / downscoping in production).
* Short-lived: default TTL is seconds, not hours — long enough for one action.
* Revocable: `revoke_extension()` invalidates every outstanding handle for an
  extension immediately. This is what makes the kill-switch real.
* Rotatable: `rotate_upstream()` swaps the upstream credential without touching
  extension code, and bumps the generation so pre-rotation handles die.
"""

from __future__ import annotations

import hashlib
import secrets as pysecrets
import time
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLog
from .errors import TokenError
from .secrets import SecretStore

DEFAULT_TTL_S = 30.0


@dataclass(frozen=True)
class TokenGrant:
    handle: str
    extension: str
    tenant: str
    resource: str
    actions: tuple[str, ...]
    secret_ref: str
    intent_hash: str
    issued_at: float
    expires_at: float
    generation: int
    upstream_scopes: tuple[str, ...] = ()

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at

    def describe(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "extension": self.extension,
            "tenant": self.tenant,
            "resource": self.resource,
            "actions": list(self.actions),
            "ttl_s": round(self.expires_at - self.issued_at, 3),
            "upstream_scopes": list(self.upstream_scopes),
        }


class TokenBroker:
    def __init__(self, store: SecretStore, audit: AuditLog, ttl_s: float = DEFAULT_TTL_S):
        self.store = store
        self.audit = audit
        self.ttl_s = ttl_s
        self._grants: dict[str, TokenGrant] = {}
        self._revoked: set[str] = set()
        self._generation: dict[str, int] = {}

    # -- issue ------------------------------------------------------------- #

    def mint(
        self,
        *,
        extension: str,
        tenant: str,
        resource: str,
        actions: tuple[str, ...],
        secret_ref: str,
        intent_hash: str,
        ttl_s: float | None = None,
        actor: str = "host",
    ) -> TokenGrant:
        if extension in self._revoked:
            raise TokenError(f"{extension} is revoked; refusing to mint tokens")
        record = self.store.resolve(secret_ref)
        wanted = _upstream_scopes(resource, actions)
        excess = set(wanted) - set(record.scopes)
        if excess:
            raise TokenError(
                f"least-privilege violation: {extension} asked for upstream scopes "
                f"{sorted(excess)} that {secret_ref} does not hold"
            )
        now = time.time()
        grant = TokenGrant(
            handle="tkn_" + pysecrets.token_hex(8),
            extension=extension,
            tenant=tenant,
            resource=resource,
            actions=tuple(actions),
            secret_ref=secret_ref,
            intent_hash=intent_hash,
            issued_at=now,
            expires_at=now + (ttl_s if ttl_s is not None else self.ttl_s),
            generation=self._generation.get(secret_ref, 0),
            upstream_scopes=tuple(wanted),
        )
        self._grants[grant.handle] = grant
        self.audit.record(
            "token.minted",
            actor=actor,
            extension=extension,
            handle=grant.handle,
            resource=resource,
            actions=list(actions),
            upstream_scopes=list(wanted),
            ttl_s=round(grant.expires_at - grant.issued_at, 3),
        )
        return grant

    # -- validate ---------------------------------------------------------- #

    def redeem(
        self,
        handle: str,
        *,
        extension: str,
        resource: str,
        action: str,
        intent_hash: str | None = None,
    ) -> TokenGrant:
        grant = self._grants.get(handle)
        if grant is None:
            raise TokenError("unknown token handle")
        if grant.extension in self._revoked:
            raise TokenError(f"token belongs to revoked extension {grant.extension}")
        if grant.extension != extension:
            raise TokenError("token handle presented by a different extension")
        if grant.expired():
            raise TokenError("token expired")
        if grant.generation != self._generation.get(grant.secret_ref, 0):
            raise TokenError("token predates a credential rotation")
        if grant.resource != resource or action not in grant.actions:
            raise TokenError(
                f"token is scoped to {grant.resource}:{list(grant.actions)}, "
                f"not {resource}:{action}"
            )
        if intent_hash is not None and grant.intent_hash != intent_hash:
            raise TokenError("token is bound to a different intent")
        return grant

    def upstream_credential(self, grant: TokenGrant) -> str:
        """Called by the egress proxy only. Never returned to extension code."""
        return self.store.resolve(grant.secret_ref).value

    # -- rotate / revoke --------------------------------------------------- #

    def rotate_upstream(self, secret_ref: str, new_value: str, actor: str = "sre") -> int:
        self.store.rotate(secret_ref, new_value)
        self._generation[secret_ref] = self._generation.get(secret_ref, 0) + 1
        killed = [h for h, g in self._grants.items() if g.secret_ref == secret_ref]
        self.audit.record(
            "token.rotated",
            actor=actor,
            extension="-",
            secret_ref=secret_ref,
            invalidated_handles=len(killed),
            generation=self._generation[secret_ref],
        )
        return len(killed)

    def revoke_extension(self, extension: str, *, reason: str, actor: str) -> int:
        self._revoked.add(extension)
        killed = [h for h, g in self._grants.items() if g.extension == extension]
        for handle in killed:
            self._grants.pop(handle, None)
        self.audit.record(
            "token.revoked",
            actor=actor,
            extension=extension,
            reason=reason,
            revoked_handles=len(killed),
        )
        return len(killed)

    def unrevoke_extension(self, extension: str, *, actor: str) -> None:
        self._revoked.discard(extension)
        self.audit.record("token.unrevoked", actor=actor, extension=extension)

    # -- inspection -------------------------------------------------------- #

    def outstanding(self, extension: str | None = None) -> list[TokenGrant]:
        now = time.time()
        return [
            g
            for g in self._grants.values()
            if not g.expired(now) and (extension is None or g.extension == extension)
        ]

    def is_revoked(self, extension: str) -> bool:
        return extension in self._revoked


def intent_hash(payload: dict[str, Any]) -> str:
    import json

    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


_UPSTREAM_SCOPE_MAP = {
    ("issue_tracker", "read"): "tickets.read",
    ("issue_tracker", "label"): "tickets.write",
    ("issue_tracker", "comment"): "tickets.write",
    ("issue_tracker", "assign"): "tickets.write",
    ("issue_tracker", "close"): "tickets.close",
    ("knowledge_base", "read"): "articles.read",
    ("knowledge_base", "search"): "articles.read",
    ("cicd", "read"): "pipelines.read",
    ("cicd", "rerun"): "pipelines.write",
}


def _upstream_scopes(resource: str, actions: tuple[str, ...]) -> tuple[str, ...]:
    out = []
    for action in actions:
        scope = _UPSTREAM_SCOPE_MAP.get((resource, action))
        if scope and scope not in out:
            out.append(scope)
    return tuple(out)
