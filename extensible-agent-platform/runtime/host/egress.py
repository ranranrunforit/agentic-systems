"""Egress proxy — the only path out of the host (FR-2, NFR-1, NFR-2).

Extensions have no network. When an extension wants to reach an external system
it asks the host, and the host:

  1. checks the destination against the extension's declared `egress.allow`;
  2. redeems the opaque token handle at the broker (scope + intent bound);
  3. resolves the upstream credential from the secret store and injects it —
     the extension never sees it;
  4. dispatches to the target and labels the response as **untrusted data**;
  5. writes an audit record with destination, action and byte count.

Credential injection in the proxy is what makes "secrets never reach extension
code in plaintext" true by construction rather than by policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .audit import AuditLog
from .broker import TokenBroker
from .errors import EgressDenied, TokenError
from .taint import TaintSet, UNTRUSTED, scan


@dataclass
class EgressResponse:
    status: int
    body: Any
    taint: TaintSet

    def to_wire(self) -> dict[str, Any]:
        return {"status": self.status, "body": self.body, "taint": self.taint.to_dict()}


class EgressProxy:
    def __init__(self, broker: TokenBroker, audit: AuditLog, routes: dict[str, Any]):
        self.broker = broker
        self.audit = audit
        self.routes = routes

    def request(
        self,
        *,
        extension: str,
        allowlist: tuple[str, ...],
        handle: str,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        resource: str,
        action: str,
        intent_hash: str | None = None,
    ) -> EgressResponse:
        parsed = urlparse(url)
        destination = parsed.netloc
        if parsed.scheme != "https":
            self._deny(extension, url, "non_https_destination")
        if not _allowed(destination, allowlist):
            self._deny(extension, url, "destination_not_in_allowlist")

        try:
            grant = self.broker.redeem(
                handle,
                extension=extension,
                resource=resource,
                action=action,
                intent_hash=intent_hash,
            )
        except TokenError as exc:
            self.audit.record(
                "egress.denied",
                actor="egress-proxy",
                extension=extension,
                url=url,
                reason=f"token: {exc}",
            )
            raise EgressDenied(f"egress denied for {extension}: {exc}") from exc

        backend = self.routes.get(destination)
        if backend is None:
            self._deny(extension, url, "no_backend_for_destination")

        credential = self.broker.upstream_credential(grant)  # host-side only
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        status, payload = backend.handle(
            method.upper(), path, body or {}, credential, grant.upstream_scopes
        )

        rendered = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
        signals = scan(rendered)
        taint = TaintSet(label=UNTRUSTED, sources=[f"{destination}{parsed.path}"], signals=signals)
        self.audit.record(
            "egress.call",
            actor="egress-proxy",
            extension=extension,
            method=method.upper(),
            destination=destination,
            path=parsed.path,
            resource=resource,
            action=action,
            status=status,
            bytes=len(rendered),
            injection_signals=signals,
        )
        return EgressResponse(status=status, body=payload, taint=taint)

    def _deny(self, extension: str, url: str, reason: str):
        self.audit.record(
            "egress.denied", actor="egress-proxy", extension=extension, url=url, reason=reason
        )
        raise EgressDenied(f"egress denied for {extension}: {reason} ({url})")


def _allowed(destination: str, allowlist: tuple[str, ...]) -> bool:
    import fnmatch

    return any(fnmatch.fnmatch(destination, pattern) for pattern in allowlist)
