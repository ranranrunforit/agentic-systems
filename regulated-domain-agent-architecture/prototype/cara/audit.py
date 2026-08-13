"""Tamper-evident, append-only, reference-only audit ledger.

Maps to: audit/audit-log-spec.md, ADR-006.

Three properties this implements, each testable:
  1. hash_n = SHA-256(prev_hash || JCS(event)) — removal/reordering is detectable
  2. no update or delete verb exists on the API
  3. payloads carry references and hashes only; a schema validator REJECTS raw
     sensitive content at write time, which is what keeps the audit retention clock
     (>=6 years) compatible with the record deletion clock
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Iterable

GENESIS = "0" * 64

#: audit/audit-log-spec.md §1. Consequential events block on the ledger write:
#: if it cannot be logged, it does not happen (FC-6).
CONSEQUENTIAL = {
    "output.released",
    "action.executed",
    "approval.granted",
    "approval.rejected",
    "approval.expired",
    "grounding.failed",
    "escalation.opened",
    "policy.allow",
    "policy.deny",
    "minimization.applied",
    "toggle.changed",
    "deletion.executed",
    "hold.placed",
}


class LedgerWriteError(RuntimeError):
    """Raised when a consequential event cannot be durably recorded."""


class ForbiddenPayloadError(ValueError):
    """Raised when a write attempts to embed raw sensitive content."""


def canonical(obj: Any) -> str:
    """JCS-ish canonicalisation: stable key order, no insignificant whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def tenant_hmac(tenant_secret: str, value: str) -> str:
    """HMAC for short identifiers.

    A plain hash of a low-entropy field (an MRN, a ZIP) is brute-forceable, so short
    identifiers are keyed. ADR-006 §Rationale.
    """
    return "hmac:" + hmac.new(tenant_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


class AuditLedger:
    """Append-only hash chain. Note the absence of update() and delete()."""

    #: Keys that must never carry raw content. The validator is the control; the
    #: convention alone would erode.
    FORBIDDEN_KEYS = {
        "name", "dob", "ssn", "tin", "phone", "email", "address", "balance",
        "note_text", "prompt", "output_text", "span_text", "identifier_value",
    }

    def __init__(self, shard: str = "region-a", clock=time.time) -> None:
        self.shard = shard
        self._entries: list[dict[str, Any]] = []
        self._journal: list[dict[str, Any]] = []  # deferred writes (FC-6)
        self._anchors: dict[str, str] = {}  # day -> root hash (WORM + notary)
        self._notary: dict[str, str] = {}
        self._clock = clock
        self.available = True  # flipped by tests to simulate an outage
        self._seq = 0

    # -- write path -------------------------------------------------------------

    def append(self, action: str, **fields: Any) -> dict[str, Any]:
        self._validate(fields)
        event = {
            "seq": self._seq,
            "shard": self.shard,
            "ts": self._clock(),
            "action": action,
            **fields,
        }
        event["prev_hash"] = self._entries[-1]["hash"] if self._entries else GENESIS
        event["hash"] = sha256(event["prev_hash"] + canonical(_without(event, "hash")))

        if not self.available:
            # Local hash-chained journal; the ACTION is aborted by the caller when the
            # event is consequential. audit/audit-log-spec.md §7.
            event["deferred_write"] = True
            self._journal.append(event)
            if action in CONSEQUENTIAL:
                raise LedgerWriteError(f"ledger unavailable; {action} aborted")
            return event

        self._entries.append(event)
        self._seq += 1
        return event

    def _validate(self, fields: dict[str, Any]) -> None:
        """Reject raw sensitive content. ADR-006: references and hashes only."""
        def walk(node: Any, path: str = "") -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in self.FORBIDDEN_KEYS:
                        raise ForbiddenPayloadError(
                            f"ledger payload may not contain raw sensitive field {path}{k}"
                        )
                    walk(v, f"{path}{k}.")
            elif isinstance(node, (list, tuple)):
                for item in node:
                    walk(item, path)

        walk(fields)

    def merge_journal(self) -> int:
        """On recovery, merge deferred writes. They keep their deferred_write marker."""
        n = 0
        for ev in self._journal:
            ev["prev_hash"] = self._entries[-1]["hash"] if self._entries else GENESIS
            ev["seq"] = self._seq
            ev["hash"] = sha256(ev["prev_hash"] + canonical(_without(ev, "hash")))
            self._entries.append(ev)
            self._seq += 1
            n += 1
        self._journal.clear()
        return n

    # -- read path --------------------------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def query(self, **filters: Any) -> list[dict[str, Any]]:
        def match(ev: dict[str, Any]) -> bool:
            return all(ev.get(k) == v for k, v in filters.items())

        return [e for e in self._entries if match(e)]

    def reconstruct(self, correlation_id: str) -> list[dict[str, Any]]:
        """The auditor's entry point: one correlation ID -> the ordered decision."""
        return [e for e in self._entries if e.get("correlation_id") == correlation_id]

    # -- integrity --------------------------------------------------------------

    def verify(self) -> dict[str, Any]:
        prev = GENESIS
        for e in self._entries:
            if e["prev_hash"] != prev:
                return {"chain_ok": False, "first_bad_seq": e["seq"], "cause": "PREV_MISMATCH"}
            recomputed = sha256(e["prev_hash"] + canonical(_without(e, "hash")))
            if recomputed != e["hash"]:
                return {"chain_ok": False, "first_bad_seq": e["seq"], "cause": "HASH_MISMATCH"}
            prev = e["hash"]
        anchors_ok = all(self._notary.get(d) == r for d, r in self._anchors.items())
        return {
            "chain_ok": True,
            "entries": len(self._entries),
            "anchors_matched": f"{len(self._anchors)}/{len(self._anchors)}" if anchors_ok else "MISMATCH",
            "deferred_writes_pending": len(self._journal),
        }

    def anchor(self, day: str) -> str:
        """Daily root to WORM + external notary. Only a hash leaves the region."""
        root = self._entries[-1]["hash"] if self._entries else GENESIS
        self._anchors[day] = root
        self._notary[day] = root  # third-party timestamping service
        return root

    # -- saved queries (audit/audit-log-spec.md §5) -----------------------------

    def tier3_without_approval(self) -> list[dict[str, Any]]:
        """MUST return empty. The single most important control test.

        A Tier-3 release with no preceding approval for the same correlation ID means
        high-risk output reached a human without a human approving it.
        """
        approved = {e["correlation_id"] for e in self.query(action="approval.granted")}
        return [
            e
            for e in self.query(action="output.released")
            if e.get("tier") == 3 and e.get("correlation_id") not in approved
        ]

    def disclosures_by_subject(self, subject_ref: str) -> list[dict[str, Any]]:
        """Accounting of disclosures (O-P5 / §164.528)."""
        return [
            e
            for e in self._entries
            if e.get("subject_ref") == subject_ref
            and e["action"] in {"output.released", "action.executed"}
        ]

    def toggle_history(self, tenant: str | None = None) -> list[dict[str, Any]]:
        out = self.query(action="toggle.changed")
        return [e for e in out if tenant is None or e.get("scope_tenant") in (tenant, None)]

    def boundary_fields(self, capability: str) -> set[str]:
        """Minimization drift detection: which field paths have ever crossed."""
        paths: set[str] = set()
        for e in self.query(action="minimization.applied"):
            if e.get("capability") == capability:
                paths |= {f["path"] for f in e.get("fields_included", [])}
        return paths


def _without(d: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k != key}
