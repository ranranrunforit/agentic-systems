"""Host-side secret store (NFR-1: secrets never reach extension code).

Extension manifests reference credentials by `secret_ref` only. The plaintext
value lives here (in production: a KMS/HSM-backed store such as Vault, AWS
Secrets Manager or GCP Secret Manager) and is read by *the egress proxy*, never
handed to extension code. An extension holds only an opaque token handle.

The fixture values below are obviously fake and exist so the reference host runs
offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import TokenError


@dataclass
class SecretRecord:
    ref: str
    value: str
    provider: str
    scopes: tuple[str, ...]
    rotated_at: float = 0.0


@dataclass
class SecretStore:
    _records: dict[str, SecretRecord] = field(default_factory=dict)

    def put(self, ref: str, value: str, provider: str, scopes: tuple[str, ...] = ()) -> None:
        self._records[ref] = SecretRecord(ref=ref, value=value, provider=provider, scopes=scopes)

    def resolve(self, ref: str) -> SecretRecord:
        if ref not in self._records:
            raise TokenError(f"unknown secret_ref {ref!r}")
        return self._records[ref]

    def rotate(self, ref: str, new_value: str) -> None:
        rec = self.resolve(ref)
        self._records[ref] = SecretRecord(ref, new_value, rec.provider, rec.scopes)

    def describe(self) -> list[dict[str, Any]]:
        """Inspectable metadata only — never values."""
        return [
            {"ref": r.ref, "provider": r.provider, "scopes": list(r.scopes)}
            for r in self._records.values()
        ]


def default_store() -> SecretStore:
    store = SecretStore()
    store.put(
        "secrets/issue-tracker/oauth-client",
        "fixture-issue-tracker-access-token",
        provider="issue-tracker-cloud",
        scopes=("tickets.read", "tickets.write", "tickets.close"),
    )
    store.put(
        "secrets/knowledge-base/oauth-client",
        "fixture-knowledge-base-access-token",
        provider="kb-cloud",
        scopes=("articles.read",),
    )
    store.put(
        "secrets/cicd/oauth-client",
        "fixture-cicd-access-token",
        provider="cicd-cloud",
        scopes=("pipelines.read",),
    )
    return store
